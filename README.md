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
