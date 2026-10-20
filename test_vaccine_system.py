"""Teste do Sistema de Análise Pós-Morte (Setor 3) e Filtro de Vacinas no Sentinela."""
import pandas as pd
from core.sentinel import check_vaccines

print("--- [TESTE 1] SENTINELA RESPEITANDO A VACINA PÓS-MORTE ---")

# Cria DataFrame simulado
dates = pd.date_range("2026-10-20 00:00", periods=5, freq="15min")
df = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 5,
    "high": [105.0] * 5,
    "low": [95.0] * 5,
    "close": [100.0] * 5,
    "adx": [15.0] * 5,        # ADX fraco (15.0 < 20.0)
    "rsi": [55.0] * 5,
    "atr": [2.0] * 5,
    "vol_ratio": [1.0] * 5,
    "bandwidth": [0.05] * 5,
})

# Vacina gerada pela autópsia do Gamma: Proíbe COMPRA se ADX < 20
vaccine_gamma = {
    "indicator": "ADX",
    "operator": "<",
    "value": 20.0,
    "condition": "avoid_buy",
    "source_agent": "ops_gamma",
    "description": "ADX fraco",
}

# Cenário A: Sentinela quer COMPRAR, mas ADX=15 viola a vacina
abort_reason = check_vaccines("ops_delta", "BUY", df, [vaccine_gamma])
assert abort_reason is not None, "Deveria ter abortado a compra!"
print(f"[OK] [Ops Delta] Gatilho acionado, mas ABORTADO pela {abort_reason}.")
assert "Vacina Pós-Morte do Agente Gamma (ADX fraco)" in abort_reason

# Cenário B: Mercado com ADX forte (25.0 >= 20.0) -> Deve liberar o gatilho sem aborto
df_strong = df.copy()
df_strong.loc[4, "adx"] = 25.0
abort_strong = check_vaccines("ops_delta", "BUY", df_strong, [vaccine_gamma])
assert abort_strong is None, f"Gatilho deveria passar com ADX=25, mas foi abortado: {abort_strong}"
print("[OK] Com ADX forte (25.0 >= 20.0), a vacina libera a execução normalmente.")

# Cenário C: Sentinela quer VENDER, mas a vacina só proíbe COMPRA -> Deve liberar
abort_sell = check_vaccines("ops_delta", "SELL", df, [vaccine_gamma])
assert abort_sell is None, "Vacina de avoid_buy não deveria bloquear SELL!"
print("[OK] Vacina de avoid_buy não interfere em ordens SELL.")

print("\n--- [TESTE 2] PERSISTÊNCIA DA VACINA EM STRATEGY_PARAMETERS ---")
from core.database import DatabaseManager
db = DatabaseManager()

# Injeta a vacina em todos os operadores ativos
immunized = db.append_vaccine_to_active_agents(vaccine_gamma, exclude_agent_id="ops_gamma")
# Verifica se os parâmetros do ops_delta contêm a vacina (já imunizado anteriormente ou nesta rodada)
delta_params = db.get_strategy_params("ops_delta")
vaccines = delta_params.get("vaccines") or []
assert any(v.get("indicator") == "ADX" and v.get("value") == 20.0 for v in vaccines), "Vacina não encontrada em ops_delta!"
print(f"[OK] Agentes imunizados / vacina confirmada em strategy_parameters (total vacinas delta: {len(vaccines)}).")
print("[OK] Parâmetros de strategy_parameters atualizados com o array 'vaccines'.")

print("\n==================================================================")
print("SISTEMA DE ANÁLISE PÓS-MORTE E VACINAS VALIDADO COM 100% DE SUCESSO!")
print("==================================================================")
