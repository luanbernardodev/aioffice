"""Trailing / breakeven nos 20 agentes novos (v4 e of_btc), mesmo sinal, SL, TP e saída por tempo.

Variantes (trail, act) em múltiplos do ATR do sinal; o stop só aperta e é atualizado no fechamento da barra:
  atual (0, 0) | trailing puro (1.0, 0.5) (1.5, 0.5) (1.5, 1.0) (2.0, 1.0)
  breakeven + trailing (0.5, 0.5) (0.75, 0.75) (1.0, 1.0): ao ganhar X ATR o stop vai para a entrada e segue a X ATR
Regra de adoção (fixada ANTES de rodar), por agente:
  1. PF IS e PF OOS >= os atuais, e pelo menos um deles >= atual + 0.05
  2. acerto >= 60% (v4) / 70% (of_btc) no IS e no OOS
  3. PF com spread x2 >= 1.05
Senão o agente fica como está.

  python -m backtest.agentes_v3.trailing_test
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents import v3_signals as V
from agents.v3_agent import load_agents_config
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt
from backtest.agentes_v3.grid4 import _stats
from orderflow import filters as OF

VARIANTS = [(0.0, 0.0), (1.0, 0.5), (1.5, 0.5), (1.5, 1.0), (2.0, 1.0), (0.5, 0.5), (0.75, 0.75), (1.0, 1.0)]


def context(g):
    """(barras, sinal final, índice do corte) exatamente como na grade que aprovou o agente."""
    sym, tf, spec = g["symbol"], g["timeframe"], dict(g["signal"])
    of = spec.pop("of_filter", None)
    if of:
        from backtest.orderflow.grid_of import CUT, dataset
        b, fx, has = dataset()
        x = V.indicators(b)
        s = np.where(V.session_mask(b["time"], spec["session"], TF_MIN[tf]), V.signal(x, spec), 0).astype(np.int64)
        s[~has] = 0
        s = OF.apply(s, fx, of)
        cut = int(np.searchsorted(b["hour"].to_numpy(), int(CUT.timestamp() * 1000)))
        return b, x, s, cut, 0.70
    b = bars(sym, tf)
    x = V.indicators(b)
    s = np.where(V.session_mask(b["time"], spec["session"], TF_MIN[tf]), V.signal(x, spec), 0).astype(np.int64)
    return b, x, s, int(len(b) * 0.6), 0.60


def run(g, b, x, s, cut, trail, act, mult=1.0):
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    ex = g["exit"]
    E, X, S, P, R, N, W = run_bt(o, h, l, c, sp, x["atr"], s, b["sday"].to_numpy(np.int64), float(ex["sl"]), trail, act,
                                 float(ex["tp"]), int(g["max_bars"]), mult)
    sp_ = SPECS[g["symbol"]]
    u = P * sp_["usd_pp"] + np.where(S == 1, sp_["swap"][0], sp_["swap"][1]) * N
    ins = X < cut
    return _stats(u[ins]), _stats(u[~ins]), _stats(u)


def main():
    rows, adopt = [], {}
    for name, g in load_agents_config().items():
        if not g["enabled"] or not (name.startswith("v4_") or name.startswith("of_btc_")):
            continue
        b, x, s, cut, wr_min = context(g)
        base = None
        for trail, act in VARIANTS:
            A, B, F = run(g, b, x, s, cut, trail, act)
            x2 = run(g, b, x, s, cut, trail, act, 2.0)[2]
            r = {"agente": name, "trail": trail, "act": act, "n_is": A[0], "wr_is": round(A[3], 3), "pf_is": round(A[2], 2),
                 "n_oos": B[0], "wr_oos": round(B[3], 3), "pf_oos": round(B[2], 2), "net": round(F[1], 1),
                 "pf_x2": round(x2[2], 2)}
            if base is None:
                base = r
                r["adota"] = "atual"
            else:
                ok = (r["pf_is"] >= base["pf_is"] and r["pf_oos"] >= base["pf_oos"]
                      and (r["pf_is"] >= base["pf_is"] + 0.05 or r["pf_oos"] >= base["pf_oos"] + 0.05)
                      and r["wr_is"] >= wr_min and r["wr_oos"] >= wr_min and r["pf_x2"] >= 1.05)
                r["adota"] = "SIM" if ok else ""
                if ok:
                    score = r["pf_is"] + r["pf_oos"]
                    if name not in adopt or score > adopt[name][2]:
                        adopt[name] = (trail, act, score, r)
            rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv("backtest/agentes_v3/trailing_test.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 500):
        print(df.to_string(index=False))
    print("\nAdoção (melhor variante que passa na regra, por agente):")
    for k, (t, a, _, r) in adopt.items():
        print(f"  {k}: trail={t} act={a} | PF IS {r['pf_is']} OOS {r['pf_oos']} | acerto IS {r['wr_is']} OOS {r['wr_oos']}")
    print(f"agentes que melhoram: {len(adopt)} de {df.agente.nunique()}")
    return adopt


if __name__ == "__main__":
    main()
