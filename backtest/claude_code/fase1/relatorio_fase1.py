"""Relatório da Fase 1: top 10 únicas aprovadas + referência — curva de capital, DD, meses positivos.

  cd backtest/claude_code/fase1 && python relatorio_fase1.py      (depois de run_fase1.py)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import engine2 as E
from run_fase1 import LOT, STRESS_SLIP_PTS, STRESS_SPREAD, TFS, exits_for
from signals_f1 import all_groups, cross_dn, cross_up, to_sig

OUT_MD = E.HERE / "relatorio_fase1.md"
OUT_SVG = E.HERE / "curvas_top10.svg"
COLORS = ["#2a6fdb", "#e0533d", "#2f9e44", "#9c36b5", "#f08c00", "#1098ad", "#c2255c", "#5c940d", "#495057",
          "#d9480f", "#000000"]


def trades_of(b, A, roll, sig, e, sw, slip=0.0, mult=1.0):
    o, h, l, c, sp = (b[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "spread"))
    p, ei, xi, sd = E.bt2(o, h, l, c, sp * mult, A, sig, *e[:5], int(e[5]), slip, roll, sw)
    return pd.DataFrame({"pnl": p, "side": sd, "ent": b["time"].iloc[ei].to_numpy(), "ex": b["time"].iloc[xi].to_numpy()})


def stats(t: pd.DataFrame, cs: float) -> dict:
    p = t.pnl.to_numpy()
    eq = np.cumsum(p)
    dd = (np.maximum.accumulate(np.maximum(eq, 0)) - eq).max() if len(p) else 0.0
    mon = t.groupby(t.ex.dt.tz_localize(None).dt.to_period("M")).pnl.sum()
    return {"trades": len(p), "net_usd": p.sum() * cs * LOT, "pf": float(E.pf(p[p > 0].sum(), -p[p < 0].sum())),
            "win": (p > 0).mean() * 100, "dd_usd": dd * cs * LOT, "meses_pos": f"{int((mon > 0).sum())}/{len(mon)}",
            "mensal_usd": (mon * cs * LOT).round(1)}


def svg(curves: list[tuple[str, pd.DataFrame]], cs: float, w=900, hgt=420, pad=50) -> str:
    t0 = min(t.ex.min() for _, t in curves if len(t))
    t1 = max(t.ex.max() for _, t in curves if len(t))
    ys = [np.cumsum(t.pnl.to_numpy()) * cs * LOT for _, t in curves]
    lo, hi = min(0, min(y.min() for y in ys)), max(y.max() for y in ys)
    X = lambda ts: pad + (ts - t0) / (t1 - t0) * (w - 2 * pad)
    Y = lambda v: hgt - pad - (v - lo) / (hi - lo) * (hgt - 2 * pad)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{hgt + 22 * ((len(curves) + 1) // 2)}" '
           f'font-family="sans-serif" font-size="11"><rect width="100%" height="100%" fill="white"/>',
           f'<line x1="{pad}" y1="{Y(0):.1f}" x2="{w - pad}" y2="{Y(0):.1f}" stroke="#999" stroke-dasharray="4"/>']
    for v in np.linspace(lo, hi, 6):
        out.append(f'<text x="{pad - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    for m in pd.date_range(t0.normalize(), t1, freq="MS"):
        out.append(f'<text x="{X(m):.1f}" y="{hgt - pad + 16}" text-anchor="middle">{m:%m/%y}</text>')
    out.append(f'<text x="{pad}" y="16">Curva de capital acumulada, US$ com lote {LOT} (inclui swap XM)</text>')
    for k, ((name, t), y) in enumerate(zip(curves, ys)):
        col = COLORS[k % len(COLORS)]
        pts = " ".join(f"{X(a):.1f},{Y(v):.1f}" for a, v in zip(t.ex, y))
        dash = ' stroke-dasharray="6 3"' if name.startswith("REF") else ""
        out.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.6"{dash} points="{X(t0):.1f},{Y(0):.1f} {pts}"/>')
        lx, ly = pad + (k % 2) * (w - 2 * pad) / 2, hgt + 4 + 22 * (k // 2)
        out.append(f'<rect x="{lx}" y="{ly}" width="12" height="4" fill="{col}"/>'
                   f'<text x="{lx + 18}" y="{ly + 6}">{name[:70]}</text>')
    return "\n".join(out + ["</svg>"])


def main() -> None:
    df = pd.read_pickle(E.HERE / "_ranking_full.pkl")
    summ = json.loads((E.HERE / "resumo_fase1.json").read_text(encoding="utf-8"))
    si = E.symbol_costs()
    sw = E.swap_per_roll(si)
    cs = float(si["trade_contract_size"])
    top = df[df.approved].head(10)
    cache = {}
    for tf, minutes in TFS.items():
        if tf in set(top.tf) | {"H1"}:
            b = E.load_bars(minutes)
            groups, A = all_groups(b)
            cache[tf] = (b, A, E.rollovers(b["time"], int(si["swap_rollover3days"])), groups, exits_for(minutes))

    curves, lines, monthly = [], [], {}
    for r in top.itertuples():
        b, A, roll, groups, ex = cache[r.tf]
        sig, e = groups[r.gidx]["sigs"][r.sidx], ex[r.eidx]
        t = trades_of(b, A, roll, sig, e, sw)
        s = stats(t, cs)
        name = f"#{r.rank} {r.tf} {r.family} {r.params} f={r.filter} SL{r.sl} TR{r.trail} ACT{r.act} TP{r.tp} BE{r.be} TS{r.ts_d}d"
        curves.append((name, t))
        monthly[f"#{r.rank}"] = s["mensal_usd"]
        lines.append(f"| {r.rank} | {r.tf} | {r.family} | `{r.params}` | {r.filter} | {r.sl}/{r.trail}/{r.act}/{r.tp}/{r.be}/{r.ts_d} "
                     f"| {s['trades']} | {s['net_usd']:.0f} | {s['pf']:.2f} | {r.pf_is:.2f} | {r.pf_oos:.2f} | {r.pf_stress:.2f} "
                     f"| {r.wf1_pf:.2f}/{r.wf2_pf:.2f}/{r.wf3_pf:.2f} | {r.neighbors:.0%} | {r.max_trade_share:.0%} "
                     f"| {s['dd_usd']:.0f} | {s['meses_pos']} | {s['win']:.0f}% |")

    # referência (RSI7 25/75 + SMA100, SL 1.5, trailing 3, sem TP) com os mesmos custos
    b, A, roll, _, _ = cache["H1"]
    c = b["close"].to_numpy(np.float64)
    R, M = E.rsi(c, 7), E.sma(c, 100)
    ref_sig = to_sig(cross_up(R, 25) & (c > M), cross_dn(R, 75) & (c < M))
    ref_e = np.array([1.5, 3.0, 0.0, 0.0, 0.0, 0])
    tr = trades_of(b, A, roll, ref_sig, ref_e, sw)
    trs = trades_of(b, A, roll, ref_sig, ref_e, sw, STRESS_SLIP_PTS * si["point"], STRESS_SPREAD)
    sr = stats(tr, cs)
    split = tr.ent < E.SPLIT
    pfx = lambda p: float(E.pf(p[p > 0].sum(), -p[p < 0].sum()))
    curves.append(("REF H1 RSI7 25/75 SMA100 SL1.5 TR3", tr))
    monthly["REF"] = sr["mensal_usd"]
    OUT_SVG.write_text(svg(curves, cs), encoding="utf-8")

    mt = pd.DataFrame(monthly).fillna(0).round(0).astype(int)
    mt.index = mt.index.astype(str)
    proc = summ["walk_forward_processo"]
    md = [
        "# Fase 1 — backtest em massa BTCUSD (H1/H2/H4)",
        "",
        f"Gerado em {summ['gerado_em'][:16]} UTC. Dados: ticks reais BTCUSD do MT5 (XM) 01/11/2025 → 10/11/2026, barras BID "
        "com spread médio real da barra; entrada no open da barra seguinte; 1 posição; motor `engine2.py` (= `bt` do "
        "`engine.py` + breakeven, slippage, swap e time-stop; idêntico ao original quando desligados).",
        "",
        f"Custos: contract size {cs:g} (US$ = pontos × {cs:g} × {LOT}); swap XM lido de `mt5.symbol_info` "
        f"(modo {si['swap_mode']}: long {si['swap_long']} / short {si['swap_short']} pontos por noite = "
        f"US$ {sw[0] * cs * LOT:.2f} / {sw[1] * cs * LOT:.2f} por noite com 0.01 lote), cobrado a cada virada de dia do "
        "servidor (NY+7h).",
        "",
        "## Volume testado",
        "",
        f"- **{summ['combinacoes_novas']:,} combinações novas** ({summ['por_tf']}); {summ['repetidas_excluidas']} "
        "combinações idênticas às de `resultados_10944.csv` foram excluídas do ranking.",
        f"- Com ≥40 trades: {summ['com_40_trades']:,}. Passaram trades + PF IS>1.3 + PF OOS>1.2: "
        f"{summ['pre_aprovadas_brutas']:,} ({summ['pre_aprovadas_unicas']:,} com comportamento distinto).",
        f"- **Aprovadas em todos os critérios: {summ['aprovadas_brutas']:,} ({summ['aprovadas_unicas']:,} distintas).** "
        "Muitas variantes são idênticas na prática (ex.: com SL 1 ATR e trailing 3 ATR a ativação 0–1.5R nunca muda o "
        "stop); o ranking guarda só a mais simples e conta as demais em `equivalentes`.",
        "",
        "Critérios: ≥40 trades; PF IS (11/2025–06/2026) > 1.3; PF OOS (07/2026–11/2026) > 1.2; ≥60% dos vizinhos "
        "(±1 passo em cada parâmetro ordenado) lucrativos; maior trade ≤30% do lucro; spread ×1.5 + slippage 10 pts "
        f"com PF > 1.10; walk-forward (3 janelas: mar–mai, jun–ago, set–nov/2026) com PF>1 em ≥2 janelas e soma positiva.",
        "",
        "## Top 10 (distintas, aprovadas)",
        "",
        "| # | TF | Família | Parâmetros | Filtro | SL/Trail/Ativ/TP/BE/TS | Trades | US$ | PF | PF IS | PF OOS | PF estresse "
        "| WF PF | Vizinhos | Maior trade | DD US$ | Meses + | Acerto |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *lines,
        f"| ref | H1 | RSIPB | `RSI7 25/75, SMA100` | none | 1.5/3/0/0/0/0 | {sr['trades']} | {sr['net_usd']:.0f} | "
        f"{sr['pf']:.2f} | {pfx(tr.pnl[split].to_numpy()):.2f} | {pfx(tr.pnl[~split].to_numpy()):.2f} | "
        f"{pfx(trs.pnl.to_numpy()):.2f} | – | – | – | {sr['dd_usd']:.0f} | {sr['meses_pos']} | {sr['win']:.0f}% |",
        "",
        "![curvas](curvas_top10.svg)",
        "",
        "## Resultado mensal (US$, lote 0.01, com swap)",
        "",
        "| Mês | " + " | ".join(mt.columns) + " |",
        "|---" * (len(mt.columns) + 1) + "|",
        *[f"| {ix} | " + " | ".join(str(v) for v in row) + " |" for ix, row in zip(mt.index, mt.to_numpy())],
        "",
        "## Walk-forward do processo de seleção (leitura obrigatória)",
        "",
        "Em cada janela, escolhe-se o top 10 por PF **só com dados anteriores** (treino ancorado desde 11/2025, mesmos "
        "critérios de trades/PF/vizinhança) e mede-se o resultado na janela seguinte:",
        "",
        "| Janela de teste | Candidatas no treino | PF agregado do top 10 no teste | US$ no teste | Positivas |",
        "|---|---|---|---|---|",
        *[f"| {p['janela']} | {p['candidatas_treino']} | {p['top10_pf_teste_agregado']:.2f} | "
          f"{p['top10_net_teste_pts'] * cs * LOT:.0f} | {p['top10_positivas']}/10 |" for p in proc],
        "",
        "Escolher a \"melhor\" pelo passado falhou em 2 das 3 janelas. Com 6,3 milhões de combinações, PF alto em IS e "
        "OOS ao mesmo tempo aparece também por acaso, e o próprio OOS deixa de ser fora da amostra quando entra no "
        "filtro. Os números do top 10 acima são, portanto, **otimistas**; espere resultado ao vivo bem menor. O período "
        "inteiro tem um único regime dominante (BTC de ~110k para ~60k), o que favorece vendas a favor da tendência.",
        "",
        "## Escolha para o agente (Fase 2)",
        "",
        "A nº 1 aprovada é da mesma família da referência (RSI7 H1, trailing 3×ATR, sem TP), muda só a média "
        "(EMA50 em vez de SMA100), o nível (30/70 em vez de 25/75) e o SL (1.0 em vez de 1.5 ATR). Variando um "
        "parâmetro por vez, todas as vizinhas com trades suficientes continuam lucrativas. Ela vai como padrão do "
        "agente; a referência fica pronta no mesmo config (bloco comentado).",
    ]
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(OUT_MD)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
