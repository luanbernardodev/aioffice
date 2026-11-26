"""Footprint H1 a partir dos aggTrades: volume comprador e vendedor (agressão) por nível de preço.

Níveis = faixas de `bucket` US$ (padrão 10): nível k cobre [k*bucket, (k+1)*bucket). Saída em data/orderflow/:
  <SYM>_bars_H1.pkl  hour(ms UTC da abertura), open, high, low, close, buy, sell, trades
  <SYM>_fp_H1_b<bucket>.pkl  hour, lvl, buy, sell  (uma linha por nível com volume)

  python -m orderflow.footprint
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

from engine.config import ROOT
from orderflow.binance_data import RAW_DIR, iter_trades

OUT_DIR = ROOT / "data" / "orderflow"
H_MS = 3_600_000


def _aggregate(ch: pd.DataFrame, bucket: float, seq: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    hour = ch["time"].to_numpy() // H_MS * H_MS
    lvl = np.floor(ch["price"].to_numpy() / bucket).astype(np.int64)
    q = ch["qty"].to_numpy()
    sell = ch["sell"].to_numpy()
    fp = pd.DataFrame({"hour": hour, "lvl": lvl, "buy": np.where(sell, 0.0, q), "sell": np.where(sell, q, 0.0)})
    fp = fp.groupby(["hour", "lvl"], sort=False, as_index=False).sum()
    g = pd.DataFrame({"hour": hour, "price": ch["price"].to_numpy(), "buy": fp_buy(q, sell), "sell": np.where(sell, q, 0.0)})
    bars = g.groupby("hour", sort=False).agg(open=("price", "first"), high=("price", "max"), low=("price", "min"),
                                             close=("price", "last"), buy=("buy", "sum"), sell=("sell", "sum"),
                                             trades=("price", "size")).reset_index()
    bars["seq"] = seq
    return fp, bars


def fp_buy(q: np.ndarray, sell: np.ndarray) -> np.ndarray:
    return np.where(sell, 0.0, q)


def build(sym: str = "BTCUSDT", bucket: float = 10.0, files: List[Path] | None = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = files or sorted(RAW_DIR.glob(f"{sym}-aggTrades-*.zip"))
    bars_h, fp = aggregate(files, bucket)
    tag = f"{bucket:g}"
    bars_h.to_pickle(OUT_DIR / f"{sym}_bars_H1.pkl")
    fp.to_pickle(OUT_DIR / f"{sym}_fp_H1_b{tag}.pkl")
    return bars_h, fp


def aggregate(files: List[Path], bucket: float = 10.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Barras H1 e footprint dos arquivos dados, sem gravar (usado também na atualização incremental semanal)."""
    fps, bars, seq = [], [], 0
    for path in files:
        n = 0
        for ch in iter_trades(path):
            f, b = _aggregate(ch, bucket, seq)
            fps.append(f)
            bars.append(b)
            seq += 1
            n += len(ch)
        print(f"{path.name}: {n:,} aggTrades", flush=True)
    fp = pd.concat(fps).groupby(["hour", "lvl"], as_index=False)[["buy", "sell"]].sum().sort_values(["hour", "lvl"])
    b = pd.concat(bars).sort_values(["hour", "seq"])
    bars_h = b.groupby("hour").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"), buy=("buy", "sum"), sell=("sell", "sum"),
                                   trades=("trades", "sum")).reset_index()
    return bars_h, fp.reset_index(drop=True)


def load(sym: str = "BTCUSDT", bucket: float = 10.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    tag = f"{bucket:g}"
    return pd.read_pickle(OUT_DIR / f"{sym}_bars_H1.pkl"), pd.read_pickle(OUT_DIR / f"{sym}_fp_H1_b{tag}.pkl")


if __name__ == "__main__":
    b, f = build()
    print(f"{len(b)} barras H1 | {len(f):,} células de footprint | "
          f"{pd.to_datetime(b.hour.iloc[0], unit='ms')} -> {pd.to_datetime(b.hour.iloc[-1], unit='ms')}")
