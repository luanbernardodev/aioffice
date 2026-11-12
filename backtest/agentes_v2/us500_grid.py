"""US500Cash (sucessor do engine A2/A3): variantes do motor com corte IS/OOS.

Mesmo código do ao vivo (Engine + SimBroker), só US500Cash, spread das barras x1.5, lote 0.1.
  python -m backtest.agentes_v2.us500_grid
"""
from __future__ import annotations

import logging
from multiprocessing import Pool

import numpy as np
import pandas as pd

from backtest import data as bdata
from backtest.simulate import run_portfolio
from engine.config import load_config

CUT = pd.Timestamp("2026-04-20", tz="UTC")
OFF = {"GOLD": {"enabled": False}, "BTCUSD": {"enabled": False}}
NY = lambda a, b: [{"tz": "America/New_York", "start": a, "end": b}]  # noqa: E731

VARIANTS = {
    "base A2+A3": {},
    "só A2": {"symbols": {"US500Cash": {"agents": ["A2_PULLBACK"]}}},
    "só A3": {"symbols": {"US500Cash": {"agents": ["A3_BOS_RETEST"]}}},
    "A2+A3 sem trailing": {"risk": {"trailing": {"activate_r": 99.0}}},
    "A2+A3 trailing 1.5R": {"risk": {"trailing": {"activate_r": 1.5}}},
    "A2+A3 trailing 2xATR": {"risk": {"trailing": {"atr_mult": 2.0}}},
    "A2+A3 alvo 1.0 Fib": {"agents": {"A2_PULLBACK": {"tp_extension": 1.0}, "A3_BOS_RETEST": {"tp_extension": 1.0}}},
    "A2+A3 alvo 1.618 Fib": {"agents": {"A2_PULLBACK": {"tp_extension": 1.618}, "A3_BOS_RETEST": {"tp_extension": 1.618}}},
    "A2+A3 NY 09:30-12:00": {"symbols": {"US500Cash": {"sessions": NY("09:30", "12:00")}}},
    "A2+A3 NY 12:00-16:00": {"symbols": {"US500Cash": {"sessions": NY("12:00", "16:00")}}},
    "A2 impulso >= 3 ATR": {"agents": {"A2_PULLBACK": {"impulse_min_atr": 3.0}}},
    "A2+A3 spread <= 0.2 ATR": {"symbols": {"US500Cash": {"max_spread_atr": 0.20}}},
}


def stats(tr) -> dict:
    if not tr:
        return {"n": 0, "net": 0.0, "pf": 0.0, "expR": 0.0, "dd": 0.0}
    u = np.array([t.pnl_usd for t in tr]); r = np.array([t.r for t in tr])
    eq = np.cumsum(u)
    return {"n": len(u), "net": round(u.sum(), 2), "pf": round(u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9), 2),
            "expR": round(r.mean(), 3), "dd": round((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max(), 2)}


def run(item):
    name, ov = item
    logging.basicConfig(level=logging.ERROR)
    cfg = load_config(overrides={"symbols": OFF, **ov} if "symbols" not in ov else
                      {**ov, "symbols": {**OFF, **ov["symbols"]}})
    d, s = bdata.load("US500Cash")
    tr = run_portfolio(cfg, {"US500Cash": d}, {"US500Cash": s}, spread_mult=1.5)
    ins = [t for t in tr if t.closed_at < CUT]; oos = [t for t in tr if t.closed_at >= CUT]
    return name, stats(ins), stats(oos), tr


def main() -> None:
    rows, trades = [], {}
    with Pool(6) as pool:
        for name, a, b, tr in pool.imap(run, VARIANTS.items()):
            rows.append({"variante": name, **{f"IS_{k}": v for k, v in a.items()}, **{f"OOS_{k}": v for k, v in b.items()}})
            trades[name] = tr
            print(name, a, b, flush=True)
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv("backtest/agentes_v2/us500_grid.csv", index=False)


if __name__ == "__main__":
    main()
