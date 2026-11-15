"""Grade v5 — trailing stop OBRIGATÓRIO, acerto >= 70% e risco que cabe numa conta de ~US$100.

84 sinais x sessões x M5/M15/H1 x 72 saídas (todas com trailing): SL 1.0/1.5/2.0 ATR x (trailing, ativação)
(0.5, 0.25) (0.75, 0.5) (1.0, 0.5) (1.5, 1.0) x alvo nenhum/1/2 ATR x saída por tempo 24/96 barras.
GOLD 54.432 + US500Cash 36.288 + BTCUSD 36.288 = 127.008 estratégias. Mesmo motor e custos da v3/v4.

Critérios (fixados ANTES de rodar), todos obrigatórios:
  1. acerto >= 70% no IS e no OOS
  2. PF >= 1.15 e resultado > 0 no IS e no OOS
  3. n_IS >= 30 e n_OOS >= 15
  4. spread x2: PF >= 1.05 e acerto >= 65%
  5. platô: >= 18 das 72 saídas do mesmo sinal/sessão/timeframe com PF >= 1.05 e acerto >= 68%
  6. risco por trade (lote mínimo): mediana <= US$4.5 e percentil 90 <= US$6
  7. drawdown máximo do período todo <= US$25

  python -m backtest.agentes_v3.grid5            (ou: GOLD / BTCUSD / US500Cash)
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from agents import v3_signals as V
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt
from backtest.agentes_v3.grid4 import SESS, _stats, _t, signal_specs
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
TRAILS = [(0.5, 0.25), (0.75, 0.5), (1.0, 0.5), (1.5, 1.0)]
EXITS = [dict(sl=sl, trail=tr, act=ac, tp=tp, max_bars=mb)
         for sl in (1.0, 1.5, 2.0) for (tr, ac) in TRAILS for tp in (0.0, 1.0, 2.0) for mb in (24, 96)]


def _dd(u):
    if len(u) == 0:
        return 0.0
    eq = np.cumsum(u)
    return float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max())


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
                E, X, S, P, R, N, W = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], ex["trail"], ex["act"], ex["tp"],
                                             ex["max_bars"], 1.0)
                u = P * usd_pp + np.where(S == 1, sw_l, sw_s) * N
                ins = X < cut_i
                n1, net1, pf1, wr1 = _stats(u[ins])
                n2, net2, pf2, wr2 = _stats(u[~ins])
                n, net, pf, wr = _stats(u)
                risk = R * usd_pp
                row = [sym, tf, sess, json.dumps(spec), ei, ex["sl"], ex["trail"], ex["act"], ex["tp"], ex["max_bars"],
                       n1, net1, pf1, wr1, n2, net2, pf2, wr2, n, net, pf, wr, _t(u),
                       float(np.median(risk)) if n else 0.0, float(np.percentile(risk, 90)) if n else 0.0, _dd(u),
                       np.nan, np.nan]
                if wr1 >= 0.7 and wr2 >= 0.7 and pf1 >= 1.15 and pf2 >= 1.15 and n1 >= 30 and n2 >= 15:
                    E2, X2, S2, P2, R2, N2, W2 = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], ex["trail"], ex["act"],
                                                        ex["tp"], ex["max_bars"], 2.0)
                    _, _, pfx, wrx = _stats(P2 * usd_pp + np.where(S2 == 1, sw_l, sw_s) * N2)
                    row[-2:] = [pfx, wrx]
                rows.append(row)
    return rows


COLS = ["sym", "tf", "sess", "spec", "exit", "ex_sl", "ex_trail", "ex_act", "ex_tp", "ex_mb", "n_is", "net_is",
        "pf_is", "wr_is", "n_oos", "net_oos", "pf_oos", "wr_oos", "n", "net", "pf", "wr", "t", "risk_med", "risk_p90",
        "dd", "pf_x2", "wr_x2"]


def run_symbol(sym: str) -> pd.DataFrame:
    t0 = time.time()
    specs = signal_specs()
    jobs = [(sym, tf, specs[i::4]) for tf in TF_MIN for i in range(4)]
    rows = []
    with Pool(8) as pool:
        for r in pool.imap_unordered(job, jobs):
            rows += r
    df = pd.DataFrame(rows, columns=COLS)
    good = (df.pf >= 1.05) & (df.wr >= 0.68)
    df["plateau"] = good.groupby([df.tf, df.sess, df.spec]).transform("sum")
    df["aprovada"] = ((df.wr_is >= .7) & (df.wr_oos >= .7) & (df.pf_is >= 1.15) & (df.pf_oos >= 1.15)
                      & (df.net_is > 0) & (df.net_oos > 0) & (df.n_is >= 30) & (df.n_oos >= 15)
                      & (df.pf_x2 >= 1.05) & (df.wr_x2 >= .65) & (df.plateau >= 18)
                      & (df.risk_med <= 4.5) & (df.risk_p90 <= 6.0) & (df.dd <= 25.0))
    df.to_csv(OUT / f"grid5_{sym}.csv", index=False)
    ok = df[df.aprovada].sort_values("t", ascending=False)
    ok.to_csv(OUT / f"aprovadas5_{sym}.csv", index=False)
    wr70 = int(((df.wr_is >= .7) & (df.wr_oos >= .7)).sum())
    print(f"\n===== {sym}: {len(df)} estratégias em {time.time() - t0:.0f}s | acerto >= 70% nos dois períodos: {wr70} | "
          f"aprovadas: {len(ok)}", flush=True)
    show = ["tf", "sess", "spec", "ex_sl", "ex_trail", "ex_act", "ex_tp", "ex_mb", "n_is", "wr_is", "pf_is", "n_oos",
            "wr_oos", "pf_oos", "pf_x2", "net", "dd", "risk_med", "risk_p90", "plateau", "t"]
    with pd.option_context("display.width", 320, "display.max_colwidth", 64):
        print(ok[show].head(15).round(3).to_string(index=False), flush=True)
    return df


if __name__ == "__main__":
    syms = sys.argv[1:] or ["GOLD", "BTCUSD", "US500Cash"]
    print(f"sinais {len(signal_specs())} | saídas {len(EXITS)} | total previsto "
          f"{sum(len(signal_specs()) * len(SESS[s]) * 3 * len(EXITS) for s in syms)}", flush=True)
    for s in syms:
        run_symbol(s)
