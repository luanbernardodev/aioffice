"""Núcleo do motor: A1 (bias + bloqueios) -> A2/A3/A4 (setups) -> A5 (risco) -> broker.

Mesmo objeto roda no backtest (SimBroker por barras), no paper (SimBroker por ticks reais)
e na DEMO (MT5Broker). Nenhuma chamada de LLM ou de rede aqui.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pandas as pd

from engine import strategies as strat
from engine.regime import BIAS_NAME, NewsCalendar, check_gates
from engine.risk import RiskManager
from engine.trade_log import TradeLogger
from engine.types import ClosedTrade, OrderIntent, Position

log = logging.getLogger("engine.core")


class Engine:
    def __init__(self, cfg: Dict[str, Any], broker: Any, risk: Optional[RiskManager] = None,
                 calendar: Optional[NewsCalendar] = None, trade_logger: Optional[TradeLogger] = None,
                 verbose: bool = False) -> None:
        self.cfg = cfg
        self.broker = broker
        self.risk = risk or RiskManager(cfg)
        self.calendar = calendar
        self.trade_logger = trade_logger
        self.verbose = verbose
        self.filled_keys: set = set()
        self.group_count: Dict[tuple, int] = defaultdict(int)
        self.last_atr: Dict[str, float] = {}
        self.closed: List[ClosedTrade] = []
        self.last_status: Dict[str, str] = {}
        broker.on_fill = self._on_fill
        broker.on_close = self._on_close

    # ------------------------------------------------------------ EntryState
    def group_entries(self, agent: str, symbol: str, group: str) -> int:
        return self.group_count[(agent, symbol, group)]

    def is_filled(self, key: str) -> bool:
        return key in self.filled_keys

    # ------------------------------------------------------------ callbacks do broker
    def _on_fill(self, pos: Position) -> None:
        if pos.key in self.filled_keys:
            return
        self.filled_keys.add(pos.key)
        self.group_count[(pos.agent, pos.symbol, pos.group)] += 1
        log.info("[EXEC] %s %s %s %s @ %.5f sl=%.5f tp=%.5f", pos.agent, pos.setup, pos.symbol,
                 "BUY" if pos.side > 0 else "SELL", pos.entry, pos.sl, pos.tp)

    def _on_close(self, t: ClosedTrade) -> None:
        self.closed.append(t)
        self.risk.on_trade_closed(t)
        if self.trade_logger:
            self.trade_logger.log(t)

    # ------------------------------------------------------------ gestão contínua (A5 trailing)
    def manage(self, symbol: str, bid: float, ask: float) -> None:
        atr = self.last_atr.get(symbol)
        if not atr:
            return
        spread = max(ask - bid, 0.0)
        for pos in self.broker.open_positions(symbol):
            new_sl = self.risk.trail(pos, bid, ask, atr, spread)
            if new_sl is not None and self.broker.modify_sl(pos.id, new_sl):
                if self.verbose:
                    log.info("[A5 TRAIL] %s %s SL -> %.5f", pos.symbol, pos.id, new_sl)

    # ------------------------------------------------------------ decisão por barra fechada
    def on_bar(self, symbol: str, feats: Dict[str, pd.DataFrame], i: int, now: pd.Timestamp,
               spread: float, quote: Optional[tuple] = None) -> List[OrderIntent]:
        d5 = feats["m5"]
        scfg = self.cfg["symbols"][symbol]
        acfgs = self.cfg.get("agents", {})
        atr = float(d5["atr"].iat[i])
        self.last_atr[symbol] = atr
        now_dt = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now

        allowed, why = self.risk.trading_allowed(now_dt)
        gate = check_gates(now_dt, scfg, spread, atr, self.calendar)
        status = f"bias={BIAS_NAME.get(int(d5['bias'].iat[i]))} " + ("OK" if allowed and gate.ok else (why or gate.reason))
        if self.verbose and self.last_status.get(symbol) != status:
            log.info("[A1] %s %s", symbol, status)
        self.last_status[symbol] = status

        if not allowed or not gate.ok:
            if not allowed or not gate.reason.startswith("spread"):
                for it in list(self.broker.pending_orders(symbol)):
                    if it.kind == "LIMIT":
                        self.broker.cancel(it.key)
            return []

        desired: List[OrderIntent] = []
        for agent in scfg.get("agents", []):
            acfg = acfgs.get(agent, {})
            if agent == "A2_PULLBACK":
                desired += strat.a2_pullback(d5, i, symbol, acfg, self, spread)
            elif agent == "A3_BOS_RETEST":
                desired += strat.a3_bos_retest(d5, i, symbol, acfg, self, spread)
            elif agent == "A4_RSI_REVERSAL":
                if bool(d5["m15_new"].iat[i]) and int(d5["m15_i"].iat[i]) >= 0:
                    desired += strat.a4_rsi_reversal(feats["m15"], int(d5["m15_i"].iat[i]), symbol, acfg,
                                                     self, atr_m5=atr, spread=spread)
        return self._reconcile(symbol, desired, now, quote)

    def _reconcile(self, symbol: str, desired: List[OrderIntent], now: pd.Timestamp,
                   quote: Optional[tuple]) -> List[OrderIntent]:
        lot = float(self.cfg["symbols"][symbol].get("lot", 0.01))
        want = {it.key: it for it in desired if it.kind == "LIMIT"}
        current = {it.key: it for it in self.broker.pending_orders(symbol) if it.kind == "LIMIT"}
        for k in current.keys() - want.keys():
            self.broker.cancel(k)
        sent: List[OrderIntent] = []
        for it in desired:
            if it.key in self.filled_keys:
                continue
            fin = self.risk.finalize(it)
            if fin is None:
                continue
            if it.kind == "LIMIT" and it.key in current:
                cur = current[it.key]
                tol = 0.1 * (it.atr or 0)
                if abs(cur.price - fin.price) > tol or abs(cur.sl - fin.sl) > tol:
                    self.broker.modify(fin)
                continue
            if it.kind == "MARKET" and any(p.key == it.key for p in self.broker.pending_orders(symbol)):
                continue
            total = len(self.broker.open_positions()) + len(self.broker.pending_orders())
            per_sym = len(self.broker.open_positions(symbol)) + len(self.broker.pending_orders(symbol))
            ok, why = self.risk.exposure_ok(symbol, total, per_sym)
            if not ok:
                if self.verbose:
                    log.info("[A5] %s recusado: %s", it.key, why)
                continue
            if self.broker.place(fin, lot, now):
                sent.append(fin)
                if self.verbose:
                    log.info("[ORDEM] %s %s %s %s px=%.5f sl=%.5f tp1=%.5f tp=%.5f", fin.kind, fin.agent,
                             fin.setup, symbol, fin.price, fin.sl, fin.tp1, fin.tp)
        return sent
