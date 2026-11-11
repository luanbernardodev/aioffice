# Validação — US100Cash RSI(2) Connors H1 (somente compra)

Gerado em 2026-11-11 00:43 UTC por `validar_rsi2.py`.

## Veredito: **REPROVADA**

- Acerto real ≥60% em cada ano: **6 de 11 anos**.
- PF em ~10 anos (com swap): **1.05** (critério ≥1.5).
- Custo ×2: PF **0.93**, acerto real 57%.
- A referência (PF 1.99, acerto 69%) cobre só 14 meses de mercado de alta (09/2025–11/2026). No histórico longo, a estratégia perde em 2016–2023 e só ganha em 2024–2026. A perda aparece mesmo com custo zero e sem swap (2022: PF 0.65), e desde 2020 o custo é só 4–9% do ATR. O problema é dependência de regime, não custo.

## Dados e custos

- H1 do MT5 (XM, `copy_rates_from_pos`, máximo do terminal). O "H1" antes de 09/2016 são barras diárias (cerca de 300 por ano), por isso o teste começa em 2016-09: **2016-09-01 → 2026-11-10**, 60,042 barras. Inclui a queda de 2018, o crash de 2020 e a baixa de 2022 (16,4k → 11,0k).
- `mt5.symbol_info("US100Cash")`: contract size 1, tick value 0.01 por tick de 0.01, **volume mínimo 0.1** (não existe 0.01 no US100Cash da XM), swap long **-4.83** (modo 3 = US$ por lote por noite), triplo no dia 5 (sexta). Com 0.1 lote: 1 ponto = US$ 0.10 e swap = US$ -0.483 por noite.
- Custo por trade: spread real da barra (mediana de 2,0 a 3,0 pts; o zero de 2016 vira 2.5 pts) + slippage de 0.5 pt por lado, igual ao `grid_nq.py`. Custo ×2 = esse total dobrado.
- Acerto real = trade com resultado > 0.1 × ATR(14) da barra do sinal; trade zerado no breakeven não conta.
- Motor: `bt2` do `us100/grid_wr.py`; `bt3` é o mesmo devolvendo o índice de saída (conferido trade a trade em `tests/test_us100_rsi2.py`).

## 1. Reprodução da referência (09/2025 → 11/2026, split 06/2026)

Sem swap: 85 trades, PF **1.99** (IS 2.61 / OOS 1.42), DD 547 pts, pior trade -314 pts. **Idêntico** ao `wr60_aprovadas.csv` (85 trades, PF 1.99, IS 2.61 / OOS 1.42, DD 547, pior −314). Acerto real 70.6% (IS 72% / OOS 69%); o CSV traz 69,4%, diferença de 1 trade na fronteira de 0.1×ATR.

Com swap: PF 1.94, 323 US$ com 0.1 lote. Custo ×2: PF 1.82.

## 2. Histórico longo (com swap)

| Período | Trades | Acerto real | Acerto bruto | PF | Pts | US$ | DD pts | DD US$ | Pior pts |
|---|---|---|---|---|---|---|---|---|---|
| Tudo | 712 | 61% | 63% | 1.05 | 1056 | 106 | 3361 | 336 | -412 |
| Tudo, custo ×2 | 720 | 57% | 58% | 0.93 | -1625 | -162 | 5775 | 577 | -415 |
| Tudo, com a guarda 20:55–21:10 UTC do agente | 707 | 61% | 64% | 1.07 | 1536 | 154 | 3303 | 330 | -371 |

### Por ano

| Ano | Trades | Acerto real | Acerto bruto | PF | Pts | US$ | DD pts | DD US$ | Pior pts | PF custo ×2 | PF custo 0 sem swap | Acerto real custo 0 | Custo/ATR | Passa |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | 23 | 43% | 43% | 0.24 | -222 | -22 | 234 | 23 | -70 | 0.22 | 0.43 | 48% | 0.38 | ❌ |
| 2017 | 77 | 52% | 57% | 0.63 | -202 | -20 | 208 | 21 | -50 | 0.34 | 1.41 | 74% | 0.39 | ❌ |
| 2018 | 73 | 53% | 56% | 0.72 | -365 | -36 | 599 | 60 | -105 | 0.57 | 1.02 | 63% | 0.16 | ❌ |
| 2019 | 69 | 57% | 59% | 0.71 | -307 | -31 | 490 | 49 | -126 | 0.53 | 1.20 | 67% | 0.19 | ❌ |
| 2020 | 72 | 65% | 67% | 0.97 | -81 | -8 | 643 | 64 | -371 | 0.87 | 1.05 | 67% | 0.08 | ❌ |
| 2021 | 73 | 63% | 64% | 0.89 | -222 | -22 | 732 | 73 | -199 | 0.77 | 1.05 | 66% | 0.09 | ❌ |
| 2022 | 49 | 49% | 53% | 0.59 | -1362 | -136 | 1524 | 152 | -294 | 0.58 | 0.65 | 51% | 0.04 | ❌ |
| 2023 | 72 | 65% | 67% | 0.92 | -171 | -17 | 846 | 85 | -185 | 0.78 | 0.98 | 67% | 0.07 | ❌ |
| 2024 | 66 | 67% | 68% | 1.10 | 201 | 20 | 502 | 50 | -156 | 1.02 | 1.25 | 68% | 0.07 | ❌ |
| 2025 | 72 | 71% | 72% | 1.41 | 1084 | 108 | 803 | 80 | -412 | 1.20 | 1.55 | 72% | 0.05 | ❌ |
| 2026 | 66 | 70% | 73% | 1.90 | 2702 | 270 | 561 | 56 | -319 | 1.74 | 2.00 | 70% | 0.04 | ✅ |

## Vizinhança (item 5, opcional)

12,960 variações (RSI(2) limiar [3, 5, 7, 10, 12, 15]; SMA [50, 75, 100, 125, 150, 200]; saída RSI(3/5/7) > 50/60/70 ou close > SMA5; SL 2–5 ATR; trailing ativação 1/1.5/2 ATR × distância 1/1.5/2 ATR), mesmo histórico de ~10 anos com swap. Metades: até/depois de 2021-10-06.

- Vencem a referência em acerto real **e** PF nas duas metades: **265**.
- Aprovadas nos critérios (acerto real ≥60% em todos os anos, PF ≥1.5, custo ×2 PF ≥1.3): **0**.
- Melhor PF do conjunto: 1.30; nenhuma tem 1ª metade com PF > 1.05 entre as que vencem a referência.

| RSI2 < | SMA | Saída | SL | Ativ | Dist | Trades | Acerto real | PF | PF 1ª metade | PF 2ª metade | Anos ≥60% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | 75 | RSI(7)>60 | 3.0 | 2.0 | 1.0 | 646 | 66% | 1.30 | 0.93 | 1.52 | 7/11 |
| 5 | 75 | RSI(7)>60 | 3.0 | 2.0 | 1.5 | 646 | 66% | 1.30 | 0.91 | 1.52 | 7/11 |
| 5 | 75 | RSI(7)>60 | 3.0 | 2.0 | 2.0 | 646 | 64% | 1.29 | 0.90 | 1.52 | 7/11 |
| 5 | 75 | RSI(7)>60 | 2.0 | 2.0 | 2.0 | 697 | 55% | 1.28 | 0.95 | 1.47 | 2/11 |
| 5 | 75 | RSI(7)>60 | 2.0 | 2.0 | 1.5 | 697 | 57% | 1.28 | 0.95 | 1.46 | 3/11 |

Como nenhuma variação passa nos critérios, **os parâmetros não foram trocados**: escolher a melhor de 12,960 no mesmo histórico seria otimização sobre os dados, não validação.

## 3. EA MQL5 e Strategy Tester

- `mql5/Experts/US100_RSI2_Connors_H1.mq5`: mesma lógica do `bt2` (RSI/ATR de Wilder calculados no EA, porque o `iATR` do MT5 usa média simples), magic 20261116, só para o tester. **Compila com 0 erros e 0 warnings.**
- **Teste com ticks reais não concluído.** `rodar_tester.py` usa uma cópia portátil do MT5 para não mexer no terminal aberto, mas a 2ª instância com a mesma conta perde a conexão durante a verificação de histórico ("history check timeout" → "no history data"). Uma dessas execuções coincidiu com o fechamento do terminal principal desta máquina (reaberto em seguida), então a automação foi interrompida.
- Para rodar manualmente (no terminal da VPS ou desta máquina): copie o `.mq5` para `MQL5/Experts`, compile, e no Strategy Tester (Ctrl+R) escolha US100Cash, H1, "Cada tick com base em ticks reais", período 01/09/2025–10/11/2026. Hoje o terminal tem ticks reais do US100Cash só desde 01/2026.
