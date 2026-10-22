"""Validação Quantitativa:
1. Restauração do Golden Ticket (Bypass Absoluto para RSI <= 30 e RSI >= 70).
2. Limitação do aprendizado do Setor 3 (vacinas atuam como filtro de meio de gráfico e otimizam SL/TP).
3. Especialização das funções dos agentes (Beta: Sniper RSI M15; Delta: SMC Scalper M1/M5; Epsilon: VWAP Momentum M1/M5).
4. Roteamento exclusivo de ordens e PnL.
"""
import pandas as pd
import numpy as np
from config import settings

settings.DRY_RUN = True

from core.sentinel import (
    analyze_market, _check_beta, _check_delta, _check_epsilon,
    _check_alpha, _check_gamma, check_vaccines, Sentinel, CHECKS, TRIGGER_NAMES
)
from core.mt5_bridge import MT5Bridge
from core.database import DatabaseManager
from agents import sector_1_ops

print("\n================================================================================")
print("INICIANDO BATERIA DE TESTES: GOLDEN TICKET, LIMITAÇÃO SETOR 3 E AGENTES DISTINTOS")
print("================================================================================\n")

# Base DataFrame de 60 períodos
dates = pd.date_range("2026-10-22 00:00", periods=60, freq="15min")
df_base = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 60,
    "high": [105.0] * 60,
    "low": [95.0] * 60,
    "close": [100.0] * 60,
    "volume": [1000.0] * 60,
    "tick_volume": [1000.0] * 60,
    "rsi": [50.0] * 60,
    "atr": [2.0] * 60,
    "adx": [25.0] * 60,
    "vol_ratio": [1.0] * 60,
    "ema9": [100.0] * 60,
    "ema21": [100.0] * 60,
    "ema20": [100.0] * 60,
    "ema50": [98.0] * 60,
    "vwap": [100.0] * 60,
    "bb_upper": [106.0] * 60,
    "bb_lower": [94.0] * 60,
    "bandwidth": [0.12] * 60,
    "support": [95.0] * 60,
    "resistance": [105.0] * 60,
    "ssl": [95.0] * 60,
    "bsl": [105.0] * 60,
})

# --------------------------------------------------------------------------------------
# TESTE 1: AGENTE BETA (Sniper RSI Exclusivo - M15) & GOLDEN TICKET
# --------------------------------------------------------------------------------------
print("--- [TESTE 1] AGENTE BETA: SNIPER RSI EXCLUSIVO & GOLDEN TICKET (BYPASS ABSOLUTO) ---")

# 1.1 Sobrevenda Extrema (RSI = 27.5 <= 30) -> BUY IMEDIATO
df_beta_buy = df_base.copy()
df_beta_buy.loc[59, "rsi"] = 27.5
res_beta_buy = _check_beta(df_beta_buy)
assert res_beta_buy == "BUY", f"Beta deveria retornar BUY, obtido {res_beta_buy}"
assert getattr(res_beta_buy, "force_execute", False) is True, "Golden Ticket deve ter force_execute=True"
assert res_beta_buy.details.get("golden_ticket") is True, "Deve marcar golden_ticket=True"
print(f"[OK] 1.1 Beta Sobrevenda (RSI 27.5): BUY com Golden Ticket e force_execute=True ({res_beta_buy.details['rationale']})")

# 1.2 Sobrecompra Extrema (RSI = 74.0 >= 70) -> SELL IMEDIATO
df_beta_sell = df_base.copy()
df_beta_sell.loc[59, "rsi"] = 74.0
res_beta_sell = _check_beta(df_beta_sell)
assert res_beta_sell == "SELL", f"Beta deveria retornar SELL, obtido {res_beta_sell}"
assert getattr(res_beta_sell, "force_execute", False) is True
assert res_beta_sell.details.get("golden_ticket") is True
print(f"[OK] 1.2 Beta Sobrecompra (RSI 74.0): SELL com Golden Ticket e force_execute=True ({res_beta_sell.details['rationale']})")

# 1.3 Meio de Gráfico (RSI = 52.0) -> BETA NÃO OPERA (Exclusividade de Extremos)
df_beta_neutral = df_base.copy()
df_beta_neutral.loc[59, "rsi"] = 52.0
assert _check_beta(df_beta_neutral) is None, "Beta NÃO deve operar em meio de gráfico (RSI 52)"
print("[OK] 1.3 Beta em meio de gráfico (RSI 52.0): None (Não opera sem extremo)")

# --------------------------------------------------------------------------------------
# TESTE 2: LIMITAÇÃO DO SETOR 3 & BYPASS DE VACINAS NO GOLDEN TICKET
# --------------------------------------------------------------------------------------
print("\n--- [TESTE 2] LIMITAÇÃO DO APRENDIZADO DO SETOR 3 & BYPASS NO GOLDEN TICKET ---")

# Vacina agressiva de IA que proibiria BUY com RSI < 40
vaccine_s3 = {
    "indicator": "RSI",
    "operator": "<",
    "value": 40.0,
    "condition": "avoid_buy",
    "description": "Veto de IA do Setor 3",
    "mid_range_only": True
}

# 2.1 Em extremo de RSI (Golden Ticket <= 30): Vacina DEVE ser sumariamente ignorada!
veto_extreme = check_vaccines("ops_beta", "BUY", df_beta_buy, [vaccine_s3])
assert veto_extreme is None, f"Vacina do Setor 3 não pode vetar Golden Ticket extremo! Obtido: {veto_extreme}"
print("[OK] 2.1 Bypass Absoluto do Golden Ticket: check_vaccines ignorou a vacina do Setor 3 em RSI 27.5!")

# 2.2 Em meio de gráfico (ex: RSI = 36.0, sem extremo): Vacina atua como filtro normal de meio de gráfico
df_mid = df_base.copy()
df_mid.loc[59, "rsi"] = 36.0
veto_mid = check_vaccines("ops_delta", "BUY", df_mid, [vaccine_s3])
assert veto_mid is not None, "Em meio de gráfico a vacina deve atuar como filtro de ruído!"
print(f"[OK] 2.2 Limitação do Setor 3: Em meio de gráfico (RSI 36.0), vacina atuou como filtro: '{veto_mid}'")

# --------------------------------------------------------------------------------------
# TESTE 3: AGENTE DELTA (SMC Scalper - M1/M5)
# --------------------------------------------------------------------------------------
print("\n--- [TESTE 3] AGENTE DELTA: SMC SCALPER (LIQUIDITY SWEEP & FALSO ROMPIMENTO) ---")

# Simula Spring (Sweep de Fundo com volume spike 2.0x e rejeição de pavio)
df_delta = df_base.copy()
support = 95.0
df_delta.loc[59, "open"] = 96.0
df_delta.loc[59, "high"] = 96.5
df_delta.loc[59, "low"] = 93.5      # Perfura suporte 95.0 (Liquidity Sweep)
df_delta.loc[59, "close"] = 95.8    # Fecha acima do suporte (Spring)
df_delta.loc[59, "vol_ratio"] = 2.0
df_delta.loc[59, "volume"] = 2000.0
df_delta.loc[59, "rsi"] = 38.0      # Meio de gráfico (não é Golden Ticket do Beta)

res_delta = _check_delta(df_delta, symbol="BTCUSD")
assert res_delta is not None, "Delta deveria detectar o Liquidity Sweep SMC!"
assert res_delta == "BUY", f"Delta deveria retornar BUY, obtido {res_delta}"
assert res_delta.details.get("strategy") == "ops_delta"
print(f"[OK] 3.1 Agente Delta detectou Spring SMC: {res_delta.details.get('rationale')}")

# --------------------------------------------------------------------------------------
# TESTE 4: AGENTE EPSILON (VWAP / Momentum Scalper - M1/M5)
# --------------------------------------------------------------------------------------
print("\n--- [TESTE 4] AGENTE EPSILON: VWAP / MOMENTUM FLOW SCALPER ---")

# Tendência de alta (Preço > VWAP, EMA9 > EMA21), pullback tocou VWAP e candle fechou positivo com volume
df_epsilon = df_base.copy()
df_epsilon.loc[59, "vwap"] = 100.0
df_epsilon.loc[59, "ema9"] = 101.0
df_epsilon.loc[59, "ema21"] = 100.5
df_epsilon.loc[59, "open"] = 100.2
df_epsilon.loc[59, "low"] = 99.9     # Tocou região da VWAP
df_epsilon.loc[59, "high"] = 101.5
df_epsilon.loc[59, "close"] = 101.2  # Fechou acima da VWAP e positivo
df_epsilon.loc[59, "vol_ratio"] = 1.4
df_epsilon.loc[59, "rsi"] = 55.0

res_epsilon = _check_epsilon(df_epsilon)
assert res_epsilon is not None, "Epsilon deveria detectar o Pullback na VWAP!"
assert res_epsilon == "BUY", f"Epsilon deveria retornar BUY, obtido {res_epsilon}"
assert res_epsilon.details.get("strategy") == "ops_epsilon"
print(f"[OK] 4.1 Agente Epsilon detectou VWAP Flow Scalp: {res_epsilon.details.get('rationale')}")

# --------------------------------------------------------------------------------------
# TESTE 5: ROTEAMENTO EXCLUSIVO DE ORDENS E REGISTRO DE PNL POR AGENTE
# --------------------------------------------------------------------------------------
print("\n--- [TESTE 5] ROTEAMENTO EXCLUSIVO DE ORDENS E PNL POR AGENTE ---")

bridge = MT5Bridge(mock=True)
db = DatabaseManager()

# Trigger gerado pelo Agente Beta
trigger_beta = {
    "agent_id": "ops_beta",
    "strategy": "ops_beta",
    "symbol": "BTCUSD",
    "bias": "BUY",
    "trigger": TRIGGER_NAMES["ops_beta"],
    "force_execute": True,
    "golden_ticket": True,
    "rsi": 27.5,
    "atr": 100.0,
    "rationale": "Sniper RSI Reversal [GOLDEN TICKET]",
    "timeframe": "M15"
}

# Execução com Golden Ticket
order_beta = sector_1_ops.execute_autonomous_trigger(trigger_beta, db, bridge)
assert order_beta is not None, "Ordem do Beta com Golden Ticket deve ser executada imediatamente!"
assert order_beta.get("action") == "BUY"
assert order_beta.get("agent_id") == "ops_beta"
print(f"[OK] 5.1 Ordem do Agente Beta executada com sucesso e atribuída exclusivamente a 'ops_beta'!")

# Trigger gerado pelo Agente Delta
trigger_delta = {
    "agent_id": "ops_delta",
    "strategy": "ops_delta",
    "symbol": "ETHUSD",
    "bias": "BUY",
    "trigger": TRIGGER_NAMES["ops_delta"],
    "force_execute": True,
    "rsi": 42.0,
    "atr": 20.0,
    "rationale": "SMC Scalper Liquidity Sweep",
    "timeframe": "M5"
}

order_delta = sector_1_ops.execute_autonomous_trigger(trigger_delta, db, bridge)
assert order_delta is not None
assert order_delta.get("agent_id") == "ops_delta"
print(f"[OK] 5.2 Ordem do Agente Delta executada com sucesso e atribuída exclusivamente a 'ops_delta'!")

# Trigger gerado pelo Agente Epsilon
trigger_epsilon = {
    "agent_id": "ops_epsilon",
    "strategy": "ops_epsilon",
    "symbol": "SOLUSD",
    "bias": "BUY",
    "trigger": TRIGGER_NAMES["ops_epsilon"],
    "force_execute": False,
    "rsi": 55.0,
    "atr": 2.0,
    "rationale": "VWAP Flow Momentum Scalp",
    "timeframe": "M5"
}

order_epsilon = sector_1_ops.execute_autonomous_trigger(trigger_epsilon, db, bridge)
assert order_epsilon is not None
assert order_epsilon.get("agent_id") == "ops_epsilon"
print(f"[OK] 5.3 Ordem do Agente Epsilon executada com sucesso e atribuída exclusivamente a 'ops_epsilon'!")

print("\n================================================================================")
print("TODOS OS 5 TESTES DE RESTAURAÇÃO DO GOLDEN TICKET E AGENTES FORAM UM SUCESSO!")
print("================================================================================\n")
