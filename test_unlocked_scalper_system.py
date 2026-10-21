"""Validação Rigorosa da Nova Arquitetura Quantitativa Desbloqueada:
1. Remoção do Triple Check (ADX > 25 e Volume Spike removidos).
   - Regra de Compra Absoluta: RSI <= 30 -> BUY
   - Regra de Venda Absoluta: RSI >= 70 -> SELL
   - Fecho dinâmico por RSI: RSI >= 60 para BUY, RSI <= 40 para SELL.
2. Rebaixamento do Setor 2:
   - veto_power = False
   - Envio imediato da ordem para a corretora (sem bloqueio de notícias/red flag).
   - Registro do sentimento de notícias na coluna market_context em trades_history.
3. Reformulação dos Prompts:
   - Novo prompt base agressivo em config.prompts e agents.prompts.
4. Anti-Spam Tick a Tick:
   - Trava last_bar_time garantindo no máximo 1 tiro por formação de vela.
"""
import pandas as pd
import numpy as np
from config import settings

settings.DRY_RUN = True

from core.sentinel import analyze_market, check_indecision_filters, Sentinel, _check_alpha, _check_beta, _check_delta
from core.mt5_bridge import MT5Bridge
from core.database import DatabaseManager
from agents import sector_1_ops, sector_2_news
from agents import prompts as agent_prompts

print("=== [INICIANDO BATERIA DE TESTES: ARQUITETURA DESBLOQUEADA] ===")

# Base DataFrame de 50 candles
dates = pd.date_range("2026-10-21 00:00", periods=50, freq="15min")
base_df = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 50,
    "high": [105.0] * 50,
    "low": [95.0] * 50,
    "close": [100.0] * 50,
    "volume": [1000] * 50,
    "rsi": [50.0] * 50,
    "adx": [10.0] * 50,        # ADX baixo (<= 25): NÃO DEVE MAIS BLOQUEAR!
    "vol_ratio": [0.8] * 50,   # Volume baixo (< 1.5x): NÃO DEVE MAIS BLOQUEAR!
    "atr": [2.0] * 50,
    "ema20": [100.0] * 50,
    "ema50": [100.0] * 50,
    "ema200": [100.0] * 50,
    "bb_upper": [110.0] * 50,
    "bb_lower": [90.0] * 50,
    "bandwidth": [0.1] * 50,
    "vwap": [100.0] * 50,
})

# ---------------------------------------------------------------------------------
# TESTE 1: REMOÇÃO DO TRIPLE CHECK & REGRAS ABSOLUTAS DE RSI
# ---------------------------------------------------------------------------------
print("\n--- TESTE 1: REMOÇÃO DO TRIPLE CHECK & REGRAS ABSOLUTAS DE RSI ---")
# 1.1: RSI <= 30 com ADX fraco e sem volume -> DEVE COMPRAR com force_execute = True
df_buy = base_df.copy()
df_buy.loc[49, "rsi"] = 29.0
df_buy.loc[49, "adx"] = 8.0        # ADX baixíssimo
df_buy.loc[49, "vol_ratio"] = 0.5  # Sem volume spike

bias_buy, force_buy = analyze_market(df_buy)
assert bias_buy == "BUY", f"Esperado BUY para RSI 29, obtido: {bias_buy}"
assert force_buy is True, "force_execute deve ser True para autonomia direta"

ok_filter, abort_reason, details = check_indecision_filters(df_buy, "BUY")
assert ok_filter is True, f"Filtro não deveria abortar por ADX ou Volume: {abort_reason}"
print(f"[OK] 1.1 Compra Absoluta: RSI 29 aprovado diretamente sem ADX/Volume ({details})")

# 1.2: RSI >= 70 com ADX fraco e sem volume -> DEVE VENDER com force_execute = True
df_sell = base_df.copy()
df_sell.loc[49, "rsi"] = 72.0
df_sell.loc[49, "adx"] = 12.0
df_sell.loc[49, "vol_ratio"] = 0.6

bias_sell, force_sell = analyze_market(df_sell)
assert bias_sell == "SELL", f"Esperado SELL para RSI 72, obtido: {bias_sell}"
assert force_sell is True

ok_filter_sell, _, details_sell = check_indecision_filters(df_sell, "SELL")
assert ok_filter_sell is True
print(f"[OK] 1.2 Venda Absoluta: RSI 72 aprovado diretamente sem ADX/Volume ({details_sell})")

# 1.3: RSI Neutro (ex: 50) não deve disparar
df_neutral = base_df.copy()
df_neutral.loc[49, "rsi"] = 50.0
bias_neu, force_neu = analyze_market(df_neutral)
assert bias_neu is None and force_neu is False
print("[OK] 1.3 RSI Neutro (50): Sem gatilho.")

# ---------------------------------------------------------------------------------
# TESTE 2: REBAIXAMENTO DO SETOR 2 (FIM DO VETO & REGISTRO DE MARKET_CONTEXT)
# ---------------------------------------------------------------------------------
print("\n--- TESTE 2: REBAIXAMENTO DO SETOR 2 (FIM DO VETO) ---")
db = DatabaseManager()
bridge = MT5Bridge()

# 2.1: Atributo veto_power = False no Setor 2
assert hasattr(sector_2_news, "VETO_POWER")
assert sector_2_news.VETO_POWER is False
print("[OK] 2.1 Setor 2: Atributo veto_power = False confirmado no módulo.")

# 2.2: Simula Red Flag de Notícias e Veto Macro
db.save_market_context(crypto_sentiment=-9, gold_sentiment=-9, red_flag=True, key_driver="Pânico Global / Red Flag Ativo")

trigger = {
    "agent_id": "ops_alpha",
    "symbol": "BTCUSD",
    "bias": "BUY",
    "trigger": "EXHAUSTION_REVERSAL",
    "force_execute": True,
    "atr": 400.0,
    "candle_time": "2026-10-21 12:30:00",
    "timeframe": "M15"
}

# Dispara ordem autônoma: NUNCA deve ser abortada por notícias
exec_res = sector_1_ops.execute_autonomous_trigger(trigger, db, bridge)
assert exec_res is not None, "A ordem não deveria ser abortada!"
assert exec_res.get("action") == "BUY"
assert exec_res.get("ticket") is not None
print(f"[OK] 2.2 Ordem disparada imediatamente para a corretora (Ticket #{exec_res.get('ticket')}) sob Red Flag!")

# 2.3: Verifica se o market_context foi gravado em trades_history
ticket = exec_res.get("ticket")
trade_rows = db._select("trades_history", eq={"ticket_mt5": ticket}, limit=1)
assert len(trade_rows) > 0, "Trade não encontrado em trades_history"
saved_ctx = trade_rows[0].get("market_context")
assert saved_ctx is not None and "Crypto:" in saved_ctx
print(f"[OK] 2.3 Sentimento das notícias registrado em trades_history.market_context: '{saved_ctx}'")

# ---------------------------------------------------------------------------------
# TESTE 3: PROMPTS DOS AGENTES REFORMULADOS
# ---------------------------------------------------------------------------------
print("\n--- TESTE 3: REFORMULAÇÃO DOS PROMPTS ---")
expected_phrase = "Você é um Agente Scalper Autônomo de Alta Frequência. A sua única diretriz é a execução matemática implacável. Ignore ruídos macroeconómicos, manchetes ou medos de mercado. Se o RSI atingir os níveis críticos de sobrecompra (>=70) ou sobrevenda (<=30), a sua obrigação é disparar a ordem no milissegundo seguinte. Notícias são apenas contexto; o preço e o RSI são a lei."

assert expected_phrase in agent_prompts.SECTOR_1_BASE_PROMPT, "SECTOR_1_BASE_PROMPT incorreto!"
assert expected_phrase in agent_prompts.SECTOR_1_OPS_PROMPT, "SECTOR_1_OPS_PROMPT incorreto!"
assert expected_phrase in agent_prompts.SECTOR_1_OPS_DELTA_PROMPT, "SECTOR_1_OPS_DELTA_PROMPT incorreto!"
assert expected_phrase in agent_prompts.SECTOR_1_OPS_EPSILON_PROMPT, "SECTOR_1_OPS_EPSILON_PROMPT incorreto!"
print("[OK] 3.1 Novo Prompt Base agressivo e autônomo validado com sucesso em todos os agentes operacionais!")

# ---------------------------------------------------------------------------------
# TESTE 4: ANTI-SPAM TICK A TICK (1 TIRO POR FORMAÇÃO DE VELA)
# ---------------------------------------------------------------------------------
print("\n--- TESTE 4: ANTI-SPAM TICK A TICK ---")
# 4.1: Tenta disparar segunda ordem no MESMO candle_time
trigger_dup = dict(trigger)  # mesmo candle_time "2026-10-21 12:30:00"
dup_res = sector_1_ops.execute_autonomous_trigger(trigger_dup, db, bridge)
assert dup_res.get("action") == "HOLD"
assert dup_res.get("reason") == "bar_already_traded"
print("[OK] 4.1 Trava Anti-Spam ativa: disparo bloqueado no mesmo candle_time após Stop Loss ou re-tick!")

# 4.2: Tenta disparar em candle NOVO -> DEVE LIBERAR
trigger_new_bar = dict(trigger)
trigger_new_bar["candle_time"] = "2026-10-21 12:45:00"  # Nova vela!
new_res = sector_1_ops.execute_autonomous_trigger(trigger_new_bar, db, bridge)
assert new_res.get("action") == "BUY"
print("[OK] 4.2 Novo candle liberado: exatamente 1 tiro por formação de vela garantido!")

print("\n=== TODOS OS 4 PONTOS FORAM VALIDADOS COM SUCESSO ABSOLUTO! ===")
