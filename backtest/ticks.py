"""Ticks do MT5 (exportados pela janela Símbolos -> Ticks) -> arrays numpy compactos + barras.

Formato de entrada (TAB): <DATE> <TIME> <BID> <ASK> <LAST> <VOLUME> <FLAGS>; hora = relógio do servidor XM
(America/New_York + 7h). Linhas com só BID ou só ASK são completadas com o último valor conhecido.

Saída: data/ticks/<SYM>.npz com
  t   int64  epoch em ms, UTC
  bid int32  centavos
  ask int32  centavos

  python -m backtest.ticks convert C:/Users/Usuario/Documents/gold_tick GOLD
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from backtest import data as bdata
from engine.features import server_to_utc

TICK_DIR = bdata.DATA_DIR / "ticks"


def _digits(a: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Inteiro formado pelos bytes ASCII [lo, hi) de cada linha de uma matriz uint8 (n, w)."""
    out = np.zeros(len(a), dtype=np.int64)
    for j in range(lo, hi):
        out = out * 10 + (a[:, j].astype(np.int64) - 48)
    return out


def _parse_chunk(df: pd.DataFrame) -> pd.DataFrame:
    d = np.frombuffer(df[0].to_numpy(dtype="S10").tobytes(), dtype=np.uint8).reshape(-1, 10)   # 2026.01.02
    tm = np.frombuffer(df[1].str.ljust(12, "0").to_numpy(dtype="S12").tobytes(), dtype=np.uint8).reshape(-1, 12)
    days = (pd.to_datetime(pd.DataFrame({"year": _digits(d, 0, 4), "month": _digits(d, 5, 7), "day": _digits(d, 8, 10)}))
            .to_numpy().astype("datetime64[s]").astype(np.int64))
    ms = (days * 1000 + _digits(tm, 0, 2) * 3_600_000 + _digits(tm, 3, 5) * 60_000 + _digits(tm, 6, 8) * 1000
          + _digits(tm, 9, 12))
    return pd.DataFrame({"srv_ms": ms, "bid": df[2].to_numpy(), "ask": df[3].to_numpy()})


def convert(src: str, sym: str = "GOLD", chunk: int = 5_000_000) -> Path:
    files = sorted(Path(src).glob(f"{sym}_*.csv"))
    if not files:
        raise FileNotFoundError(f"nenhum {sym}_*.csv em {src}")
    parts = []
    for f in files:
        t0 = time.time()
        for df in pd.read_csv(f, sep="\t", header=None, skiprows=1, usecols=[0, 1, 2, 3],
                              dtype={0: str, 1: str, 2: np.float64, 3: np.float64}, chunksize=chunk):
            parts.append(_parse_chunk(df))
        print(f"  {f.name}: {time.time() - t0:.0f}s", flush=True)
    x = pd.concat(parts, ignore_index=True)
    del parts
    if not x["srv_ms"].is_monotonic_increasing:
        x = x.sort_values("srv_ms", kind="stable", ignore_index=True)
    x[["bid", "ask"]] = x[["bid", "ask"]].ffill()
    x = x.dropna()
    # servidor -> UTC: converte só as horas distintas e aplica o deslocamento
    hrs = x["srv_ms"].to_numpy() // 3_600_000
    uh = np.unique(hrs)
    utc_h = (server_to_utc(uh * 3600).dt.tz_convert(None).to_numpy().astype("datetime64[s]").astype(np.int64)
             // 3600)
    off_ms = dict(zip(uh, (utc_h - uh) * 3_600_000))
    t = x["srv_ms"].to_numpy() + pd.Series(hrs).map(off_ms).to_numpy()
    bid = np.round(x["bid"].to_numpy() * 100).astype(np.int32)
    ask = np.round(x["ask"].to_numpy() * 100).astype(np.int32)
    TICK_DIR.mkdir(parents=True, exist_ok=True)
    out = TICK_DIR / f"{sym}.npz"
    np.savez(out, t=t.astype(np.int64), bid=bid, ask=ask)
    print(f"{sym}: {len(t):,} ticks {pd.to_datetime(t[0], unit='ms', utc=True)} -> "
          f"{pd.to_datetime(t[-1], unit='ms', utc=True)} | {out}")
    return out


def load(sym: str = "GOLD") -> Dict[str, np.ndarray]:
    z = np.load(TICK_DIR / f"{sym}.npz")
    return {"t": z["t"], "bid": z["bid"].astype(np.float64) / 100, "ask": z["ask"].astype(np.float64) / 100}


def bars(tk: Dict[str, np.ndarray], minutes: int) -> pd.DataFrame:
    """Barras de BID (como o MT5), com spread médio, máximo e no fechamento, e índices [i0, i1) dos ticks."""
    t, bid, ask = tk["t"], tk["bid"], tk["ask"]
    key = t // (minutes * 60_000)
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(t)]
    sp = ask - bid
    return pd.DataFrame({
        "time": pd.to_datetime(key[starts] * minutes * 60_000, unit="ms", utc=True),
        "open": bid[starts], "high": np.maximum.reduceat(bid, starts), "low": np.minimum.reduceat(bid, starts),
        "close": bid[ends - 1], "ask_high": np.maximum.reduceat(ask, starts),
        "spread": np.add.reduceat(sp, starts) / (ends - starts), "spread_max": np.maximum.reduceat(sp, starts),
        "spread_close": sp[ends - 1], "n": ends - starts, "i0": starts, "i1": ends})


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "convert":
        convert(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "GOLD")
    else:
        print(__doc__)
