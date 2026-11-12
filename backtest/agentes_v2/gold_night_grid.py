"""GOLD madrugada (fora de Londres/NY): reentrada x trailing x teto de risco, tick a tick.

  python -m backtest.agentes_v2.gold_night_grid
"""
import itertools

import pandas as pd

from backtest import ticks as T
from backtest.flip_tick import Cfg, by_month, prepare, simulate, stats

CUT = pd.Timestamp("2026-06-01", tz="UTC")


def main() -> None:
    P = prepare(T.load("GOLD"))
    for reentry, trail, cap in itertools.product(("flip", "bar", "episode"), (2.5, 3.0, 3.5), (0.0, 8.0, 10.0)):
        c = Cfg(name="gold_night_v2", window="night", trail=trail, reentry=reentry, max_risk_usd=cap)
        tr = simulate(P, c)
        print(f"{reentry:8s} trail={trail} cap={cap:4.0f} | IS {stats(tr[tr.t_out < CUT])}\n"
              f"{'':27s} | OOS {stats(tr[tr.t_out >= CUT])}\n{'':27s} | {by_month(tr)}", flush=True)


if __name__ == "__main__":
    main()
