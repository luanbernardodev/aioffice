"""Dados e motor de backtest dos agentes v3 (mesmas regras de execução do agents/v3_agent.py).

Barras de BID com spread REAL:
  GOLD   ticks 2026-01 -> 2026-11 (data/ticks/GOLD.npz)
  BTCUSD ticks 2025-11 -> 2026-11 (data/ticks/BTCUSD.npz)  -> spread ~US$50, não o ~0.4 das barras do MT5
  US500  M5 do MT5 2025-06 -> 2026-11, spread da barra com piso de 0.8 (spread ao vivo = 80 pontos)
Lote mínimo de cada ativo; swap por noite do servidor (relógio NY+7) com os valores do symbol_info.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
from numba import njit

from backtest import ticks as T
from engine.config import ROOT

CACHE = ROOT / "data" / "v3"
TF_MIN = {"M5": 5, "M15": 15, "H1": 60}

# USD por 1.0 de preço no lote mínimo, swap em USD por noite no lote mínimo (compra, venda)
SPECS = {
    "GOLD": {"lot": 0.01, "usd_pp": 1.0, "swap": (-0.786, 0.168)},
    "BTCUSD": {"lot": 0.01, "usd_pp": 0.01, "swap": (-0.322, -0.215)},
    "US500Cash": {"lot": 0.1, "usd_pp": 0.1, "swap": (-0.132, 0.019)},
}


def server_day(time_utc: pd.Series) -> np.ndarray:
    """Dia do servidor XM (NY + 7h): a virada é o rollover do swap (17:00 NY)."""
    ny = pd.to_datetime(time_utc, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    return (((ny + pd.Timedelta(hours=7)) - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy()


def bars(sym: str, tf: str) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{sym}_{tf}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    m = TF_MIN[tf]
    if sym in ("GOLD", "BTCUSD"):
        tk = T.load(sym)
        b = T.bars(tk, m)[["time", "open", "high", "low", "close", "spread"]]
    else:
        raw = pd.read_csv(ROOT / "data" / f"{sym}_M5.csv")
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        g = raw.set_index("time").resample(f"{m}min", label="left", closed="left")
        b = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last(), "spread": g["spread"].mean()}).dropna().reset_index()
        b["spread"] = np.maximum(b["spread"], 0.8)
    b = b.reset_index(drop=True)
    b["sday"] = server_day(b["time"])
    b.to_pickle(path)
    return b


@njit(cache=True)
def run_bt(o, h, l, c, sp, a, sig, sday, sl_k, tr_k, act_k, tp_k, max_bars, sp_mult):
    """Uma posição por vez. Retorna (i_entrada, i_saida, lado, pnl_preço, risco_preço, noites, motivo).
    motivo: 0 SL/trail, 1 TP, 2 tempo."""
    n = len(c)
    E = np.empty(n, np.int64); X = np.empty(n, np.int64); S = np.empty(n, np.int64)
    P = np.empty(n); R = np.empty(n); N = np.empty(n, np.int64); W = np.empty(n, np.int64)
    k = 0
    i = 0
    while i < n - 2:
        s = sig[i]
        if s == 0 or not (a[i] > 0):
            i += 1
            continue
        j = i + 1
        a0 = a[i]
        spj = sp[j] * sp_mult
        entry = o[j] + spj if s == 1 else o[j]
        sl = entry - s * sl_k * a0
        tp = entry + s * tp_k * a0 if tp_k > 0 else 0.0
        best = entry
        px = 0.0
        why = -1
        t = j
        while t < n:
            spt = sp[t] * sp_mult
            if s == 1:
                if l[t] <= sl:
                    px = min(sl, o[t]) if t > j else sl
                    why = 0
                elif tp > 0 and h[t] >= tp:
                    px = max(tp, o[t]) if t > j else tp
                    why = 1
            else:
                if h[t] + spt >= sl:
                    px = max(sl, o[t] + spt) if t > j else sl
                    why = 0
                elif tp > 0 and l[t] + spt <= tp:
                    px = min(tp, o[t] + spt) if t > j else tp
                    why = 1
            if why >= 0:
                break
            # fechamento da barra t: melhor preço, trailing e tempo
            if s == 1:
                best = max(best, h[t])
            else:
                best = min(best, l[t] + spt)
            if tr_k > 0 and (best - entry) * s >= act_k * a0:
                new = best - s * tr_k * a0
                sl = max(sl, new) if s == 1 else min(sl, new)
            if t - j + 1 >= max_bars and t + 1 < n:
                t += 1
                px = o[t] if s == 1 else o[t] + sp[t] * sp_mult
                why = 2
                break
            t += 1
        if why < 0:
            break
        E[k] = j; X[k] = t; S[k] = s
        P[k] = (px - entry) * s
        R[k] = sl_k * a0
        N[k] = sday[t] - sday[j]
        W[k] = why
        k += 1
        i = t if why != 2 else t       # tempo: sai na abertura de t; próximo sinal a partir do fechamento de t
    return E[:k], X[:k], S[:k], P[:k], R[:k], N[:k], W[:k]


def trades_usd(sym: str, b: pd.DataFrame, res) -> pd.DataFrame:
    E, X, S, P, R, N, W = res
    sp = SPECS[sym]
    swap = np.where(S == 1, sp["swap"][0], sp["swap"][1]) * N
    return pd.DataFrame({"t_in": b["time"].to_numpy()[E], "t_out": b["time"].to_numpy()[X], "side": S,
                         "usd": P * sp["usd_pp"] + swap, "risk_usd": R * sp["usd_pp"], "r": P / np.maximum(R, 1e-12),
                         "why": W})


def summarize(u: np.ndarray) -> Dict[str, float]:
    if len(u) == 0:
        return {"n": 0, "net": 0.0, "pf": 0.0, "dd": 0.0, "wr": 0.0}
    eq = np.cumsum(u)
    gl = -u[u < 0].sum()
    return {"n": int(len(u)), "net": float(u.sum()), "pf": float(u[u > 0].sum() / gl) if gl > 0 else 99.0,
            "dd": float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max()), "wr": float((u > 0).mean())}
