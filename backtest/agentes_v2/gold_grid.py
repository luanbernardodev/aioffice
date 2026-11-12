"""GOLD (sessão Londres/NY, sucessor do goldflip): grade tick a tick de reentrada x trailing x teto de risco.

  python -m backtest.agentes_v2.gold_grid
"""
import itertools

import pandas as pd

from backtest import ticks as T
from backtest.flip_tick import Cfg, simulate, stats

CUT = pd.Timestamp("2026-06-01", tz="UTC")


def main() -> None:
    P = prepare_cached()
    rows = []
    for reentry, trail, cap in itertools.product(("flip", "bar", "episode"), (1.5, 2.0, 2.5, 3.0), (0.0, 10.0)):
        c = Cfg(name="gold_v2", window="day", trail=trail, reentry=reentry, max_risk_usd=cap)
        tr = simulate(P, c)
        for lab, x in (("IS", tr[tr.t_out < CUT]), ("OOS", tr[tr.t_out >= CUT])):
            u = x.usd
            pf = u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9) if len(u) else 0
            rows.append(dict(reentry=reentry, trail=trail, cap=cap, part=lab, n=len(u), net=round(u.sum(), 1),
                             pf=round(pf, 2), dd=round((u.cumsum().cummax().clip(lower=0) - u.cumsum()).max(), 1) if len(u) else 0))
        print(f"{reentry:8s} trail={trail} cap={cap:4.0f} | {stats(tr)}", flush=True)
    df = pd.DataFrame(rows)
    out = df.pivot_table(index=["reentry", "trail", "cap"], columns="part", values=["n", "net", "pf", "dd"])
    print(out.to_string())
    df.to_csv("backtest/agentes_v2/gold_grid.csv", index=False)


def prepare_cached():
    from backtest.flip_tick import prepare
    return prepare(T.load("GOLD"))


if __name__ == "__main__":
    main()
