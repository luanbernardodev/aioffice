"""Validação Rigorosa dos 3 Pontos de Confirmação Confluentes (Triple Check) no Sentinela:
Ponto 1: Exaustão Institucional (RSI < 20 para BUY, RSI > 85 para SELL)
Ponto 2: Filtro Anti-Lateralização (ADX > 25)
Ponto 3: Rejeição ou Fluxo Institucional (Volume Spike >= 1.5x OU Pavio >= 60%)
"""
import pandas as pd
from core.sentinel import (
    check_indecision_filters,
    _check_alpha,
    _check_beta,
    _check_gamma,
    _check_delta,
    _check_epsilon
)

print("--- [TESTE TRIPLE CHECK] VALIDAÇÃO DOS 3 PONTOS CONFLUENTES ---")

# Base DataFrame de 70 candles M5
dates = pd.date_range("2026-10-20 00:00", periods=70, freq="5min")
base_df = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 70,
    "high": [105.0] * 70,
    "low": [95.0] * 70,
    "close": [100.0] * 70,
    "volume": [1000] * 70,
    "rsi": [50.0] * 70,
    "adx": [20.0] * 70,
    "vol_ratio": [1.0] * 70,
    "ema20": [102.0] * 70,
    "ema50": [100.0] * 70,
    "ema200": [98.0] * 70,
    "bb_upper": [110.0] * 70,
    "bb_mid": [100.0] * 70,
    "bb_lower": [90.0] * 70,
    "bandwidth": [0.08] * 70,
    "atr": [2.0] * 70,
    "vwap": [100.0] * 70,
})

last_idx = 69

# =====================================================================
# CENÁRIO 1: PONTO 1 - RSI NEUTRO (20 a 85) DEVE ABORTAR
# =====================================================================
df_neutral_rsi = base_df.copy()
df_neutral_rsi.loc[last_idx, "rsi"] = 45.0
df_neutral_rsi.loc[last_idx, "adx"] = 30.0
df_neutral_rsi.loc[last_idx, "vol_ratio"] = 2.0
approved, reason, _ = check_indecision_filters(df_neutral_rsi, "BUY")
assert not approved, "RSI 45 deveria ter sido abortado para BUY!"
assert "RSI Neutro" in reason, f"Motivo incorreto: {reason}"
print(f"[OK] Ponto 1: RSI 45 abortado para BUY -> {reason}")

approved_sell, reason_sell, _ = check_indecision_filters(df_neutral_rsi, "SELL")
assert not approved_sell, "RSI 45 deveria ter sido abortado para SELL!"
assert "RSI Neutro" in reason_sell
print(f"[OK] Ponto 1: RSI 45 abortado para SELL -> {reason_sell}")

# =====================================================================
# CENÁRIO 2: PONTO 2 - ADX BAIXO (<= 25) DEVE ABORTAR
# =====================================================================
df_low_adx = base_df.copy()
df_low_adx.loc[last_idx, "rsi"] = 18.0    # RSI extremo OK (< 20)
df_low_adx.loc[last_idx, "adx"] = 22.0    # ADX fraco (<= 25)
df_low_adx.loc[last_idx, "vol_ratio"] = 2.0
approved, reason, _ = check_indecision_filters(df_low_adx, "BUY")
assert not approved, "ADX 22 deveria ter sido abortado!"
assert "ADX Baixo" in reason, f"Motivo incorreto: {reason}"
print(f"[OK] Ponto 2: ADX 22 abortado -> {reason}")

# =====================================================================
# CENÁRIO 3: PONTO 3 - SEM VOLUME E SEM PAVIO DEVE ABORTAR
# =====================================================================
df_no_rejection = base_df.copy()
df_no_rejection.loc[last_idx, "rsi"] = 18.0       # RSI extremo OK
df_no_rejection.loc[last_idx, "adx"] = 28.0       # ADX forte OK
df_no_rejection.loc[last_idx, "vol_ratio"] = 1.1  # Volume normal (< 1.5x)
# Vela sem pavio longo: open 96, close 104, high 105, low 95 -> pavio inferior = 1 / 10 = 10% (< 60%)
df_no_rejection.loc[last_idx, "open"] = 96.0
df_no_rejection.loc[last_idx, "close"] = 104.0
df_no_rejection.loc[last_idx, "high"] = 105.0
df_no_rejection.loc[last_idx, "low"] = 95.0
approved, reason, _ = check_indecision_filters(df_no_rejection, "BUY")
assert not approved, "Sem volume e sem pavio deveria ter sido abortado!"
print(f"[OK] Ponto 3: Sem fluxo nem pavio abortado -> {reason}")

# =====================================================================
# CENÁRIO 4: SUCESSO COMPLETO (COMPRA COM VOLUME SPIKE)
# =====================================================================
df_success_buy = base_df.copy()
df_success_buy.loc[last_idx, "rsi"] = 18.0       # Ponto 1: RSI 18 (< 20)
df_success_buy.loc[last_idx, "adx"] = 28.0       # Ponto 2: ADX 28 (> 25)
df_success_buy.loc[last_idx, "vol_ratio"] = 1.8  # Ponto 3: Volume Spike 1.8x (>= 1.5x)
df_success_buy.loc[last_idx - 2:last_idx, "low"] = 93.0  # Sweep de liquidez abaixo do swing de 95
approved, reason, details = check_indecision_filters(df_success_buy, "BUY")
assert approved, f"Deveria ter aprovado compra! Motivo: {reason}"
print(f"[OK] [Ops Delta] TRIPLE CHECK APROVADO: {details} -> Ordem de Compra enviada!")
assert "RSI 18" in details
assert "ADX 28" in details
assert "Volume Spike 1.8x" in details

# =====================================================================
# CENÁRIO 5: SUCESSO COMPLETO (VENDA COM PINBAR DE REJEIÇÃO >= 60%)
# =====================================================================
df_success_sell = base_df.copy()
df_success_sell.loc[last_idx, "rsi"] = 88.0       # Ponto 1: RSI 88 (> 85)
df_success_sell.loc[last_idx, "adx"] = 32.0       # Ponto 2: ADX 32 (> 25)
df_success_sell.loc[last_idx, "vol_ratio"] = 1.2  # Volume normal, mas tem Pinbar
# Pinbar de Venda: range 10, pavio superior = high (110) - max(open 101, close 102) = 8 -> 8/10 = 80% (>= 60%)
df_success_sell.loc[last_idx, "open"] = 101.0
df_success_sell.loc[last_idx, "close"] = 102.0
df_success_sell.loc[last_idx, "high"] = 110.0
df_success_sell.loc[last_idx, "low"] = 100.0
approved_sell, _, details_sell = check_indecision_filters(df_success_sell, "SELL")
assert approved_sell, "Deveria ter aprovado venda por Pinbar de rejeição!"
print(f"[OK] [Ops Beta] TRIPLE CHECK APROVADO: {details_sell} -> Ordem de Venda enviada!")
assert "Pinbar 80%" in details_sell

# =====================================================================
# CENÁRIO 6: TESTE DOS GATILHOS DOS AGENTES OPERACIONAIS
# =====================================================================
# 1. Beta no setup de compra
bias_beta = _check_beta(df_success_buy)
assert bias_beta == "BUY", f"Ops Beta deveria retornar BUY, obtido {bias_beta}"
print("[OK] Ops Beta aprovado sob Triple Check Confluente: BUY")

# 2. Alpha no setup de compra
bias_alpha = _check_alpha(df_success_buy)
assert bias_alpha == "BUY", f"Ops Alpha deveria retornar BUY, obtido {bias_alpha}"
print("[OK] Ops Alpha aprovado sob Triple Check Confluente: BUY")

# 3. Delta no setup de compra (Sweep + Triple Check)
bias_delta = _check_delta(df_success_buy)
assert bias_delta == "BUY", f"Ops Delta deveria retornar BUY, obtido {bias_delta}"
print("[OK] Ops Delta aprovado sob Triple Check Confluente: BUY")

# 4. Epsilon no setup de compra (VWAP + Triple Check)
bias_epsilon = _check_epsilon(df_success_buy)
assert bias_epsilon == "BUY", f"Ops Epsilon deveria retornar BUY, obtido {bias_epsilon}"
print("[OK] Ops Epsilon aprovado sob Triple Check Confluente: BUY")

print("\n==================================================================")
print("TODAS AS REGRAS DO TRIPLE CHECK FORAM RIGOROSAMENTE VALIDADAS!")
print("==================================================================")
