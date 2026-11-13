"""Agente genérico v3 (competição 11/2026): executa uma estratégia da grade backtest/agentes_v3 ao vivo.

Mesmas regras do backtest (backtest/agentes_v3/bt.py), barra a barra do timeframe do agente:
  * fechou uma barra e não há posição: sinal da barra (agents/v3_signals.py, com filtro de sessão) ->
    ordem a mercado; SL = entrada -/+ sl x ATR(sinal), TP = entrada +/- tp x ATR(sinal) (0 = sem TP);
  * fechou uma barra com posição: melhor preço desde a entrada -> trailing (só a favor, >= 1 tick) e
    saída por tempo após max_bars barras (fecha a mercado). Não reabre na mesma barra.
Guardas FIXAS: só conta DEMO, 1 posição por agente, magic exclusivo, spread acima de max_spread bloqueia a
entrada, perda acumulada do magic (realizado + flutuante) <= -loss_limit_usd -> zera e desliga (gravado),
kill switch (kill_switch: true no YAML ou arquivo state/KILL_<NOME>).
"""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from agents import v3_signals as V
from engine.config import ROOT
from engine.features import server_to_utc
from engine.mt5_broker import AccountGuardError, verify_account

log = logging.getLogger("agents.v3")

CONFIG_PATH = ROOT / "config" / "agente_v3_competicao.yaml"
TF_MIN = {"M5": 5, "M15": 15, "H1": 60}
CSV_FIELDS = ["ts_utc", "agent", "event", "ticket", "side", "bar_utc", "A", "spread", "price", "sl", "tp",
              "profit", "reason", "detail"]


def load_agents_config(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and "magic" in v}


class V3Agent:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], section: str, g: Dict[str, Any],
                 state_dir: Optional[Path] = None, clock=None) -> None:
        self.mt5, self.cfg, self.section, self.g = mt5, cfg, section, g
        self.name = str(g.get("name", section))
        self.tag = f"[{self.name.upper()}]"
        self.symbol, self.magic, self.tf = g["symbol"], int(g["magic"]), str(g["timeframe"])
        self.bar_min = TF_MIN[self.tf]
        self.spec, self.ex = dict(g["signal"]), dict(g["exit"])
        self.max_bars = int(g.get("max_bars", 96))
        self.server_time = cfg.get("account", {}).get("server_time", "ny_plus_7")
        sd = Path(state_dir or ROOT / "state")
        self.state_path = sd / f"{self.name}.json"
        self.kill_file = sd / f"KILL_{self.name.upper()}"
        self.csv_path = ROOT / "logs" / "v3_trades.csv"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.state: Dict[str, Any] = {"last_bar": 0, "trades": {}, "halted": ""}
        self.last_head = 0
        self.last_close_try: Dict[str, float] = {}
        self.realized, self.realized_at = 0.0, 0.0

    # ------------------------------------------------------------ persistência e log
    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self.state.update(json.loads(self.state_path.read_text()))
            except (ValueError, OSError) as exc:
                log.error("%s estado ilegível (%s)", self.tag, exc)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_path)

    def _csv(self, event: str, **kw: Any) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"ts_utc": self.clock().isoformat(), "agent": self.name, "event": event, **kw})

    # ------------------------------------------------------------ conta e símbolo
    def _check_account(self) -> Any:
        info = self.mt5.account_info()
        if info is None:
            raise AccountGuardError("MT5 sem conta conectada")
        if int(info.trade_mode) != int(getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)):
            raise AccountGuardError(f"{self.name} roda só em conta DEMO; conta #{info.login} recusada")
        return verify_account(self.mt5, self.cfg)

    def start(self) -> None:
        self._check_account()
        self.mt5.symbol_select(self.symbol, True)
        si = self.mt5.symbol_info(self.symbol)
        self.point, self.digits = float(si.point), int(si.digits)
        self.tick_size = float(getattr(si, "trade_tick_size", 0) or si.point)
        self.filling_mode = int(getattr(si, "filling_mode", 0))
        lot = self.g.get("lot", "min")
        self.lot = float(si.volume_min) if str(lot).lower() == "min" else float(lot)
        self._load()
        for p in self._positions():
            if str(p.ticket) not in self.state["trades"]:
                self._adopt(p)
        self._save()
        log.info("%s %s %s magic=%s lote=%s | sinal %s | saída %s | max %d barras | limite -%.2f USD%s", self.tag,
                 self.symbol, self.tf, self.magic, self.lot, self.spec, self.ex, self.max_bars,
                 float(self.g.get("loss_limit_usd", 0)), f" | PARADO: {self.state['halted']}" if self.state["halted"] else "")

    def _positions(self) -> List[Any]:
        return [p for p in (self.mt5.positions_get(symbol=self.symbol) or []) if int(p.magic) == self.magic]

    def _rates(self) -> Optional[pd.DataFrame]:
        tfc = getattr(self.mt5, f"TIMEFRAME_{self.tf}")
        r = self.mt5.copy_rates_from_pos(self.symbol, tfc, 1, int(self.g.get("bars", 1200)))
        if r is None or len(r) < 400:
            return None
        df = pd.DataFrame(r)
        df["server_time"] = df["time"].astype("int64")
        df["time"] = server_to_utc(df["server_time"].to_numpy(), self.server_time).to_numpy()
        return df

    def killed(self) -> bool:
        return self.kill_file.exists() or bool(self.g.get("kill_switch", False)) or not bool(self.g.get("enabled", True))

    # ------------------------------------------------------------ ordens
    def _filling(self) -> int:
        if self.filling_mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        if self.filling_mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: Dict[str, Any]) -> Any:
        self._check_account()
        return self.mt5.order_send(req)

    def _ok(self, res: Any) -> bool:
        return res is not None and getattr(res, "retcode", None) == self.mt5.TRADE_RETCODE_DONE

    def _round(self, px: float) -> float:
        return round(round(px / self.tick_size) * self.tick_size, self.digits)

    def _enter(self, side: int, a0: float, bar_server: int, tick: Any) -> None:
        price = float(tick.ask if side == 1 else tick.bid)
        sl, tp = V.initial_levels(side, price, a0, self.ex)
        req = {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.lot,
               "type": self.mt5.ORDER_TYPE_BUY if side == 1 else self.mt5.ORDER_TYPE_SELL, "price": price,
               "sl": self._round(sl), "tp": self._round(tp) if tp else 0.0,
               "deviation": int(self.g.get("deviation_points", 500)), "magic": self.magic,
               "comment": f"V3|{self.name}"[:31], "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling()}
        res = self._send(req)
        ok = self._ok(res)
        self._csv("ORDER" if ok else "ORDER_FAIL", ticket=getattr(res, "order", ""), side=side, bar_utc=bar_server,
                  A=round(a0, 5), spread=round(float(tick.ask - tick.bid), self.digits), price=price, sl=req["sl"],
                  tp=req["tp"], detail=f"retcode={getattr(res, 'retcode', None)}")
        if not ok:
            log.error("%s ordem recusada: retcode=%s %s", self.tag, getattr(res, "retcode", None),
                      getattr(res, "comment", self.mt5.last_error()))
            return
        fill = float(getattr(res, "price", 0) or price)
        self.state["trades"][str(int(res.order))] = {"side": side, "entry": fill, "A": a0, "sl": req["sl"],
                                                     "entry_bar": int(bar_server) + self.bar_min * 60}
        self._save()
        log.info("%s %s ticket=%s @%.5f SL=%.5f TP=%s A=%.5f", self.tag, "COMPRA" if side == 1 else "VENDA", res.order,
                 fill, req["sl"], req["tp"], a0)

    def _close(self, pos: Any, reason: str) -> bool:
        key = str(pos.ticket)
        if time.time() - self.last_close_try.get(key, 0.0) < 5.0:
            return False
        self.last_close_try[key] = time.time()
        tick = self.mt5.symbol_info_tick(self.symbol)
        buy = int(pos.type) == int(self.mt5.POSITION_TYPE_BUY)
        res = self._send({"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(pos.volume),
                          "type": self.mt5.ORDER_TYPE_SELL if buy else self.mt5.ORDER_TYPE_BUY,
                          "position": int(pos.ticket), "price": float(tick.bid if buy else tick.ask),
                          "deviation": int(self.g.get("deviation_points", 500)), "magic": self.magic,
                          "comment": f"V3|{self.name} {reason}"[:31], "type_time": self.mt5.ORDER_TIME_GTC,
                          "type_filling": self._filling()})
        ok = self._ok(res)
        if key in self.state["trades"]:
            self.state["trades"][key]["exit_reason" if ok else "exit_pending"] = reason
            self._save()
        log.log(logging.INFO if ok else logging.ERROR, "%s fechamento #%s (%s): retcode=%s", self.tag, pos.ticket,
                reason, getattr(res, "retcode", None))
        return ok

    def _set_sl(self, pos: Any, new_sl: float) -> None:
        sl = self._round(new_sl)
        cur = float(pos.sl or 0.0)
        side = 1 if int(pos.type) == int(self.mt5.POSITION_TYPE_BUY) else -1
        if cur and (sl - cur) * side < self.tick_size - 1e-12:
            return
        res = self._send({"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol, "position": int(pos.ticket),
                          "sl": sl, "tp": float(pos.tp), "magic": self.magic})
        code = getattr(res, "retcode", None)
        if self._ok(res) or code == 10025:
            self.state["trades"][str(pos.ticket)]["sl"] = sl
            self._save()
            if code != 10025:
                self._csv("SL_CHANGE", ticket=pos.ticket, side=side, sl=sl)
                log.info("%s #%s SL -> %.5f", self.tag, pos.ticket, sl)
        else:
            log.warning("%s #%s SL -> %.5f recusado (retcode=%s)", self.tag, pos.ticket, sl, code)

    # ------------------------------------------------------------ recuperação e fim
    def _adopt(self, p: Any) -> None:
        side = 1 if int(p.type) == int(self.mt5.POSITION_TYPE_BUY) else -1
        a0 = abs(float(p.price_open) - float(p.sl)) / float(self.ex["sl"]) if p.sl else 0.0
        bar = int(p.time) - int(p.time) % (self.bar_min * 60)
        self.state["trades"][str(p.ticket)] = {"side": side, "entry": float(p.price_open), "A": a0,
                                               "sl": float(p.sl), "entry_bar": bar}
        log.warning("%s posição #%s adotada (A=%.5f)", self.tag, p.ticket, a0)

    def _finish(self, key: str) -> None:
        deals = self.mt5.history_deals_get(position=int(key)) or []
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        tr = self.state["trades"].pop(key)
        out = [d for d in deals if int(d.entry) in (1, 3)]
        reason = tr.get("exit_reason") or ({4: "SL", 5: "TP"}.get(int(out[-1].reason), "EXTERNO") if out else "?")
        self._csv("EXIT", ticket=key, side=tr.get("side"), price=out[-1].price if out else "", profit=round(profit, 2),
                  reason=reason)
        log.info("%s SAÍDA #%s (%s) resultado=%.2f USD", self.tag, key, reason, profit)
        self.realized_at = 0.0
        self._save()

    def _realized_total(self) -> float:
        if time.time() - self.realized_at < 60:
            return self.realized
        self.realized_at = time.time()
        now = self.clock()
        deals = self.mt5.history_deals_get(datetime(2020, 1, 1), now.replace(tzinfo=None) + timedelta(days=2)) or []
        self.realized = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals
                            if int(d.magic) == self.magic and int(d.type) in (0, 1))
        return self.realized

    # ------------------------------------------------------------ barra fechada
    def _manage_bar(self, pos: Any, df: pd.DataFrame) -> None:
        tr = self.state["trades"].get(str(pos.ticket))
        if not tr or not tr.get("A"):
            return
        side = int(tr["side"])
        since = df[df["server_time"] >= int(tr["entry_bar"])]
        if len(since) >= self.max_bars:
            self._close(pos, f"TEMPO_{self.max_bars}")
            return
        if since.empty:
            return
        sp = since["spread"].to_numpy(float) * self.point if "spread" in since else 0.0
        best = float(since["high"].max()) if side == 1 else float((since["low"] + sp).min())
        best = max(best, tr["entry"]) if side == 1 else min(best, tr["entry"])
        new = V.trail_after_close(side, float(tr["entry"]), float(tr["sl"]), best, float(tr["A"]), self.ex)
        if (new - float(tr["sl"])) * side > 0:
            self._set_sl(pos, new)

    def _on_new_bar(self, tick: Any) -> None:
        df = self._rates()
        if df is None:
            return
        bar = int(df["server_time"].iat[-1])
        if bar == int(self.state.get("last_bar") or 0):
            return
        self.state["last_bar"] = bar
        self._save()
        positions = self._positions()
        for p in positions:
            self._manage_bar(p, df)
        if positions or self.state["halted"] or self.killed():
            return
        side, a0 = V.entry_signal_now(df[["time", "open", "high", "low", "close"]], self.spec, self.bar_min)
        if side == 0 or not a0 > 0:
            return
        spread = float(tick.ask - tick.bid)
        mx = float(self.g.get("max_spread", 0) or 0)
        age = float(tick.time) - (bar + self.bar_min * 60)
        why = ("spread %.5f > %.5f" % (spread, mx)) if mx and spread > mx else \
              ("sinal atrasado %.0fs" % age) if age > float(self.g.get("signal_max_age_seconds", 120)) else ""
        self._csv("SIGNAL", side=side, bar_utc=bar, A=round(a0, 5), spread=round(spread, self.digits),
                  detail=f"ignorado: {why}" if why else "")
        log.info("%s SINAL %s barra=%s A=%.5f%s", self.tag, "COMPRA" if side == 1 else "VENDA", bar, a0,
                 f" (ignorado: {why})" if why else "")
        if not why:
            self._enter(side, a0, bar, tick)

    # ------------------------------------------------------------ passo do loop
    def step(self) -> None:
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return
        positions = self._positions()
        live = {str(p.ticket) for p in positions}
        for key in [k for k in self.state["trades"] if k not in live]:
            self._finish(key)
        for p in positions:
            if str(p.ticket) not in self.state["trades"]:
                self._adopt(p)
        if self.killed() or self.state["halted"]:
            for p in positions:
                self._close(p, "KILL" if self.killed() else "LIMITE")
            return
        limit = float(self.g.get("loss_limit_usd", 0) or 0)
        if limit > 0:
            total = self._realized_total() + sum(float(p.profit) + float(p.swap) for p in positions)
            if total <= -limit:
                self.state["halted"] = f"perda acumulada {total:.2f} <= -{limit:.2f} USD"
                self._save()
                self._csv("HALT", profit=round(total, 2), reason=self.state["halted"])
                log.critical("%s PARADO: %s", self.tag, self.state["halted"])
                return
        for p in positions:
            tr = self.state["trades"].get(str(p.ticket), {})
            if tr.get("exit_pending"):
                self._close(p, tr["exit_pending"])
        head = self.mt5.copy_rates_from_pos(self.symbol, getattr(self.mt5, f"TIMEFRAME_{self.tf}"), 0, 1)
        if head is None or len(head) == 0 or int(head[0]["time"]) == self.last_head:
            return
        self.last_head = int(head[0]["time"])
        self._on_new_bar(tick)
