"""Acesso ao Supabase. Se SUPABASE_KEY não estiver configurada, usa armazenamento em memória
(permite testar o fluxo localmente sem banco)."""
import copy
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from config import settings

log = logging.getLogger("database")

# Estados que impedem o agente de operar completamente (QUARANTINED opera em Shadow Trading / DEMO)
BLOCKED_STATES = ("IN_MEETING", "FIRED")

# DDL de referência (já aplicado no Supabase via migration). Rode no SQL Editor se o ensure_schema() avisar.
SCHEMA_SQL = """
alter table public.agents_status
  add column if not exists consecutive_losses integer not null default 0,
  add column if not exists quarantine_until timestamptz,
  add column if not exists strategy_type text,
  add column if not exists parent_agent_id text,
  add column if not exists macro_viable boolean not null default false,
  add column if not exists macro_valid_until timestamptz,
  add column if not exists macro_reason text;
alter table public.trades_history
  add column if not exists risk_processed boolean not null default false;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value: Any) -> Optional[datetime]:
    """Converte string/datetime em datetime UTC (tolerante a formatos do Postgres)."""
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:  # noqa: BLE001
        return None


def strategy_of(agent: Any) -> str:
    """Estratégia-base de um agente (linha de agents_status ou agent_id). Clones usam `strategy_type`."""
    if isinstance(agent, dict):
        if agent.get("strategy_type"):
            return agent["strategy_type"]
        agent = agent.get("agent_id", "")
    return re.sub(r"_v\d+$", "", str(agent))


class DatabaseManager:
    def __init__(self) -> None:
        self.client = None
        self._mem: Dict[str, List[dict]] = {
            "agents_status": [], "strategy_parameters": [],
            "market_context": [], "trades_history": [],
            "mt5_account_status": [],
        }
        if settings.SUPABASE_KEY and settings.SUPABASE_URL:
            try:
                from supabase import create_client
                self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
                log.info("Supabase conectado: %s", settings.SUPABASE_URL)
                if settings.SUPABASE_KEY.startswith("sb_publishable_") or settings.SUPABASE_KEY.startswith("eyJ"):
                    log.warning("SUPABASE_KEY parece uma chave pública: com RLS ativo, o backend precisa da "
                                "chave service_role para escrever nas tabelas.")
            except Exception as exc:  # noqa: BLE001
                log.error("Falha ao conectar no Supabase (%s). Usando memória.", exc)
        else:
            log.warning("SUPABASE_KEY ausente: usando armazenamento em MEMÓRIA.")

    @property
    def is_remote(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------ helpers
    def _select(self, table: str, eq: Optional[dict] = None, neq: Optional[dict] = None,
                gte: Optional[dict] = None, order: Optional[str] = None,
                desc: bool = True, limit: Optional[int] = None) -> List[dict]:
        if self.client:
            q = self.client.table(table).select("*")
            for k, v in (eq or {}).items():
                q = q.eq(k, v)
            for k, v in (neq or {}).items():
                q = q.neq(k, v)
            for k, v in (gte or {}).items():
                q = q.gte(k, v)
            if order:
                q = q.order(order, desc=desc)
            if limit:
                q = q.limit(limit)
            return q.execute().data or []
        rows = [r for r in self._mem[table]
                if all(r.get(k) == v for k, v in (eq or {}).items())
                and all(r.get(k) != v for k, v in (neq or {}).items())
                and all((r.get(k) or "") >= v for k, v in (gte or {}).items())]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order)), reverse=desc)
        if limit:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    def _upsert(self, table: str, row: dict, key: str) -> None:
        if self.client:
            self.client.table(table).upsert(row, on_conflict=key).execute()
            return
        for existing in self._mem[table]:
            if existing.get(key) == row.get(key):
                existing.update(row)
                return
        self._mem[table].append(dict(row))

    def _insert(self, table: str, row: dict) -> dict:
        if self.client:
            res = self.client.table(table).insert(row).execute()
            return (res.data or [row])[0]
        row = dict(row)
        row.setdefault("id", str(uuid.uuid4()))
        self._mem[table].append(row)
        return row

    def _update(self, table: str, values: dict, eq: dict) -> int:
        """Atualiza linhas que casam com `eq`; retorna quantas foram afetadas."""
        if self.client:
            q = self.client.table(table).update(values)
            for k, v in eq.items():
                q = q.eq(k, v)
            return len(q.execute().data or [])
        count = 0
        for r in self._mem[table]:
            if all(r.get(k) == v for k, v in eq.items()):
                r.update(values)
                count += 1
        return count

    # ------------------------------------------------------------ agents_status
    def ensure_schema(self) -> bool:
        """Verifica se as colunas de risco/macro existem (supabase-py não executa DDL). Retorna True se ok."""
        if not self.client:
            return True
        try:
            self.client.table("agents_status").select("consecutive_losses,quarantine_until,strategy_type,"
                                                      "macro_viable,macro_valid_until,macro_reason").limit(1).execute()
            self.client.table("trades_history").select("risk_processed").limit(1).execute()
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Schema desatualizado (%s). Execute database.SCHEMA_SQL no SQL Editor do Supabase.", exc)
            return False

    def register_agents(self) -> None:
        """Garante os agentes (5 operadores do Setor 1 + demais setores) e parâmetros padrão.
        Existentes não têm estado sobrescrito; apenas nome/estratégia são sincronizados."""
        self.ensure_schema()
        existing = {r["agent_id"] for r in self._select("agents_status")}
        for agent_id, (sector, name) in settings.AGENTS.items():
            extra = {"strategy_type": agent_id} if sector == 1 else {}
            if agent_id not in existing:
                self._upsert("agents_status", {
                    "agent_id": agent_id, "sector": sector, "name": name,
                    "current_state": "IDLE", "last_thought": "Chegando no escritório...",
                    "allocation_weight": 1.0, "consecutive_losses": 0, "updated_at": _now(), **extra,
                }, "agent_id")
            else:
                self._update("agents_status", {"name": name, **extra}, {"agent_id": agent_id})
        for agent_id, params in settings.DEFAULT_STRATEGY_PARAMS.items():
            if not self._select("strategy_parameters", eq={"agent_id": agent_id}):
                self._upsert("strategy_parameters",
                             {"agent_id": agent_id, "params": params, "updated_at": _now()}, "agent_id")

    def update_agent_status(self, agent_id: str, state: str, thought: str,
                            weight: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> None:
        sector, name = settings.AGENTS.get(agent_id, (1 if agent_id.startswith("ops_") else 0, agent_id))
        values: Dict[str, Any] = {
            "current_state": state, "last_thought": (thought or "")[:300], "updated_at": _now(),
        }
        if weight is not None:
            values["allocation_weight"] = float(weight)
        if extra:
            values.update(extra)
        try:
            # UPDATE primeiro: a tabela tem colunas NOT NULL (name), então upsert parcial falharia.
            if not self._update("agents_status", values, {"agent_id": agent_id}):
                self._insert("agents_status", {"agent_id": agent_id, "sector": sector, "name": name,
                                               "allocation_weight": 1.0, **values})
        except Exception as exc:  # noqa: BLE001
            log.error("update_agent_status(%s) falhou: %s", agent_id, exc)

    def set_agent_fields(self, agent_id: str, values: Dict[str, Any]) -> None:
        """Atualiza colunas arbitrárias de agents_status sem mexer em estado/pensamento."""
        try:
            self._update("agents_status", {**values, "updated_at": _now()}, {"agent_id": agent_id})
        except Exception as exc:  # noqa: BLE001
            log.error("set_agent_fields(%s) falhou: %s", agent_id, exc)

    def get_agent_status(self, agent_id: str) -> Optional[dict]:
        rows = self._select("agents_status", eq={"agent_id": agent_id}, limit=1)
        return rows[0] if rows else None

    def get_all_agents_status(self) -> List[dict]:
        return self._select("agents_status")

    def get_ops_agents(self, include_fired: bool = False) -> List[dict]:
        rows = self._select("agents_status", eq={"sector": 1})
        return rows if include_fired else [r for r in rows if r.get("current_state") != "FIRED"]

    def get_ops_agent_ids(self) -> List[str]:
        """Operadores do Setor 1 ainda empregados (inclui clones, exclui demitidos)."""
        return [r["agent_id"] for r in self.get_ops_agents()]

    def get_active_ops_agents(self) -> List[dict]:
        """Agentes do setor 1 aptos a operar (inclui agentes em quarentena operando em Shadow Trading/Demo).
        Exclui apenas agentes demitidos (FIRED) ou em reunião (IN_MEETING)."""
        out = []
        for r in self.get_ops_agents():
            if r.get("current_state") in BLOCKED_STATES:
                continue
            out.append(r)
        return out

    def release_expired_quarantines(self) -> List[str]:
        """Relógio de Quarentena: busca agentes em QUARANTINED cujo quarantine_until expirou (<= NOW()).
        Executa UPDATE para status IDLE, permitindo que o frontend reposicione o boneco na mesa operacional."""
        now = datetime.now(timezone.utc)
        released = []
        # Consulta agentes atualmente em quarentena
        quarantined_agents = self._select("agents_status", eq={"current_state": "QUARANTINED"})
        for r in quarantined_agents:
            aid = r.get("agent_id")
            if not aid:
                continue
            until = parse_ts(r.get("quarantine_until"))
            # Se quarantine_until <= now (ou se for nulo/ausente em quarentena)
            if not until or until <= now:
                weight = float(r.get("allocation_weight") or 0.0)
                reintegrated_weight = weight if weight > 0 else 1.0
                self.update_agent_status(
                    aid,
                    "IDLE",
                    "Quarentena encerrada pelo relógio de risco. Retornando ao posto operacional.",
                    reintegrated_weight,
                    extra={"quarantine_until": None, "consecutive_losses": 0}
                )
                released.append(aid)
                log.info("[RELÓGIO DE QUARENTENA] Agente %s liberado da quarentena. Status -> IDLE.", aid)
        return released

    def get_best_ops_by_net_pnl(self, exclude: Optional[List[str]] = None) -> Optional[str]:
        """Busca na tabela trades_history o operador ativo com o MAIOR Lucro Líquido (Net PnL) acumulado (status='CLOSED')."""
        exclude_set = set(exclude or [])
        active_ids = [a for a in self.get_ops_agent_ids() if a not in exclude_set]
        if not active_ids:
            return None

        closed_trades = self._select("trades_history", eq={"status": "CLOSED"})
        pnl_map: Dict[str, float] = {a: 0.0 for a in active_ids}

        for t in closed_trades:
            aid = t.get("agent_id")
            if aid in pnl_map:
                pnl = float(t.get("profit_usd") if t.get("profit_usd") is not None else (t.get("pnl") or 0.0))
                pnl_map[aid] += pnl

        best = max(active_ids, key=lambda a: pnl_map.get(a, 0.0))
        log.info("[Setor 5] Melhor operador por Net PnL acumulado em trades_history: %s ($%.2f)",
                 best, pnl_map.get(best, 0.0))
        return best

    def create_agent(self, agent_id: str, name: str, strategy_type: str, params: Dict[str, Any],
                     parent_agent_id: Optional[str] = None) -> None:
        """Contrata um novo operador (ex.: clone ops_gamma_v2) e grava seus parâmetros, resetando lucros para zero."""
        self._insert("agents_status", {
            "agent_id": agent_id, "sector": 1, "name": name, "current_state": "IDLE",
            "last_thought": f"Novo contratado! Clone de alta performance ({parent_agent_id}) assumindo o posto operacional.",
            "allocation_weight": 1.0, "consecutive_losses": 0, "strategy_type": strategy_type,
            "parent_agent_id": parent_agent_id, "updated_at": _now(),
        })
        self.update_strategy_params(agent_id, params)

    # ------------------------------------------------------------ gate macro (Setor 3)
    def set_macro_gate(self, agent_id: str, viable: bool, reason: str, valid_minutes: int) -> None:
        self.set_agent_fields(agent_id, {
            "macro_viable": bool(viable), "macro_reason": (reason or "")[:300],
            "macro_valid_until": (datetime.now(timezone.utc) + timedelta(minutes=valid_minutes)).isoformat(),
        })

    @staticmethod
    def is_macro_ok(agent_row: Optional[dict]) -> bool:
        """True somente se o Setor 3 liberou o agente e a autorização ainda não expirou (fail-closed)."""
        if not agent_row or not agent_row.get("macro_viable"):
            return False
        until = parse_ts(agent_row.get("macro_valid_until"))
        return bool(until and until > datetime.now(timezone.utc))

    # -------------------------------------------------------- strategy_parameters
    def get_strategy_params(self, agent_id: str) -> Dict[str, Any]:
        rows = self._select("strategy_parameters", eq={"agent_id": agent_id}, limit=1)
        if rows:
            return rows[0].get("params") or {}
        return dict(settings.DEFAULT_STRATEGY_PARAMS.get(agent_id, {}))

    def update_strategy_params(self, agent_id: str, new_params: Dict[str, Any]) -> None:
        self._upsert("strategy_parameters",
                     {"agent_id": agent_id, "params": new_params, "updated_at": _now()}, "agent_id")

    def append_vaccine_to_active_agents(self, vaccine_rule: Dict[str, Any],
                                       exclude_agent_id: Optional[str] = None) -> List[str]:
        """Aplica uma nova vacina matemática pós-morte ao campo 'vaccines' de strategy_parameters
        de todos os operadores ativos do Setor 1. Atualiza também o thought dos agentes imunizados."""
        active_ids = [a for a in self.get_ops_agent_ids() if a != exclude_agent_id]
        immunized = []

        ind = str(vaccine_rule.get("indicator") or "").upper()
        op = str(vaccine_rule.get("operator") or "")
        val = vaccine_rule.get("value")
        cond = str(vaccine_rule.get("condition") or "").lower()
        desc = vaccine_rule.get("description") or f"{ind} {op} {val}"
        rule_key = f"{ind}_{op}_{val}_{cond}"

        for aid in active_ids:
            current_params = self.get_strategy_params(aid)
            vaccines = current_params.get("vaccines") or []
            if not isinstance(vaccines, list):
                vaccines = []

            existing_keys = {
                f"{str(v.get('indicator') or '').upper()}_{v.get('operator')}_{v.get('value')}_{str(v.get('condition') or '').lower()}"
                for v in vaccines if isinstance(v, dict)
            }

            if rule_key not in existing_keys:
                vaccines.append(vaccine_rule)
                current_params["vaccines"] = vaccines
                self.update_strategy_params(aid, current_params)
                immunized.append(aid)
                self.update_agent_status(aid, "IDLE", f"Estratégia Imunizada contra {desc}.")
                log.info("[Vacina Pós-Morte] Operador %s vacinado com sucesso: %s", aid, desc)

        return immunized

    def get_all_active_vaccines(self) -> Dict[str, List[Dict[str, Any]]]:
        """Retorna as vacinas registradas em strategy_parameters agrupadas por agent_id."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for aid in self.get_ops_agent_ids():
            params = self.get_strategy_params(aid)
            vacs = params.get("vaccines") or []
            if isinstance(vacs, list) and vacs:
                out[aid] = vacs
        return out

    def get_recent_stop_losses(self, agent_id: str, limit: int = 4) -> List[dict]:
        """Retorna as últimas operações encerradas com Stop Loss ou prejuízo efetivo do agente."""
        raw = self._select("trades_history", eq={"agent_id": agent_id, "status": "CLOSED"},
                           order="closed_at", desc=True, limit=limit * 4)
        sl_trades = []
        for r in raw:
            reason = str(r.get("exit_reason") or "").upper()
            pnl = float(r.get("profit_usd") if r.get("profit_usd") is not None else (r.get("pnl") or 0.0))
            if reason == "SL_HIT" or pnl < 0:
                sl_trades.append(self._normalize_trade(r))
                if len(sl_trades) >= limit:
                    break
        return sl_trades

    # ------------------------------------------------------------ market_context
    def save_market_context(self, crypto_sentiment: float, gold_sentiment: float,
                            red_flag: bool, key_driver: str,
                            headlines: Optional[list] = None) -> None:
        """`headlines` é aceito por compatibilidade, mas a tabela não possui essa coluna."""
        self._insert("market_context", {
            "created_at": _now(), "crypto_sentiment": int(round(crypto_sentiment)),
            "gold_sentiment": int(round(gold_sentiment)),
            "red_flag_pause_trading": bool(red_flag), "key_driver": key_driver,
        })

    def get_latest_market_context(self) -> Optional[dict]:
        rows = self._select("market_context", order="created_at", desc=True, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------ system_config
    def get_system_config(self) -> dict:
        """Obtém configuração global do sistema (trading_mode: 'DEMO' | 'REAL', active_assets: list)."""
        default_assets = ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD"]
        try:
            rows = self._select("system_config", eq={"id": 1}, limit=1)
            if rows:
                cfg = rows[0]
                if not cfg.get("active_assets"):
                    cfg["active_assets"] = default_assets
                return cfg
        except Exception as exc:
            log.warning("get_system_config falhou: %s", exc)
        return {"id": 1, "trading_mode": "DEMO", "active_assets": default_assets}

    def set_system_config(self, trading_mode: str) -> bool:
        """Atualiza o trading_mode global ('DEMO' ou 'REAL')."""
        mode = "REAL" if str(trading_mode).upper() == "REAL" else "DEMO"
        try:
            self._upsert("system_config", {"id": 1, "trading_mode": mode, "updated_at": _now()}, "id")
            log.info("[SYSTEM CONFIG] trading_mode atualizado para %s", mode)
            return True
        except Exception as exc:
            log.error("set_system_config falhou: %s", exc)
            return False

    def set_active_assets(self, assets: list) -> bool:
        """Atualiza a lista de ativos monitorados pelo Sentinela em system_config."""
        try:
            self._upsert("system_config", {"id": 1, "active_assets": assets, "updated_at": _now()}, "id")
            log.info("[SYSTEM CONFIG] active_assets atualizado para %s", assets)
            return True
        except Exception as exc:
            log.error("set_active_assets falhou: %s", exc)
            return False

    # ------------------------------------------------------------ mt5_account_status
    def sync_mt5_account(self, account_data: dict) -> None:
        """Upsert na tabela mt5_account_status (sempre id=1) com métricas financeiras reais do MT5."""
        row = {
            "id": 1,
            "balance": float(account_data.get("balance", 0.0)),
            "equity": float(account_data.get("equity", 0.0)),
            "floating_pnl": float(account_data.get("floating_pnl", 0.0)),
            "free_margin": float(account_data.get("free_margin", 0.0)),
            "margin_level": float(account_data.get("margin_level", 0.0)),
            "total_tp_gain": float(account_data.get("total_tp_gain", 0.0)),
            "total_sl_loss": float(account_data.get("total_sl_loss", 0.0)),
            "win_count": int(account_data.get("win_count", 0)),
            "loss_count": int(account_data.get("loss_count", 0)),
            "is_connected": bool(account_data.get("is_connected", False)),
            "updated_at": _now(),
        }
        try:
            self._upsert("mt5_account_status", row, "id")
            log.info("Status da conta MT5 sincronizado no Supabase (Saldo: $%.2f | Equity: $%.2f | Flutuante: $%.2f)",
                     row["balance"], row["equity"], row["floating_pnl"])
        except Exception as exc:
            log.error("sync_mt5_account falhou: %s", exc)

    def get_mt5_account(self) -> Optional[dict]:
        rows = self._select("mt5_account_status", eq={"id": 1}, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------ trades_history
    @staticmethod
    def _normalize_trade(row: dict) -> dict:
        """Traduz colunas da tabela para os nomes usados pelos setores."""
        row = dict(row)
        row["action"] = row.get("order_type")
        row["id"] = row.get("ticket_mt5")
        row["pnl"] = row.get("profit_usd") if row.get("status") == "CLOSED" else None
        row["rationale"] = row.get("technical_rationale")
        row["execution_account"] = row.get("execution_account") or "REAL"
        return row

    def log_trade(self, agent_id: str, symbol: str, action: str, volume: float,
                  entry_price: float, sl: float, tp: float, risk_amount: float,
                  confidence: float = 0.0, rationale: str = "", ticket: Optional[int] = None,
                  dry_run: bool = True, status: str = "OPEN", pnl: Optional[float] = None,
                  opened_at: Optional[str] = None, closed_at: Optional[str] = None,
                  current_price: Optional[float] = None, exit_reason: Optional[str] = None,
                  execution_account: str = "REAL") -> dict:
        row = {
            # ticket_mt5 é PK sem default: em simulação geramos um número único
            "ticket_mt5": int(ticket) if ticket else uuid.uuid4().int % 10**15,
            "agent_id": agent_id, "symbol": symbol, "order_type": action, "volume": volume,
            "entry_price": entry_price, "current_price": current_price or entry_price,
            "sl": sl, "tp": tp, "status": status,
            "profit_usd": pnl if pnl is not None else 0.0,
            "exit_reason": exit_reason or ("OPEN" if status == "OPEN" else ("TP_HIT" if (pnl or 0) >= 0 else "SL_HIT")),
            "technical_rationale": (rationale or "")[:500],
            "risk_amount": risk_amount, "confidence": confidence, "dry_run": dry_run,
            "opened_at": opened_at or _now(), "closed_at": closed_at,
            "execution_account": execution_account,
        }
        return self._normalize_trade(self._insert("trades_history", row))

    def upsert_trade(self, trade_data: dict) -> None:
        """Upsert direto de trade em trades_history baseado no ticket_mt5."""
        trade_data.setdefault("current_price", trade_data.get("entry_price") or trade_data.get("close_price") or 0.0)
        trade_data.setdefault("entry_price", trade_data.get("close_price") or trade_data.get("current_price") or 0.0)
        trade_data.setdefault("sl", 0.0)
        trade_data.setdefault("tp", 0.0)
        trade_data.setdefault("exit_reason", "OPEN" if trade_data.get("status") == "OPEN" else "TP_HIT")
        trade_data.setdefault("order_type", "BUY")
        trade_data.setdefault("agent_id", "ops_alpha")
        trade_data.setdefault("opened_at", _now())
        trade_data.setdefault("execution_account", "REAL")
        self._upsert("trades_history", trade_data, "ticket_mt5")

    def get_open_trades(self) -> List[dict]:
        return [self._normalize_trade(r) for r in self._select("trades_history", eq={"status": "OPEN"})]

    def close_trade(self, trade_id: Any, pnl: float, exit_price: float, outcome: str) -> None:
        """`trade_id` é o ticket_mt5. `outcome` (TP/SL) é registrado no log e exit_reason."""
        reason = "TP_HIT" if "TP" in outcome.upper() or pnl >= 0 else "SL_HIT"
        self._update("trades_history", {
            "status": "CLOSED", "profit_usd": pnl, "close_price": exit_price,
            "current_price": exit_price, "exit_reason": reason, "closed_at": _now(),
        }, {"ticket_mt5": trade_id})
        log.info("Trade %s fechado por %s (%s): %.2f", trade_id, outcome, reason, pnl)

    def get_trades_last_24h(self) -> List[dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = self._select("trades_history", gte={"opened_at": since}, order="opened_at", desc=False)
        return [self._normalize_trade(r) for r in rows]

    def get_unprocessed_closed_trades(self) -> List[dict]:
        """Trades fechados de agentes ainda não avaliados pela gerência de risco (ordem cronológica)."""
        raw = self._select("trades_history", eq={"status": "CLOSED"})
        rows = [r for r in raw
                if not r.get("risk_processed")
                and r.get("agent_id")
                and str(r.get("status") or "").strip().upper() == "CLOSED"]
        rows.sort(key=lambda r: str(r.get("closed_at") or r.get("opened_at") or ""))
        return [self._normalize_trade(r) for r in rows]

    def mark_trade_processed(self, ticket: Any) -> None:
        self._update("trades_history", {"risk_processed": True}, {"ticket_mt5": ticket})

