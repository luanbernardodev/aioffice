"""O filtro de orderflow é melhor que um filtro aleatório com a mesma taxa de corte?
Sorteia, 2000 vezes, quais sinais da BASE manter (mesma fração que o filtro CONF manteve) e compara o PF OOS.
Também mede a sensibilidade do CONF aos limiares (sem escolher nenhum: só para ver se o efeito é estável).
  python -m backtest.orderflow.teste_aleatorio
"""
import numpy as np
import pandas as pd

import orderflow.metrics as M
from backtest.orderflow import bt_rsi7_orderflow as B


def pf_oos(d, sig):
    tr = B.simulate(d, sig)
    if tr.empty:
        return 0.0, 0
    t = pd.to_datetime(tr["t_out"], utc=True)
    s = B.stats(tr[t >= B.CUT])
    return s["pf"], s["n"]


def main():
    d = B.dataset()
    base = B.filtered(d, B.raw_signals(d), "BASE", 1)
    conf = B.filtered(d, base, "CONF", 1)
    keep = (conf != 0).sum() / max((base != 0).sum(), 1)
    pf_c, n_c = pf_oos(d, conf)
    rng = np.random.default_rng(42)
    idx = np.flatnonzero(base)
    pfs = []
    for _ in range(2000):
        s = base.copy()
        s[idx[rng.random(len(idx)) > keep]] = 0
        pf, n = pf_oos(d, s)
        if n >= 5:
            pfs.append(min(pf, 20.0))
    pfs = np.array(pfs)
    print(f"sinais mantidos pelo CONF: {100 * keep:.0f}% | PF OOS do CONF {pf_c:.2f} ({n_c} trades)")
    print(f"filtro aleatório (mesma taxa): PF OOS mediano {np.median(pfs):.2f} | p90 {np.percentile(pfs, 90):.2f} | "
          f"P(aleatório >= CONF) = {100 * (pfs >= pf_c).mean():.1f}%")
    # sensibilidade: limiares vizinhos do CONF (w=1)
    rows = []
    for stack, dz, ratio in [(3, 2.0, 3.0), (2, 2.0, 3.0), (4, 2.0, 3.0), (3, 1.5, 3.0), (3, 2.5, 3.0), (3, 2.0, 2.0), (3, 2.0, 4.0)]:
        bars, fp = B.load("BTCUSDT", B.BUCKET)
        M_ = M.per_bar if ratio == 3.0 else (lambda f, b, r=ratio: pd.DataFrame(
            [{**M.bar_metrics(g.lvl.to_numpy(), g.buy.to_numpy(), g.sell.to_numpy(), b, ratio=r), "hour": h}
             for h, g in f.groupby("hour")]))
        f = M.series_features(bars, M_(fp, B.BUCKET), stack=stack)
        f["absorb_bull"] = (f["dz"] <= -dz) & (f["low"] >= f["low"].rolling(3).min().shift(1))
        f["absorb_bear"] = (f["dz"] >= dz) & (f["high"] <= f["high"].rolling(3).max().shift(1))
        dd = d.drop(columns=[c for c in ("absorb_bull", "absorb_bear", "exh_bull", "exh_bear", "stacked_bull",
                                         "stacked_bear") if c in d]).merge(
            f[["hour", "absorb_bull", "absorb_bear", "exh_bull", "exh_bear", "stacked_bull", "stacked_bear"]],
            on="hour", how="left").fillna({c: False for c in ("absorb_bull", "absorb_bear", "exh_bull", "exh_bear",
                                                               "stacked_bull", "stacked_bear")})
        sig = B.filtered(dd, base, "CONF", 1)
        tr = B.simulate(dd, sig)
        t = pd.to_datetime(tr["t_out"], utc=True)
        a, b = B.stats(tr[t < B.CUT]), B.stats(tr[t >= B.CUT])
        rows.append({"stack": stack, "dz": dz, "ratio": ratio, "IS_n": a["n"], "IS_pf": a["pf"], "OOS_n": b["n"],
                     "OOS_pf": b["pf"]})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
