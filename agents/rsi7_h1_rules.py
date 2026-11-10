"""Regras puras do agente RSI7_H1 — mesmas fórmulas de backtest/claude_code/engine.py (RSI/ATR de Wilder,
EMA/SMA do pandas) e mesma sequência de decisões do motor `bt` (sinal no fechamento, stop móvel a partir do
extremo, atualizado só no fechamento da barra e só apertando).
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

BUY, SELL = 1, -1


# ----------------------------------------------------------------- indicadores (idênticos ao engine.py)
def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).mean().to_numpy()


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    ad = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-9))


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    pc = np.roll(c, 1)
    pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """df com open/high/low/close (BID) em ordem cronológica, só barras fechadas."""
    d = df.copy()
    c = d["close"].to_numpy(np.float64)
    d["rsi"] = rsi(c, int(p["rsi_period"]))
    d["ma"] = ema(c, int(p["ma_period"])) if p["ma_type"] == "ema" else sma(c, int(p["ma_period"]))
    d["atr"] = atr(d["high"].to_numpy(np.float64), d["low"].to_numpy(np.float64), c, int(p["atr_period"]))
    return d


# ----------------------------------------------------------------- sinal
def signal(rsi_prev: float, rsi_now: float, close: float, ma: float, lo: float) -> int:
    """BUY: RSI cruza para cima de lo com close > MA. SELL: RSI cruza para baixo de 100-lo com close < MA."""
    if any(np.isnan(v) for v in (rsi_prev, rsi_now, close, ma)):
        return 0
    if rsi_now > lo and rsi_prev <= lo and close > ma:
        return BUY
    hi = 100 - lo
    if rsi_now < hi and rsi_prev >= hi and close < ma:
        return SELL
    return 0


def signal_last(d: pd.DataFrame, p: dict) -> int:
    if len(d) < 2:
        return 0
    return signal(float(d["rsi"].iat[-2]), float(d["rsi"].iat[-1]), float(d["close"].iat[-1]), float(d["ma"].iat[-1]),
                  float(p["rsi_level"]))


# ----------------------------------------------------------------- stops
def initial_stop(side: int, entry: float, a: float, sl_atr: float) -> float:
    return entry - side * sl_atr * a


def take_profit(side: int, entry: float, a: float, tp_atr: float) -> float:
    return entry + side * tp_atr * a if tp_atr > 0 else 0.0


def trailing_stop(side: int, entry: float, stop0: float, risk: float, highs: Sequence[float], lows: Sequence[float],
                  atrs: Sequence[float], spread: float, trail_atr: float, act_r: float, be_r: float = 0.0) -> float:
    """Stop após as barras FECHADAS desde a barra de entrada (inclusive), como no backtest.

    Compra: extremo = máxima (BID); stop = extremo - trail*ATR(barra), ativado quando extremo-entrada >= act*R.
    Venda: extremo = mínima + spread (ASK). Breakeven em be_r*R (0 = desligado). Só aperta; nunca afrouxa.
    Sem estado: dá o mesmo resultado depois de um reinício do agente."""
    st, ext = float(stop0), float(entry)
    for h, l, a in zip(highs, lows, atrs):
        if side == BUY:
            ext = max(ext, float(h))
            if be_r > 0 and ext - entry >= be_r * risk and entry > st:
                st = entry
            if ext - entry >= act_r * risk:
                st = max(st, ext - trail_atr * float(a))
        else:
            ext = min(ext, float(l) + spread)
            if be_r > 0 and entry - ext >= be_r * risk and entry < st:
                st = entry
            if entry - ext >= act_r * risk:
                st = min(st, ext + trail_atr * float(a))
    return st


def tighter(side: int, new: float, old: Optional[float]) -> bool:
    if not old:
        return True
    return new > old if side == BUY else new < old


def stop_hit(side: int, bid: float, ask: float, stop: float) -> bool:
    return bid <= stop if side == BUY else ask >= stop


def daily_loss_hit(day_pnl: float, start_balance: float, max_pct: float) -> bool:
    """max_pct <= 0 = trava desligada."""
    return max_pct > 0 and start_balance > 0 and day_pnl <= -max_pct / 100 * start_balance
