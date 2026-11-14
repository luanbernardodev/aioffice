"""aggTrades da Binance (spot BTCUSDT) a partir de data.binance.vision — dados públicos, somente leitura.

Arquivos: mensais (…/monthly/aggTrades/BTCUSDT/BTCUSDT-aggTrades-YYYY-MM.zip) e diários para o mês corrente,
cada um com o .CHECKSUM (SHA-256) conferido no download. CSV sem cabeçalho:
  agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker, is_best_match
is_buyer_maker = True -> o agressor VENDEU (bate no bid); False -> o agressor COMPROU (levanta o ask).
Desde 2025 o transact_time do spot vem em MICROssegundos (antes, milissegundos): normalizado para ms.

  python -m orderflow.binance_data          # baixa 2025-11 .. 2026-10 (mensal) + 2026-11-01..10 (diário)
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, List

import numpy as np
import pandas as pd
import requests

from engine.config import ROOT

BASE = "https://data.binance.vision/data/spot"
RAW_DIR = ROOT / "data" / "binance" / "aggTrades"
COLS = ["agg_id", "price", "qty", "first_id", "last_id", "time", "is_buyer_maker", "best_match"]


def monthly_url(sym: str, ym: str) -> str:
    return f"{BASE}/monthly/aggTrades/{sym}/{sym}-aggTrades-{ym}.zip"


def daily_url(sym: str, d: date) -> str:
    return f"{BASE}/daily/aggTrades/{sym}/{sym}-aggTrades-{d:%Y-%m-%d}.zip"


def default_files(sym: str = "BTCUSDT") -> List[str]:
    months = pd.period_range("2025-11", "2026-10", freq="M").strftime("%Y-%m")
    urls = [monthly_url(sym, m) for m in months]
    d = date(2026, 11, 1)
    while d <= date(2026, 11, 10):
        urls.append(daily_url(sym, d))
        d += timedelta(days=1)
    return urls


def download(url: str, dest_dir: Path = RAW_DIR, session: requests.Session | None = None) -> Path:
    """Baixa (se ainda não existe) e confere o SHA-256 contra o .CHECKSUM publicado."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / url.rsplit("/", 1)[1]
    s = session or requests.Session()
    expected = s.get(url + ".CHECKSUM", timeout=30).text.split()[0].strip().lower()
    if path.exists() and _sha256(path) == expected:
        return path
    tmp = path.with_suffix(".part")
    with s.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 22):
                fh.write(chunk)
    got = _sha256(tmp)
    if got != expected:
        tmp.unlink(missing_ok=True)
        raise IOError(f"checksum não confere em {path.name}: {got} != {expected}")
    tmp.replace(path)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def iter_trades(path: Path, chunksize: int = 5_000_000) -> Iterator[pd.DataFrame]:
    """Blocos com colunas time (ms, int64), price (float64), qty (float64), sell (bool = agressor vendedor)."""
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            for ch in pd.read_csv(fh, header=None, names=COLS, usecols=["price", "qty", "time", "is_buyer_maker"],
                                  dtype={"price": np.float64, "qty": np.float64, "time": np.int64},
                                  chunksize=chunksize):
                t = ch["time"].to_numpy()
                if len(t) and t[0] > 10 ** 14:          # microssegundos -> milissegundos
                    t = t // 1000
                sell = ch["is_buyer_maker"].astype(str).str.lower().eq("true").to_numpy()
                yield pd.DataFrame({"time": t, "price": ch["price"].to_numpy(), "qty": ch["qty"].to_numpy(),
                                    "sell": sell})


if __name__ == "__main__":
    sess = requests.Session()
    for u in (sys.argv[1:] or default_files()):
        p = download(u, session=sess)
        print(f"ok {p.name} ({p.stat().st_size / 2 ** 20:.0f} MB)", flush=True)
