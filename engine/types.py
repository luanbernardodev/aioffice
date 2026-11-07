"""Tipos compartilhados entre estratégias, risco, brokers (sim/MT5) e backtest."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

BUY, SELL = 1, -1


def side_name(side: int) -> str:
    return "BUY" if side == BUY else "SELL"


@dataclass
class OrderIntent:
    key: str                 # id único e estável: agente|ativo|grupo|tag
    agent: str
    symbol: str
    side: int                # +1 compra / -1 venda
    kind: str                # "LIMIT" | "MARKET"
    price: float             # preço limite (LIMIT) ou referência (MARKET)
    sl: float
    tp: float                # alvo final (extensão Fib / R)
    setup: str
    group: str               # impulso/BOS/episódio: limita entradas por grupo
    tp1: float = 0.0         # 1.5R (preenchido pelo A5)
    expiry: Optional[pd.Timestamp] = None
    atr: float = 0.0         # ATR(M5) no momento da decisão
    spread: float = 0.0
    tp_r: float = 0.0        # >0: alvo final = tp_r x R (recalculado após o A5 ajustar o SL)


@dataclass
class Position:
    id: str
    key: str
    agent: str
    symbol: str
    side: int
    volume: float
    entry: float
    sl: float
    tp: float
    tp1: float
    initial_sl: float
    setup: str
    group: str
    opened_at: pd.Timestamp
    atr_at_entry: float = 0.0
    spread_at_entry: float = 0.0
    be_locked: bool = False

    @property
    def initial_risk(self) -> float:
        return abs(self.entry - self.initial_sl)


@dataclass
class ClosedTrade:
    agent: str
    setup: str
    symbol: str
    side: int
    volume: float
    entry: float
    initial_sl: float
    tp: float
    tp1: float
    exit: float
    opened_at: pd.Timestamp
    closed_at: pd.Timestamp
    reason: str
    pnl_usd: float
    r: float
    spread_at_entry: float
    atr_at_entry: float
    ticket: str = ""
    extra: dict = field(default_factory=dict)
