"""Fase 1 — backtest em massa BTCUSD (H1/H2/H4) com validação IS/OOS/walk-forward/vizinhança/estresse.

  cd backtest/claude_code/fase1 && python run_fase1.py

Saídas: backtest/claude_code/ranking_fase1.csv, fase1/relatorio_fase1.md, fase1/curvas_top10.png,
        fase1/resumo_fase1.json, fase1/melhor_estrategia.json
"""
from __future__ import annotations

import itertools
import json
import time

import numpy as np
import pandas as pd

import engine2 as E
from signals_f1 import all_groups

OUT_DIR = E.HERE
RANK_CSV = E.HERE.parent / "ranking_fase1.csv"
OLD_CSV = E.HERE.parent / "resultados_10944.csv"

TFS = {"H1": 60, "H2": 120, "H4": 240}
TF_OLD = {"H1": "1h", "H4": "4h"}
SL = (1.0, 1.5, 2.0, 3.0)
TRAIL = (2.0, 3.0, 4.0, 5.0)
ACT = (0.0, 0.5, 1.0, 1.5)
TP = (0.0, 2.0, 3.0, 5.0)
BE = (0.0, 1.0)
TS_DAYS = (0, 3)                              # time-stop opcional: 3 dias
EXIT_AXES = [("sl", SL), ("trail", TRAIL), ("act", ACT), ("tp", TP), ("be", BE), ("ts_d", TS_DAYS)]

# critérios de aprovação
MIN_TRADES, PF_IS, PF_OOS, NEIGH, MAX_SHARE = 40, 1.3, 1.2, 0.60, 0.30
STRESS_SPREAD, STRESS_SLIP_PTS, PF_STRESS = 1.5, 10, 1.10
LOT = 0.01


def exits_for(minutes: int) -> np.ndarray:
    bars_day = 1440 // minutes
    return np.array([(sl, tr, ac, tp, be, td * bars_day) for sl, tr, ac, tp, be, td
                     in itertools.product(SL, TRAIL, ACT, TP, BE, TS_DAYS)], np.float64)


def neighbor_frac(pos: np.ndarray) -> np.ndarray:
    """Fração de vizinhos (±1 passo em cada eixo ordenado) com resultado positivo."""
    cnt = np.zeros(pos.shape, np.int32)
    good = np.zeros(pos.shape, np.int32)
    p = pos.astype(np.int32)
    for d in range(pos.ndim):
        if pos.shape[d] < 2:
            continue
        lo = [slice(None)] * pos.ndim
        hi = [slice(None)] * pos.ndim
        lo[d], hi[d] = slice(0, -1), slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        cnt[lo] += 1; good[lo] += p[hi]
        cnt[hi] += 1; good[hi] += p[lo]
    return np.where(cnt > 0, good / np.maximum(cnt, 1), 0.0)


def old_keys() -> set:
    d = pd.read_csv(OLD_CSV, usecols=["tf", "strat", "sl", "trail", "act", "tp"])
    return set(zip(d.tf, d.strat, d.sl.round(3), d.trail.round(3), d.act.round(3), d.tp.round(3)))


def repeat_mask(tf: str, g: dict, shape: tuple, olds: set) -> np.ndarray:
    """Combinações idênticas às de resultados_10944.csv (mesma regra de sinal, mesma saída, sem BE/time-stop)."""
    rep = np.zeros(shape, bool)
    if g["family"] != "RSIPB" or g["cat"]["ma_t"] != "sma" or g["cat"]["filter"] != "none" or tf not in TF_OLD:
        return rep
    axes = [v for _, v in g["axes"]] + [v for _, v in EXIT_AXES]
    for idx in itertools.product(*[range(len(v)) for v in axes]):
        rn, lo, mn, sl, tr, ac, tp, be, td = (axes[j][i] for j, i in enumerate(idx))
        if be or td:
            continue
        names = [f"RSIREV_r{rn}_{lo}/{100 - lo}_ma{mn}", f"RSIPULL_r{rn}_{lo}_ma{mn}"]
        if any((TF_OLD[tf], nm, round(sl, 3), round(tr, 3), round(ac, 3), round(tp, 3)) in olds for nm in names):
            rep[idx] = True
    return rep


def describe(g: dict, sidx: tuple) -> str:
    parts = [f"{name}={vals[i]}" for (name, vals), i in zip(g["axes"], sidx)]
    cat = [f"{k}={v}" for k, v in g["cat"].items() if k != "filter"]
    return " ".join(cat + parts)


def main() -> None:
    t_all = time.time()
    si = E.symbol_costs()
    swl, sws, swpl, swps = E.swap_per_roll(si)
    cs = float(si["trade_contract_size"])
    slip_stress = STRESS_SLIP_PTS * float(si["point"])
    print(f"BTCUSD ({si['source']}): contract={cs} swap_mode={si['swap_mode']} long={si['swap_long']} "
          f"short={si['swap_short']} pts -> {swl:.2f}/{sws:.2f} preço por rollover", flush=True)
    olds = old_keys()
    rows, wf_proc, totals = [], [], {"combos": 0, "repetidas": 0, "com_40_trades": 0, "por_tf": {}}
    data = {}

    for tf, minutes in TFS.items():
        t0 = time.time()
        b = E.load_bars(minutes)
        o, h, l, c, sp = (b[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread"))
        roll = E.rollovers(b["time"], int(si["swap_rollover3days"]))
        split, wf = E.window_idx(b["time"])
        groups, A = all_groups(b)
        ex = exits_for(minutes)
        data[tf] = (b, A, roll, groups, ex)
        n_tf = 0
        for gi, g in enumerate(groups):
            sdims = tuple(len(v) for _, v in g["axes"])
            res = E.grid(o, h, l, c, sp, A, g["sigs"], ex, split, wf, 0.0, roll, swl, sws, swpl, swps)
            res = res.reshape(sdims + tuple(len(v) for _, v in EXIT_AXES) + (E.NM,)).astype(np.float64)
            rep = repeat_mask(tf, g, res.shape[:-1], olds)
            n_cells = int(np.prod(res.shape[:-1]))
            totals["combos"] += n_cells - int(rep.sum()); totals["repetidas"] += int(rep.sum()); n_tf += n_cells
            N, net = res[..., E.M_N], res[..., E.M_NET]
            totals["com_40_trades"] += int(((N >= MIN_TRADES) & ~rep).sum())
            nb = neighbor_frac(net > 0)
            pf_is = E.pf(res[..., E.M_GPIS], res[..., E.M_GLIS])
            pf_oos = E.pf(res[..., E.M_GPOOS], res[..., E.M_GLOOS])
            share = np.where(net > 0, res[..., E.M_MAXW] / np.where(net > 0, net, 1), 9.0)
            pre = (N >= MIN_TRADES) & (pf_is > PF_IS) & (pf_oos > PF_OOS) & ~rep

            # walk-forward do PROCESSO: treino ancorado = tudo antes da janela (aditivo: total - janelas >= w)
            for w in range(3):
                after = sum(res[..., E.M_WF0 + 3 * j: E.M_WF0 + 3 * j + 3] for j in range(w, 3))
                tr = res[..., [E.M_N, E.M_GP, E.M_GL]] - after
                te = res[..., E.M_WF0 + 3 * w: E.M_WF0 + 3 * w + 3]
                trn = tr[..., 1] - tr[..., 2]
                frac_train = (wf[w, 0]) / len(c)
                okt = ((tr[..., 0] >= MIN_TRADES * frac_train) & (E.pf(tr[..., 1], tr[..., 2]) > PF_IS)
                       & (neighbor_frac(trn > 0) >= NEIGH) & ~rep)
                cand = np.flatnonzero(okt)
                ptr = E.pf(tr[..., 1], tr[..., 2]).ravel()[cand]
                for flat in cand[np.argsort(-ptr)[:10]]:
                    idx = np.unravel_index(flat, okt.shape)
                    wf_proc.append((w, tf, gi, idx, float(E.pf(tr[idx][1], tr[idx][2])), float(trn[idx]),
                                    int(te[idx][0]), float(te[idx][1]), float(te[idx][2])))

            for idx in zip(*np.nonzero(pre)):
                m = res[idx]
                k_s = len(sdims)
                wfp = [float(E.pf(m[E.M_WF0 + 3 * j + 1], m[E.M_WF0 + 3 * j + 2])) for j in range(3)]
                wfn = [m[E.M_WF0 + 3 * j + 1] - m[E.M_WF0 + 3 * j + 2] for j in range(3)]
                exv = {name: vals[i] for (name, vals), i in zip(EXIT_AXES, idx[k_s:])}
                rows.append({"tf": tf, "family": g["family"], "params": describe(g, idx[:k_s]),
                             "filter": g["cat"]["filter"], **exv, "gidx": gi, "sidx": int(np.ravel_multi_index(idx[:k_s], sdims)),
                             "eidx": int(np.ravel_multi_index(idx[k_s:], tuple(len(v) for _, v in EXIT_AXES))),
                             "n": int(m[E.M_N]), "net_pts": m[E.M_NET], "net_usd": m[E.M_NET] * cs * LOT,
                             "pf": float(E.pf(m[E.M_GP], m[E.M_GL])), "dd_pts": m[E.M_DD], "dd_usd": m[E.M_DD] * cs * LOT,
                             "n_is": int(m[E.M_NIS]), "pf_is": float(pf_is[idx]), "n_oos": int(m[E.M_NOOS]),
                             "pf_oos": float(pf_oos[idx]), "wf1_pf": wfp[0], "wf2_pf": wfp[1], "wf3_pf": wfp[2],
                             "wf_pos": int(sum(x > 0 for x in wfn)), "wf_net": float(sum(wfn)),
                             "neighbors": float(nb[idx]), "max_trade_share": float(share[idx])})
        totals["por_tf"][tf] = n_tf
        print(f"{tf}: {len(groups)} grupos, {n_tf:,} combinações, {time.time() - t0:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    print(f"pré-aprovadas (trades/PF IS/PF OOS): {len(df)}", flush=True)

    # estresse (spread x1.5 + slippage) e métricas por trade para as pré-aprovadas
    stress = []
    for r in df.itertuples():
        b, A, roll, groups, ex = data[r.tf]
        o, h, l, c, sp = (b[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread"))
        sig = groups[r.gidx]["sigs"][r.sidx]
        e = ex[r.eidx]
        p, ei, xi, sd = E.bt2(o, h, l, c, sp * STRESS_SPREAD, A, sig, *e[:5], int(e[5]), slip_stress, roll,
                              (swl, sws, swpl, swps))
        p0, ei0, xi0, sd0 = E.bt2(o, h, l, c, sp, A, sig, *e[:5], int(e[5]), 0.0, roll, (swl, sws, swpl, swps))
        mon = pd.Series(p0, index=b["time"].iloc[xi0].dt.tz_localize(None).dt.to_period("M")).groupby(level=0).sum()
        stress.append({"pf_stress": float(E.pf(p[p > 0].sum(), -p[p < 0].sum())), "net_stress_pts": p.sum(),
                       "wr": float((p0 > 0).mean()), "months_pos": int((mon > 0).sum()), "months": int(len(mon)),
                       "worst_trade_pts": float(p0.min()), "long_n": int((sd0 == 1).sum()), "short_n": int((sd0 == -1).sum())})
    df = pd.concat([df, pd.DataFrame(stress, index=df.index)], axis=1)
    df["ok_neighbors"] = df.neighbors >= NEIGH
    df["ok_share"] = df.max_trade_share <= MAX_SHARE
    df["ok_stress"] = (df.pf_stress > PF_STRESS) & (df.net_stress_pts > 0)
    df["ok_wf"] = (df.wf_pos >= 2) & (df.wf_net > 0)
    df["approved"] = df.ok_neighbors & df.ok_share & df.ok_stress & df.ok_wf
    df["score"] = df[["pf_is", "pf_oos", "pf_stress"]].min(axis=1)
    # combinações com comportamento idêntico (ex.: ativação que nunca muda o stop, time-stop que nunca dispara)
    # viram uma linha só: fica a variante mais simples e "equivalentes" conta quantas eram iguais
    df = df.sort_values(["approved", "score", "net_pts", "act", "ts_d", "be", "tp"],
                        ascending=[False, False, False, True, True, True, True]).reset_index(drop=True)
    key = [df.tf, df.family, df.params, df["filter"], df.n, df.net_pts.round(2), df.dd_pts.round(2),
           df.pf_stress.round(4)]
    df["equivalentes"] = df.groupby(key)["n"].transform("size")
    n_pre_raw, n_appr_raw = len(df), int(df.approved.sum())
    df = df.drop_duplicates(subset=["tf", "family", "params", "filter", "n", "net_pts", "dd_pts", "pf_stress"]
                            ).reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, len(df) + 1))
    pub = [c for c in df.columns if c not in ("gidx", "sidx", "eidx")]
    df[pub].to_csv(RANK_CSV, index=False, float_format="%.4f")

    # walk-forward do processo: top-10 por PF de treino em cada janela -> resultado na janela de teste
    wfp = pd.DataFrame(wf_proc, columns=["w", "tf", "g", "idx", "pf_train", "net_train", "n_test", "gp_test", "gl_test"])
    proc = []
    for w in range(3):
        top = wfp[wfp.w == w].sort_values(["pf_train", "net_train"], ascending=False).head(10)
        proc.append({"janela": f"{E.WF[w][0]:%Y-%m}..{E.WF[w][1]:%Y-%m}", "candidatas_treino": int((wfp.w == w).sum()),
                     "top10_pf_teste_agregado": float(E.pf(top.gp_test.sum(), top.gl_test.sum())) if len(top) else None,
                     "top10_net_teste_pts": float((top.gp_test - top.gl_test).sum()) if len(top) else None,
                     "top10_positivas": int(((top.gp_test - top.gl_test) > 0).sum())})

    appr = df[df.approved]
    summary = {"gerado_em": pd.Timestamp.now(tz="UTC").isoformat(), "symbol_info": si,
               "swap_por_rollover_preco": {"long": swl, "short": sws},
               "combinacoes_novas": totals["combos"], "repetidas_excluidas": totals["repetidas"],
               "por_tf": totals["por_tf"], "com_40_trades": totals["com_40_trades"],
               "pre_aprovadas_brutas": n_pre_raw, "aprovadas_brutas": n_appr_raw,
               "pre_aprovadas_unicas": int(len(df)), "aprovadas_unicas": int(len(appr)),
               "falhas": {k: int((~df[k]).sum()) for k in ("ok_neighbors", "ok_share", "ok_stress", "ok_wf")},
               "walk_forward_processo": proc, "segundos": round(time.time() - t_all)}
    (OUT_DIR / "resumo_fase1.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    best = appr.iloc[0] if len(appr) else None
    (OUT_DIR / "melhor_estrategia.json").write_text(json.dumps(
        None if best is None else {k: (v.item() if hasattr(v, "item") else v) for k, v in best[pub].items()},
        indent=2, default=str), encoding="utf-8")
    df.to_pickle(OUT_DIR / "_ranking_full.pkl")
    print(json.dumps({k: v for k, v in summary.items() if k != "symbol_info"}, indent=2, default=str))


if __name__ == "__main__":
    main()
