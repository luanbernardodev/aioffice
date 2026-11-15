"""engine A2 e A3 (US500Cash) no motor deles, com variações de trailing, num capital de US$100.

Trailing do A5: ativa em max(activate_r x R, 3 x spread) -> stop na entrada +/- spread, depois segue a atr_mult x ATR(M5).
Variantes: activate_r 0.5/1.0/1.5 x atr_mult 0.5/1.0/1.5/2.0, para A2 e para A3 separados (24 backtests).
Mesma regra da grade v7: escolhe pelo IS (60% iniciais: maior resultado com n >= 30, PF >= 1.2, DD <= US$30) e mostra o OOS.
  python -m backtest.agentes_v3.engine_trailing_100
"""
import itertools
import logging
from multiprocessing import Pool

import numpy as np
import pandas as pd

from backtest import data as bdata
from backtest.simulate import run_portfolio
from engine.config import load_config

OFF = {"GOLD": {"enabled": False}, "BTCUSD": {"enabled": False}}


def run(args):
    agent, act, mult = args
    logging.basicConfig(level=logging.ERROR)
    cfg = load_config(overrides={"symbols": {**OFF, "US500Cash": {"agents": [agent]}},
                                 "risk": {"trailing": {"activate_r": act, "atr_mult": mult}}})
    d, s = bdata.load("US500Cash")
    cut = d["M5"]["time"].iloc[int(len(d["M5"]) * 0.6)]
    tr = run_portfolio(cfg, {"US500Cash": d}, {"US500Cash": s}, spread_mult=1.5)
    t = pd.Series([x.closed_at for x in tr])
    u = np.array([x.pnl_usd for x in tr])
    out = {"agente": f"engine {agent[:2]}", "activate_r": act, "atr_mult": mult}
    for lab, m in (("is", (t < cut).to_numpy() if len(t) else np.zeros(0, bool)),
                   ("oos", (t >= cut).to_numpy() if len(t) else np.zeros(0, bool)), ("tot", np.ones(len(u), bool))):
        v = u[m] if len(u) else u
        eq = 100 + np.cumsum(v)
        gl = -v[v < 0].sum()
        out.update({f"n_{lab}": len(v), f"net_{lab}": round(float(v.sum()), 2),
                    f"pf_{lab}": round(float(v[v > 0].sum() / gl), 2) if gl > 0 else 99.0,
                    f"wr_{lab}": round(float((v > 0).mean()), 3) if len(v) else 0.0,
                    f"dd_{lab}": round(float((np.maximum.accumulate(np.r_[100, eq])[1:] - eq).max()), 2) if len(v) else 0.0})
    return out


if __name__ == "__main__":
    jobs = list(itertools.product(("A2_PULLBACK", "A3_BOS_RETEST"), (0.5, 1.0, 1.5), (0.5, 1.0, 1.5, 2.0)))
    with Pool(8) as p:
        df = pd.DataFrame(p.map(run, jobs))
    df.to_csv("backtest/agentes_v3/engine_trailing_100.csv", index=False)
    pd.set_option("display.width", 300)
    print(df.to_string(index=False))
    for ag, g in df.groupby("agente"):
        e = g[(g.n_is >= 30) & (g.pf_is >= 1.2) & (g.dd_is <= 30)].sort_values("net_is", ascending=False)
        print(f"\n{ag}: elegíveis no IS {len(e)}" + (f" | escolha act={e.iloc[0].activate_r} mult={e.iloc[0].atr_mult}: "
              f"OOS {e.iloc[0].n_oos} trades US${e.iloc[0].net_oos:+.2f} PF {e.iloc[0].pf_oos} DD {e.iloc[0].dd_oos}"
              if len(e) else " -> nenhuma configuração passa no IS"))
