"""Validação Quantitativa das Novas Regras de Reversão por RSI:
1. Regras de Entrada e Bypass de Veto (Golden Ticket) no sentinel.py
2. Stop Loss Médio Dinâmico (1.5x ATR) e Remoção de TP Fixo (TP=0) no mt5_bridge.py
3. Loop de Fecho Dinâmico por RSI no main.py e mt5_bridge.py (BUY fecha com RSI >= 60, SELL fecha com RSI <= 40)
"""
import pandas as pd
import numpy as np
from config import settings

# Garante modo isolado de teste
settings.DRY_RUN = True

from core.sentinel import analyze_market, _check_beta, Sentinel
from core.mt5_bridge import MT5Bridge
from core.database import DatabaseManager
from agents import sector_1_ops
import main

print("=== INICIANDO VALIDAÇÃO QUANTITATIVA DA ESTRATÉGIA DE REVERSÃO POR RSI ===")

# -----------------------------------------------------------------------------------------
# TESTE 1: sentinel.py - analyze_market e _check_beta
# -----------------------------------------------------------------------------------------
dates = pd.date_range("2026-10-20 00:00", periods=50, freq="15min")
df_base = pd.DataFrame({
    "time": dates,
    "open": [100.0] * 50,
    "high": [105.0] * 50,
    "low": [95.0] * 50,
    "close": [100.0] * 50,
    "volume": [1000] * 50,
    "rsi": [50.0] * 50,
    "atr": [2.0] * 50,
    "adx": [15.0] * 50,
    "vol_ratio": [1.0] * 50,
})

# Cenário 1.1: RSI <= 30 (Sinal de Compra + Golden Ticket)
df_buy = df_base.copy()
df_buy.loc[49, "rsi"] = 28.5
bias, force = analyze_market(df_buy)
assert bias == "BUY", f"Deveria ser BUY para RSI 28.5, obtido: {bias}"
assert force is True, f"force_execute deveria ser True para RSI <= 30"

beta_res = _check_beta(df_buy)
assert beta_res == "BUY", f"_check_beta deveria ser BUY, obtido: {beta_res}"
assert getattr(beta_res, "force_execute", False) is True, "beta_res deveria ter force_execute=True"
print("[OK] Teste 1.1: RSI <= 30 gerou BUY com force_execute = True (Golden Ticket).")

# Cenário 1.2: RSI >= 70 (Sinal de Venda + Golden Ticket)
df_sell = df_base.copy()
df_sell.loc[49, "rsi"] = 73.2
bias_s, force_s = analyze_market(df_sell)
assert bias_s == "SELL", f"Deveria ser SELL para RSI 73.2, obtido: {bias_s}"
assert force_s is True, f"force_execute deveria ser True para RSI >= 70"

beta_res_s = _check_beta(df_sell)
assert beta_res_s == "SELL", f"_check_beta deveria ser SELL, obtido: {beta_res_s}"
assert getattr(beta_res_s, "force_execute", False) is True
print("[OK] Teste 1.2: RSI >= 70 gerou SELL com force_execute = True (Golden Ticket).")

# Cenário 1.3: RSI Neutro (31 a 69) não deve disparar
df_neutral = df_base.copy()
df_neutral.loc[49, "rsi"] = 52.0
bias_n, force_n = analyze_market(df_neutral)
assert bias_n is None, f"Deveria ser None para RSI 52, obtido: {bias_n}"
assert force_n is False
assert _check_beta(df_neutral) is None
print("[OK] Teste 1.3: RSI neutro (52) retornou None sem gatilho.")

# -----------------------------------------------------------------------------------------
# TESTE 2: Bypass de Veto dos Setores 2 e 3 com Golden Ticket (force_execute = True)
# -----------------------------------------------------------------------------------------
db = DatabaseManager()
bridge = MT5Bridge()

# Simula Veto do Setor 2 (Notícias Red Flag) e Veto do Setor 3 (macro_viable = False)
db.save_market_context(crypto_sentiment=-10, gold_sentiment=-10, red_flag=True, key_driver="Crise Macro")
db.set_macro_gate("ops_beta", viable=False, reason="Veto Macro Auditoria S3", valid_minutes=1)

trigger_forced = {
    "agent_id": "ops_beta",
    "symbol": "BTCUSD",
    "bias": "BUY",
    "trigger": "EXHAUSTION_REVERSAL",
    "force_execute": True,
    "atr": 500.0,
    "timeframe": "M15"
}

# Deve executar sem ser bloqueado por red_flag nem por macro_veto
res = sector_1_ops.execute_autonomous_trigger(trigger_forced, db, bridge)
assert res is not None, "execute_autonomous_trigger não deveria ser bloqueado com force_execute=True!"
assert res.get("action") == "BUY"
assert res.get("reason") != "red_flag"
assert res.get("reason") != "macro_veto"
print("[OK] Teste 2: Golden Ticket (force_execute=True) bypassou red flag do Setor 2 e veto do Setor 3 com sucesso!")

# -----------------------------------------------------------------------------------------
# TESTE 3: Stop Loss Médio Dinâmico (1.5x ATR) e Injeção de Hard Take Profit Físico (R:R 1:1.5)
# -----------------------------------------------------------------------------------------
order = bridge.execute_order("BTCUSD", "BUY", 0.05, comment="ops_beta", db=db)
assert order["success"] is True
sl_dist = abs(order["price"] - order["sl"])
expected_tp = round(order["price"] + sl_dist * 1.5, 2)
assert abs(order["tp"] - expected_tp) < 1.0, f"Hard TP esperado ~{expected_tp}, obtido: {order['tp']}"

# Verifica se o SL foi calculado dinamicamente com 1.5x ATR
current_price = order["price"]
current_atr = bridge.get_current_atr("BTCUSD", "M15", 14)
expected_sl = round(current_price - 1.5 * current_atr, 2)
assert abs(order["sl"] - expected_sl) < 1.0, f"SL esperado ~{expected_sl}, obtido {order['sl']}"
print(f"[OK] Teste 3: execute_order definiu Hard TP físico ({order['tp']}) e Stop Loss ({order['sl']}) com sucesso!")

# -----------------------------------------------------------------------------------------
# TESTE 4: Loop de Fecho Dinâmico por RSI (monitor_open_positions_and_close)
# -----------------------------------------------------------------------------------------
# Cria trades simulados com tickets dinâmicos únicos para evitar duplicidade de PK no Supabase
import time
ticket_buy = int(time.time() * 1000) % (10**8)
db.log_trade(
    agent_id="ops_beta", symbol="BTCUSD", action="BUY", volume=0.1,
    entry_price=60000.0, sl=58000.0, tp=0.0, risk_amount=100.0,
    ticket=ticket_buy, dry_run=True, status="OPEN"
)

# Simula taxa de RSI >= 60 para BTCUSD alterando temporariamente o método get_current_rsi
original_get_rsi = bridge.get_current_rsi
bridge.get_current_rsi = lambda symbol, timeframe="M15", period=14: 65.0

# Executa o monitor de fecho dinâmico
closed = bridge.monitor_open_positions_and_close(db)
assert any(c["ticket"] == ticket_buy for c in closed), "Posição BUY deveria ter sido fechada por RSI >= 60!"
closed_trade = db._select("trades_history", eq={"ticket_mt5": ticket_buy})[0]
assert closed_trade["status"] == "CLOSED"
assert "RSI" in closed_trade["exit_reason"]
print(f"[OK] Teste 4.1: Posição BUY fechada com sucesso por RSI >= 60 (RSI: 65.0, PnL: ${closed_trade['profit_usd']:.2f}, Motivo: {closed_trade['exit_reason']}).")

# Testa fechamento de posição SELL com RSI <= 40
ticket_sell = ticket_buy + 1
db.log_trade(
    agent_id="ops_beta", symbol="ETHUSD", action="SELL", volume=0.5,
    entry_price=3000.0, sl=3100.0, tp=0.0, risk_amount=100.0,
    ticket=ticket_sell, dry_run=True, status="OPEN"
)

bridge.get_current_rsi = lambda symbol, timeframe="M15", period=14: 35.0
closed_sell = main.monitor_open_positions_and_close(bridge, db)
assert any(c["ticket"] == ticket_sell for c in closed_sell), "Posição SELL deveria ter sido fechada por RSI <= 40!"
closed_trade_s = db._select("trades_history", eq={"ticket_mt5": ticket_sell})[0]
assert closed_trade_s["status"] == "CLOSED"
assert "RSI" in closed_trade_s["exit_reason"]
print(f"[OK] Teste 4.2: Posição SELL fechada com sucesso por RSI <= 40 (RSI: 35.0, PnL: ${closed_trade_s['profit_usd']:.2f}).")

# Restaura método
bridge.get_current_rsi = original_get_rsi

print("\n==================================================================")
print("TODAS AS REFATORAÇÕES DE REVERSÃO POR RSI FORAM VALIDADAS COM SUCESSO!")
print("==================================================================")
