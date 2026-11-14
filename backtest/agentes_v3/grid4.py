"""Grade v4 — foco em ACERTO >= 60% sem abrir mão do lucro. Um ativo por vez: GOLD, BTCUSD, US500Cash.

84 sinais (8 famílias, parâmetros ampliados) x sessões x M5/M15/H1 x 32 saídas (SL 1.5/2/3/4 ATR, alvo
0.5/0.75/1/1.5 ATR, saída por tempo em 24 ou 96 barras). Mesmo motor e custos da v3 (spread real de ticks).

Critérios (fixados ANTES de rodar), todos obrigatórios:
  1. acerto >= 60% no IS e no OOS (trade vencedor = resultado em US$ > 0, já com spread e swap)
  2. PF >= 1.15 e resultado > 0 no IS e no OOS
  3. n_IS >= 40 e n_OOS >= 20
  4. spread x2: PF >= 1.05 e acerto >= 55% no período todo
  5. platô: >= 8 das 32 saídas do mesmo sinal/sessão/timeframe com PF >= 1.05 e acerto >= 58%
  6. risco mediano <= US$12 por trade (lote mínimo)
Ranking: estatística t do resultado por trade.

  python -m backtest.agentes_v3.grid4 GOLD        (ou BTCUSD / US500Cash; sem argumento roda os três)
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from agents import v3_signals as V
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
SESS = {"GOLD": ["all", "day", "night"], "US500Cash": ["all", "ny"], "BTCUSD": ["all", "us"]}
EXITS = [dict(sl=sl, trail=0.0, act=0.0, tp=tp, max_bars=mb)
         for sl in (1.5, 2.0, 3.0, 4.0) for tp in (0.5, 0.75, 1.0, 1.5) for mb in (24, 96)]


def signal_specs():
    s = []
    s += [dict(family="ST", p=p, m=m, filter=f) for p, m, f in itertools.product((7, 10, 14), (1.5, 2.0, 3.0), ("none", "ema200"))]
    s += [dict(family="CHAN", k=k, filter=f) for k, f in itertools.product((1.0, 1.5, 2.0, 3.0), ("none", "slope"))]
    s += [dict(family="SWEEP", n=n, filter=f) for n, f in itertools.product((12, 24, 48, 96), ("none", "ma100_300", "ema200"))]
    s += [dict(family="RSIX", x=x, side=sd, filter=f)
          for x, sd, f in itertools.product((15, 20, 25, 30), ("long", "both"), ("none", "ma200"))]
    s += [dict(family="RSIPB", n=n, lvl=lv, filter="ma200") for n, lv in itertools.product((2, 3, 7), (5, 10, 20, 30))]
    s += [dict(family="DON", n=n, filter=f) for n, f in itertools.product((10, 20, 55), ("none", "ma200"))]
    s += [dict(family="EMAX", f=f, s=sl) for f, sl in ((5, 13), (9, 21), (20, 50), (50, 200))]
    s += [dict(family="BB", k=k, filter=f) for k, f in itertools.product((1.5, 2.0, 2.5, 3.0), ("none", "ma200"))]
    return s


def _stats(u):
    n = len(u)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    gl = -u[u < 0].sum()
    return n, float(u.sum()), (float(u[u > 0].sum() / gl) if gl > 0 else 99.0), float((u > 0).mean())


def _t(u):
    return float(u.mean() / u.std(ddof=1) * np.sqrt(len(u))) if len(u) > 2 and u.std() > 0 else 0.0


def job(args):
    sym, tf, chunk = args
    b = bars(sym, tf)
    x = V.indicators(b)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    cut_i = int(len(b) * 0.6)
    usd_pp, (sw_l, sw_s) = SPECS[sym]["usd_pp"], SPECS[sym]["swap"]
    rows = []
    for spec in chunk:
        base = V.signal(x, spec)
        for sess in SESS[sym]:
            sig = np.where(V.session_mask(b["time"], sess, TF_MIN[tf]), base, 0).astype(np.int64)
            for ei, ex in enumerate(EXITS):
                E, X, S, P, R, N, W = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], 0.0, 0.0, ex["tp"], ex["max_bars"], 1.0)
                u = P * usd_pp + np.where(S == 1, sw_l, sw_s) * N
                ins = X < cut_i
                n1, net1, pf1, wr1 = _stats(u[ins])
                n2, net2, pf2, wr2 = _stats(u[~ins])
                n, net, pf, wr = _stats(u)
                row = (sym, tf, sess, json.dumps(spec), ei, ex["sl"], ex["tp"], ex["max_bars"], n1, net1, pf1, wr1,
                       n2, net2, pf2, wr2, n, net, pf, wr, _t(u), float(np.median(R) * usd_pp) if n else 0.0,
                       float(u.min()) if n else 0.0, np.nan, np.nan)
                if wr1 >= 0.6 and wr2 >= 0.6 and pf1 >= 1.15 and pf2 >= 1.15 and n1 >= 40 and n2 >= 20:
                    E2, X2, S2, P2, R2, N2, W2 = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], 0.0, 0.0, ex["tp"],
                                                        ex["max_bars"], 2.0)
                    _, _, pfx, wrx = _stats(P2 * usd_pp + np.where(S2 == 1, sw_l, sw_s) * N2)
                    row = row[:-2] + (pfx, wrx)
                rows.append(row)
    return rows


COLS = ["sym", "tf", "sess", "spec", "exit", "ex_sl", "ex_tp", "ex_mb", "n_is", "net_is", "pf_is", "wr_is", "n_oos",
        "net_oos", "pf_oos", "wr_oos", "n", "net", "pf", "wr", "t", "risk_med", "worst", "pf_x2", "wr_x2"]


def run_symbol(sym: str) -> pd.DataFrame:
    t0 = time.time()
    for tf in TF_MIN:
        bars(sym, tf)
    specs = signal_specs()
    chunks = [specs[i::4] for i in range(4)]
    jobs = [(sym, tf, ch) for tf in TF_MIN for ch in chunks]
    rows = []
    with Pool(8) as pool:
        for r in pool.imap_unordered(job, jobs):
            rows += r
    df = pd.DataFrame(rows, columns=COLS)
    good = (df.pf >= 1.05) & (df.wr >= 0.58)
    df["plateau"] = good.groupby([df.tf, df.sess, df.spec]).transform("sum")
    df["aprovada"] = ((df.wr_is >= 0.6) & (df.wr_oos >= 0.6) & (df.pf_is >= 1.15) & (df.pf_oos >= 1.15)
                      & (df.net_is > 0) & (df.net_oos > 0) & (df.n_is >= 40) & (df.n_oos >= 20)
                      & (df.pf_x2 >= 1.05) & (df.wr_x2 >= 0.55) & (df.plateau >= 8) & (df.risk_med <= 12.0))
    df.to_csv(OUT / f"grid4_{sym}.csv", index=False)
    ok = df[df.aprovada].sort_values("t", ascending=False)
    ok.to_csv(OUT / f"aprovadas4_{sym}.csv", index=False)
    print(f"\n===== {sym}: {len(df)} estratégias em {time.time() - t0:.0f}s | aprovadas: {len(ok)} | "
          f"com acerto >= 60% nos dois períodos (sem outros critérios): {int(((df.wr_is >= .6) & (df.wr_oos >= .6)).sum())}",
          flush=True)
    show = ["tf", "sess", "spec", "ex_sl", "ex_tp", "ex_mb", "n_is", "wr_is", "pf_is", "n_oos", "wr_oos", "pf_oos",
            "pf_x2", "wr_x2", "net", "t", "plateau", "risk_med", "worst"]
    with pd.option_context("display.width", 300, "display.max_colwidth", 70):
        print(ok[show].head(15).round(3).to_string(index=False), flush=True)
    return df


if __name__ == "__main__":
    syms = sys.argv[1:] or ["GOLD", "BTCUSD", "US500Cash"]
    print(f"sinais: {len(signal_specs())} | saídas: {len(EXITS)} | total previsto: "
          f"{sum(len(signal_specs()) * len(SESS[s]) * 3 * len(EXITS) for s in syms)}", flush=True)
    for s in syms:
        run_symbol(s)
