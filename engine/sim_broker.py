"""Broker simulado — usado pelo BACKTEST (barras) e pelo PAPER/DRY_RUN ao vivo (ticks reais do MT5).

Convenções conservadoras:
- Preços das barras são BID; ASK = BID + spread.
- BUY LIMIT executa se ASK mínima <= preço; SELL LIMIT se BID máxima >= preço (gap: melhor preço da abertura).
- MARKET no backtest executa na abertura da barra seguinte (com spread).
- SL e TP tocados na mesma barra -> assume SL. Barra da execução também é checada.
- BUY sai no BID; SELL sai no ASK.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

from engine.types import BUY, ClosedTrade, OrderIntent, Position


@dataclass
class Pending:
    intent: OrderIntent
    volume: float
    placed_at: pd.Timestamp


class SimBroker:
    def __init__(self, specs: Dict[str, Dict[str, float]], immediate_market: bool = False) -> None:
        """specs[symbol] = {"value_per_unit": USD por 1.0 de preço por 1 lote}."""
        self.specs = specs
        self.immediate_market = immediate_market
        self.pending: Dict[str, Pending] = {}
        self.positions: Dict[str, Position] = {}
        self.market_queue: List[Pending] = []
        self.on_fill: Optional[Callable[[Position], None]] = None
        self.on_close: Optional[Callable[[ClosedTrade], None]] = None
        self._ids = itertools.count(1)
        self.last_quote: Dict[str, tuple] = {}

    # ------------------------------------------------------------ consultas
    def pending_orders(self, symbol: Optional[str] = None) -> List[OrderIntent]:
        return [p.intent for p in self.pending.values() if symbol is None or p.intent.symbol == symbol] + \
               [p.intent for p in self.market_queue if symbol is None or p.intent.symbol == symbol]

    def open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        return [p for p in self.positions.values() if symbol is None or p.symbol == symbol]

    # ------------------------------------------------------------ ações
    def place(self, it: OrderIntent, volume: float, now: pd.Timestamp) -> bool:
        if it.kind == "LIMIT":
            self.pending[it.key] = Pending(it, volume, now)
            return True
        if self.immediate_market and it.symbol in self.last_quote:
            bid, ask = self.last_quote[it.symbol]
            self._open(it, volume, ask if it.side == BUY else bid, now)
            return True
        self.market_queue.append(Pending(it, volume, now))
        return True

    def cancel(self, key: str) -> None:
        self.pending.pop(key, None)

    def modify(self, it: OrderIntent) -> None:
        if it.key in self.pending:
            self.pending[it.key].intent = it

    def modify_sl(self, pos_id: str, sl: float) -> bool:
        p = self.positions.get(pos_id)
        if p is None:
            return False
        p.sl = sl
        p.be_locked = True
        return True

    # ------------------------------------------------------------ simulação
    def _open(self, it: OrderIntent, volume: float, price: float, t: pd.Timestamp) -> Position:
        pid = f"S{next(self._ids)}"
        pos = Position(pid, it.key, it.agent, it.symbol, it.side, volume, price, it.sl, it.tp, it.tp1, it.sl,
                       it.setup, it.group, t, atr_at_entry=it.atr, spread_at_entry=it.spread)
        self.positions[pid] = pos
        if self.on_fill:
            self.on_fill(pos)
        return pos

    def _close(self, pos: Position, price: float, t: pd.Timestamp, reason: str) -> None:
        self.positions.pop(pos.id, None)
        vpu = self.specs.get(pos.symbol, {}).get("value_per_unit", 1.0)
        pnl = (price - pos.entry) * pos.side * pos.volume * vpu
        r = (price - pos.entry) * pos.side / pos.initial_risk if pos.initial_risk > 0 else 0.0
        tr = ClosedTrade(pos.agent, pos.setup, pos.symbol, pos.side, pos.volume, pos.entry, pos.initial_sl,
                         pos.tp, pos.tp1, price, pos.opened_at, t, reason, pnl, r,
                         pos.spread_at_entry, pos.atr_at_entry, ticket=pos.id, group=pos.group)
        if self.on_close:
            self.on_close(tr)

    def process_bar(self, symbol: str, t_open: pd.Timestamp, t_close: pd.Timestamp,
                    o: float, h: float, l: float, c: float, spread: float) -> None:
        self.last_quote[symbol] = (c, c + spread)
        # 1) expiração de pendentes
        for k, p in list(self.pending.items()):
            if p.intent.symbol == symbol and p.intent.expiry is not None and p.intent.expiry <= t_open:
                self.pending.pop(k, None)
        # 2) ordens a mercado enfileiradas -> abertura desta barra
        keep = []
        for p in self.market_queue:
            if p.intent.symbol != symbol:
                keep.append(p)
                continue
            self._open(p.intent, p.volume, o + spread if p.intent.side == BUY else o, t_open)
        self.market_queue = keep
        # 3) LIMITs
        for k, p in list(self.pending.items()):
            it = p.intent
            if it.symbol != symbol:
                continue
            if it.side == BUY and l + spread <= it.price:
                self.pending.pop(k)
                self._open(it, p.volume, min(it.price, o + spread), t_open)
            elif it.side != BUY and h >= it.price:
                self.pending.pop(k)
                self._open(it, p.volume, max(it.price, o), t_open)
        # 4) saídas
        for pos in list(self.positions.values()):
            if pos.symbol != symbol:
                continue
            if pos.side == BUY:
                hit_sl, hit_tp = l <= pos.sl, h >= pos.tp
                if hit_sl:
                    self._close(pos, min(pos.sl, o) if o < pos.sl else pos.sl, t_close, "SL" if not pos.be_locked else "TRAIL")
                elif hit_tp:
                    self._close(pos, max(pos.tp, o) if o > pos.tp else pos.tp, t_close, "TP")
            else:
                ah, al, ao = h + spread, l + spread, o + spread
                hit_sl, hit_tp = ah >= pos.sl, al <= pos.tp
                if hit_sl:
                    self._close(pos, max(pos.sl, ao) if ao > pos.sl else pos.sl, t_close, "SL" if not pos.be_locked else "TRAIL")
                elif hit_tp:
                    self._close(pos, min(pos.tp, ao) if ao < pos.tp else pos.tp, t_close, "TP")

    def process_tick(self, symbol: str, t: pd.Timestamp, bid: float, ask: float) -> None:
        self.process_bar(symbol, t, t, bid, bid, bid, bid, max(ask - bid, 0.0))
