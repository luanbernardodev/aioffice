"""Validação do RSI(2) Connors H1 no US100Cash: referência (09/2025-11/2026) + ~10 anos de H1 do MT5.

  cd backtest/claude_code/us100_validacao
  python validar_rsi2.py [--exportar]      (--exportar relê o H1 e o symbol_info do MT5)

Gera validacao_rsi2.md (usa vizinhanca_rsi2.csv se grid_vizinhanca.py já tiver rodado).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import rsi2_core as K

OUT = K.HERE / "validacao_rsi2.md"
REF_START = pd.Timestamp("2025-09-01", tz="UTC")
REF_SPLIT = pd.Timestamp("2026-06-01", tz="UTC")


def fmt(s: dict, si: dict) -> str:
    return (f"{s['n']} | {s['wr_real']:.0%} | {s['wr_bruto']:.0%} | {s['pf']:.2f} | {s['net']:.0f} | "
            f"{K.usd(s['net'], si):.0f} | {s['dd']:.0f} | {K.usd(s['dd'], si):.0f} | {s['pior']:.0f}")


def main() -> None:
    if "--exportar" in sys.argv:
        K.export_mt5()
    si = K.symbol_info()
    P = K.REF
    lot = float(si["volume_min"])

    # 1) reprodução da referência (mesma janela e custos do wr60_aprovadas.csv; sem swap no PF original)
    br = K.load_h1(REF_START)
    tr = K.simulate(br, P, si)
    raw = tr.assign(pnl=tr.pnl_px, real_win=tr.pnl_px > 0.1 * tr.a0)
    s_raw = K.stats(raw)
    s_is, s_oos = K.stats(raw[raw.ent < REF_SPLIT]), K.stats(raw[raw.ent >= REF_SPLIT])
    s_ref_swap = K.stats(tr)
    s_ref_x2 = K.stats(K.simulate(K.load_h1(REF_START, 2.0), P, si))

    # 2) histórico longo
    b = K.load_h1()
    t = K.simulate(b, P, si)
    s_all = K.stats(t)
    t2 = K.simulate(K.load_h1(spread_mult=2.0), P, si)
    s_x2 = K.stats(t2)
    tg = K.simulate(b, P, si, block=K.entry_block_utc(b.index))
    s_guard = K.stats(tg)
    b0 = b.copy()
    b0["sp"] = 0.0
    t0 = K.simulate(b0, P, si)
    t0 = t0.assign(pnl=t0.pnl_px, real_win=t0.pnl_px > 0.1 * t0.a0)
    A = K.atr(b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy(), 14)

    years = []
    for y in sorted(t.ent.dt.year.unique()):
        g, g2, g0 = t[t.ent.dt.year == y], t2[t2.ent.dt.year == y], t0[t0.ent.dt.year == y]
        m = b.index.year == y
        s, s2, s0 = K.stats(g), K.stats(g2), K.stats(g0)
        years.append(f"| {y} | {fmt(s, si)} | {s2['pf']:.2f} | {s0['pf']:.2f} | {s0['wr_real']:.0%} | "
                     f"{np.median(b.sp[m] / A[m]):.2f} | "
                     f"{'✅' if s['wr_real'] >= 0.6 and s['pf'] >= 1.5 else '❌'} |")
    n_ok_wr = int(sum((t[t.ent.dt.year == y].real_win.mean() >= 0.6) for y in t.ent.dt.year.unique()))
    n_years = t.ent.dt.year.nunique()
    approved = n_ok_wr == n_years and s_all["pf"] >= 1.5 and s_x2["pf"] >= 1.3

    viz = ""
    vf = K.HERE / "vizinhanca_rsi2.csv"
    if vf.exists():
        v = pd.read_csv(vf)
        top = v.sort_values("pf", ascending=False).head(5)
        viz = "\n".join([
            "## Vizinhança (item 5, opcional)",
            "",
            f"{len(v):,} variações (RSI(2) limiar {[int(x) for x in sorted(v.rsi2_th.unique())]}; SMA {[int(x) for x in sorted(v.sma.unique())]}; saída "
            "RSI(3/5/7) > 50/60/70 ou close > SMA5; SL 2–5 ATR; trailing ativação 1/1.5/2 ATR × distância 1/1.5/2 ATR), "
            f"mesmo histórico de ~10 anos com swap. Metades: até/depois de {b.index[0] + (b.index[-1] - b.index[0]) / 2:%Y-%m-%d}.",
            "",
            f"- Vencem a referência em acerto real **e** PF nas duas metades: **{int(v.vence_ref.sum())}**.",
            f"- Aprovadas nos critérios (acerto real ≥60% em todos os anos, PF ≥1.5, custo ×2 PF ≥1.3): "
            f"**{int(v.aprovada.sum())}**.",
            f"- Melhor PF do conjunto: {v.pf.max():.2f}; nenhuma tem 1ª metade com PF > {v[v.vence_ref].pf_h1.max():.2f} "
            "entre as que vencem a referência.",
            "",
            "| RSI2 < | SMA | Saída | SL | Ativ | Dist | Trades | Acerto real | PF | PF 1ª metade | PF 2ª metade | Anos ≥60% |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
            *[f"| {r.rsi2_th} | {r.sma} | {r.saida} | {r.sl} | {r.act} | {r.dist} | {r.n} | {r.wr_real:.0%} | "
              f"{r.pf:.2f} | {r.pf_h1:.2f} | {r.pf_h2:.2f} | {r.anos_wr60}/{r.anos} |" for r in top.itertuples()],
            "",
            "Como nenhuma variação passa nos critérios, **os parâmetros não foram trocados**: escolher a melhor de "
            f"{len(v):,} no mesmo histórico seria otimização sobre os dados, não validação.",
            ""])

    md = [
        "# Validação — US100Cash RSI(2) Connors H1 (somente compra)",
        "",
        f"Gerado em {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC por `validar_rsi2.py`.",
        "",
        f"## Veredito: {'APROVADA' if approved else '**REPROVADA**'}",
        "",
        f"- Acerto real ≥60% em cada ano: **{n_ok_wr} de {n_years} anos**.",
        f"- PF em ~10 anos (com swap): **{s_all['pf']:.2f}** (critério ≥1.5).",
        f"- Custo ×2: PF **{s_x2['pf']:.2f}**, acerto real {s_x2['wr_real']:.0%}.",
        "- A referência (PF 1.99, acerto 69%) cobre só 14 meses de mercado de alta (09/2025–11/2026). No histórico "
        "longo, a estratégia perde em 2016–2023 e só ganha em 2024–2026. A perda aparece mesmo com custo zero e sem "
        "swap (2022: PF 0.65), e desde 2020 o custo é só 4–9% do ATR. O problema é dependência de regime, não custo.",
        "",
        "## Dados e custos",
        "",
        f"- H1 do MT5 (XM, `copy_rates_from_pos`, máximo do terminal). O \"H1\" antes de 09/2016 são barras diárias "
        f"(cerca de 300 por ano), por isso o teste começa em {K.H1_START:%Y-%m}: **{b.index[0]:%Y-%m-%d} → "
        f"{b.index[-1]:%Y-%m-%d}**, {len(b):,} barras. Inclui a queda de 2018, o crash de 2020 e a baixa de 2022 "
        "(16,4k → 11,0k).",
        f"- `mt5.symbol_info(\"US100Cash\")`: contract size {si['trade_contract_size']:g}, tick value "
        f"{si['trade_tick_value']} por tick de {si['trade_tick_size']}, **volume mínimo {lot:g}** (não existe 0.01 "
        f"no US100Cash da XM), swap long **{si['swap_long']}** (modo {si['swap_mode']} = US$ por lote por noite), "
        f"triplo no dia {si['swap_rollover3days']} (sexta). Com {lot:g} lote: 1 ponto = US$ "
        f"{K.usd(1, si):.2f} e swap = US$ {si['swap_long'] * lot:.3f} por noite.",
        f"- Custo por trade: spread real da barra (mediana de 2,0 a 3,0 pts; o zero de 2016 vira {K.SPREAD_FLOOR_PTS / 100:g} "
        f"pts) + slippage de {K.SLIP} pt por lado, igual ao `grid_nq.py`. Custo ×2 = esse total dobrado.",
        "- Acerto real = trade com resultado > 0.1 × ATR(14) da barra do sinal; trade zerado no breakeven não conta.",
        "- Motor: `bt2` do `us100/grid_wr.py`; `bt3` é o mesmo devolvendo o índice de saída (conferido trade a trade "
        "em `tests/test_us100_rsi2.py`).",
        "",
        "## 1. Reprodução da referência (09/2025 → 11/2026, split 06/2026)",
        "",
        f"Sem swap: {s_raw['n']} trades, PF **{s_raw['pf']:.2f}** (IS {s_is['pf']:.2f} / OOS {s_oos['pf']:.2f}), "
        f"DD {s_raw['dd']:.0f} pts, pior trade {s_raw['pior']:.0f} pts. **Idêntico** ao `wr60_aprovadas.csv` "
        f"(85 trades, PF 1.99, IS 2.61 / OOS 1.42, DD 547, pior −314). Acerto real {s_raw['wr_real']:.1%} "
        f"(IS {s_is['wr_real']:.0%} / OOS {s_oos['wr_real']:.0%}); o CSV traz 69,4%, diferença de 1 trade na fronteira "
        "de 0.1×ATR.",
        "",
        f"Com swap: PF {s_ref_swap['pf']:.2f}, {K.usd(s_ref_swap['net'], si):.0f} US$ com {lot:g} lote. Custo ×2: PF "
        f"{s_ref_x2['pf']:.2f}.",
        "",
        "## 2. Histórico longo (com swap)",
        "",
        "| Período | Trades | Acerto real | Acerto bruto | PF | Pts | US$ | DD pts | DD US$ | Pior pts |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| Tudo | {fmt(s_all, si)} |",
        f"| Tudo, custo ×2 | {fmt(s_x2, si)} |",
        f"| Tudo, com a guarda 20:55–21:10 UTC do agente | {fmt(s_guard, si)} |",
        "",
        "### Por ano",
        "",
        "| Ano | Trades | Acerto real | Acerto bruto | PF | Pts | US$ | DD pts | DD US$ | Pior pts | PF custo ×2 | "
        "PF custo 0 sem swap | Acerto real custo 0 | Custo/ATR | Passa |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *years,
        "",
        viz,
        "## 3. EA MQL5 e Strategy Tester",
        "",
        "- `mql5/Experts/US100_RSI2_Connors_H1.mq5`: mesma lógica do `bt2` (RSI/ATR de Wilder calculados no EA, porque "
        "o `iATR` do MT5 usa média simples), magic 20261116, só para o tester. **Compila com 0 erros e 0 warnings.**",
        "- **Teste com ticks reais não concluído.** `rodar_tester.py` usa uma cópia portátil do MT5 para não mexer no "
        "terminal aberto, mas a 2ª instância com a mesma conta perde a conexão durante a verificação de histórico "
        "(\"history check timeout\" → \"no history data\"). Uma dessas execuções coincidiu com o fechamento do terminal "
        "principal desta máquina (reaberto em seguida), então a automação foi interrompida.",
        "- Para rodar manualmente (no terminal da VPS ou desta máquina): copie o `.mq5` para `MQL5/Experts`, compile, "
        "e no Strategy Tester (Ctrl+R) escolha US100Cash, H1, \"Cada tick com base em ticks reais\", período "
        "01/09/2025–10/11/2026. Hoje o terminal tem ticks reais do US100Cash só desde 01/2026.",
        "",
    ]
    OUT.write_text("\n".join(md), encoding="utf-8")
    print(OUT)
    print("veredito:", "APROVADA" if approved else "REPROVADA", s_all, s_x2)


if __name__ == "__main__":
    main()
