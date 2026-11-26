"""Grade semanal: a grade v8 (sinais da família de cada agente x M5/M15/M30/H1 x sessões x 6.336 saídas, US$100,
proteção de 8%) rodada de novo com os dados atualizados, só para os agentes ligados que têm família na v8.

Regras FIXAS (as mesmas da v8, decididas antes de rodar):
  escolha  = maior lucro no IS entre as elegíveis (PF IS >= 1.2, DD IS <= US$30, sem quebra)  -> o OOS não escolhe
  candidata se, no OOS: >= 10 trades, PF >= 1.2, acerto >= 60%, lucro > 0 e sem quebra
Candidata NÃO é aprovada: só entra no relatório. Trocar configuração ao vivo é decisão do usuário.
of_btc ficam fora (motor de orderflow próprio); são cobertos pela revalidação.
"""
from __future__ import annotations

import os
import time
from multiprocessing import Pool
from typing import Dict, List

import pandas as pd

from backtest.agentes_v3 import grid8_agentes as G8
from backtest.agentes_v3.bt import bars

# agente ligado -> família de sinais na v8 (o m15n nasceu da família RSIPB do ouro)
FAMILIA = {"v4_gold_rsipb_m15n": "v4_gold_rsipb_m5", "v4_gold_rsix_m5": "v4_gold_rsix_m5",
           "v4_us500_st_h1": "v4_us500_st_h1", "v4_us500_bb_h1": "v4_us500_bb_h1", "v4_btc_rsipb_h1": "v4_btc_rsipb_h1",
           "goldnight_v2": "goldnight_v2", "sweep48": "sweep48", "rsi20": "rsi20"}


def escolher(g: pd.DataFrame) -> Dict:
    elig = g[(g.pf_is >= 1.2) & (g.dd_is <= 30) & (~g.quebra_is)]
    r = {"testadas_com_trades": len(g), "elegiveis_IS": len(elig)}
    if not len(elig):
        return {**r, "candidata": False, "motivo": "nenhuma elegível no IS"}
    p = elig.sort_values("net_is", ascending=False).iloc[0]
    ok = bool(p.n_oos >= 10 and p.pf_oos >= 1.2 and p.wr_oos >= 0.60 and p.net_oos > 0 and not p.quebra_oos)
    return {**r, "candidata": ok, "motivo": "passou no OOS" if ok else "melhor do IS reprovou no OOS",
            "config": f"{p.tf} {p.sess} {p.spec} SL{p.ex_sl} TR{p.ex_trail}/{p.ex_act} TP{p.ex_tp} T{p.ex_mb}",
            "IS_US$": round(p.net_is, 2), "IS_PF": round(p.pf_is, 2), "IS_acerto": round(p.wr_is, 3),
            "OOS_n": int(p.n_oos), "OOS_US$": round(p.net_oos, 2), "OOS_PF": round(p.pf_oos, 2),
            "OOS_acerto": round(p.wr_oos, 3), "OOS_DD": round(p.dd_oos, 2), "risco_med": round(p.risco_med, 2)}


def rodar(ativos: List[str], max_horas: float = 8.0, processos: int | None = None) -> pd.DataFrame:
    t0 = time.time()
    fams = {a: FAMILIA[a] for a in ativos if a in FAMILIA}
    keys = sorted(set(fams.values()))
    for k in keys:                                            # cache de barras antes de abrir os processos
        for tf in G8.TFS:
            bars(G8.AGENTS[k][0], tf)
    jobs = [(k, tf, G8.AGENTS[k][1][i::2], G8.AGENTS[k][2]) for k in keys for tf in G8.TFS for i in range(2)]
    n_proc = processos or max(1, (os.cpu_count() or 2) - 2)  # deixa núcleos livres para os agentes ao vivo
    tested = {k: 0 for k in keys}
    rows, done, cortada = [], 0, False
    deadline = t0 + max_horas * 3600
    with Pool(n_proc) as pool:
        it = pool.imap_unordered(G8.job, jobs)
        while done < len(jobs):
            try:
                agent, n, out = it.next(timeout=max(1.0, deadline - time.time()))
            except Exception:  # noqa: BLE001  (TimeoutError do multiprocessing)
                cortada = True
                pool.terminate()
                break
            tested[agent] += n
            rows += out
            done += 1
    df = pd.DataFrame(rows, columns=G8.COLS)
    res = []
    for live, k in fams.items():
        res.append({"agente": live, "familia_v8": k, "testadas": tested[k], **escolher(df[df.agente == k])})
    out = pd.DataFrame(res)
    out.attrs.update({"segundos": round(time.time() - t0), "processos": n_proc, "cortada_por_tempo": cortada,
                      "jobs": f"{done}/{len(jobs)}", "total_testado": sum(tested.values())})
    return out
