"""Monta o painel multi-timeframe (M5 base + M15 + H1) e o regime A1, de forma causal.

Entrada: DataFrames com colunas time (UTC tz-aware, abertura da barra), open, high, low, close, spread
(spread em unidades de preço). Apenas barras FECHADAS.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from engine import indicators as ind

TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600}


def server_to_utc(epoch_seconds, mode: str = "ny_plus_7") -> pd.Series:
    """Converte o 'epoch' do MT5 (relógio de parede do servidor) para UTC.

    XM usa a convenção 'NY close': servidor = America/New_York + 7h (UTC+2 inverno, UTC+3 verão).
    """
    naive = pd.to_datetime(pd.Series(epoch_seconds), unit="s")
    if mode == "ny_plus_7":
        ny = naive - pd.Timedelta(hours=7)
        loc = ny.dt.tz_localize("America/New_York", ambiguous=np.zeros(len(ny), dtype=bool),
                                nonexistent="shift_forward")
        return loc.dt.tz_convert("UTC")
    if mode.startswith("utc"):  # ex.: "utc+2"
        off = float(mode[3:] or 0)
        return (naive - pd.Timedelta(hours=off)).dt.tz_localize("UTC")
    raise ValueError(f"server_time desconhecido: {mode}")


def _with_close_time(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    out = df.reset_index(drop=True).copy()
    out["close_time"] = out["time"] + pd.Timedelta(seconds=TF_SECONDS[tf])
    return out


def build_h1(h1: pd.DataFrame, rcfg: Dict[str, Any]) -> pd.DataFrame:
    d = _with_close_time(h1, "H1")
    n = int(rcfg.get("h1_ma", 100))
    d["h1_sma"] = ind.sma(d["close"], n)
    d["h1_atr"] = ind.atr(d)
    k = int(rcfg.get("h1_slope_bars", 5))
    slope = (d["h1_sma"] - d["h1_sma"].shift(k)) / d["h1_atr"]
    min_slope = float(rcfg.get("h1_min_slope_atr", 0.0))
    side = np.where((d["close"] > d["h1_sma"]) & (slope > min_slope), 1,
                    np.where((d["close"] < d["h1_sma"]) & (slope < -min_slope), -1, 0))
    d["h1_side"] = np.where(d["h1_sma"].isna() | slope.isna(), 0, side).astype(int)
    d["h1_above_ma"] = np.where(d["h1_sma"].isna(), 0, np.where(d["close"] > d["h1_sma"], 1, -1)).astype(int)
    return d[["close_time", "h1_sma", "h1_side", "h1_above_ma", "h1_atr", "close"]].rename(columns={"close": "h1_close"})


def build_m15(m15: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    d = _with_close_time(m15, "M15")
    rcfg = cfg.get("regime", {})
    a4 = cfg.get("agents", {}).get("A4_RSI_REVERSAL", {})
    sw = ind.swings(d["high"].to_numpy(), d["low"].to_numpy(), int(rcfg.get("m15_swing_k", 3)))
    st = ind.structure(d["close"].to_numpy(), sw)
    d["m15_trend"] = st["trend"]
    d["rsi"] = ind.rsi(d["close"], int(a4.get("rsi_period", 14)))
    d["atr"] = ind.atr(d)
    return d


def build_m5(m5: pd.DataFrame, swing_k: int = 3, ma_period: int = 100) -> pd.DataFrame:
    d = _with_close_time(m5, "M5")
    d["atr"] = ind.atr(d)
    d["sma"] = ind.sma(d["close"], ma_period)
    sw = ind.swings(d["high"].to_numpy(), d["low"].to_numpy(), swing_k)
    st = ind.structure(d["close"].to_numpy(), sw)
    for k, v in {**sw, **st}.items():
        d[k] = v
    return d


def build_features(m5: pd.DataFrame, m15: pd.DataFrame, h1: pd.DataFrame, cfg: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """Retorna {"m5": painel base com bias A1, "m15": painel M15 (A4) com h1 alinhado}."""
    a2 = cfg.get("agents", {}).get("A2_PULLBACK", {})
    d5 = build_m5(m5, int(a2.get("swing_k", 3)), int(a2.get("ma_period", 100)))
    d15 = build_m15(m15, cfg)
    dh = build_h1(h1, cfg.get("regime", {}))

    # H1 -> M15 (última H1 fechada até o fechamento da M15)
    d15 = pd.merge_asof(d15.sort_values("close_time"), dh, on="close_time", direction="backward")
    for c in ("h1_side", "h1_above_ma"):
        d15[c] = d15[c].fillna(0).astype(int)

    # M15 -> M5 (última M15 fechada até o fechamento da M5)
    m15_cols = d15[["close_time", "m15_trend", "h1_side", "h1_above_ma", "h1_sma", "h1_atr"]].copy()
    m15_cols["m15_i"] = np.arange(len(d15))
    m15_cols["m15_close_time"] = m15_cols["close_time"]
    d5 = pd.merge_asof(d5.sort_values("close_time"), m15_cols, on="close_time", direction="backward")
    d5["m15_i"] = d5["m15_i"].fillna(-1).astype(int)
    d5["m15_new"] = d5["m15_close_time"].eq(d5["close_time"])  # esta M5 fecha junto com uma M15
    d5["m15_trend"] = d5["m15_trend"].fillna(0).astype(int)
    d5["h1_side"] = d5["h1_side"].fillna(0).astype(int)
    d5["h1_above_ma"] = d5["h1_above_ma"].fillna(0).astype(int)
    # A1: bias = H1 (MA100 + inclinação) concordando com a estrutura M15
    d5["bias"] = np.where((d5["h1_side"] != 0) & (d5["h1_side"] == d5["m15_trend"]), d5["h1_side"], 0).astype(int)
    d5["spread_atr"] = d5["spread"] / d5["atr"]
    return {"m5": d5.reset_index(drop=True), "m15": d15.reset_index(drop=True)}
