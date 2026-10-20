-- O projeto Supabase chewvhgnalvtcrizjyhq já possuía as tabelas agents_status, strategy_parameters,
-- market_context e trades_history. O código em core/database.py foi adaptado a esse esquema.
-- Única alteração feita (aditiva, já aplicada via MCP):
alter table public.trades_history
  add column if not exists risk_amount double precision,
  add column if not exists confidence double precision,
  add column if not exists dry_run boolean default true;

-- Mapeamento usado pelo código em trades_history:
--   ticket_mt5 (PK) | order_type (BUY/SELL) | profit_usd | close_price | technical_rationale
-- Recomendado: habilitar RLS (as tabelas hoje estão abertas para a chave anon/publishable).
