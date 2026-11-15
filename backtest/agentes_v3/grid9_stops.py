"""Grade v9 — onde colocar o stop de cada agente, num capital de US$140 (814.752 estratégias).

23 agentes (15 of_btc, 5 v4, goldnight_v2/sweep48/rsi20 pela família equivalente), cada um com o SINAL EXATO que está
configurado, x 41 stops x 8 alvos x 6 trailings x 3 saídas por tempo x 6 limites de risco por trade:
  stops   ATR: 0.5/0.75/1/1.25/1.5/1.75/2/2.5/3/3.5/4/5 x ATR do sinal
          estrutura: além da mínima/máxima das últimas 3/5/10/20/50 barras + folga 0/0.1/0.25/0.5 ATR
          fixo: US$3/4/5/6/8/10/12/15/20 de risco no lote mínimo
  alvos   nenhum/0.5/0.75/1/1.5/2/3/5 ATR · trailing (0,0) (0.5,0.25) (0.5,0.5) (1,0.5) (1.5,1) (2,1)
  tempo   24/48/96 barras · limite de risco por trade: sem limite / 5 / 8 / 10 / 12 / 15% de US$140
Escolha só pelo IS (60% iniciais): maior resultado com n_IS >= 20, PF_IS >= 1.2, DD_IS <= US$49 (35%), sem quebra
(quebra = equity <= US$28); mostra o OOS. Robustez por família de stop: % das configurações com resultado > 0 no IS e no OOS.

  python -m backtest.agentes_v3.grid9_stops
"""
from __future__ import annotations

import json
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from agents import v3_signals as V
from agents.v3_agent import load_agents_config
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt_stop
from backtest.agentes_v3.grid7_robusto import CUR
from backtest.agentes_v3.trailing_test import context
from engine.config import ROOT

OUT = ROOT / "backtest" / "agentes_v3"
CAPITAL = 140.0
ATR_K = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0)
STRUCT = [(n, b) for n in (3, 5, 10, 20, 50) for b in (0.0, 0.1, 0.25, 0.5)]
FIXED = (3, 4, 5, 6, 8, 10, 12, 15, 20)
TPS = (0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
TRAILS = [(0.0, 0.0), (0.5, 0.25), (0.5, 0.5), (1.0, 0.5), (1.5, 1.0), (2.0, 1.0)]
MBS = (24, 48, 96)
CAPS = (None, 5.0, 8.0, 10.0, 12.0, 15.0)
OLD = ("goldnight_v2", "sweep48", "rsi20")


def stop_list():
    return ([("ATR", 0, k, 0) for k in ATR_K] + [("estrutura", 1, b, n) for n, b in STRUCT] +
            [("fixo", 2, float(u), 0) for u in FIXED])


def agent_setup(name):
    if name in OLD:
        sym, tf, spec, _ = CUR[name]
        b = bars(sym, tf)
        x = V.indicators(b)
        s = np.where(V.session_mask(b["time"], spec.get("session", "all"), TF_MIN[tf]), V.signal(x, spec), 0).astype(np.int64)
        return sym, b, x, s, int(len(b) * 0.6)
    g = load_agents_config()[name]
    b, x, s, cut, _ = context(g)
    return g["symbol"], b, x, s, cut


def eq_stats(u):
    if len(u) == 0:
        return 0.0, 0.0, False
    eq = CAPITAL + np.cumsum(u)
    dd = float((np.maximum.accumulate(np.r_[CAPITAL, eq])[1:] - eq).max())
    return float(u.sum()), dd, bool(eq.min() <= 0.2 * CAPITAL)


def job(name):
    sym, b, x, s, cut = agent_setup(name)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    usd_pp, sw = SPECS[sym]["usd_pp"], SPECS[sym]["swap"]
    lows, highs = pd.Series(l), pd.Series(h)
    LLs = {n: lows.rolling(n).min().to_numpy() for n in (3, 5, 10, 20, 50)}
    HHs = {n: highs.rolling(n).max().to_numpy() for n in (3, 5, 10, 20, 50)}
    cols = {k: [] for k in ("familia", "stop", "tp", "trail", "act", "mb", "cap", "n_is", "net_is", "pf_is", "wr_is",
                            "dd_is", "q_is", "n_oos", "net_oos", "pf_oos", "wr_oos", "dd_oos", "q_oos", "risco_med")}
    for fam, mode, k, n in stop_list():
        LL, HH = (LLs[n], HHs[n]) if mode == 1 else (c, c)
        kk = k / usd_pp if mode == 2 else k
        label = f"{k:g}xATR" if mode == 0 else (f"N{n}+{k:g}ATR" if mode == 1 else f"US${k:g}")
        for cap in CAPS:
            cap_px = 1e18 if cap is None else cap / 100 * CAPITAL / usd_pp
            for tp in TPS:
                for tr, ac in TRAILS:
                    for mb in MBS:
                        E, X, S, P, R, N, W = run_bt_stop(o, h, l, c, sp, a, s, sday, mode, kk, LL, HH, tr, ac, tp, mb,
                                                          1.0, cap_px)
                        u = P * usd_pp + np.where(S == 1, sw[0], sw[1]) * N
                        ins = X < cut
                        ui, uo = u[ins], u[~ins]
                        ni, di, qi = eq_stats(ui)
                        no, do, qo = eq_stats(uo)
                        gi, go = -ui[ui < 0].sum(), -uo[uo < 0].sum()
                        for key, v in (("familia", fam), ("stop", label), ("tp", tp), ("trail", tr), ("act", ac),
                                       ("mb", mb), ("cap", -1.0 if cap is None else cap), ("n_is", len(ui)),
                                       ("net_is", ni), ("pf_is", ui[ui > 0].sum() / gi if gi > 0 else 99.0),
                                       ("wr_is", float((ui > 0).mean()) if len(ui) else 0.0), ("dd_is", di), ("q_is", qi),
                                       ("n_oos", len(uo)), ("net_oos", no), ("pf_oos", uo[uo > 0].sum() / go if go > 0 else 99.0),
                                       ("wr_oos", float((uo > 0).mean()) if len(uo) else 0.0), ("dd_oos", do), ("q_oos", qo),
                                       ("risco_med", float(np.median(R)) * usd_pp if len(R) else 0.0)):
                            cols[key].append(v)
    df = pd.DataFrame(cols)
    df.insert(0, "agente", name)
    return df


def main(reuse: bool = False):
    t0 = time.time()
    names = [k for k, g in load_agents_config().items() if g["enabled"]] + list(OLD)
    if reuse and (OUT / "grid9_stops.pkl").exists():
        df = pd.read_pickle(OUT / "grid9_stops.pkl")
    else:
        for sym in SPECS:
            for tf in TF_MIN:
                bars(sym, tf)
        with Pool(8) as pool:
            parts = pool.map(job, names)
        df = pd.concat(parts, ignore_index=True)
        df.to_pickle(OUT / "grid9_stops.pkl")
    print(f"{len(df):,} estratégias em {time.time() - t0:.0f}s ({len(names)} agentes)")
    # 1) escolha pelo IS, por agente
    el = df[(df.n_is >= 20) & (df.pf_is >= 1.2) & (df.dd_is <= 0.35 * CAPITAL) & (~df.q_is)]
    pick = el.sort_values("net_is", ascending=False).groupby("agente").head(1).set_index("agente")
    # 2) robustez por família de stop
    rob = df.assign(ok=(df.net_is > 0) & (df.net_oos > 0) & (~df.q_is) & (~df.q_oos)).groupby(["agente", "familia"]).agg(
        robustas=("ok", "mean"), oos_mediano=("net_oos", "median")).unstack()
    fam = df.assign(ok=(df.net_is > 0) & (df.net_oos > 0) & (~df.q_is) & (~df.q_oos)).groupby("familia").agg(
        robustas=("ok", "mean"), oos_mediano=("net_oos", "median"), quebra_oos=("q_oos", "mean"))
    # 3) melhor stop por agente dentro da família mais robusta (escolha pelo IS)
    rows = []
    for name in names:
        g = df[df.agente == name]
        best_fam = rob.loc[name, ("robustas", slice(None))].droplevel(0).idxmax()
        e = el[(el.agente == name) & (el.familia == best_fam)]
        r = {"agente": name, "familia_mais_robusta": best_fam,
             "robustas_%": {f: round(100 * rob.loc[name, ("robustas", f)], 1) for f in ("ATR", "estrutura", "fixo")}}
        if name in pick.index:
            p = pick.loc[name]
            r["melhor_IS"] = (f"{p.stop} TP{p.tp:g} TR{p.trail:g}/{p.act:g} T{p.mb} cap{('-' if p.cap < 0 else f'{p.cap:g}')}% "
                              f"| IS {p.net_is:+.1f} -> OOS {p.net_oos:+.1f} (PF {p.pf_oos:.2f}, DD {p.dd_oos:.1f}, quebra {p.q_oos})")
        if len(e):
            q = e.sort_values("net_is", ascending=False).iloc[0]
            r["melhor_na_familia_robusta"] = (f"{q.stop} TP{q.tp:g} TR{q.trail:g}/{q.act:g} T{q.mb} cap{('-' if q.cap < 0 else f'{q.cap:g}')}% "
                                              f"| IS {q.net_is:+.1f} -> OOS {q.net_oos:+.1f} (PF {q.pf_oos:.2f}, DD {q.dd_oos:.1f}, risco {q.risco_med:.1f})")
        rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "grid9_stops_resultado.csv", index=False)
    fam.to_csv(OUT / "grid9_stops_familias.csv")
    with pd.option_context("display.width", 400, "display.max_colwidth", 140, "display.max_rows", 100):
        print("\nFAMÍLIAS DE STOP (todas as configurações de todos os agentes):")
        print(fam.round(3).to_string())
        print(out.to_string(index=False))


if __name__ == "__main__":
    import sys
    main(reuse="--relatorio" in sys.argv)
