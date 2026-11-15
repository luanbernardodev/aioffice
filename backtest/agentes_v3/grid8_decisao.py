"""Decisão sobre a grade v8 (regras fixadas ANTES de rodar a grade; US$100, proteção de 8%).

Por agente, só com o IS (60% iniciais):
  T = escolha robusta entre as saídas COM trailing; C = escolha robusta entre as saídas SEM trailing com stop curto e
  alvo longo (SL <= 1 ATR e alvo >= 3 x SL). Robusta = sinal (tf/sessão/parâmetros) com mais saídas elegíveis no IS
  (n >= 30, PF >= 1.2, DD <= US$30, sem quebra) e maior mediana de resultado IS; dentro dele, a saída com resultado IS
  mais próximo da mediana. Entre T e C fica a de maior resultado IS.
Portão no OOS (40% finais, nunca vistos): lucro > 0, PF >= 1.2, sem quebra, DD <= US$40 e resultado maior que o da
configuração ATUAL do agente no mesmo US$100. Para v4_gold_rsipb_m5 também maior que +72.03 (escolha da v7); se não
passar, aplica-se a escolha da v7 (M15 madrugada com trailing). goldflip e engine A2 são desligados (sugestão aprovada).

  python -m backtest.agentes_v3.grid8_decisao
"""
from __future__ import annotations

import json

import pandas as pd

from backtest.agentes_v3.grid7_robusto import CUR, run
from backtest.agentes_v3.grid7_agentes import equity_stats

V7_GOLD = {"tf": "M15", "sess": "night", "spec": {"family": "RSIPB", "n": 7, "lvl": 30, "filter": "ma200"},
           "exit": {"sl": 1.0, "trail": 1.0, "act": 0.5, "tp": 3.0, "max_bars": 24}, "oos": 72.03}


def robust(e: pd.DataFrame):
    if e.empty:
        return None
    sig = e.groupby(["tf", "sess", "spec"]).net_is.agg(["size", "median"]).sort_values(["size", "median"], ascending=False)
    key = sig.index[0]
    cand = e[(e.tf == key[0]) & (e.sess == key[1]) & (e.spec == key[2])]
    return cand.iloc[(cand.net_is - cand.net_is.median()).abs().argsort()[:1]].iloc[0], int(sig.iloc[0]["size"])


def main():
    df = pd.read_pickle("backtest/agentes_v3/grid8_candidatos.pkl")
    eleg = df[(df.pf_is >= 1.2) & (df.dd_is <= 30) & (~df.quebra_is)]
    rows, apply = [], {}
    for name in sorted(df.agente.unique()):
        g = eleg[eleg.agente == name]
        T = robust(g[g.ex_trail > 0])
        C = robust(g[(g.ex_trail == 0) & (g.ex_sl <= 1.0) & (g.ex_tp >= 3 * g.ex_sl)])
        picks = [(lab, p) for lab, p in (("trailing", T), ("stop curto/alvo longo", C)) if p is not None]
        ui, uo = run(*CUR[name])
        base = float(uo.sum())
        r = {"agente": name, "atual_OOS_US$": round(base, 2), "atual_OOS_n": len(uo), "atual_OOS_DD": round(equity_stats(uo)[1], 2)}
        for lab, (p, k) in picks:
            r[f"{lab}: escolha"] = f"{p.tf} {p.sess} {p.spec} SL{p.ex_sl} TR{p.ex_trail}/{p.ex_act} TP{p.ex_tp} T{p.ex_mb} ({k} saídas)"
            r[f"{lab}: IS/OOS US$"] = f"{p.net_is:+.2f} / {p.net_oos:+.2f} (PF {p.pf_oos:.2f}, DD {p.dd_oos:.1f}, n {p.n_oos})"
        decision = "mantém a configuração atual"
        if picks:
            lab, (p, k) = max(picks, key=lambda t: t[1][0].net_is)
            gate = (p.net_oos > 0 and p.pf_oos >= 1.2 and not p.quebra_oos and p.dd_oos <= 40 and p.net_oos > base)
            if name == "v4_gold_rsipb_m5":
                gate = gate and p.net_oos > V7_GOLD["oos"]
            if gate:
                decision = f"APLICA {lab}"
                apply[name] = {"tf": p.tf, "sess": p.sess, "spec": json.loads(p.spec),
                               "exit": {"sl": p.ex_sl, "trail": p.ex_trail, "act": p.ex_act, "tp": p.ex_tp,
                                        "max_bars": int(p.ex_mb)}, "oos": round(p.net_oos, 2), "origem": f"v8 {lab}"}
        if name == "v4_gold_rsipb_m5" and name not in apply:
            decision = "APLICA a escolha da v7 (v8 não superou +72.03)"
            apply[name] = {**V7_GOLD, "origem": "v7 trailing"}
        r["decisão"] = decision
        rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv("backtest/agentes_v3/grid8_decisao.csv", index=False)
    with open("backtest/agentes_v3/grid8_decisao.json", "w", encoding="utf-8") as fh:
        json.dump({"aplicar": apply, "desligar": ["goldflip", "engine A2"]}, fh, ensure_ascii=False, indent=2)
    with pd.option_context("display.width", 500, "display.max_colwidth", 120):
        print(out.T.to_string())
    print("\naplicar:", json.dumps(apply, ensure_ascii=False))


if __name__ == "__main__":
    main()
