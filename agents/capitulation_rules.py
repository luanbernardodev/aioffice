"""Regras puras do agente CAPITULATION (compra em RSI extremo). Mesmo código no backtest e ao vivo."""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

RSI_N = 14


def rsi_state(close: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
    """Médias de Wilder de ganho e perda das M15 fechadas (mesma definição de indicators.rsi)."""
    d = close.diff()
    a = 1 / RSI_N
    g = d.clip(lower=0).ewm(alpha=a, adjust=False, min_periods=RSI_N).mean().to_numpy()
    l = (-d.clip(upper=0)).ewm(alpha=a, adjust=False, min_periods=RSI_N).mean().to_numpy()
    return g, l


def rsi_with_partial(avg_gain: float, avg_loss: float, last_close: float, price: float) -> float:
    """RSI(14) como se a M15 em formação fechasse agora em `price`."""
    delta = price - last_close
    g = avg_gain + (max(delta, 0.0) - avg_gain) / RSI_N
    l = avg_loss + (max(-delta, 0.0) - avg_loss) / RSI_N
    if np.isnan(g) or np.isnan(l):
        return float("nan")
    return 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)


def trail_buy(entry: float, sl: float, bid: float, a: float, trigger: float, dist: float) -> float:
    """Stop móvel de compra: ao atingir +trigger*A, segue a dist*A do bid; sempre acima da entrada e só sobe."""
    return max(sl, bid - dist * a) if bid - entry >= trigger * a else sl


def episode_step(armed: bool, locked: bool, r: float, trigger: float, add: float,
                 n_open: int, max_entries: int) -> Tuple[bool, bool, bool]:
    """Avaliado a cada M5 fechada. Retorna (armado, travado, comprar_agora).

    Arma com RSI <= trigger. Enquanto RSI < add compra até max_entries, e para quando algum stop ficar positivo
    (travado). RSI >= add encerra o episódio e libera o próximo.
    """
    if r >= add:
        return False, False, False
    if not armed and not locked and r <= trigger:
        armed = True
    return armed, locked, armed and not locked and n_open < max_entries
