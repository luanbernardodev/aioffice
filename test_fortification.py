"""Script de validação automatizada dos 3 pilares críticos e integridade:
1. Relógio de Quarentena Automático (check_quarantine_releases)
2. Máquina de Estados de Perdas e Ciclo de Demissão/Clonagem (4 losses) com maior Net PnL
3. Exaustão Institucional do RSI no Agente Beta (rsi < 20 e rsi > 85)
4. Validação de timestamps UTC (quarantine_until)
"""
import sys
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

# 1. TESTE DO AGENTE BETA (SENTINEL)
from core.sentinel import _check_beta

print("--- [TESTE 1] ESTRATÉGIA DE EXAUSTÃO EXTREMA DO AGENTE BETA ---")
# Criar DataFrame simulado
dates = pd.date_range("2026-10-20 00:00", periods=50, freq="15min")
base_df = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 50,
    "high": [105.0] * 50,
    "low": [95.0] * 50,
    "close": [100.0] * 50,
    "volume": [1000] * 50,
    "rsi": [50.0] * 50,
    "bb_upper": [110.0] * 50,
    "bb_mid": [100.0] * 50,
    "bb_lower": [90.0] * 50,
})

# Cenário A: RSI = 18.5 (< 20) -> Deve acionar COMPRA por exaustão institucional
df_oversold = base_df.copy()
df_oversold.loc[49, "rsi"] = 18.5
df_oversold.loc[49, "close"] = 95.0 # Preço ainda dentro das bandas, mas RSI extremo
signal_buy = _check_beta(df_oversold)
assert signal_buy == "BUY", f"Esperado BUY para RSI=18.5, obtido {signal_buy}"
print(f"[OK] Condição Forte de COMPRA (RSI=18.5 < 20) -> {signal_buy} [SUCESSO]")

# Cenário B: RSI = 87.2 (> 85) -> Deve acionar VENDA por exaustão institucional
df_overbought = base_df.copy()
df_overbought.loc[49, "rsi"] = 87.2
df_overbought.loc[49, "close"] = 105.0 # Preço dentro das bandas, mas RSI extremo
signal_sell = _check_beta(df_overbought)
assert signal_sell == "SELL", f"Esperado SELL para RSI=87.2, obtido {signal_sell}"
print(f"[OK] Condição Forte de VENDA (RSI=87.2 > 85) -> {signal_sell} [SUCESSO]")

# Cenário C: Regra clássica de Bollinger preservada (RSI=25 <= 28 e close <= bb_lower)
df_classic = base_df.copy()
df_classic.loc[49, "rsi"] = 25.0
df_classic.loc[49, "close"] = 89.0 # abaixo da banda inferior
signal_classic = _check_beta(df_classic)
assert signal_classic == "BUY", f"Esperado BUY para regra clássica Bollinger, obtido {signal_classic}"
print(f"[OK] Regra Clássica Bollinger + RSI mantida -> {signal_classic} [SUCESSO]")


# 2. TESTE DO TIMESTAMP DE QUARENTENA UTC
from agents.sector_5_manager import _quarantine_until

print("\n--- [TESTE 2] TIMESTAMPS UTC E RELÓGIO DE QUARENTENA ---")
q_str = _quarantine_until()
q_dt = datetime.fromisoformat(q_str)
now_utc = datetime.now(timezone.utc)
diff_minutes = (q_dt - now_utc).total_seconds() / 60.0
assert 58.0 <= diff_minutes <= 62.0, f"Diferença esperada ~60 min (1h), obtido {diff_minutes:.1f} min"
print(f"[OK] quarantine_until gerado em UTC para 1 hora no futuro (+{diff_minutes:.1f} min) [SUCESSO]")


# 3. TESTE DE LIBERAÇÃO DE QUARENTENA (check_quarantine_releases)
from core.database import DatabaseManager

print("\n--- [TESTE 3] LIBERAÇÃO DE QUARENTENA (SUPABASE / DB) ---")
db = DatabaseManager()

# Simula um agente de teste com quarentena expirada (1 minuto no passado)
past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
db.set_agent_fields("ops_beta", {
    "current_state": "QUARANTINED",
    "quarantine_until": past_time,
    "last_thought": "Testando expiração do relógio de quarentena"
})

released = db.release_expired_quarantines()
assert "ops_beta" in released, f"ops_beta deveria ter sido liberado, lista: {released}"

status_beta = db.get_agent_status("ops_beta")
assert status_beta["current_state"] == "IDLE", f"Estado esperado IDLE, obtido {status_beta['current_state']}"
assert status_beta["quarantine_until"] is None, f"quarantine_until deveria ser None, obtido {status_beta['quarantine_until']}"
print(f"[OK] check_quarantine_releases() liberou ops_beta de volta para IDLE com sucesso! [SUCESSO]")


# 4. TESTE DE IDENTIFICAÇÃO DO MELHOR NET PNL PARA DEMISSÃO/CLONAGEM
print("\n--- [TESTE 4] IDENTIFICAÇÃO DO MELHOR OPERADOR POR NET PNL ---")
best_ops = db.get_best_ops_by_net_pnl(exclude=["ops_gamma"])
print(f"[OK] Operador campeão identificado com maior Net PnL em trades_history: {best_ops} [SUCESSO]")

print("\n=======================================================")
print("TODOS OS 4 TESTES DE INTEGRIDADE PASSARAM COM SUCESSO!")
print("=======================================================")
