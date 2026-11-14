"""Filtros de orderflow sobre os sinais (mesmo código no backtest e ao vivo).

`masks(f, name)` recebe as features de orderflow (orderflow.metrics.series_features, uma linha por barra H1 em
ordem cronológica) e devolve (permite_compra, permite_venda) por barra. A decisão de uma barra usa só ela e as
anteriores. Ao vivo, toma-se a última linha (barra do sinal).
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

FILTERS = ["none", "conf_w1", "conf_w3", "absorb_w3", "exh_w1", "exh_w3", "stk_w1", "stk_w3", "veto_cvd",
           "delta_agree", "dz_agree", "cvd_slope", "poc_side", "va_inside"]


def _any(f: pd.DataFrame, col: str, w: int) -> np.ndarray:
    return f[col].fillna(False).astype(bool).rolling(w, min_periods=1).max().astype(bool).to_numpy()


def masks(f: pd.DataFrame, name: str) -> Tuple[np.ndarray, np.ndarray]:
    n = len(f)
    if name == "none":
        t = np.ones(n, bool)
        return t, t
    if name in ("conf_w1", "conf_w3"):
        w = int(name[-1])
        bull = _any(f, "absorb_bull", w) | _any(f, "exh_bull", w) | _any(f, "stacked_bull", w)
        bear = _any(f, "absorb_bear", w) | _any(f, "exh_bear", w) | _any(f, "stacked_bear", w)
        return bull, bear
    if name == "absorb_w3":
        return _any(f, "absorb_bull", 3), _any(f, "absorb_bear", 3)
    if name in ("exh_w1", "exh_w3"):
        w = int(name[-1])
        return _any(f, "exh_bull", w), _any(f, "exh_bear", w)
    if name in ("stk_w1", "stk_w3"):
        w = int(name[-1])
        return _any(f, "stacked_bull", w), _any(f, "stacked_bear", w)
    if name == "veto_cvd":
        return ~f["cvd_div_buy"].fillna(False).to_numpy(bool), ~f["cvd_div_sell"].fillna(False).to_numpy(bool)
    if name == "delta_agree":
        d = f["delta"].to_numpy(float)
        return d > 0, d < 0
    if name == "dz_agree":
        z = f["dz"].to_numpy(float)
        return z >= 1.0, z <= -1.0
    if name == "cvd_slope":
        dv = (f["cvd"] - f["cvd"].shift(3)).to_numpy(float)
        return dv > 0, dv < 0
    if name == "poc_side":
        c, p = f["close"].to_numpy(float), f["poc"].to_numpy(float)
        return c > p, c < p
    if name == "va_inside":
        c = f["close"].to_numpy(float)
        ins = (c >= f["val"].to_numpy(float)) & (c <= f["vah"].to_numpy(float))
        return ins, ins
    raise ValueError(name)


def apply(sig: np.ndarray, f: pd.DataFrame, name: str, has_of: np.ndarray | None = None) -> np.ndarray:
    """sig e f alinhados barra a barra. Barra sem orderflow (has_of False) nunca entra com filtro."""
    if name == "none":
        return sig
    bull, bear = masks(f, name)
    out = sig.copy()
    out[(out == 1) & ~bull] = 0
    out[(out == -1) & ~bear] = 0
    if has_of is not None:
        out[~has_of] = 0
    return out
