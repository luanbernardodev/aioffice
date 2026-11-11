"""Varredura na vizinhança do RSI(2) Connors H1 (US100Cash, 2016-09 -> hoje, swap incluso).

Um set só substitui a referência se vencer em acerto real E PF nas DUAS metades do histórico.

  cd backtest/claude_code/us100_validacao && python grid_vizinhanca.py
"""
from __future__ import annotations

import itertools
import time

import numpy as np
import pandas as pd

import rsi2_core as K

OUT = K.HERE / "vizinhanca_rsi2.csv"
TH = (3, 5, 7, 10, 12, 15)
MA = (50, 75, 100, 125, 150, 200)
EXITS = [("rsi", n, v) for n in (3, 5, 7) for v in (50, 60, 70)] + [("sma5", 0, 0)]
SL = (2.0, 3.0, 4.0, 5.0)
ACT = (1.0, 1.5, 2.0)
DIST = (1.0, 1.5, 2.0)


def half_stats(t: pd.DataFrame, cut: pd.Timestamp) -> tuple[dict, dict]:
    return K.stats(t[t.ent < cut]), K.stats(t[t.ent >= cut])


def main() -> None:
    t0 = time.time()
    si = K.symbol_info()
    b = K.load_h1()
    b2 = K.load_h1(spread_mult=2.0)
    cut = b.index[0] + (b.index[-1] - b.index[0]) / 2
    rows = []
    for th, ma, (xm, xn, xv), sl, act, dist in itertools.product(TH, MA, EXITS, SL, ACT, DIST):
        p = {**K.REF, "rsi_th": float(th), "ma_n": ma, "exit_mode": xm, "exit_rsi_n": xn or 5, "exit_rsi": float(xv),
             "sl": sl, "act": act, "trail": dist}
        t = K.simulate(b, p, si)
        s = K.stats(t)
        h1, h2 = half_stats(t, cut)
        yr = t.groupby(t.ent.dt.year).real_win.mean()
        rows.append({"rsi2_th": th, "sma": ma, "saida": "close>SMA5" if xm == "sma5" else f"RSI({xn})>{xv}",
                     "sl": sl, "act": act, "dist": dist, "n": s["n"], "wr_real": s["wr_real"], "pf": s["pf"],
                     "net_pts": s["net"], "dd_pts": s["dd"], "wr_h1": h1["wr_real"], "pf_h1": h1["pf"],
                     "wr_h2": h2["wr_real"], "pf_h2": h2["pf"], "anos_wr60": int((yr >= 0.6).sum()), "anos": len(yr),
                     "wr_min_ano": float(yr.min()) if len(yr) else np.nan})
    df = pd.DataFrame(rows)
    ref = df[(df.rsi2_th == 5) & (df.sma == 100) & (df.saida == "RSI(5)>60") & (df.sl == 3) & (df.act == 1.5)
             & (df.dist == 1.5)].iloc[0]
    df["vence_ref"] = ((df.wr_h1 > ref.wr_h1) & (df.pf_h1 > ref.pf_h1) & (df.wr_h2 > ref.wr_h2) & (df.pf_h2 > ref.pf_h2))
    df["aprovada"] = (df.anos_wr60 == df.anos) & (df.pf >= 1.5)
    cand = df[df.vence_ref | df.aprovada].copy()
    stress = []
    for r in cand.itertuples():
        xm = "sma5" if r.saida == "close>SMA5" else "rsi"
        xn, xv = (0, 0) if xm == "sma5" else (int(r.saida[4]), float(r.saida.split(">")[1]))
        p = {**K.REF, "rsi_th": float(r.rsi2_th), "ma_n": r.sma, "exit_mode": xm, "exit_rsi_n": xn or 5,
             "exit_rsi": xv, "sl": r.sl, "act": r.act, "trail": r.dist}
        stress.append(K.stats(K.simulate(b2, p, si))["pf"])
    cand["pf_custo_x2"] = stress
    df = df.merge(cand[["pf_custo_x2"]], left_index=True, right_index=True, how="left")
    df["aprovada"] = df.aprovada & (df.pf_custo_x2 >= 1.3)
    df = df.sort_values(["aprovada", "vence_ref", "pf"], ascending=False)
    df.to_csv(OUT, index=False, float_format="%.4f")
    print(f"{len(df)} combinações em {time.time() - t0:.0f}s | metade: {cut:%Y-%m-%d}")
    print("referência:", ref[["n", "wr_real", "pf", "wr_h1", "pf_h1", "wr_h2", "pf_h2", "anos_wr60"]].to_dict())
    print("vencem a referência nas 2 metades:", int(df.vence_ref.sum()), "| aprovadas:", int(df.aprovada.sum()))
    print(df.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
