"""CAPITULATION — compra de exaustão em BTCUSD (magic exclusivo). Determinístico, sem LLM.

A cada M5 fechada calcula o RSI(14) do M15 com a barra em formação. RSI <= 10 arma o episódio; enquanto RSI < 20
compra uma vez por M5 (máx. 3 posições), até algum stop ficar positivo. Cada posição: SL inicial 2*A, sem TP;
ao atingir +0.5*A o stop segue a 0.25*A do bid a cada tick; saída por tempo em 240 min.
A = ATR14 de Wilder da M5 do sinal, fixo. Regras em agents/capitulation_rules.py.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from agents.capitulation_rules import episode_step, rsi_state, rsi_with_partial, trail_buy
from agents.sweep48 import BUY, Sweep48Agent, loss_limit_usd
from engine import indicators as ind
from engine.config import ROOT
from engine.mt5_broker import verify_account

log = logging.getLogger("agents.capitulation")


class CapitulationAgent(Sweep48Agent):
    """Reaproveita persistência, CSV, envio e sincronização de SL do Sweep48Agent; gerencia várias posições."""

    def __init__(self, mt5: Any, cfg: Dict[str, Any], state_path: Optional[Path] = None,
                 csv_path: Optional[Path] = None) -> None:
        self.mt5, self.cfg = mt5, cfg
        self.g = cfg["capitulation"]
        self.symbol = self.g["symbol"]
        self.magic = int(self.g["magic"])
        self.lot = float(self.g["lot"])
        self.state_path = Path(state_path or ROOT / "state" / "capitulation.json")
        self.csv_path = Path(csv_path or ROOT / "logs" / "capitulation_trades.csv")
        self.state: Dict[str, Any] = {"halted": False, "halt_reason": "", "last_bar": 0, "trades": {}, "pending": None,
                                      "armed": False, "locked": False}
        self.realized = 0.0
        self.limit = 0.0
        self.last_msc = 0
        self.last_head = 0
        self.last_sl_send = 0.0
        self.last_close_try = 0.0
        self.exit_reason = ""
        self.missing: Dict[str, int] = {}

    # ------------------------------------------------------------ inicialização e recuperação
    def start(self) -> None:
        verify_account(self.mt5, self.cfg)
        self.mt5.symbol_select(self.symbol, True)
        si = self.mt5.symbol_info(self.symbol)
        self.point, self.digits = float(si.point), int(si.digits)
        self.stops_level, self.freeze_level = int(si.trade_stops_level), int(si.trade_freeze_level)
        self.contract, self.filling_mode = float(si.trade_contract_size), int(si.filling_mode)
        self.limit = loss_limit_usd(float(self.g["loss_limit_usd_per_btc"]), self.lot, self.contract)
        self._load()
        self.realized = self._realized()
        log.info("[CAPITULATION] %s magic=%s lote=%s | gatilho RSI<=%s, novas compras RSI<%s, máx %s | limite=%.2f USD | "
                 "acumulado=%.2f USD", self.symbol, self.magic, self.lot, self.g["trigger_rsi"], self.g["add_rsi"],
                 self.g["max_entries"], self.limit, self.realized)
        if self.state["halted"]:
            log.warning("[CAPITULATION] PARADO: %s", self.state["halt_reason"])
        self._recover_all()

    def _positions(self) -> List[Any]:
        return [p for p in (self.mt5.positions_get(symbol=self.symbol) or []) if int(p.magic) == self.magic]

    def _recover_all(self) -> None:
        for pos in self._positions():
            self._adopt(pos)
        self.state["pending"] = None
        self._save()

    def _adopt(self, pos: Any) -> None:
        key = str(pos.ticket)
        tr = self.state["trades"].get(key) or self.state.get("pending") or {}
        bar = tr.get("signal_bar")
        a = self._atr_of_bar(bar) if bar else None
        a = a or tr.get("A") or (abs(float(pos.price_open) - float(pos.sl)) / float(self.g["sl_atr"]) if pos.sl else None)
        if not a:
            log.error("[CAPITULATION] posição #%s sem A e sem SL: fechando por segurança", pos.ticket)
            self.state["trades"][key] = {"ticket": int(pos.ticket), "A": 0.0, "side": BUY, "sl": 0.0, "signal_bar": bar}
            self._close(pos, "RECUPERACAO_SEM_A")
            return
        sl = max(float(pos.sl), float(tr.get("sl") or 0.0)) or float(pos.price_open) - float(self.g["sl_atr"]) * a
        self.state["trades"][key] = {"ticket": int(pos.ticket), "A": float(a), "side": BUY, "sl": sl, "signal_bar": bar}
        self._save()
        self._csv("RECOVER", ticket=pos.ticket, signal_bar_server=bar, side=BUY, A=a, sl=sl, executed=pos.price_open)
        log.warning("[CAPITULATION] posição #%s adotada: A=%.2f SL em código=%.2f", pos.ticket, a, sl)

    # ------------------------------------------------------------ gestão por tick
    def _manage(self, pos: Any, tick: Any) -> None:
        tr = self.state["trades"].get(str(pos.ticket))
        if tr is None:
            self._adopt(pos)
            return
        a, entry = float(tr["A"]), float(pos.price_open)
        self.last_close_try, self.exit_reason = tr.get("_close_try", 0.0), tr.get("exit_reason", "")
        if float(tick.time_msc) / 1000 - int(pos.time) >= float(self.g["max_minutes"]) * 60:
            self._close(pos, "TEMPO")
        else:
            trig, dist = float(self.g["trail_trigger_atr"]), float(self.g["trail_dist_atr"])
            tr["sl"] = trail_buy(entry, float(tr["sl"]), float(tick.bid), a, trig, dist)
            if float(tick.bid) - entry >= trig * a and not self.state["locked"]:
                self.state["locked"] = True
                self._save()
                log.info("[CAPITULATION] #%s com stop positivo: novas compras encerradas neste episódio", pos.ticket)
            if float(tick.bid) <= tr["sl"]:
                self._close(pos, "STOP_EM_CODIGO")
            else:
                self.last_sl_send = tr.get("_sl_send", 0.0)
                self._sync_broker_sl(pos, tr, tick)
                tr["_sl_send"] = self.last_sl_send
        tr["_close_try"], tr["exit_reason"] = self.last_close_try, self.exit_reason

    def _finish_one(self, key: str) -> None:
        deals = self.mt5.history_deals_get(position=int(key)) or []
        out = [d for d in deals if int(d.entry) in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_OUT_BY)]
        if not out and self.missing.get(key, 0) < 50:   # histórico ainda não atualizou
            self.missing[key] = self.missing.get(key, 0) + 1
            return
        tr = self.state["trades"].pop(key)
        self.missing.pop(key, None)
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        reasons = {self.mt5.DEAL_REASON_SL: "SL", self.mt5.DEAL_REASON_TP: "TP"}
        reason = tr.get("exit_reason") or (reasons.get(int(out[-1].reason), "EXTERNO") if out else "SEM_HISTORICO")
        self._csv("EXIT", ticket=key, signal_bar_server=tr.get("signal_bar"), side=BUY, A=tr.get("A"),
                  exit_price=out[-1].price if out else "", profit=round(profit, 2), reason=reason)
        log.info("[CAPITULATION] SAÍDA #%s (%s) resultado=%.2f USD", key, reason, profit)
        self.realized = self._realized()
        self._save()

    # ------------------------------------------------------------ sinal por M5 fechada
    def _live_rsi(self, m5_time: int, price: float) -> float:
        r = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_M15, 0, 800)
        if r is None or len(r) < 100:
            return float("nan")
        df = pd.DataFrame(r)
        hit = df.index[df["time"] == int(m5_time) - int(m5_time) % 900]
        if len(hit) == 0 or hit[0] == 0:
            return float("nan")
        k = int(hit[0])
        g, l = rsi_state(df["close"].iloc[:k])
        return rsi_with_partial(float(g[-1]), float(l[-1]), float(df["close"].iat[k - 1]), price)

    def _enter(self, a: float, bar: int, tick: Any, r: float) -> None:
        price = float(tick.ask)
        sl = round(price - float(self.g["sl_atr"]) * a, self.digits)
        req = self.build_buy(price, sl)
        self.state["pending"] = {"A": a, "signal_bar": bar, "sl": sl}     # antes do envio: queda ainda recupera A
        self._save()
        res = self._send(req)
        rc = getattr(res, "retcode", None)
        ok = res is not None and rc == self.mt5.TRADE_RETCODE_DONE
        fill = float(res.price) if ok else ""
        self._csv("ORDER", ticket=getattr(res, "order", ""), signal_bar_server=bar, side=BUY, A=a,
                  spread=round(tick.ask - tick.bid, self.digits), requested=price, executed=fill,
                  slippage=round(fill - price, self.digits) if ok else "", retcode=rc, sl=sl, tp=0,
                  reason=f"RSI={r:.1f}", detail=getattr(res, "comment", str(self.mt5.last_error())))
        self.state["pending"] = None
        if ok:
            self.state["trades"][str(int(res.order))] = {"ticket": int(res.order), "A": a, "side": BUY, "sl": sl, "signal_bar": bar}
            log.info("[CAPITULATION] COMPRA ticket=%s RSI=%.1f pedido=%.2f executado=%.2f sl=%.2f", res.order, r, price, fill, sl)
        else:
            log.error("[CAPITULATION] ordem recusada: retcode=%s %s", rc, getattr(res, "comment", self.mt5.last_error()))
        self._save()

    def build_buy(self, price: float, sl: float) -> Dict[str, Any]:
        return {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.lot,
                "type": self.mt5.ORDER_TYPE_BUY, "price": price, "sl": sl, "tp": 0.0,
                "deviation": int(self.g["deviation_points"]), "magic": self.magic, "comment": "CAPITULATION",
                "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling()}

    def _new_bar(self, positions: List[Any], tick: Any) -> None:
        df = self._bars(500)
        if df is None or len(df) < 100:
            return
        bar, close = int(df["time"].iat[-1]), float(df["close"].iat[-1])
        if bar == int(self.state.get("last_bar") or 0):
            return
        self.state["last_bar"] = bar
        r = self._live_rsi(bar, close)
        a = float(ind.atr(df, 14).iat[-1])
        if np.isnan(r) or np.isnan(a):
            self._save()
            return
        was = self.state["armed"]
        self.state["armed"], self.state["locked"], buy = episode_step(
            was, self.state["locked"], r, float(self.g["trigger_rsi"]), float(self.g["add_rsi"]),
            len(positions), int(self.g["max_entries"]))
        self._save()
        if self.state["armed"] and not was:
            log.warning("[CAPITULATION] EPISÓDIO ARMADO: RSI=%.1f", r)
            self._csv("ARMED", signal_bar_server=bar, A=round(a, self.digits), reason=f"RSI={r:.1f}")
        if buy and float(tick.time) - (bar + 300) <= float(self.g["signal_max_age_seconds"]):
            self._enter(a, bar, tick, r)

    # ------------------------------------------------------------ loop
    def step(self) -> None:
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None or int(tick.time_msc) == self.last_msc:
            return
        self.last_msc = int(tick.time_msc)
        positions = self._positions()
        floating = sum(float(p.profit) + float(p.swap) for p in positions)
        if not self.state["halted"] and self.realized + floating <= self.limit:
            self._halt(f"limite de perda atingido: {self.realized + floating:.2f} <= {self.limit:.2f} USD")
        live = {str(p.ticket) for p in positions}
        for key in [k for k in self.state["trades"] if k not in live]:
            self._finish_one(key)
        if self.state["halted"]:
            for p in positions:
                self.last_close_try = 0.0
                self._close(p, "AGENTE_PARADO")
            return
        for p in positions:
            self._manage(p, tick)
        head = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_M5, 0, 1)
        if head is None or len(head) == 0 or int(head[0]["time"]) == self.last_head:
            return
        self.last_head = int(head[0]["time"])
        self._new_bar(self._positions(), tick)

    def run_forever(self) -> None:
        pause = float(self.g.get("poll_ms", 50)) / 1000
        last_hb = 0.0
        while True:
            self.step()
            if time.time() - last_hb >= 60:
                last_hb = time.time()
                log.info("[CAPITULATION HEARTBEAT] posições=%d | armado=%s | acumulado=%.2f USD | parado=%s",
                         len(self.state["trades"]), self.state["armed"], self.realized, self.state["halted"])
            time.sleep(pause)
