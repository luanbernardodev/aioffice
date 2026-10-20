"""Teste do Módulo de Auditoria (Setor 3): Integração com Servidor MCP MT5 e Pós-Morte V2."""
import pytest
from unittest.mock import MagicMock, patch
from config import settings
from agents.sector_3_analytics import MT5MCPClient, generate_post_mortem_vaccine
from core.database import DatabaseManager


def test_mcp_client_credentials_and_tools():
    """Valida se as credenciais do .env foram carregadas e se os schemas das ferramentas estão configurados."""
    client = MT5MCPClient()
    assert client.endpoint == settings.MT5_MCP_ADDRESS
    assert client.api_key == settings.MT5_MCP_API_KEY
    assert "Bearer" in client.headers["Authorization"]

    tools = client.get_anthropic_tools()
    tool_names = [t["name"] for t in tools]
    assert "get_price_history" in tool_names
    assert "get_indicator_data" in tool_names
    assert "get_terminal_state" in tool_names
    print(f"[OK] MT5MCPClient configurado com {len(tools)} ferramentas de leitura: {tool_names}")


def test_mcp_security_guardrail_read_only():
    """Valida a Blindagem de Escopo: o Setor 3 é proibido de executar ou alterar ordens."""
    client = MT5MCPClient()

    # Tentativas de operações de execução proibidas
    prohibited_calls = [
        ("order_send", {"symbol": "BTCUSD", "volume": 0.1, "type": "BUY"}),
        ("order_close", {"ticket": 12345}),
        ("trade_open", {"symbol": "ETHUSD"}),
        ("position_close", {"ticket": 999}),
        ("cancel_order", {"ticket": 555}),
    ]

    for name, args in prohibited_calls:
        try:
            client.call_tool(name, args)
            assert False, f"Deveria ter bloqueado a ferramenta '{name}' com PermissionError!"
        except PermissionError as exc:
            assert "BLINDAGEM DE ESCOPO VIOLADA" in str(exc)
            print(f"[OK] Trava de Segurança ativada: tentativa de '{name}' bloqueada com sucesso!")

    # Operações de leitura permitidas
    price_res = client.call_tool("get_price_history", {"symbol": "BTCUSD", "timeframe": "M5", "count": 5})
    assert "candles" in price_res or "status" in price_res
    print("[OK] Ferramenta de leitura 'get_price_history' executada com sucesso!")

    indicator_res = client.call_tool("get_indicator_data", {"symbol": "BTCUSD", "timeframe": "M5", "indicator_name": "RSI"})
    assert "values" in indicator_res or "indicator" in indicator_res
    print("[OK] Ferramenta de leitura 'get_indicator_data' executada com sucesso!")


def test_post_mortem_v2_flow():
    """Valida o novo fluxo investigativo do Pós-Morte V2 com chamada autônoma de ferramentas."""
    db = DatabaseManager()
    mcp_client = MT5MCPClient()

    # Mock do ClaudeClient simulando a investigação do LLM
    mock_claude = MagicMock()
    tool_invocations = []

    def mock_ask_with_tools(model, system_prompt, initial_user_message, tools, tool_executor, max_turns, max_tokens):
        # 1. Verifica se o prompt investigativo obrigatório foi transmitido
        assert "Use a sua conexão MCP ao MT5 para extrair os candles M1/M5" in initial_user_message
        assert "verificar o nível de volume e cruzar com as médias móveis" in initial_user_message

        # 2. Simula o Claude chamando autonomamente get_price_history e get_indicator_data
        tool_invocations.append("get_price_history")
        hist = tool_executor("get_price_history", {"symbol": "BTCUSD", "timeframe": "M5", "count": 15})
        assert "candles" in hist

        tool_invocations.append("get_indicator_data")
        ind = tool_executor("get_indicator_data", {"symbol": "BTCUSD", "timeframe": "M5", "indicator_name": "RSI", "period": 14})
        assert "values" in ind

        # 3. Retorna a vacina matemática sintetizada pelo Claude
        return {
            "toxic_pattern_identified": "Compra em exaustão de baixa com RSI < 40 e volume decrescente identificado via MT5 MCP",
            "new_avoidance_rule": {
                "indicator": "RSI",
                "operator": "<",
                "value": 40.0,
                "condition": "avoid_buy",
                "description": "RSI < 40 em exaustão de baixa",
            }
        }

    mock_claude.ask_with_tools.side_effect = mock_ask_with_tools

    # Executa a autópsia investigativa V2 para um agente falho
    result = generate_post_mortem_vaccine(db, mock_claude, failed_agent_id="ops_alpha", mcp_client=mcp_client)

    assert result is not None
    assert result["failed_agent_id"] == "ops_alpha"
    assert "RSI" in str(result["new_avoidance_rule"])
    assert result["new_avoidance_rule"]["value"] == 40.0
    assert len(tool_invocations) == 2
    print(f"[OK] Pós-Morte V2 concluído! Prompt investigativo validado, ferramentas chamadas: {tool_invocations}")
    print(f"[OK] Vacina matemática injetada: {result['new_avoidance_rule']}")


if __name__ == "__main__":
    test_mcp_client_credentials_and_tools()
    test_mcp_security_guardrail_read_only()
    test_post_mortem_v2_flow()
    print("\n==================================================================")
    print("TODOS OS TESTES DO MT5 MCP E PÓS-MORTE V2 PASSARAM COM SUCESSO!")
    print("==================================================================")
