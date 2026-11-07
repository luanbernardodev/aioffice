# Quant Office AI 🏢📈

Sistema multi-agente quantitativo autônomo com visualização 2D/3D (Next.js/Three.js), orquestração assíncrona e integração com MetaTrader 5 e Supabase.

## 🚀 Configuração Rápida do Ambiente

1. Clone o repositório e configure seu ambiente virtual:
   ```bash
   python -m venv venv
   # No Windows:
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Crie seu arquivo `.env` baseado no `.env.example`:
   ```bash
   cp .env.example .env
   ```

3. **Chaves de API obrigatórias no `.env`:**
   - `SUPABASE_URL` e `SUPABASE_KEY`: Credenciais do projeto Supabase.
   - `ANTHROPIC_API_KEY`: Chave da API Claude da Anthropic (usada nos Setores 1 a 6).
   - **`FINNHUB_API_KEY`**: Chave de API da Finnhub (obtenha gratuitamente em [https://finnhub.io](https://finnhub.io)).
     > **Atenção:** O módulo `core/news_collector.py` opera em modelo híbrido. A chave da Finnhub alimenta as notícias de criptomoedas e macroeconomia geral da API da Finnhub, que são combinadas com feeds RSS nativos (CoinTelegraph, Investing.com) e o calendário econômico do ForexFactory para o filtro de veto macro do Setor 3.

## 🔄 Fluxo de Notícias e Veto Macro (Cadeia de Comando)

1. **News Collector (`core/news_collector.py`):**
   Coleta híbrida (Finnhub API + RSS CoinTelegraph + RSS Investing Ouro/Commodities + Calendário XML de alto impacto do ForexFactory) a cada 30 minutos e persiste o contexto preliminar na tabela `market_context`.
2. **Setor 2 (News Desk - `agents/sector_2_news.py`):**
   Gera o "Score de Sentimento" (-10 a +10 para Cripto e Ouro, identificação de Red Flags e resumo macro) e atualiza `market_context`.
3. **Setor 3 (Auditor Quantitativo - `agents/sector_3_analytics.py`):**
   Cruza o sentimento macro com o estilo operacional de cada algoritmo (`ops_alpha`, `ops_beta`, `ops_gamma`, `ops_delta`, `ops_epsilon`) e emite a decisão de veto estrita:
   ```json
   {
     "is_market_safe": true,
     "strategy_authorization": {
       "ops_alpha": true,
       "ops_beta": false,
       "ops_gamma": true,
       "ops_delta": false,
       "ops_epsilon": false
     },
     "veto_reason": "Payroll em 30 minutos. Scalpers (Delta/Epsilon) e Reversão (Beta) vetados por risco de spike de volatilidade."
   }
   ```
4. **Setor 1 (Operadores):**
   Só executam ordens no MetaTrader 5 caso possuam autorização macro ativa e vigente emitida pelo Setor 3.

## ⚙️ Motor determinístico (engine/) — substitui o Loop 1 legado

Sem LLM no caminho de execução. A1 regime/veto → A2 pullback / A3 BOS-retest / A4 RSI BTC → A5 risco → MT5.
Parâmetros em `config/engine.yaml` (por ativo, em múltiplos de ATR).

```bash
python -m pytest                                  # testes do motor (tests/)
python -m backtest.run_backtest --fetch           # baixa histórico do MT5 (read-only) e roda o comparativo
python run_engine.py                              # DRY_RUN: dados reais da DEMO, ordens simuladas
python run_engine.py --live-demo                  # ordens reais na DEMO 309673774 (trava recusa outra conta/REAL)
```
Trades: `logs/trades.csv` (demo) / `logs/trades_paper.csv` (dry-run). Relatórios: `reports/`.
Eventos de notícia históricos para o backtest (opcional): `config/news_events.csv` com colunas `datetime_utc,title`.

### VPS (conta DEMO)
1. MT5 aberto, logado na demo 309673774, botão **Algo Trading** ligado.
2. `pip install -r requirements.txt`
3. Duplo clique em `start_engine.bat` (ordens reais na DEMO, reinicia sozinho se cair).
4. **Não** rode o `main.py` legado junto, nem o motor em duas máquinas na mesma conta.
Logs: `logs/engine.log` · trades: `logs/trades.csv`.

### 6º agente: EA GoldFlipTrail (magic 20261108)
Stop-and-reverse com trailing ATR em GOLD M5 (`mql5/Experts/GoldFlipTrail.mq5`), controlado por
`agents/goldflip_supervisor.py` (roda dentro do `run_engine.py`) via `MQL5/Files/goldflip_control.json`:
regime ATR/MA100 a cada 5 min, sessões Londres/NY, ±15 min de CPI/FOMC/NFP (zera), kill switch de DD diário 3% (zera).
Backtest: `python -m backtest.goldflip_bt` (resultado atual: negativo — ver relatório na conversa/commit).

Instalar/atualizar na VPS (MT5 aberto):
```
git pull origin main
python -m tools.deploy_mql5        # copia include + EA para o terminal e compila
```
Uma vez só: gráfico **GOLD M5** -> arrastar **GoldFlipTrail** -> marcar *Permitir Algo Trading*. O MT5 reabre o gráfico com o EA
nos próximos reinícios. O EA só roda em conta DEMO e recusa duas cópias ao mesmo tempo.
Nenhum agente fecha posições de outro magic (legado 777777, engine 20261107, GoldFlip 20261108).
