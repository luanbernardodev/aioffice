"""Regras puras do agente US100_RSI2_H1 (RSI(2) Connors, somente compra). Mesma sequência do bt2 de
backtest/claude_code/us100/grid_wr.py; indicadores com as fórmulas do engine.py do backtest.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np
import pandas as pd

from agents.rsi7_h1_rules import atr, rsi, sma   # mesmas fórmulas (RSI/ATR de Wilder, SMA do pandas)


def add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    d = df.copy()
    c = d["close"].to_numpy(np.float64)
    d["rsi_in"] = rsi(c, int(p["rsi_period"]))
    d["rsi_out"] = rsi(c, int(p["exit_rsi_period"]))
    d["ma"] = sma(c, int(p["ma_period"]))
    d["atr"] = atr(d["high"].to_numpy(np.float64), d["low"].to_numpy(np.float64), c, int(p["atr_period"]))
    return d


def entry_signal(rsi_in: float, close: float, ma: float, threshold: float) -> bool:
    """Compra quando RSI(2) < limiar com close acima da SMA (tendência de alta)."""
    if any(np.isnan(v) for v in (rsi_in, close, ma)):
        return False
    return rsi_in < threshold and close > ma


def exit_signal(rsi_out: float, level: float) -> bool:
    return not np.isnan(rsi_out) and rsi_out > level


def initial_stop(entry: float, a0: float, sl_atr: float) -> float:
    return entry - sl_atr * a0


def trailing_stop(entry: float, stop0: float, a0: float, highs: Sequence[float], atrs: Sequence[float],
                  act_atr: float, trail_atr: float) -> float:
    """Stop após as barras FECHADAS desde a barra de entrada (inclusive), como no bt2: quando a máxima desde a
    entrada >= entrada + act*ATR(sinal), stop = máxima - trail*ATR(barra); só sobe. Sem estado."""
    st, mx = float(stop0), float(entry)
    for h, a in zip(highs, atrs):
        mx = max(mx, float(h))
        if act_atr > 0 and mx - entry >= act_atr * a0:
            st = max(st, mx - trail_atr * float(a))
    return st


def in_blocked_window(now_utc: datetime, start: str = "20:55", end: str = "21:10") -> bool:
    """Janela sem entradas (UTC), inclusiva nas pontas."""
    m = now_utc.hour * 60 + now_utc.minute
    s = int(start[:2]) * 60 + int(start[3:])
    e = int(end[:2]) * 60 + int(end[3:])
    return s <= m <= e if s <= e else (m >= s or m <= e)


def spread_too_wide(spread: float, median_spread: float, mult: float = 3.0) -> bool:
    return median_spread > 0 and spread > mult * median_spread
