"""Sincronização MT5 -> Supabase para o painel do escritório (somente leitura no MT5; escrita só no Supabase).

A cada ciclo (padrão 20 s), com a chave secreta do .env (nunca vai para o navegador):
  agents_status       só os agentes ATIVOS (roster do auditor): resultado acumulado (total_pnl), da competição
                      (total_profit), do último trade fechado (pnl = valor da plaquinha), posição no placar
                      (allocation_weight), estado (EXECUTING com posição aberta / IDLE) e a última ação (last_thought)
  trades_history      trades dos agentes ativos desde SYNC_START: posição aberta entra como OPEN e vira CLOSED ao
                      fechar -> é o EVENTO que o painel usa para animar a plaquinha
  mt5_account_status  conta (id 1) · system_config (id 1): ativos atuais e o placar da competição em agents_pnl
Mapeamento de agentes igual ao do auditor (magic + comentário da entrada para engine A2/A3/A4).
Só envia o que mudou (cache por linha), para não inundar o Realtime.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from agents import auditor_mt5 as AUD
from engine.config import ROOT
from engine.features import server_to_utc

log = logging.getLogger("agents.supabase_sync")

SYNC_START = datetime(2026, 11, 1, tzinfo=timezone.utc)
SECTOR = {"GOLD": 1, "US500Cash": 2, "BTCUSD": 3}
REASON = {4: "SL_HIT", 5: "TP_HIT", 3: "EXPERT", 0: "MANUAL"}


def group_of(name: str) -> str:
    if name.startswith("of_btc_"):
        return "of_btc"
    if name.startswith("v4_"):
        return "v4"
    return "antigo"


def describe(name: str) -> str:
    """Resumo da estratégia para o painel (sem segredos)."""
    try:
        from agents.v3_agent import load_agents_config
        g = load_agents_config().get(name)
    except Exception:  # noqa: BLE001
        g = None
    if g:
        s, e = g["signal"], g["exit"]
        params = ", ".join(f"{k}={v}" for k, v in s.items() if k not in ("family", "session", "of_filter"))
        of = f" + orderflow {s['of_filter']}" if s.get("of_filter") else ""
        trail = f", trailing {e['trail']}/{e['act']} ATR" if float(e.get("trail", 0)) > 0 else ""
        return (f"{s['family']}({params}){of} · {g['timeframe']} · sessão {s.get('session', 'all')} · "
                f"SL {e['sl']} ATR, alvo {e['tp']} ATR{trail}, máx. {g.get('max_bars', 96)} barras")
    return {"engine A3": "Rompimento de estrutura (BOS) + reteste · US500 M5 · trailing do A5",
            "sweep48": "Varredura de liquidez de 48 barras · BTC M5 · 15-20h do servidor · trailing por tick",
            "rsi20": "Compra com RSI(14) M15 <= 20 · BTC · stop 2 ATR, trailing 0.25 ATR",
            "goldnight_v2": "SAR com trailing 3 ATR na madrugada · GOLD M5 · teto de risco US$10"}.get(name, name)


class SupabaseSync:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], url: str, key: str, session: Optional[requests.Session] = None,
                 clock=None) -> None:
        self.mt5, self.cfg = mt5, cfg
        self.url = url.rstrip("/")
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.s = session or requests.Session()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.server_time = cfg["account"].get("server_time", "ny_plus_7")
        self.sent: Dict[str, str] = {}
        self.legacy_cleaned = False

    # ------------------------------------------------------------ REST
    def _req(self, method: str, table: str, params: str = "", body: Any = None, prefer: str = "") -> Any:
        h = dict(self.h)
        if prefer:
            h["Prefer"] = prefer
        r = self.s.request(method, f"{self.url}/rest/v1/{table}{('?' + params) if params else ''}", headers=h,
                           data=None if body is None else json.dumps(body, default=str), timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {method} {table}: {r.status_code} {r.text[:300]}")
        return r.json() if r.text else None

    def upsert(self, table: str, rows: List[Dict[str, Any]], key: str) -> int:
        """Só envia linhas que mudaram desde o último envio."""
        fresh = []
        for row in rows:
            ident = f"{table}:{row[key]}"
            digest = hashlib.md5(json.dumps({k: v for k, v in row.items() if k != "updated_at"}, sort_keys=True,
                                            default=str).encode()).hexdigest()
            if self.sent.get(ident) != digest:
                fresh.append((ident, digest, row))
        if not fresh:
            return 0
        self._req("POST", table, f"on_conflict={key}", [r for _, _, r in fresh],
                  prefer="resolution=merge-duplicates,return=minimal")
        for ident, digest, _ in fresh:
            self.sent[ident] = digest
        return len(fresh)

    # ------------------------------------------------------------ MT5 (somente leitura)
    def roster(self) -> Dict[str, Dict[str, Any]]:
        return {n: r for n, r in AUD.agent_roster(self.cfg).items() if r.get("ligado")}

    def utc(self, server_epoch: int) -> datetime:
        return server_to_utc([int(server_epoch)], self.server_time).iloc[0].to_pydatetime()

    def collect_trades(self, names: Dict[int, str], active: set) -> List[Dict[str, Any]]:
        now = self.clock()
        deals = self.mt5.history_deals_get(SYNC_START.replace(tzinfo=None) - timedelta(days=3),
                                           now.replace(tzinfo=None) + timedelta(days=1)) or []
        by_pos: Dict[int, List[Any]] = {}
        for d in deals:
            if int(d.type) in (0, 1) and int(d.position_id) and int(d.magic) not in AUD.EXCLUDED_MAGICS:
                by_pos.setdefault(int(d.position_id), []).append(d)
        open_ids = {int(p.ticket) for p in (self.mt5.positions_get() or [])}
        rows = []
        for pid, ds in by_pos.items():
            entry = next((d for d in ds if int(d.entry) == 0), None)
            exits = [d for d in ds if int(d.entry) in (1, 2, 3)]
            if entry is None or not exits or pid in open_ids:
                continue
            agent = AUD.agent_of(int(entry.magic), str(entry.comment), names)
            closed = self.utc(max(int(d.time) for d in exits))
            if agent not in active or closed < SYNC_START:
                continue
            last = max(exits, key=lambda d: int(d.time))
            rows.append({"ticket_mt5": pid, "agent_id": agent, "symbol": entry.symbol,
                         "order_type": "BUY" if int(entry.type) == 0 else "SELL", "volume": float(entry.volume),
                         "entry_price": float(entry.price), "close_price": float(last.price), "current_price": float(last.price),
                         "profit_usd": round(sum(float(d.profit) + float(d.swap) + float(d.commission) for d in ds), 2),
                         "status": "CLOSED", "exit_reason": REASON.get(int(getattr(last, "reason", -1)), "CLOSE"),
                         "opened_at": self.utc(int(entry.time)).isoformat(), "closed_at": closed.isoformat(),
                         "dry_run": False, "execution_account": "DEMO", "technical_rationale": str(entry.comment)[:120]})
        for p in self.mt5.positions_get() or []:
            if int(p.magic) in AUD.EXCLUDED_MAGICS:
                continue
            agent = AUD.agent_of(int(p.magic), str(getattr(p, "comment", "")), names)
            if agent not in active:
                continue
            rows.append({"ticket_mt5": int(p.ticket), "agent_id": agent, "symbol": p.symbol,
                         "order_type": "BUY" if int(p.type) == 0 else "SELL", "volume": float(p.volume),
                         "entry_price": float(p.price_open), "sl": float(p.sl), "tp": float(p.tp),
                         "current_price": float(p.price_current), "close_price": None,
                         "profit_usd": round(float(p.profit) + float(getattr(p, "swap", 0.0)), 2), "status": "OPEN",
                         "exit_reason": "OPEN", "opened_at": self.utc(int(p.time)).isoformat(), "closed_at": None,
                         "dry_run": False, "execution_account": "DEMO",
                         "technical_rationale": str(getattr(p, "comment", ""))[:120]})
        return rows

    # ------------------------------------------------------------ agregados
    def build_agents(self, roster: Dict[str, Dict[str, Any]], trades: List[Dict[str, Any]],
                     comp: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = self.clock().isoformat()
        ranks = {r["agente"]: i for i, r in enumerate((comp or {}).get("placar", []), 1)}
        comp_pnl = {r["agente"]: r["pnl"] for r in (comp or {}).get("placar", [])}
        rows = []
        for name, r in roster.items():
            mine = sorted([t for t in trades if t["agent_id"] == name], key=lambda t: t["closed_at"] or t["opened_at"])
            closed = [t for t in mine if t["status"] == "CLOSED"]
            opened = [t for t in mine if t["status"] == "OPEN"]
            streak = 0
            for t in reversed(closed):
                if t["profit_usd"] < 0:
                    streak += 1
                else:
                    break
            last = closed[-1] if closed else None
            sym = (r.get("simbolos") or ["-"])[0]
            if opened:
                o = opened[0]
                thought = (f"Posição {o['order_type']} {o['volume']:g} @ {o['entry_price']:.2f} aberta · "
                           f"flutuante {o['profit_usd']:+.2f}")
            elif last:
                thought = f"Último trade: {last['profit_usd']:+.2f} ({last['exit_reason']}) em {last['closed_at'][:16].replace('T', ' ')} UTC"
            else:
                thought = "Aguardando sinal da estratégia"
            rows.append({"agent_id": name, "name": name, "sector": SECTOR.get(sym, 0), "strategy_style": describe(name),
                         "strategy_type": group_of(name), "current_state": "EXECUTING" if opened else "IDLE",
                         "last_thought": thought, "allocation_weight": float(ranks.get(name, 0)),
                         "total_pnl": round(sum(t["profit_usd"] for t in closed), 2),
                         "total_profit": round(float(comp_pnl.get(name, 0.0)), 2),
                         "pnl": round(last["profit_usd"], 2) if last else 0.0, "consecutive_losses": streak,
                         "macro_viable": True, "macro_reason": sym, "parent_agent_id": None, "quarantine_until": None,
                         "updated_at": now})
        return rows

    def competition(self, trades: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        comp = AUD.competition_config()
        if not comp:
            return None
        hist = [{"agente": t["agent_id"], "pnl": t["profit_usd"],
                 "fechado_utc": (t["closed_at"] or "")[:16].replace("T", " ")} for t in trades if t["status"] == "CLOSED"]
        return AUD.competition_table(hist, comp)

    # ------------------------------------------------------------ ciclo
    def clean_legacy(self, active: set) -> None:
        """Remove agentes e trades que não são dos agentes ativos (backup feito antes, ver backups/)."""
        if self.legacy_cleaned:
            return
        keep = ",".join(f'"{n}"' for n in sorted(active))
        # trades primeiro: trades_history.agent_id referencia agents_status.agent_id (chave estrangeira)
        for dep in ("trades_history", "strategy_parameters", "agent_learning"):   # tabelas que referenciam o agente
            self._req("DELETE", dep, f"agent_id=not.in.({keep})", prefer="return=minimal")
        self._req("DELETE", "agents_status", f"agent_id=not.in.({keep})", prefer="return=minimal")
        self.legacy_cleaned = True

    def step(self) -> Dict[str, int]:
        acc = self.mt5.account_info()
        if acc is None:
            raise RuntimeError(f"MT5 sem conta: {self.mt5.last_error()}")
        roster = self.roster()
        active = set(roster)
        self.clean_legacy(active)
        names = AUD.agent_names(self.cfg)
        trades = self.collect_trades(names, active)
        comp = self.competition(trades)
        closed = [t for t in trades if t["status"] == "CLOSED"]
        now = self.clock().isoformat()
        n_ag = self.upsert("agents_status", self.build_agents(roster, trades, comp), "agent_id")   # antes dos trades (FK)
        n_tr = self.upsert("trades_history", trades, "ticket_mt5")
        self.upsert("mt5_account_status", [{
            "id": 1, "balance": float(acc.balance), "equity": float(acc.equity),
            "floating_pnl": round(float(acc.equity) - float(acc.balance), 2), "free_margin": float(acc.margin_free),
            "margin_level": float(getattr(acc, "margin_level", 0.0) or 0.0),
            "total_tp_gain": round(sum(t["profit_usd"] for t in closed if t["profit_usd"] > 0), 2),
            "total_sl_loss": round(sum(t["profit_usd"] for t in closed if t["profit_usd"] < 0), 2),
            "win_count": sum(1 for t in closed if t["profit_usd"] > 0),
            "loss_count": sum(1 for t in closed if t["profit_usd"] < 0), "is_connected": True, "updated_at": now}], "id")
        self.upsert("system_config", [{
            "id": 1, "trading_mode": "DEMO" if int(acc.trade_mode) == 0 else "REAL",
            "active_assets": sorted({(r.get("simbolos") or ["-"])[0] for r in roster.values()}),
            "total_pnl": round(sum((comp or {}).get("total_por_grupo", {}).values()), 2),
            "agents_pnl": {"competicao": comp, "agentes_ativos": len(roster)},
            "balance": float(acc.balance), "equity": float(acc.equity), "margin_free": float(acc.margin_free),
            "updated_at": now}], "id")
        return {"trades": n_tr, "agentes": n_ag}


def push_auditor_analysis(url: str, key: str, analysis: str, status: str, session: Optional[requests.Session] = None) -> None:
    """Grava a análise do auditor em market_context (o painel mostra a mais recente)."""
    s = session or requests.Session()
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
    body = {"crypto_sentiment": 0, "gold_sentiment": 0, "red_flag_pause_trading": "CRÍTICO" in status.upper(),
            "key_driver": analysis[:4000], "created_at": datetime.now(timezone.utc).isoformat()}
    r = s.post(f"{url.rstrip('/')}/rest/v1/market_context", headers=h, data=json.dumps(body), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase market_context: {r.status_code} {r.text[:200]}")
