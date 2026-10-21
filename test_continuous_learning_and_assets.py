"""Validação completa dos 3 requisitos vitais:
1. Rastreio de ciclo de 2 operações por agente.
2. Gatilho de falha contínua disparando auditoria MCP do Setor 3 com prompt cripto institucional.
3. Persistência em agent_learning e distribuição global da vacina para todos os operadores.
4. SELECT rápido de ativos ativos em system_config.
"""
import pytest
from unittest.mock import MagicMock
from core.database import DatabaseManager
from core.continuous_learning import (
    get_agent_cycle,
    reset_agent_cycle,
    record_trade_closure,
)
from agents.sector_3_analytics import MT5MCPClient, audit_cycle_failure_mcp
from core.sentinel import check_vaccines


def test_asset_selector_fast_select():
    db = DatabaseManager()
    assets = db.get_active_assets()
    assert isinstance(assets, list)
    assert len(assets) > 0
    print(f"\n[OK] SELECT rápido de ativos retornou: {assets}")


def test_continuous_learning_cycle_tracker():
    db = DatabaseManager()
    agent_id = "ops_delta"
    reset_agent_cycle(agent_id)

    cycle_0 = get_agent_cycle(agent_id)
    assert cycle_0["trades_count"] == 0
    assert cycle_0["cycle_pnl"] == 0.0

    # 1. Trade 1: Lucro de +$20.00
    res1 = record_trade_closure(db, None, agent_id, 20.0, symbol="BTCUSD")
    assert res1["status"] == "in_progress"
    assert res1["trades_count"] == 1
    assert res1["cycle_pnl"] == 20.0

    # 2. Trade 2: Lucro de +$15.00 -> Ciclo concluído com sucesso (+35.00)
    res2 = record_trade_closure(db, None, agent_id, 15.0, symbol="BTCUSD")
    assert res2["status"] == "success"
    assert res2["cycle_pnl"] == 35.0

    # O ciclo deve ter sido zerado
    cycle_reset = get_agent_cycle(agent_id)
    assert cycle_reset["trades_count"] == 0
    assert cycle_reset["cycle_pnl"] == 0.0
    print("[OK] Ciclo positivo de 2 operações concluído com sucesso e zerado.")


def test_continuous_learning_failure_mcp_audit():
    db = DatabaseManager()
    mcp_client = MT5MCPClient()
    agent_id = "ops_alpha"
    reset_agent_cycle(agent_id)

    mock_claude = MagicMock()
    tool_calls = []

    def mock_ask_with_tools(model, system_prompt, initial_user_message, tools, tool_executor, max_turns, max_tokens):
        # Validação do Prompt Dinâmico Cripto Institucional Obrigatório
        assert "O Agente Alpha realizou 2 entradas consecutivas em BTCUSD e obteve saldo negativo de" in initial_user_message
        assert "Order Blocks, Imbalances/FVG, absorção de volume ou níveis de Liquidação" in initial_user_message

        tool_calls.append("get_price_history")
        hist = tool_executor("get_price_history", {"symbol": "BTCUSD", "timeframe": "M5", "count": 20})
        assert "candles" in hist

        tool_calls.append("get_indicator_data")
        ind = tool_executor("get_indicator_data", {"symbol": "BTCUSD", "timeframe": "M5", "indicator_name": "RSI", "period": 14})
        assert "values" in ind

        return {
            "technical_failure": "Rejeição violenta em Order Block de 1H com FVG não preenchido e absorção de volume institucional.",
            "vaccine_rule": {
                "indicator": "RSI",
                "operator": "<",
                "value": 42.0,
                "condition": "avoid_buy",
                "description": "Evitar compra em zona de absorção institucional / Order Block não mitigado",
            }
        }

    mock_claude.ask_with_tools.side_effect = mock_ask_with_tools

    # Trade 1: Perda de -$15.00
    res1 = record_trade_closure(db, mock_claude, agent_id, -15.0, symbol="BTCUSD")
    assert res1["status"] == "in_progress"

    # Trade 2: Perda de -$10.00 -> Dispara auditoria MCP
    res2 = record_trade_closure(db, mock_claude, agent_id, -10.0, symbol="BTCUSD")
    assert res2["status"] == "failure_evolved"
    assert res2["cycle_pnl"] == -25.0
    assert len(tool_calls) == 2

    evolution = res2["evolution"]
    assert "technical_failure" in evolution
    assert "Order Block" in evolution["technical_failure"]
    assert len(evolution["immunized_agents"]) > 0

    # Todos os agentes operacionais devem ter sido vacinados
    for op_id in ["ops_alpha", "ops_beta", "ops_gamma", "ops_delta", "ops_epsilon"]:
        params = db.get_strategy_params(op_id)
        vacs = params.get("vaccines") or []
        descriptions = [v.get("description", "") for v in vacs]
        assert any("Order Block" in d for d in descriptions), f"Agente {op_id} não recebeu a vacina global!"

    print(f"[OK] Falha em ciclo de 2 trades acionou MCP e vacinou {len(evolution['immunized_agents'])} operadores globalmente!")


if __name__ == "__main__":
    test_asset_selector_fast_select()
    test_continuous_learning_cycle_tracker()
    test_continuous_learning_failure_mcp_audit()
    print("\n==================================================================")
    print("TODAS AS VALIDAÇÕES DE BACKEND E SETOR 3 PASSARAM COM SUCESSO!")
    print("==================================================================")
