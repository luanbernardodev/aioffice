# Análise reversa de capital — todos os agentes (15/11/2026)

Pergunta: quanto capital a conta precisa para cada agente (e todos juntos) operar a sua probabilidade sem quebrar.
Script: `backtest/agentes_v3/capital_reverso.py`. Configurações atuais, lote mínimo, custos reais, sem a proteção de 8%.

**Capital adequado = maior de:** drawdown do pior 1% de 10.000 anos simulados ÷ 30% · risco por trade (p95) ÷ 2% · margem.

## Por agente

| Agente | Status | Classe | Trades/ano | Acerto | PF | Lucro/ano (US$) | Risco p95 | DD pior 1% (1 ano) | P(lucro 1 ano) | **Capital adequado** | Retorno/ano |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rsi20 | ligado | frágil | 7.8 | 88% | 6.07 | +8 | 8.5 |  |  | amostra pequena |  |
| v4_us500_st_h1 | ligado | lucrativo | 88.1 | 79% | 1.53 | +32 | 5.7 | 34 | 95% | **US$284** | 11% |
| sweep48 | ligado | lucrativo | 64.5 | 74% | 1.24 | +12 | 9.0 | 40 | 75% | **US$452** | 3% |
| of_btc_07_st_dz_agree | desligado | lucrativo | 139.7 | 73% | 1.33 | +94 | 12.6 | 116 | 93% | **US$628** | 15% |
| v4_us500_bb_h1 | ligado | lucrativo | 52.6 | 92% | 1.97 | +20 | 13.7 | 25 | 94% | **US$686** | 3% |
| of_btc_13_rsipb_conf_w3 | desligado | lucrativo | 48.8 | 74% | 1.7 | +63 | 13.8 | 66 | 95% | **US$688** | 9% |
| of_btc_09_rsipb_exh_w1 | desligado | lucrativo | 62.5 | 86% | 1.61 | +44 | 14.4 | 66 | 92% | **US$722** | 6% |
| of_btc_06_chan_dz_agree | desligado | lucrativo | 85.9 | 73% | 1.44 | +100 | 16.1 | 118 | 93% | **US$804** | 12% |
| goldnight_v2 | ligado | lucrativo | 279.8 | 36% | 1.54 | +588 | 9.8 | 298 | 99% | **US$992** | 59% |
| v4_gold_rsix_m5 | ligado | lucrativo | 106.5 | 69% | 1.8 | +288 | 21.8 | 169 | 99% | **US$1,089** | 26% |
| of_btc_02_rsipb_conf_w1 | desligado | lucrativo | 87.9 | 92% | 1.91 | +85 | 23.0 | 94 | 96% | **US$1,151** | 7% |
| of_btc_01_rsipb_conf_w1 | desligado | lucrativo | 47.9 | 92% | 2.92 | +99 | 23.5 | 58 | 99% | **US$1,173** | 8% |
| of_btc_12_rsipb_delta_agree | desligado | lucrativo | 65.4 | 91% | 1.63 | +53 | 24.1 | 94 | 90% | **US$1,208** | 4% |
| v4_btc_rsipb_h1 | ligado | lucrativo | 97.7 | 92% | 1.89 | +98 | 24.5 | 92 | 97% | **US$1,223** | 8% |
| of_btc_15_st_dz_agree | desligado | lucrativo | 66.4 | 91% | 1.33 | +35 | 24.7 | 126 | 77% | **US$1,234** | 3% |
| v4_gold_rsipb_m5 | desligado | lucrativo | 204.9 | 74% | 1.54 | +256 | 24.8 | 144 | 99% | **US$1,238** | 21% |
| of_btc_05_chan_delta_agree | desligado | lucrativo | 152.4 | 81% | 1.39 | +181 | 25.5 | 197 | 95% | **US$1,275** | 14% |
| of_btc_14_chan_stk_w1 | desligado | lucrativo | 63.5 | 72% | 1.33 | +81 | 26.3 | 197 | 82% | **US$1,314** | 6% |
| of_btc_08_bb_dz_agree | desligado | lucrativo | 116.2 | 82% | 1.41 | +132 | 26.5 | 173 | 92% | **US$1,326** | 10% |
| of_btc_04_st_dz_agree | desligado | lucrativo | 169.9 | 81% | 1.4 | +200 | 27.1 | 203 | 96% | **US$1,353** | 15% |
| of_btc_03_chan_dz_agree | desligado | lucrativo | 182.6 | 75% | 1.37 | +192 | 27.1 | 181 | 96% | **US$1,357** | 14% |
| of_btc_10_chan_veto_cvd | desligado | lucrativo | 155.3 | 75% | 1.3 | +136 | 28.1 | 194 | 91% | **US$1,403** | 10% |
| of_btc_11_chan_cvd_slope | desligado | lucrativo | 136.7 | 79% | 1.35 | +142 | 29.4 | 212 | 90% | **US$1,472** | 10% |
| v4_gold_rsipb_m15n | ligado | negativo | 214.2 | 37% | 0.8 | -206 | 20.6 |  |  | nenhum (expectativa negativa) |  |
| goldflip | desligado | negativo | 1656.5 | 32% | 0.93 | -477 | 19.8 |  |  | nenhum (expectativa negativa) |  |
| engine A3 | ligado | negativo | 221.0 | 36% | 0.83 | -16 | 1.4 |  |  | nenhum (expectativa negativa) |  |
| engine A2 | desligado | negativo | 621.1 | 39% | 0.8 | -101 | 3.0 |  |  | nenhum (expectativa negativa) |  |

## Carteiras (PnL diário alinhado, sorteio em blocos de 7 dias — mantém a correlação)

| Carteira | Agentes | Lucro/ano estimado | DD pior 1% (1 ano) | Risco aberto p95 | **Capital adequado** |
|---|---|---|---|---|---|
| lucrativos | 22 | US$2,496 | US$538 | US$86 | **US$1,794** |
| lucrativos + frágeis | 23 | US$2,505 | US$541 | US$86 | **US$1,802** |
| ligados e lucrativos | 6 | US$1,093 | US$276 | US$18 | **US$1,223** |

## Leitura

- **Negativos (nenhum capital resolve):** engine A3 (ligado), engine A2 e goldflip (desligados) e **v4_gold_rsipb_m15n sem teto fixo**. 
  O m15n só tem vantagem pulando trades com stop > US$8 (como na grade v7); recebeu `max_risk_usd: 8` fixo no agente.
- **Capital para TODOS os lucrativos (22 agentes, inclusive os 15 of_btc): ~US$1.800.** O que manda é o drawdown conjunto
  (agentes BTC muito correlacionados) e a regra de 2% para os stops de BTC H1 (US$23–29).
- **Capital para os 6 ligados e lucrativos** (v4_us500_st, sweep48, v4_us500_bb, goldnight_v2, v4_gold_rsix, v4_btc_rsipb): **~US$1.220**.
  Sem o v4_btc_rsipb (stop de ~US$24), o teto cai para o drawdown conjunto (~US$920).
- **Com ~US$143 de saldo**, só cabem com folga o v4_us500_st (US$284) e, no limite, o sweep48 (US$452) — por isso a proteção bloqueia tanto.

## Cuidados (o número real tende a ser MAIOR e o lucro MENOR)

- **Viés de seleção:** v4 e of_btc foram escolhidos nesses mesmos dados (grades de dezenas a milhões de estratégias). A expectativa e a
  "P(lucro) ≈ 100%" são otimistas; na grade v7, escolhas pelo IS falharam no OOS na maioria dos agentes.
- **Período curto:** GOLD tem só 01–11/2026 (ano de tendência forte); BTC 12 meses; US500 17 meses.
- Tolerância de 30% de drawdown e regra de 2% por trade são escolhas de gestão (mais conservador = mais capital).
- Ao vivo há poucos trades de cada agente — a competição desta semana é a primeira amostra real.
