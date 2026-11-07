"""Indicadores e estrutura de mercado — todos CAUSAIS (valor em i usa apenas barras <= i).

Os mesmos cálculos alimentam o backtest e o motor ao vivo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)  # sem perdas -> RSI 100
    return out.where(gain.notna())


def swings(high: np.ndarray, low: np.ndarray, k: int) -> dict:
    """Pivôs fractais (k barras de cada lado). Um pivô em j só fica conhecido em j+k.

    Retorna arrays por barra i (estado conhecido no fechamento de i):
      sh_price/sh_idx: último swing high confirmado; sl_price/sl_idx: último swing low confirmado.
    """
    n = len(high)
    sh_price = np.full(n, np.nan)
    sh_idx = np.full(n, -1, dtype=np.int64)
    sl_price = np.full(n, np.nan)
    sl_idx = np.full(n, -1, dtype=np.int64)
    cur_h, cur_hi, cur_l, cur_li = np.nan, -1, np.nan, -1
    for i in range(n):
        j = i - k
        if j - k >= 0:
            win_h = high[j - k:j + k + 1]
            if high[j] == win_h.max() and np.argmax(win_h) == k:
                cur_h, cur_hi = high[j], j
            win_l = low[j - k:j + k + 1]
            if low[j] == win_l.min() and np.argmin(win_l) == k:
                cur_l, cur_li = low[j], j
        sh_price[i], sh_idx[i], sl_price[i], sl_idx[i] = cur_h, cur_hi, cur_l, cur_li
    return {"sh_price": sh_price, "sh_idx": sh_idx, "sl_price": sl_price, "sl_idx": sl_idx}


def structure(close: np.ndarray, sw: dict) -> dict:
    """Máquina de estados de estrutura (BOS/CHoCH) por fechamento além do último swing confirmado.

    trend[i]: +1 alta, -1 baixa, 0 indefinido.
    break_dir[i]: +1/-1 se a barra i rompeu estrutura (BOS se a favor da tendência anterior, CHoCH se contra).
    choch[i]: True se o rompimento em i inverteu a tendência.
    brk_level/brk_idx/brk_dir: último rompimento conhecido em i.
    pre_brk_swing: swing oposto vigente no momento do rompimento (origem da perna).
    """
    n = len(close)
    trend = np.zeros(n, dtype=np.int8)
    break_dir = np.zeros(n, dtype=np.int8)
    choch = np.zeros(n, dtype=bool)
    brk_level = np.full(n, np.nan)
    brk_idx = np.full(n, -1, dtype=np.int64)
    brk_dir = np.zeros(n, dtype=np.int8)
    pre_brk_swing = np.full(n, np.nan)
    t = 0
    used_h, used_l = -1, -1
    last_level, last_idx, last_dir, last_pre = np.nan, -1, 0, np.nan
    for i in range(n):
        hi, li = sw["sh_idx"][i], sw["sl_idx"][i]
        if hi >= 0 and hi != used_h and close[i] > sw["sh_price"][i]:
            break_dir[i] = 1
            choch[i] = t == -1
            t = 1
            used_h = hi
            last_level, last_idx, last_dir, last_pre = sw["sh_price"][i], i, 1, sw["sl_price"][i]
        elif li >= 0 and li != used_l and close[i] < sw["sl_price"][i]:
            break_dir[i] = -1
            choch[i] = t == 1
            t = -1
            used_l = li
            last_level, last_idx, last_dir, last_pre = sw["sl_price"][i], i, -1, sw["sh_price"][i]
        trend[i] = t
        brk_level[i], brk_idx[i], brk_dir[i], pre_brk_swing[i] = last_level, last_idx, last_dir, last_pre
    return {"trend": trend, "break_dir": break_dir, "choch": choch, "brk_level": brk_level,
            "brk_idx": brk_idx, "brk_dir": brk_dir, "pre_brk_swing": pre_brk_swing}


# ------------------------------------------------------------- padrões de candle
def bullish_confirmation(o: float, h: float, l: float, c: float, po: float, pc: float) -> bool:
    """Rejeição (pin bar de compra) ou engolfo de alta."""
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    pin = lower_wick >= 2 * body and lower_wick >= 0.5 * rng and (c - l) >= 0.6 * rng
    engulf = c > o and pc < po and c >= po and o <= pc
    return bool(pin or engulf)


def bearish_confirmation(o: float, h: float, l: float, c: float, po: float, pc: float) -> bool:
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    pin = upper_wick >= 2 * body and upper_wick >= 0.5 * rng and (h - c) >= 0.6 * rng
    engulf = c < o and pc > po and c <= po and o >= pc
    return bool(pin or engulf)
