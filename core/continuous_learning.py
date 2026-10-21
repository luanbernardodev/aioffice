"""Módulo de Machine Learning Contínuo do Setor 3 (Evolução Contínua via MCP).
Implementa o rastreamento rigoroso de ciclos de 2 operações por agente:
- Se cycle_pnl >= 0: o agente foi bem -> zera o ciclo e continua.
- Se cycle_pnl < 0: o agente falhou -> zera o ciclo e dispara auditoria imediata
  via servidor MCP do MetaTrader 5 (http://127.0.0.1:22346/mcp) e Claude,
  distribuindo a vacina institucional globalmente para TODOS os operadores.
"""
import logging
from typing import Any, Dict, Optional

log = logging.getLogger("continuous_ml")

# Rastreamento em memória dos ciclos de 2 operações por agente:
# Formato: {agent_id: {"trades_count": int, "cycle_pnl": float, "last_symbol": str}}
_AGENT_CYCLES: Dict[str, Dict[str, Any]] = {}


def get_agent_cycle(agent_id: str) -> Dict[str, Any]:
    """Retorna o estado atual do ciclo do agente."""
    if agent_id not in _AGENT_CYCLES:
        _AGENT_CYCLES[agent_id] = {
            "trades_count": 0,
            "cycle_pnl": 0.0,
            "last_symbol": "BTCUSD",
        }
    return _AGENT_CYCLES[agent_id]


def get_all_cycles() -> Dict[str, Dict[str, Any]]:
    """Retorna snapshot de todos os ciclos ativos em memória."""
    return dict(_AGENT_CYCLES)


def reset_agent_cycle(agent_id: str) -> None:
    """Zera o contador e o PnL do ciclo do agente."""
    _AGENT_CYCLES[agent_id] = {
        "trades_count": 0,
        "cycle_pnl": 0.0,
        "last_symbol": "BTCUSD",
    }


def record_trade_closure(db: Any, claude: Any, agent_id: str,
                         pnl: float, symbol: str = "BTCUSD") -> Optional[Dict[str, Any]]:
    """Atualiza o contador e PnL do ciclo de 2 operações do agente.
    Ao atingir trades_count == 2:
      - Se cycle_pnl >= 0: zera o ciclo e continua.
      - Se cycle_pnl < 0: zera o ciclo e invoca IMEDIATAMENTE a auditoria do Setor 3 via MCP.
    """
    if not agent_id:
        return None

    cycle = get_agent_cycle(agent_id)
    cycle["trades_count"] += 1
    cycle["cycle_pnl"] = round(cycle["cycle_pnl"] + float(pnl), 2)
    cycle["last_symbol"] = symbol

    trades_count = cycle["trades_count"]
    cycle_pnl = cycle["cycle_pnl"]

    log.info("[SETOR 3 - CONTINUOUS ML] Agente %s registrou trade (%+.2f USD em %s). "
             "Ciclo Atual: %d/2 trades | PnL Acumulado do Ciclo: %+.2f USD",
             agent_id, float(pnl), symbol, trades_count, cycle_pnl)

    # Gatilho de 2 Operações
    if trades_count >= 2:
        # Armazena snapshot e zera o ciclo imediatamente
        finished_pnl = cycle_pnl
        finished_symbol = symbol or cycle.get("last_symbol", "BTCUSD")
        reset_agent_cycle(agent_id)

        if finished_pnl >= 0:
            log.info("[SETOR 3 - CICLO BEM-SUCEDIDO] Agente %s concluiu ciclo de 2 operações com LUCRO (+%.2f USD). "
                     "Desempenho aprovado. Ciclo zerado.", agent_id, finished_pnl)
            return {
                "status": "success",
                "agent_id": agent_id,
                "trades_count": 2,
                "cycle_pnl": finished_pnl,
                "symbol": finished_symbol,
            }
        else:
            log.warning("[SETOR 3 - GATILHO DE FALHA CONTÍNUA] Agente %s concluiu ciclo de 2 operações com SALDO NEGATIVO (%.2f USD)! "
                        "Invocando IMEDIATAMENTE auditoria investigativa via MCP do MT5...",
                        agent_id, finished_pnl)

            from agents.sector_3_analytics import audit_cycle_failure_mcp
            result = audit_cycle_failure_mcp(
                db=db,
                claude=claude,
                agent_id=agent_id,
                symbol=finished_symbol,
                cycle_loss=finished_pnl,
            )
            return {
                "status": "failure_evolved",
                "agent_id": agent_id,
                "trades_count": 2,
                "cycle_pnl": finished_pnl,
                "symbol": finished_symbol,
                "evolution": result,
            }

    return {
        "status": "in_progress",
        "agent_id": agent_id,
        "trades_count": trades_count,
        "cycle_pnl": cycle_pnl,
    }
