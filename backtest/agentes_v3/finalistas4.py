"""Finalistas da grade v4 (acerto >= 60%): análise detalhada com o mesmo motor.
  python -m backtest.agentes_v3.finalistas4
"""
import itertools

import numpy as np

from backtest.agentes_v3.bt import summarize, trades_usd, bars, TF_MIN, run_bt
from agents import v3_signals as V

CAND = {
    "GOLD_rsipb_m5_day": ("GOLD", "M5", dict(family="RSIPB", n=7, lvl=20, filter="ma200", session="day"), (2.0, 0.75, 24)),
    "GOLD_rsix_m5_all": ("GOLD", "M5", dict(family="RSIX", x=30, side="long", filter="ma200", session="all"), (2.0, 1.5, 24)),
    "US500_st_h1_ny": ("US500Cash", "H1", dict(family="ST", p=10, m=3.0, filter="none", session="ny"), (2.0, 0.75, 96)),
    "US500_chan_h1_ny": ("US500Cash", "H1", dict(family="CHAN", k=3.0, filter="none", session="ny"), (4.0, 0.75, 24)),
    "US500_bb_h1_all": ("US500Cash", "H1", dict(family="BB", k=2.5, filter="ma200", session="all"), (4.0, 0.5, 96)),
    "US500_sweep_h1_all": ("US500Cash", "H1", dict(family="SWEEP", n=48, filter="none", session="all"), (4.0, 1.0, 24)),
    "BTC_rsipb_h1_all": ("BTCUSD", "H1", dict(family="RSIPB", n=3, lvl=10, filter="ma200", session="all"), (3.0, 0.5, 96)),
}


def trades(sym, tf, spec, ex, mult=1.0):
    b = bars(sym, tf)
    x = V.indicators(b)
    sig = np.where(V.session_mask(b["time"], spec["session"], TF_MIN[tf]), V.signal(x, spec), 0).astype(np.int64)
    sl, tp, mb = ex
    res = run_bt(*(b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread")), x["atr"], sig,
                 b["sday"].to_numpy(np.int64), sl, 0.0, 0.0, tp, mb, mult)
    return trades_usd(sym, b, res)


def main():
    for name, (sym, tf, spec, ex) in CAND.items():
        tr = trades(sym, tf, spec, ex)
        u = tr.usd.to_numpy()
        f = summarize(u)
        streak = max((len(list(g)) for k, g in itertools.groupby(u < 0) if k), default=0)
        wins, losses = u[u > 0], u[u < 0]
        m = tr.groupby(tr.t_out.dt.strftime("%y-%m")).usd.sum()
        x2 = summarize(trades(sym, tf, spec, ex, 2.0).usd.to_numpy())
        print(f"\n=== {name} {spec} SL={ex[0]} TP={ex[1]} max={ex[2]}")
        print(f"  n={f['n']} acerto={100 * f['wr']:.1f}% PF={f['pf']:.2f} net=${f['net']:+.1f} DD=${f['dd']:.1f} | ganho médio "
              f"${wins.mean():.2f} perda média ${losses.mean():.2f} | pior ${u.min():.2f} | perdas seguidas {streak} | "
              f"sem as 3 piores... sem os 3 maiores ${u.sum() - np.sort(u)[-3:].sum():+.1f}")
        print(f"  spread x2: acerto {100 * x2['wr']:.0f}% PF {x2['pf']:.2f} | meses + {(m > 0).sum()}/{len(m)}: "
              + " ".join(f"{k}:{v:+.0f}" for k, v in m.items()))


if __name__ == "__main__":
    main()
