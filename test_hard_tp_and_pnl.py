"""Teste de validação para as duas correções críticas:
1. Injeção de Hard Take Profit físico com Risco:Retorno mínimo de 1:1.5 e normalização de casas decimais.
2. Atualização imediata do PnL do agente no Supabase ao fechar posição.
"""
import time
from config import settings
from core.database import DatabaseManager
from core.mt5_bridge import MT5Bridge

def run_tests():
    print("=== TESTE 1: INJEÇÃO DE HARD TAKE PROFIT (core/mt5_bridge.py) ===")
    bridge = MT5Bridge()
    db = DatabaseManager()

    # 1. Ordem de COMPRA
    order_buy = bridge.execute_order("BTCUSD", "BUY", 0.05, comment="ops_alpha", db=db)
    assert order_buy["success"] is True, "Falha na ordem de BUY"
    entry_buy = order_buy["price"]
    sl_buy = order_buy["sl"]
    tp_buy = order_buy["tp"]
    sl_dist_buy = abs(entry_buy - sl_buy)
    expected_min_tp_buy = round(entry_buy + (sl_dist_buy * 1.5), 2)

    print(f"[BUY] Preço: {entry_buy} | SL: {sl_buy} | Distância SL: {sl_dist_buy:.2f} | Hard TP: {tp_buy}")
    assert tp_buy > entry_buy, "Hard TP de COMPRA deve ser superior ao preço de entrada"
    assert abs(tp_buy - expected_min_tp_buy) < 0.05, f"Esperado TP ~{expected_min_tp_buy}, obtido {tp_buy}"
    print("[OK] Hard TP de COMPRA validado com R:R de 1:1.5!")

    # 2. Ordem de VENDA
    order_sell = bridge.execute_order("BTCUSD", "SELL", 0.05, comment="ops_beta", db=db)
    assert order_sell["success"] is True, "Falha na ordem de SELL"
    entry_sell = order_sell["price"]
    sl_sell = order_sell["sl"]
    tp_sell = order_sell["tp"]
    sl_dist_sell = abs(entry_sell - sl_sell)
    expected_min_tp_sell = round(entry_sell - (sl_dist_sell * 1.5), 2)

    print(f"[SELL] Preço: {entry_sell} | SL: {sl_sell} | Distância SL: {sl_dist_sell:.2f} | Hard TP: {tp_sell}")
    assert tp_sell < entry_sell, "Hard TP de VENDA deve ser inferior ao preço de entrada"
    assert abs(tp_sell - expected_min_tp_sell) < 0.05, f"Esperado TP ~{expected_min_tp_sell}, obtido {tp_sell}"
    print("[OK] Hard TP de VENDA validado com R:R de 1:1.5!")

    print("\n=== TESTE 2: ATUALIZAÇÃO DO PNL DOS AGENTES NO SUPABASE ===")
    test_agent = "ops_beta"
    initial_stat = db.get_agent_status(test_agent) or {}
    initial_pnl = float(initial_stat.get("total_profit") if initial_stat.get("total_profit") is not None else (initial_stat.get("pnl") or 0.0))
    print(f"PnL inicial de {test_agent} no Supabase: ${initial_pnl:.2f}")

    profit_delta = 50.25
    ticket_test = int(time.time() * 1000) % (10**9)

    # Cria trade aberto
    db.log_trade(
        agent_id=test_agent,
        symbol="BTCUSD",
        action="BUY",
        volume=0.05,
        entry_price=entry_buy,
        sl=sl_buy,
        tp=tp_buy,
        risk_amount=30.0,
        ticket=ticket_test,
        dry_run=True,
        status="OPEN"
    )

    # Fecha trade disparando a rotina de fecho
    db.close_trade(ticket_test, pnl=profit_delta, exit_price=tp_buy, outcome="TP_HIT", agent_id=test_agent)

    # Verifica atualização imediata em agents_status
    updated_stat = db.get_agent_status(test_agent) or {}
    new_pnl = float(updated_stat.get("total_profit") if updated_stat.get("total_profit") is not None else (updated_stat.get("pnl") or 0.0))
    expected_pnl = round(initial_pnl + profit_delta, 2)

    print(f"PnL atualizado de {test_agent} no Supabase: ${new_pnl:.2f} (Esperado: ${expected_pnl:.2f})")
    assert abs(new_pnl - expected_pnl) < 0.01, f"PnL inconsistente: esperado {expected_pnl}, obtido {new_pnl}"
    print("[OK] Atualização de PnL no Supabase validada com sucesso!")

    # Limpa o delta do teste para não poluir o saldo de produção
    db.add_agent_profit(test_agent, -profit_delta)
    restored_stat = db.get_agent_status(test_agent) or {}
    restored_pnl = float(restored_stat.get("total_profit") or 0.0)
    print(f"PnL restaurado de {test_agent} pós-teste: ${restored_pnl:.2f}")

    print("\n==================================================================")
    print("TODAS AS CORREÇÕES CRÍTICAS FORAM VALIDADAS COM SUCESSO!")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
