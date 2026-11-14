# Orderflow da Binance como filtro do BTC RSI(7) H1 — relatório

Gerado em 14/11/2026. Os agentes ativos não foram alterados. O módulo `orderflow/` só lê dados públicos.

## Resumo

| | Trades OOS | PF OOS | Acerto OOS | DD OOS (US$) |
|---|---|---|---|---|
| Base, sem filtro | 22 | 1.75 | 41% | 13.2 |
| **Filtro CONF (barra do sinal)** | **11** | **4.36** | 45% | 5.6 |

O filtro CONF entra só com absorção, exaustão ou stacked imbalance a favor. Ele **cumpre a regra de integração no papel**: o PF fora da amostra melhora e o corte fica em exatamente 50% dos trades, sem passar do limite.

A melhora, porém, **não se distingue do acaso**. Um filtro aleatório que mantém a mesma fração de sinais (44%) chega ao PF 4.36 ou acima em 14.6% de 2.000 sorteios. Além disso, o resultado OOS vem de só 11 trades.

**Decisão: não integrei ao agente ao vivo.** A regra pedida é condição necessária ("só integrar se"), e a evidência atual é fraca demais para justificar um feed ao vivo e uma mudança de agente. A recomendação está no fim.

## 1. Dados

- **Binance spot BTCUSDT, aggTrades.**
  - Fonte: data.binance.vision, de 01/11/2025 a 10/11/2026.
  - Arquivos: 12 mensais e 10 diários, cada um com o SHA-256 conferido contra o `.CHECKSUM` publicado.
  - Volume: **436.969.000 aggTrades** (de 21 a 52 milhões por mês).
  - Timestamp em microssegundos desde 2025; normalizado para milissegundos.
  - `is_buyer_maker=True` foi contado como agressão vendedora.
- **Footprint H1:**
  - Níveis de US$10.
  - **9.000 barras**, toda hora do período, sem falha.
  - 437 mil células (barra × nível) com o volume comprador e o volume vendedor.
- **XM BTCUSD H1:**
  - Barras montadas dos ticks reais da XM, com spread de ~US$50.
  - 8.975 barras, todas com orderflow correspondente.
  - Lote de 0.01 e swap por noite.

## 2. Métricas por barra (`orderflow/metrics.py`)

| Métrica | Definição |
|---|---|
| delta / CVD | Volume comprador − vendedor da barra / delta acumulado |
| POC | Centro do nível com mais volume |
| VAH / VAL | Área de valor com 70% do volume, expandida a partir do POC pelo lado de maior volume |
| Stacked imbalance | ≥3 níveis seguidos com desequilíbrio diagonal ≥300%: compra[k] ≥ 3 × venda[k−1] (venda: espelho). O denominador mínimo é 0.2% do volume da barra, para nível vazio não virar desequilíbrio. |
| Absorção | z-score do delta (contra as 100 barras anteriores) ≤ −2 sem nova mínima de 3 barras (compradora). Espelho com +2 sem nova máxima (vendedora). |
| Exaustão | Nova mínima de 10 barras com ≤5% do volume nos 2 níveis mais baixos (venda esgotada). Espelho na máxima. |
| Divergência de CVD (veto de compra) | Preço subiu nas últimas 3 barras e o CVD caiu |

Todas as janelas usam só barras anteriores. Os testes conferem que o valor numa barra não muda quando se acrescentam barras futuras.

Frequência, em % das barras:

| Sinal | % das barras |
|---|---|
| Absorção, cada lado | 0.7% |
| Exaustão compradora / vendedora | 13.2% / 12.7% |
| Stacked imbalance comprador / vendedor | 14.9% / 16.2% |
| Divergência de CVD contra compra | 16.2% |

## 3. Mapeamento Binance → XM

O diferencial é calculado no fechamento de cada barra: `offset = fechamento XM − fechamento Binance`, e cada nível vira `nível_xm = nível + offset`.

- Mediana do diferencial: **−24.6 USD**.
- Faixa de 90%: de −39.5 a −11.6 USD.
- POC, VAH e VAL ficam disponíveis no preço da XM (`poc_xm`, `vah_xm`, `val_xm`).

## 4. Backtest

**Estratégia** (regras do agente RSI7_H1, bloco "fallback"):
- Compra quando o RSI(7) cruza para cima de 25 com close > SMA100; venda é o espelho, em 75.
- Entrada na abertura seguinte (compra no ask).
- SL de 1.5 × ATR(14).
- Trailing de 3 × ATR(14) a partir do extremo, atualizado no fechamento.
- Sem TP.

**Corte:** IS até 30/06/2026, OOS depois.

| Variante | IS n | IS PF | IS acerto | IS DD | OOS n | OOS PF | OOS acerto | OOS resultado | OOS DD | Passa na regra |
|---|---|---|---|---|---|---|---|---|---|---|
| BASE (sem filtro) | 39 | 1.85 | 38.5% | 56.9 | 22 | 1.75 | 40.9% | +39.0 | 13.2 | — |
| CONF (w=1) | 16 | 2.46 | 37.5% | 30.5 | 11 | 4.36 | 45.5% | +66.8 | 5.6 | sim, no limite |
| CONF (w=3) | 38 | 1.66 | 36.8% | 83.6 | 20 | 1.83 | 40.0% | +40.6 | 13.2 | sim, mas o IS piora |
| VETO de CVD na compra | 39 | 1.85 | 38.5% | 56.9 | 22 | 1.75 | 40.9% | +39.0 | 13.2 | não (sem efeito) |
| VETO compra + venda | 36 | 1.56 | 33.3% | 83.6 | 21 | 1.68 | 38.1% | +35.3 | 13.5 | não |
| CONF + VETO (w=1) | 16 | 2.46 | 37.5% | 30.5 | 11 | 4.36 | 45.5% | +66.8 | 5.6 | sim, no limite |
| CONF + VETO (w=3) | 38 | 1.66 | 36.8% | 83.6 | 20 | 1.83 | 40.0% | +40.6 | 13.2 | sim, mas o IS piora |

- w = 1: o sinal de orderflow vale só na barra do sinal. w = 3: vale em qualquer das 3 últimas barras.
- **O veto de CVD não tem efeito na compra.** A compra só acontece quando o RSI volta de sobrevendido, logo depois de uma queda. Por isso, "preço subiu nas últimas 3 barras" quase nunca coincide com o sinal.

## 5. A melhora é real?

**Filtro aleatório:** mantendo 44% dos sinais da base por sorteio, em 2.000 repetições:
- PF OOS mediano: 2.34.
- Percentil 90: 4.96.
- **P(aleatório ≥ 4.36) = 14.6%**, longe dos ~5% que indicariam um efeito real.

**Sensibilidade aos limiares** (só para observar; nada foi escolhido por aqui):

| stack | dz | ratio | IS n | IS PF | OOS n | OOS PF |
|---|---|---|---|---|---|---|
| 3 | 2.0 | 3.0 | 16 | 2.46 | 11 | 4.36 |
| 2 | 2.0 | 3.0 | 23 | 2.46 | 16 | 2.56 |
| 4 | 2.0 | 3.0 | 13 | 3.10 | 9 | 3.55 |
| 3 | 1.5 | 3.0 | 17 | 2.27 | 11 | 4.36 |
| 3 | 2.5 | 3.0 | 16 | 2.46 | 11 | 4.36 |
| 3 | 2.0 | 2.0 | 27 | 1.87 | 17 | 2.20 |
| 3 | 2.0 | 4.0 | 14 | 2.79 | 10 | 3.59 |

- **A favor:** o efeito tem a mesma direção em todos os vizinhos. O PF melhora no IS e no OOS em todos.
- **Contra:**
  - As amostras são de 9 a 17 trades fora da amostra.
  - Os vizinhos mais seletivos já cortam mais de 50% dos trades.
  - O teste aleatório não rejeita o acaso.

## 6. Decisão e próximos passos

**Não integrei.** Não há websocket ao vivo e nenhum agente mudou.

Para decidir com dados, o caminho barato é um **modo sombra**: o feed `aggTrade` da Binance por websocket (grátis) alimenta as mesmas métricas ao vivo, e um registro anota, a cada sinal do RSI7, se o filtro teria deixado entrar. Isso não envia ordem. Com uns 3 meses (~15 sinais a mais) dá para repetir o teste aleatório.

Uma observação à parte: a estratégia base, sem filtro, ficou com PF 1.85 no IS e 1.75 no OOS, com spread real e ~60 trades por ano. É razoável por conta própria, mas tem acerto de ~40% e fica abaixo do critério de 60% de acerto pedido para os agentes da competição.

## Reproduzir

```
python -m orderflow.binance_data                     # download (~6 GB, com checksum)
python -m orderflow.footprint                        # footprint H1 (~20 min)
python -m backtest.orderflow.bt_rsi7_orderflow       # tabela da seção 4
python -m backtest.orderflow.teste_aleatorio         # seção 5
```

Os dados brutos e os caches ficam em `data/binance`, `data/orderflow` e `backtest/orderflow/*.pkl`, e não vão para o git.
