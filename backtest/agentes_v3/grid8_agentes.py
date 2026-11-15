"""Grade v8 — +600 mil estratégias POR AGENTE num capital de US$100: trailing E stop curto/alvo longo sem trailing.

Mesmos sinais por agente da v7 (família de cada agente x M5/M15/M30/H1 x sessões) x 6.336 saídas:
SL 0.5/0.75/1/1.25/1.5/2/2.5/3 ATR x { sem trailing x alvo nenhum/0.75/1/1.5/2/3/4/5 ATR
                                        | trailing 0.25/0.5/0.75/1/1.25/1.5/2/3 ATR x ativação 0/0.25/0.5/1 ATR x mesmos alvos }
x saída por tempo 24/48/96 barras. US$100, lote mínimo, custos reais, proteção de 8% (stop > US$8 -> pula).
Regras de decisão em backtest/agentes_v3/grid8_decisao.py (fixadas ANTES de rodar).

  python -m backtest.agentes_v3.grid8_agentes
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
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt_cap
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
CAPITAL, RISK_CAP_PCT = 100.0, 8.0
TPS = (0.0, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
EXITS = [dict(sl=sl, trail=tr, act=ac, tp=tp, max_bars=mb)
         for sl in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0) for mb in (24, 48, 96)
         for (tr, ac) in ([(0.0, 0.0)] + [(t, a) for t in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)
                                          for a in (0.0, 0.25, 0.5, 1.0)])
         for tp in TPS]
TFS = ["M5", "M15", "M30", "H1"]


def _p(fam, **grid):
    keys = list(grid)
    return [dict(family=fam, **dict(zip(keys, v))) for v in itertools.product(*grid.values())]


AGENTS = {
    "v4_gold_rsipb_m5": ("GOLD", _p("RSIPB", n=(2, 3, 7), lvl=(10, 20, 30), filter=("ma200",)), ("day", "all", "night")),
    "v4_gold_rsix_m5": ("GOLD", _p("RSIX", x=(20, 25, 30), side=("long", "both"), filter=("ma200", "none")),
                        ("all", "day", "night")),
    "v4_us500_st_h1": ("US500Cash", _p("ST", p=(7, 10, 14), m=(2.0, 2.5, 3.0), filter=("none", "ema200")), ("ny", "all")),
    "v4_us500_bb_h1": ("US500Cash", _p("BB", k=(1.5, 1.75, 2.0, 2.25, 2.5, 3.0), filter=("ma200", "none", "ema200")),
                       ("all", "ny")),
    "v4_btc_rsipb_h1": ("BTCUSD", _p("RSIPB", n=(2, 3, 7), lvl=(5, 10, 20, 30), filter=("ma200", "ema200")), ("all", "us")),
    "goldflip": ("GOLD", _p("CHAN", k=(1.0, 1.5, 2.0, 2.5, 3.0), filter=("slope", "none")), ("day", "all", "night")),
    "goldnight_v2": ("GOLD", _p("CHAN", k=(2.0, 2.5, 3.0, 3.5, 4.0), filter=("slope", "none")), ("night", "all", "day")),
    "sweep48": ("BTCUSD", _p("SWEEP", n=(24, 36, 48, 72, 96), filter=("none", "ma100_300", "ema200")), ("us", "all")),
    "rsi20": ("BTCUSD", _p("RSIX", x=(15, 20, 25, 30), side=("long", "both"), filter=("none", "ma200")), ("all", "us")),
}


def equity_stats(u):
    if len(u) == 0:
        return CAPITAL, 0.0, CAPITAL, False
    eq = CAPITAL + np.cumsum(u)
    peak = np.maximum.accumulate(np.r_[CAPITAL, eq])[1:]
    return float(eq[-1]), float((peak - eq).max()), float(min(CAPITAL, eq.min())), bool(eq.min() <= 10.0)


def job(args):
    agent, tf, specs, sessions = args
    sym = AGENTS[agent][0]
    b = bars(sym, tf)
    x = V.indicators(b)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    cut_i = int(len(b) * 0.6)
    usd_pp, (sw_l, sw_s) = SPECS[sym]["usd_pp"], SPECS[sym]["swap"]
    cap_px = RISK_CAP_PCT / 100 * CAPITAL / usd_pp
    out = []
    for spec in specs:
        base = V.signal(x, spec)
        for sess in sessions:
            sig = np.where(V.session_mask(b["time"], sess, TF_MIN[tf]), base, 0).astype(np.int64)
            if not sig.any():
                continue
            for ei, ex in enumerate(EXITS):
                E, X, S, P, R, N, W = run_bt_cap(o, h, l, c, sp, a, sig, sday, ex["sl"], ex["trail"], ex["act"], ex["tp"],
                                                 ex["max_bars"], 1.0, cap_px)
                u = P * usd_pp + np.where(S == 1, sw_l, sw_s) * N
                ins = X < cut_i
                ui, uo = u[ins], u[~ins]
                n_is = len(ui)
                if n_is < 30:
                    continue
                gl = -ui[ui < 0].sum()
                pf_is = ui[ui > 0].sum() / gl if gl > 0 else 99.0
                if pf_is < 1.0:
                    continue
                fi, ddi, mni, ruin_i = equity_stats(ui)
                fo, ddo, mno, ruin_o = equity_stats(uo)
                ff, ddf, mnf, ruin_f = equity_stats(u)
                glo = -uo[uo < 0].sum()
                out.append((agent, sym, tf, sess, json.dumps(spec), ei, ex["sl"], ex["trail"], ex["act"], ex["tp"],
                            ex["max_bars"], n_is, float(ui.sum()), pf_is, float((ui > 0).mean()), ddi, ruin_i,
                            len(uo), float(uo.sum()), (uo[uo > 0].sum() / glo if glo > 0 else 99.0),
                            float((uo > 0).mean()) if len(uo) else 0.0, ddo, ruin_o,
                            ff, ddf, mnf, ruin_f, float(np.median(R) * usd_pp)))
    return agent, len(specs) * len(sessions) * len(EXITS), out


COLS = ["agente", "sym", "tf", "sess", "spec", "exit", "ex_sl", "ex_trail", "ex_act", "ex_tp", "ex_mb", "n_is", "net_is",
        "pf_is", "wr_is", "dd_is", "quebra_is", "n_oos", "net_oos", "pf_oos", "wr_oos", "dd_oos", "quebra_oos",
        "capital_final", "dd_total", "capital_min", "quebra", "risco_med"]


def main(names):
    t0 = time.time()
    for name in names:                                      # cache de barras antes de abrir os processos
        for tf in TFS:
            bars(AGENTS[name][0], tf)
    jobs = []
    for name in names:
        sym, specs, sessions = AGENTS[name]
        for tf in TFS:
            for i in range(2):
                jobs.append((name, tf, specs[i::2], sessions))
    tested = {n: 0 for n in names}
    rows = []
    with Pool(8) as pool:
        for agent, n, out in pool.imap_unordered(job, jobs):
            tested[agent] += n
            rows += out
    df = pd.DataFrame(rows, columns=COLS)
    df.to_pickle(OUT / "grid8_candidatos.pkl")
    res = []
    for name in names:
        g = df[df.agente == name]
        elig = g[(g.pf_is >= 1.2) & (g.dd_is <= 30) & (~g.quebra_is)]
        pick = elig.sort_values("net_is", ascending=False).head(1)
        hind = g[~g.quebra].sort_values("capital_final", ascending=False).head(1)
        r = {"agente": name, "testadas": tested[name], "elegiveis_IS": len(elig)}
        if len(pick):
            p = pick.iloc[0]
            r.update({"escolha_IS": f"{p.tf} {p.sess} {p.spec} SL{p.ex_sl} TR{p.ex_trail}/{p.ex_act} TP{p.ex_tp} T{p.ex_mb}",
                      "IS_US$": round(p.net_is, 2), "IS_acerto": round(p.wr_is, 3), "OOS_n": int(p.n_oos),
                      "OOS_US$": round(p.net_oos, 2), "OOS_PF": round(p.pf_oos, 2), "OOS_acerto": round(p.wr_oos, 3),
                      "OOS_DD": round(p.dd_oos, 2), "OOS_quebra": bool(p.quebra_oos), "risco_med": round(p.risco_med, 2)})
        if len(hind):
            h = hind.iloc[0]
            r.update({"retrospecto_capital_final": round(h.capital_final, 2), "retrospecto_DD": round(h.dd_total, 2)})
        res.append(r)
    out = pd.DataFrame(res).sort_values("OOS_US$", ascending=False)
    out.to_csv(OUT / "grid8_resultado.csv", index=False)
    with pd.option_context("display.width", 400, "display.max_colwidth", 130):
        print(out.to_string(index=False))
    print(f"\ntotal testado: {sum(tested.values()):,} em {time.time() - t0:.0f}s | por agente: {tested}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(AGENTS))
