"""Complementos da grade v7 (US$100, proteção de 8%):
  A) escolha ROBUSTA só pelo IS: o sinal (tf/sessão/parâmetros) com mais saídas de trailing elegíveis no IS
     (n>=30, PF>=1.2, DD<=30, sem quebra) e maior mediana de resultado IS entre elas; dentro dele, a saída com
     resultado IS mais próximo da mediana (não a melhor) -> mostra o OOS.
  B) linha de base: a configuração ATUAL de cada agente (como está rodando), no mesmo US$100 e mesma proteção.
  python -m backtest.agentes_v3.grid7_robusto
"""
import json

import numpy as np
import pandas as pd

from agents import v3_signals as V
from agents.v3_agent import load_agents_config
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt_cap
from backtest.agentes_v3.grid7_agentes import CAPITAL, RISK_CAP_PCT, equity_stats

CUR = {   # configuração atual (agentes antigos: família equivalente no motor rápido, com o trailing deles)
    "goldflip": ("GOLD", "M5", dict(family="CHAN", k=1.5, filter="slope", session="day"), dict(sl=1.5, trail=1.5, act=0, tp=0, max_bars=96)),
    "goldnight_v2": ("GOLD", "M5", dict(family="CHAN", k=3.0, filter="slope", session="night"), dict(sl=3.0, trail=3.0, act=0, tp=0, max_bars=96)),
    "sweep48": ("BTCUSD", "M5", dict(family="SWEEP", n=48, filter="ma100_300", session="us"), dict(sl=3.0, trail=0.15, act=0.75, tp=5.0, max_bars=48)),
    "rsi20": ("BTCUSD", "M15", dict(family="RSIX", x=20, side="long", filter="none", session="all"), dict(sl=2.0, trail=0.25, act=0.5, tp=0, max_bars=16)),
}
for k, g in load_agents_config().items():
    if k.startswith("v4_"):
        CUR[k] = (g["symbol"], g["timeframe"], dict(g["signal"]), dict(g["exit"], max_bars=g["max_bars"]))


def run(sym, tf, spec, ex):
    b = bars(sym, tf)
    x = V.indicators(b)
    sig = np.where(V.session_mask(b["time"], spec.get("session", "all"), TF_MIN[tf]), V.signal(x, spec), 0).astype(np.int64)
    usd_pp, sw = SPECS[sym]["usd_pp"], SPECS[sym]["swap"]
    E, X, S, P, R, N, W = run_bt_cap(*(b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread")), x["atr"],
                                     sig, b["sday"].to_numpy(np.int64), float(ex["sl"]), float(ex["trail"]),
                                     float(ex["act"]), float(ex["tp"]), int(ex["max_bars"]), 1.0,
                                     RISK_CAP_PCT / 100 * CAPITAL / usd_pp)
    u = P * usd_pp + np.where(S == 1, sw[0], sw[1]) * N
    ins = X < int(len(b) * 0.6)
    return u[ins], u[~ins]


def pf(v):
    gl = -v[v < 0].sum()
    return round(float(v[v > 0].sum() / gl), 2) if gl > 0 else 99.0


def main():
    df = pd.read_pickle("backtest/agentes_v3/grid7_candidatos.pkl")
    rows = []
    for name, g in df.groupby("agente"):
        e = g[(g.pf_is >= 1.2) & (g.dd_is <= 30) & (~g.quebra_is)]
        r = {"agente": name}
        if len(e):
            sig = e.groupby(["tf", "sess", "spec"]).net_is.agg(["size", "median"]).sort_values(["size", "median"],
                                                                                               ascending=False)
            key = sig.index[0]
            cand = e[(e.tf == key[0]) & (e.sess == key[1]) & (e.spec == key[2])]
            pick = cand.iloc[(cand.net_is - cand.net_is.median()).abs().argsort()[:1]].iloc[0]
            r.update({"robusta": f"{pick.tf} {pick.sess} {pick.spec} SL{pick.ex_sl} TR{pick.ex_trail}/{pick.ex_act} "
                                 f"TP{pick.ex_tp} T{pick.ex_mb}", "saidas_elegiveis": int(sig.iloc[0]["size"]),
                      "IS_US$": round(pick.net_is, 2), "OOS_n": int(pick.n_oos), "OOS_US$": round(pick.net_oos, 2),
                      "OOS_PF": round(pick.pf_oos, 2), "OOS_acerto": round(pick.wr_oos, 3), "OOS_DD": round(pick.dd_oos, 2),
                      "OOS_quebra": bool(pick.quebra_oos)})
        if name in CUR:
            ui, uo = run(*CUR[name])
            r.update({"ATUAL_IS_US$": round(float(ui.sum()), 2), "ATUAL_OOS_n": len(uo), "ATUAL_OOS_US$": round(float(uo.sum()), 2),
                      "ATUAL_OOS_PF": pf(uo), "ATUAL_OOS_acerto": round(float((uo > 0).mean()), 3) if len(uo) else 0.0,
                      "ATUAL_OOS_DD": round(equity_stats(uo)[1], 2)})
        rows.append(r)
    out = pd.DataFrame(rows).sort_values("OOS_US$", ascending=False)
    out.to_csv("backtest/agentes_v3/grid7_robusto.csv", index=False)
    with pd.option_context("display.width", 420, "display.max_colwidth", 110):
        print(out.to_string(index=False))


if __name__ == "__main__":
    main()
