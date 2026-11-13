"""Grade de estratégias v3: 47 sinais x sessões x 3 timeframes x 12 saídas em US500Cash, GOLD e BTCUSD.

Critérios de aprovação (fixados ANTES de rodar):
  1. n_IS >= 30 e n_OOS >= 15 (IS = 60% iniciais do período de cada ativo, OOS = 40% finais)
  2. PF >= 1.20 e resultado > 0 no IS e no OOS
  3. spread x2: PF do período todo >= 1.10
  4. platô: pelo menos 6 das 12 saídas do mesmo sinal/sessão/timeframe com PF >= 1.05 no período todo
  5. risco mediano por trade <= US$12 no lote mínimo (conta de ~US$164)
Ranking: estatística t do resultado por trade (período todo), exigindo t > 0 nas duas metades.

  python -m backtest.agentes_v3.grid
"""
from __future__ import annotations

import itertools
import json
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from agents import v3_signals as V
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt, summarize, trades_usd
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
MAX_BARS = 96
SESS = {"GOLD": ["all", "day", "night"], "US500Cash": ["all", "ny"], "BTCUSD": ["all", "us"]}
EXITS = [dict(sl=sl, trail=tr, act=ac, tp=tp) for sl in (1.5, 3.0)
         for (tr, ac, tp) in ((0, 0, 0), (0, 0, 3.0), (1.5, 0, 0), (1.5, 1.0, 0), (3.0, 0, 0), (3.0, 1.0, 0))]


def signal_specs():
    s = []
    s += [dict(family="ST", p=p, m=m, filter=f) for p, m, f in itertools.product((10, 14), (2.0, 3.0), ("none", "ema200"))]
    s += [dict(family="CHAN", k=k, filter=f) for k, f in itertools.product((1.5, 2.0, 3.0), ("none", "slope"))]
    s += [dict(family="SWEEP", n=n, filter=f) for n, f in itertools.product((24, 48, 96), ("none", "ma100_300"))]
    s += [dict(family="RSIX", x=x, side=sd, filter=f)
          for x, sd, f in itertools.product((15, 20, 25), ("long", "both"), ("none", "ma200"))]
    s += [dict(family="RSIPB", n=n, lvl=lv, filter="ma200") for n, lv in itertools.product((2, 7), (10, 30))]
    s += [dict(family="DON", n=n, filter=f) for n, f in itertools.product((20, 55), ("none", "ma200"))]
    s += [dict(family="EMAX", f=f, s=sl) for f, sl in ((9, 21), (20, 50), (50, 200))]
    s += [dict(family="BB", k=k, filter=f) for k, f in itertools.product((2.0, 2.5), ("none", "ma200"))]
    return s


def name(spec):
    return "_".join(f"{k}={v}" for k, v in spec.items())


def job(args):
    sym, tf = args
    b = bars(sym, tf)
    x = V.indicators(b)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    cut = b["time"].iloc[int(len(b) * 0.6)]
    rows = []
    for spec in signal_specs():
        base = V.signal(x, spec)
        for sess in SESS[sym]:
            sig = np.where(V.session_mask(b["time"], sess, TF_MIN[tf]), base, 0).astype(np.int64)
            for ei, ex in enumerate(EXITS):
                res = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], ex["trail"], ex["act"], ex["tp"], MAX_BARS, 1.0)
                tr = trades_usd(sym, b, res)
                u = tr["usd"].to_numpy()
                ins = (tr["t_out"] < cut).to_numpy()
                A, B, F = summarize(u[ins]), summarize(u[~ins]), summarize(u)
                tstat = lambda v: float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))) if len(v) > 2 and v.std() > 0 else 0.0
                row = {"sym": sym, "tf": tf, "sess": sess, "sig": name(spec), "exit": ei, **{f"ex_{k}": v for k, v in ex.items()},
                       "n_is": A["n"], "pf_is": A["pf"], "net_is": A["net"], "n_oos": B["n"], "pf_oos": B["pf"],
                       "net_oos": B["net"], "n": F["n"], "pf": F["pf"], "net": F["net"], "dd": F["dd"], "wr": F["wr"],
                       "t": tstat(u), "t_is": tstat(u[ins]), "t_oos": tstat(u[~ins]),
                       "risk_med": float(tr["risk_usd"].median()) if len(tr) else 0.0, "pf_x2": np.nan, "spec": json.dumps(spec)}
                if A["pf"] >= 1.2 and B["pf"] >= 1.2 and A["n"] >= 30 and B["n"] >= 15:
                    r2 = trades_usd(sym, b, run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], ex["trail"], ex["act"],
                                                   ex["tp"], MAX_BARS, 2.0))
                    row["pf_x2"] = summarize(r2["usd"].to_numpy())["pf"]
                rows.append(row)
    return rows


def main() -> None:
    t0 = time.time()
    for sym in SPECS:                               # cache de barras (carrega os ticks uma vez por ativo)
        for tf in TF_MIN:
            bars(sym, tf)
    print(f"barras prontas em {time.time() - t0:.0f}s", flush=True)
    jobs = [(s, tf) for s in SPECS for tf in TF_MIN]
    rows = []
    with Pool(min(8, len(jobs))) as pool:
        for r in pool.imap_unordered(job, jobs):
            rows += r
            print(f"{r[0]['sym']} {r[0]['tf']}: {len(r)} estratégias ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    plateau = df.groupby(["sym", "tf", "sess", "sig"])["pf"].transform(lambda v: int((v >= 1.05).sum()))
    df["plateau"] = plateau
    df["aprovada"] = ((df.n_is >= 30) & (df.n_oos >= 15) & (df.pf_is >= 1.2) & (df.pf_oos >= 1.2) & (df.net_is > 0)
                      & (df.net_oos > 0) & (df.pf_x2 >= 1.1) & (df.plateau >= 6) & (df.risk_med <= 12.0)
                      & (df.t_is > 0) & (df.t_oos > 0))
    df.to_csv(OUT / "grid_v3.csv", index=False)
    ok = df[df.aprovada].sort_values("t", ascending=False)
    print(f"\n{len(df)} estratégias testadas | aprovadas: {len(ok)} ({time.time() - t0:.0f}s)")
    print(df.groupby("sym").agg(testadas=("aprovada", "size"), aprovadas=("aprovada", "sum")).to_string())
    cols = ["sym", "tf", "sess", "sig", "ex_sl", "ex_trail", "ex_act", "ex_tp", "n_is", "pf_is", "n_oos", "pf_oos",
            "pf_x2", "net", "dd", "wr", "t", "plateau", "risk_med"]
    print(ok[cols].head(40).to_string(index=False))
    ok.to_csv(OUT / "aprovadas_v3.csv", index=False)


if __name__ == "__main__":
    main()
