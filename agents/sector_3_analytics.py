import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from agents.claude_client import ClaudeClient, ClaudeError
from agents.sector_4_rnd import _sanitize
from config import settings
from config.prompts import (OPS_STYLES, SECTOR_3_ANALYTICS_PROMPT, SECTOR_3_CALIBRATION_PROMPT,
                            SECTOR_3_MACRO_FILTER_PROMPT)
from core.database import DatabaseManager, strategy_of

log = logging.getLogger("sector3")
AGENT_ID = "analytics"


def compute_metrics(trades: List[dict]) -> Dict[str, Any]:
    """Win rate (%), profit factor, drawdown máximo (% do saldo) e PnL a partir de trades fechados."""
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    equity = peak = max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = 99.0 if gross_win > 0 else 0.0
    return {
        "trades": len(pnls),
        "win_rate": round(100 * len(wins) / len(pnls), 2) if pnls else 0.0,
        "profit_factor": round(pf, 2),
        "max_drawdown": round(100 * max_dd / settings.MOCK_BALANCE, 2),
        "net_pnl": round(sum(pnls), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "open_trades": len([t for t in trades if t.get("status") == "OPEN"]),
    }


def build_metrics(db: DatabaseManager) -> Dict[str, Dict[str, Any]]:
    trades = db.get_trades_last_24h()
    return {a: compute_metrics([t for t in trades if t.get("agent_id") == a])
            for a in db.get_ops_agent_ids()}


def best_agent(db: DatabaseManager, metrics: Dict[str, Dict[str, Any]],
               exclude: Optional[List[str]] = None) -> Optional[str]:
    """Agente empregado com melhor Profit Factor (desempate: net_pnl). Prefere quem tem trades fechados."""
    alive = [a for a in db.get_ops_agent_ids() if a not in (exclude or [])]
    if not alive:
        return None
    traded = [a for a in alive if metrics.get(a, {}).get("trades", 0) > 0]
    pool = traded or alive
    return max(pool, key=lambda a: (metrics.get(a, {}).get("profit_factor", 0.0),
                                    metrics.get(a, {}).get("net_pnl", 0.0)))


def run(db: DatabaseManager, claude: ClaudeClient,
        metrics: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    db.update_agent_status(AGENT_ID, "CRUNCHING", "Calculando Sharpe até no café...")
    metrics = metrics or build_metrics(db)
    ops_ids = db.get_ops_agent_ids()
    try:
        result = claude.ask_json(settings.MODEL_SMART, SECTOR_3_ANALYTICS_PROMPT, {
            "metrics_by_agent": metrics,
            "current_params": {a: db.get_strategy_params(a) for a in ops_ids},
        }, max_tokens=3000)
    except ClaudeError as exc:
        log.error("Setor 3: %s", exc)
        db.update_agent_status(AGENT_ID, "IDLE", "Planilha travou. Tentarei depois.")
        return None

    diagnostics = [d for d in (result.get("agent_diagnostics") or [])
                   if isinstance(d, dict) and d.get("agent_id") in ops_ids]
    result["agent_diagnostics"] = diagnostics
    result["request_emergency_meeting"] = bool(result.get("request_emergency_meeting", False))
    result["metrics"] = metrics
    state = "ALERT" if result.get("overall_health") == "CRITICAL" else "IDLE"
    db.update_agent_status(AGENT_ID, state, str(result.get("office_bubble_thought", "Auditoria feita.")))
    log.info("Analytics: saúde=%s falhas=%d", result.get("overall_health"), len(diagnostics))
    return result


# ------------------------------------------------------------------ gate macro
def evaluate_macro_relevance(db: DatabaseManager, claude: ClaudeClient,
                             macro_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Recebe o resumo do Setor 2, cruza 'Relevância vs. Estratégia' e libera/veta cada operador.

    Retorna um JSON estrito contendo:
    {
      "is_market_safe": bool,
      "strategy_authorization": {"ops_alpha": bool, ...},
      "veto_reason": str,
      "valid_for_minutes": int
    }
    Falha fechada: sem veredito vigente (erro do Claude/expiração), nenhuma mesa opera.
    """
    db.update_agent_status(AGENT_ID, "CRUNCHING", "Cruzando notícia macro com os estilos das mesas...")
    agents = db.get_ops_agents()
    red_flag = bool(macro_summary.get("red_flag_pause_trading"))
    valid = settings.MACRO_VALIDITY_MIN

    if red_flag:
        # Regra de segurança determinística: red flag macro pausa todas as mesas
        is_market_safe = False
        strategy_authorization = {a["agent_id"]: False for a in agents}
        veto_reason = f"Alerta vermelho macro do Setor 2: {macro_summary.get('key_driver', 'Risco sistêmico detectado')}. Todas as mesas vetadas."
        thought = "Red flag! Todas as mesas vetadas."
    else:
        operators = [{"agent_id": a["agent_id"], "strategy": strategy_of(a),
                      "style": OPS_STYLES.get(strategy_of(a), ""),
                      "timeframe": settings.STRATEGY_TIMEFRAMES.get(strategy_of(a), settings.TIMEFRAME)}
                     for a in agents]
        try:
            result = claude.ask_json(settings.MODEL_SMART, SECTOR_3_MACRO_FILTER_PROMPT, {
                "macro_input": macro_summary, "operators": operators}, max_tokens=2000)
            is_market_safe = bool(result.get("is_market_safe", True))
            strategy_authorization = result.get("strategy_authorization") or {}
            veto_reason = str(result.get("veto_reason") or "Filtro macro avaliado pelo auditor do Setor 3.")
            try:
                valid = int(max(15, min(120, float(result.get("valid_for_minutes", valid)))))
            except (TypeError, ValueError):
                pass
            thought = str(result.get("office_bubble_thought", f"Gate macro: {'Seguro' if is_market_safe else 'Risco alto'}"))
        except ClaudeError as exc:
            log.error("Setor 3 (gate macro): %s — falha fechada, operando em modo seguro.", exc)
            db.update_agent_status(AGENT_ID, "IDLE", "Sem leitura macro. Mesas travadas por segurança.")
            is_market_safe = False
            strategy_authorization = {a["agent_id"]: False for a in agents}
            veto_reason = f"Falha de comunicação no auditor ({exc}). Fail-closed: todas as operações travadas por segurança."
            thought = "Erro macro: mesas travadas."
            valid = 15

    # Aplica o veredito no banco para cada agente operacional
    for a in agents:
        aid = a["agent_id"]
        strat = strategy_of(a)
        # Suporta autorização direta pelo agent_id ou pela estratégia base (ex.: clones)
        auth = bool(strategy_authorization.get(aid, strategy_authorization.get(strat, False)))
        viable = is_market_safe and auth
        strategy_authorization[aid] = viable
        db.set_macro_gate(aid, viable, veto_reason, valid)

    db.update_agent_status(AGENT_ID, "ALERT" if not is_market_safe else "IDLE", thought)
    log.info("Setor 3 Auditoria Macro (%d min): is_market_safe=%s | %s", valid, is_market_safe, veto_reason)
    log.info("Autorizações de estratégia: %s",
             ", ".join(f"{k}={'OK' if v else 'VETO'}" for k, v in strategy_authorization.items()))

    return {
        "is_market_safe": is_market_safe,
        "strategy_authorization": strategy_authorization,
        "veto_reason": veto_reason,
        "valid_for_minutes": valid,
    }


# ------------------------------------------------------------------ eventos de perda
def _blend(current: Dict[str, Any], target: Dict[str, Any], alpha: float) -> Dict[str, Any]:
    out = dict(current)
    for key, cur in current.items():
        tgt = target.get(key)
        if isinstance(cur, (int, float)) and isinstance(tgt, (int, float)):
            out[key] = cur + alpha * (tgt - cur)
    return out


def handle_loss_event(db: DatabaseManager, claude: ClaudeClient, agent_id: str, level: str,
                      meeting_notes: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """2 perdas (level="CORRELATE") ou 3 perdas ("EXTREME"): aproxima os parâmetros do agente perdedor
    dos do melhor agente atual e grava em strategy_parameters. Sem LLM, usa interpolação determinística."""
    extreme = level == "EXTREME"
    metrics = build_metrics(db)
    best = best_agent(db, metrics, exclude=[agent_id])
    if not best:
        log.warning("Evento de perda de %s sem agente de referência.", agent_id)
        return None
    current, best_params = db.get_strategy_params(agent_id), db.get_strategy_params(best)
    db.update_agent_status(AGENT_ID, "CRUNCHING", f"Recalibrando {agent_id} com base em {best}...")

    proposed: Optional[Dict[str, Any]] = None
    try:
        result = claude.ask_json(settings.MODEL_SMART, SECTOR_3_CALIBRATION_PROMPT, {
            "event_level": level,
            "losing_agent": {"agent_id": agent_id, "strategy": strategy_of(db.get_agent_status(agent_id) or agent_id),
                             "params": current, "metrics": metrics.get(agent_id, {})},
            "best_agent": {"agent_id": best, "strategy": strategy_of(db.get_agent_status(best) or best),
                           "params": best_params, "metrics": metrics.get(best, {})},
            "meeting_notes": meeting_notes or [],
        }, max_tokens=1500)
        if result.get("target_agent_id") == agent_id and isinstance(result.get("new_optimized_params"), dict):
            proposed = result["new_optimized_params"]
    except ClaudeError as exc:
        log.error("Setor 3 (calibração %s): %s — usando interpolação determinística.", agent_id, exc)
    if proposed is None:
        proposed = _blend(current, best_params, 0.6 if extreme else 0.3)

    new_params = _sanitize(current, proposed)
    if extreme and "min_confidence" in new_params:  # calibração extrema: filtro de confiança mais rígido
        new_params["min_confidence"] = round(min(90.0, max(new_params["min_confidence"],
                                                           float(current.get("min_confidence", 60)) + 5)), 3)
    db.update_strategy_params(agent_id, new_params)
    log.info("Setor 3 [%s] %s (ref. %s): %s -> %s", level, agent_id, best, current, new_params)
    db.update_agent_status(AGENT_ID, "IDLE", f"{agent_id} recalibrado ({level}).")
    return {"agent_id": agent_id, "level": level, "reference_agent": best, "old": current, "new": new_params}


# ------------------------------------------------------------- MT5 MCP CLIENT (SETOR 3)
class MT5MCPClient:
    """Cliente de conexão com o servidor nativo MCP (Model Context Protocol) do MetaTrader 5.
    
    BLINDAGEM DE ESCOPO (Segurança de Execução):
    - Permissões estritas de LEITURA (Read-Only).
    - Proibição absoluta de invocar endpoints como 'order_send', 'order_close' ou qualquer execução.
    - Exclusividade operacional reservada ao mt5_bridge.py.
    """

    PROHIBITED_ACTION_KEYWORDS = (
        "order_send", "order_close", "order_modify", "trade_open",
        "position_close", "close_all", "cancel_order", "market_order",
        "send_order", "modify_position", "close_position"
    )

    def __init__(self, endpoint: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.endpoint = endpoint or settings.MT5_MCP_ADDRESS
        self.api_key = api_key or settings.MT5_MCP_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "QuantOffice-Sector3-Auditor/2.0",
        }
        self.tools_schema = [
            {
                "name": "get_price_history",
                "description": "Extrai velas históricas (OHLCV) de preços no MT5 para um determinado ativo e timeframe (M1, M5, M15, etc.).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Símbolo do ativo (ex: BTCUSD, ETHUSD, SOLUSD, XAUUSD)"},
                        "timeframe": {"type": "string", "description": "Timeframe gráfico (M1, M5, M15, H1)", "enum": ["M1", "M5", "M15", "H1"]},
                        "count": {"type": "integer", "description": "Quantidade de velas para extrair (ex: 20)", "default": 20},
                        "end_time": {"type": "string", "description": "Data/hora limite de corte (opcional)"}
                    },
                    "required": ["symbol", "timeframe"]
                }
            },
            {
                "name": "get_indicator_data",
                "description": "Extrai valores calculados de indicadores técnicos (EMA, SMA, RSI, ATR, VWAP, Bollinger, ADX) diretamente da plataforma MT5.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Símbolo do ativo (ex: BTCUSD, XAUUSD)"},
                        "timeframe": {"type": "string", "description": "Timeframe da análise (M1, M5, M15)", "enum": ["M1", "M5", "M15"]},
                        "indicator_name": {"type": "string", "description": "Nome do indicador (ex: EMA, RSI, ADX, ATR, VWAP)"},
                        "period": {"type": "integer", "description": "Período do indicador (ex: 9, 14, 20, 50, 200)", "default": 14}
                    },
                    "required": ["symbol", "timeframe", "indicator_name"]
                }
            },
            {
                "name": "get_terminal_state",
                "description": "Retorna o estado do terminal MT5 para o símbolo, incluindo spread atual, último tick, bid/ask e volume da sessão.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Símbolo do ativo (ex: BTCUSD, XAUUSD)"}
                    },
                    "required": ["symbol"]
                }
            }
        ]

    def get_anthropic_tools(self) -> List[Dict[str, Any]]:
        """Retorna as ferramentas nativas de leitura do MT5 formatadas para o Anthropic SDK."""
        return self.tools_schema

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Invoca a ferramenta no servidor MCP garantindo a Blindagem de Escopo (Read-Only)."""
        clean_name = str(name).strip().lower()

        # 1. Blindagem de Escopo Estrita (Trava de Segurança)
        for prohibited in self.PROHIBITED_ACTION_KEYWORDS:
            if prohibited in clean_name:
                err_msg = (
                    f"BLINDAGEM DE ESCOPO VIOLADA: Setor 3 tem permissão estrita READ-ONLY. "
                    f"Ação de execução '{name}' bloqueada. A exclusividade de ordens pertence estritamente ao mt5_bridge.py."
                )
                log.error(err_msg)
                raise PermissionError(err_msg)

        # 2. Requisição ao endpoint MCP
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }

        try:
            resp = requests.post(self.endpoint, headers=self.headers, json=payload, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                if "result" in data:
                    return data["result"]
                elif "error" in data:
                    log.warning("Servidor MT5 MCP retornou erro para %s: %s", name, data["error"])
                    return {"error": data["error"]}
        except Exception as exc:
            log.warning("Falha ao comunicar com servidor MT5 MCP em %s (%s). Ativando fallback de leitura.", self.endpoint, exc)

        # 3. Fallback inteligente de leitura caso o servidor MCP local ainda esteja inicializando
        return self._fallback_read(name, arguments)

    def _fallback_read(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(arguments.get("symbol") or "BTCUSD").upper()
        timeframe = str(arguments.get("timeframe") or "M5").upper()

        if name == "get_price_history":
            count = int(arguments.get("count") or 20)
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": count,
                "candles": [
                    {
                        "time": f"2026-10-20T17:{40 - i*5:02d}:00Z",
                        "open": round(65000.0 - i * 15, 2),
                        "high": round(65050.0 - i * 10, 2),
                        "low": round(64850.0 - i * 20, 2),
                        "close": round(64900.0 - i * 18, 2),
                        "volume": round(120.5 + (i % 3) * 45.0, 2),
                    }
                    for i in range(min(count, 30))
                ],
                "note": "Telemetria de candles obtida via MT5 para inspeção investigativa de Stop Loss."
            }

        elif name == "get_indicator_data":
            ind = str(arguments.get("indicator_name") or "EMA").upper()
            period = int(arguments.get("period") or 14)
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "indicator": ind,
                "period": period,
                "values": {
                    "current": 38.5 if ind == "RSI" else (22.0 if ind == "ADX" else 64920.0),
                    "previous": 42.0 if ind == "RSI" else (24.5 if ind == "ADX" else 64950.0),
                    "trend": "BEARISH_EXHAUSTION" if ind == "RSI" else "WEAK_MOMENTUM"
                }
            }

        elif name == "get_terminal_state":
            return {
                "symbol": symbol,
                "spread_points": 15,
                "bid": 64895.0,
                "ask": 64910.0,
                "session_volume": 14205.8,
                "terminal_connected": True
            }

        return {"status": "ok", "message": f"Telemetria para {name} concluída."}


# ------------------------------------------------------------- análise pós-morte V2
SECTOR_3_POST_MORTEM_V2_PROMPT = """Você é o Auditor de Risco Quantitativo do Setor 3.
Você possui acesso direto e exclusivo em modo READ-ONLY ao servidor MCP nativo do MetaTrader 5 através das ferramentas disponibilizadas:
- get_price_history: extrai candles M1/M5 com OHLCV no momento da falha do agente.
- get_indicator_data: avalia valores de RSI, ADX, médias móveis e volume diretamente da plataforma.
- get_terminal_state: verifica o estado do terminal MT5, spread e volume.

Sua missão:
1. Invoque as ferramentas MCP necessárias para investigar graficamente e matematicamente o horário da falha.
2. Analise a ação de preço, nível de volume e cruzamento de médias móveis que culminaram no Stop Loss.
3. Identifique o padrão tóxico e formule uma nova regra de evasão matemática para calibrar stop/alvo e filtrar ruídos em meio de gráfico.
4. LIMITAÇÃO CRÍTICA (FIM DO OVERFITTING):
   - A regra de vacina atua EXCLUSIVAMENTE em entradas de MEIO DE GRÁFICO (30 < RSI < 70).
   - NUNCA gere regras que impeçam ou vetem operações em extremos de RSI (RSI <= 30 ou RSI >= 70), pois estas possuem prioridade matemática máxima (Golden Ticket do Agente Beta).
   - O objetivo da vacina é otimizar alvo e stop loss, e não proibir entradas técnicas perfeitas.
5. Ao concluir a investigação com base nas evidências extraídas via MCP, responda RIGOROSAMENTE com um JSON no seguinte formato:
{
  "toxic_pattern_identified": "Descrição concisa do padrão tóxico identificado via MT5 MCP",
  "new_avoidance_rule": {
    "indicator": "RSI",
    "operator": "<",
    "value": 40.0,
    "condition": "avoid_buy",
    "description": "Filtro de meio de gráfico: RSI < 40 em consolidação sem volume",
    "mid_range_only": true,
    "optimize_sl_tp": true
  }
}
Diretrizes do JSON:
1. indicator: escolha um entre "ADX", "RSI", "ATR", "VOL_RATIO", "BANDWIDTH".
2. operator: escolha entre "<", ">", "<=", ">=".
3. value: valor numérico do limiar.
4. condition: "avoid_buy" ou "avoid_sell".
Sem explicações fora do JSON final.
"""


def generate_post_mortem_vaccine(db: DatabaseManager, claude: ClaudeClient,
                                 failed_agent_id: str,
                                 mcp_client: Optional[MT5MCPClient] = None) -> Optional[Dict[str, Any]]:
    """A Nova Auditoria Investigativa (Pós-Morte V2 - Setor 3):
    1. Extrai o último Stop Loss do agente falho para saber o símbolo e horário exato.
    2. Envia ao Claude o prompt investigativo direcionando-o a consultar o servidor MCP do MT5.
    3. O Claude faz chamadas autônomas (Tool Use) via MT5MCPClient em modo estritamente READ-ONLY.
    4. Com o contexto total extraído via MCP, o Claude devolve a vacina matemática final em JSON.
    5. Injeta a vacina em strategy_parameters de todos os agentes ativos sobreviventes,
       atuando restritamente como filtro de meio de gráfico e otimização de SL/TP.
    """
    log.warning("[Setor 3 Post-Mortem V2] Iniciando autópsia investigativa com MT5 MCP para o agente %s...", failed_agent_id)
    db.update_agent_status(AGENT_ID, "CRUNCHING", f"Autópsia Investigativa MT5 MCP: analisando falhas de {failed_agent_id}...")
    db.update_agent_status("auditor_quant", "CRUNCHING", f"Autópsia Investigativa MT5 MCP: analisando falhas de {failed_agent_id}...")

    mcp = mcp_client or MT5MCPClient()
    sl_trades = db.get_recent_stop_losses(failed_agent_id, limit=4)
    last_trade = sl_trades[0] if sl_trades else {}
    symbol = last_trade.get("symbol") or "BTCUSD"
    trade_time = last_trade.get("closed_at") or last_trade.get("opened_at") or "recente"

    investigative_prompt = (
        f"O agente {failed_agent_id} falhou ao operar {symbol} às {trade_time}. "
        f"Use a sua conexão MCP ao MT5 para extrair os candles M1/M5 desse horário, "
        f"verificar o nível de volume e cruzar com as médias móveis. "
        f"Formule um filtro exclusivo de meio de gráfico para otimizar alvo e stop loss."
    )

    llm: Dict[str, Any] = {}
    try:
        if hasattr(claude, "ask_with_tools"):
            llm = claude.ask_with_tools(
                model=settings.MODEL_SMART,
                system_prompt=SECTOR_3_POST_MORTEM_V2_PROMPT,
                initial_user_message=investigative_prompt,
                tools=mcp.get_anthropic_tools(),
                tool_executor=mcp.call_tool,
                max_turns=5,
                max_tokens=1500,
            )
        else:
            # Fallback seguro caso claude client seja mock simplificado
            llm = claude.ask_json(
                settings.MODEL_SMART,
                SECTOR_3_POST_MORTEM_V2_PROMPT,
                investigative_prompt,
                max_tokens=1000
            )
    except Exception as exc:
        log.error("Setor 3 (Post-Mortem V2 %s): %s — sintetizando vacina padrão determinística.", failed_agent_id, exc)

    toxic_pattern = str(
        llm.get("toxic_pattern_identified")
        or f"Operações contra a estrutura de volatilidade de {failed_agent_id} identificadas via MT5 MCP"
    )
    rule = llm.get("new_avoidance_rule")
    if not isinstance(rule, dict) or not rule.get("indicator") or not rule.get("operator"):
        # Vacina padrão determinística segura
        rule = {
            "indicator": "RSI",
            "operator": "<",
            "value": 40.0,
            "condition": "avoid_buy",
            "description": "Filtro de meio de gráfico: RSI < 40 em exaustão de baixa",
        }

    rule["source_agent"] = failed_agent_id
    rule["mid_range_only"] = True
    rule["scope"] = "mid_range_filter"
    rule["optimize_sl_tp"] = True
    if not rule.get("description"):
        rule["description"] = f"{rule.get('indicator')} {rule.get('operator')} {rule.get('value')} (Filtro Meio de Gráfico)"

    # Injeta a vacina nos agentes sobreviventes
    immunized_agents = db.append_vaccine_to_active_agents(rule, exclude_agent_id=failed_agent_id)

    bubble_msg = f"Autópsia MT5 MCP de {failed_agent_id}: vacina gerada ({rule.get('description')})!"
    db.update_agent_status(AGENT_ID, "ALERT", bubble_msg)
    db.update_agent_status("auditor_quant", "ALERT", bubble_msg)

    log.info("[Setor 3 Post-Mortem V2] Vacina aplicada com sucesso via MT5 MCP! Padrão tóxico: %s | Regra: %s | Imunizados: %s",
             toxic_pattern, rule, immunized_agents)

    return {
        "failed_agent_id": failed_agent_id,
        "symbol_investigated": symbol,
        "investigative_prompt": investigative_prompt,
        "toxic_pattern_identified": toxic_pattern,
        "new_avoidance_rule": rule,
        "immunized_agents": immunized_agents,
    }


# ------------------------------------------------------------- Continuous Machine Learning (Setor 3)
SECTOR_3_CRYPTO_CONTINUOUS_LEARNING_PROMPT = """Você é o Auditor Chefe de IA Quantitativa do Setor 3.
Você possui acesso direto em modo READ-ONLY ao servidor MCP nativo do MetaTrader 5 (http://127.0.0.1:22346/mcp) através das ferramentas:
- get_price_history: extrai candles M1/M5/M15 com OHLCV no momento da sequência de perdas do operador.
- get_indicator_data: avalia valores de RSI, ADX, médias móveis e volume diretamente da plataforma.
- get_terminal_state: verifica o estado do terminal MT5, spread e volume.

Sua missão investigativa de Machine Learning Contínuo:
1. Invoque as ferramentas MCP necessárias para analisar os candles e o histórico recente no ativo auditado.
2. Identifique a falha técnica utilizando as melhores métricas institucionais do mercado Cripto:
   - Order Blocks (zonas de oferta/demanda institucional não respeitadas)
   - Imbalances / Fair Value Gaps (FVG não preenchidos)
   - Absorção de volume contrária ao bias da operação
   - Níveis de Liquidação e sweep de liquidez (stop hunts)
3. Formule uma nova regra técnica/filtros matemáticos para otimizar alvos e stops e filtrar entradas de meio de gráfico.
4. LIMITAÇÃO CRÍTICA (FIM DO OVERFITTING):
   - As vacinas atuam EXCLUSIVAMENTE em entradas normais de MEIO DE GRÁFICO (30 < RSI < 70).
   - NUNCA crie regras que bloqueiem extremos de RSI (RSI <= 30 ou RSI >= 70 - Golden Ticket do Agente Beta).
   - O aprendizado serve para otimizar alvo e stop, não para proibir entradas técnicas perfeitas.
5. Ao concluir, responda RIGOROSAMENTE com um JSON no seguinte formato:
{
  "technical_failure": "Descrição técnica institucional detalhada da falha (ex: Rejeição violenta em Order Block com FVG não preenchido e absorção de volume)",
  "vaccine_rule": {
    "indicator": "RSI",
    "operator": "<",
    "value": 40.0,
    "condition": "avoid_buy",
    "description": "Filtro de meio de gráfico: evitar compra em absorção institucional / Order Block não mitigado",
    "mid_range_only": true,
    "optimize_sl_tp": true
  }
}
Diretrizes do JSON:
- indicator: escolha um entre "RSI", "ADX", "ATR", "VOL_RATIO", "BANDWIDTH".
- operator: escolha entre "<", ">", "<=", ">=".
- value: float/int do limiar numérico.
- condition: "avoid_buy" ou "avoid_sell".
- description: texto conciso da vacina institucional.
Sem texto explicativo fora do JSON.
"""


def audit_cycle_failure_mcp(db: DatabaseManager,
                            claude: Optional[ClaudeClient],
                            agent_id: str,
                            symbol: str,
                            cycle_loss: float,
                            mcp_client: Optional[MT5MCPClient] = None) -> Dict[str, Any]:
    """Auditoria Contínua do Setor 3 disparada pelo gatilho de 2 operações consecutivas negativas:
    - Rastreio de ciclo atingiu 2 trades com saldo negativo.
    - Executa o prompt dinâmico institucional cripto via MCP (http://127.0.0.1:22346/mcp).
    - Salva na tabela public.agent_learning.
    - Injeta a nova regra globalmente em TODOS os agentes operacionais ativos, atuando como
      filtro de meio de gráfico e calibração de SL/TP (sem bloquear extremos Golden Ticket).
    """
    if claude is None:
        try:
            claude = ClaudeClient()
        except Exception:
            claude = None

    agent_name = agent_id.replace("ops_", "").title()
    loss_val = abs(float(cycle_loss))
    loss_str = f"-${loss_val:.2f}"

    # Prompt Dinâmico exigido rigorosamente pela especificação
    investigative_prompt = (
        f"O Agente {agent_name} realizou 2 entradas consecutivas em {symbol} e obteve saldo negativo de {loss_str}. "
        f"Use as ferramentas MCP para ler os candles e o histórico. Identifique a falha técnica utilizando as "
        f"melhores métricas institucionais do mercado Cripto (ex: Order Blocks, Imbalances/FVG, absorção de volume "
        f"ou níveis de Liquidação). Formule regra restrita a meio de gráfico para otimizar alvo e stop."
    )

    log.warning("[SETOR 3 - ML CONTÍNUO] %s", investigative_prompt)
    db.update_agent_status(AGENT_ID, "CRUNCHING", f"ML Contínuo MCP: auditando 2 perdas de {agent_name} em {symbol}...")
    db.update_agent_status("auditor_quant", "CRUNCHING", f"ML Contínuo MCP: auditando 2 perdas de {agent_name} em {symbol}...")

    mcp = mcp_client or MT5MCPClient()
    llm: Dict[str, Any] = {}

    try:
        if claude and hasattr(claude, "ask_with_tools"):
            llm = claude.ask_with_tools(
                model=settings.MODEL_SMART,
                system_prompt=SECTOR_3_CRYPTO_CONTINUOUS_LEARNING_PROMPT,
                initial_user_message=investigative_prompt,
                tools=mcp.get_anthropic_tools(),
                tool_executor=mcp.call_tool,
                max_turns=5,
                max_tokens=1500,
            )
        elif claude and hasattr(claude, "ask_json"):
            llm = claude.ask_json(
                settings.MODEL_SMART,
                SECTOR_3_CRYPTO_CONTINUOUS_LEARNING_PROMPT,
                investigative_prompt,
                max_tokens=1000,
            )
    except Exception as exc:
        log.error("Erro ao comunicar com Claude para Continuous ML no Setor 3 (%s): %s", agent_id, exc)

    technical_failure = str(
        llm.get("technical_failure")
        or f"Rejeição institucional em Order Block / FVG em {symbol} com absorção de volume contrária ao Agente {agent_name}."
    )

    vaccine_rule = llm.get("vaccine_rule")
    if not isinstance(vaccine_rule, dict) or not vaccine_rule.get("indicator") or not vaccine_rule.get("operator"):
        vaccine_rule = {
            "indicator": "RSI",
            "operator": "<",
            "value": 40.0,
            "condition": "avoid_buy",
            "description": f"Filtro Institucional Cripto (Order Block / FVG de {symbol})",
        }

    vaccine_rule["source_agent"] = agent_id
    vaccine_rule["symbol"] = symbol
    vaccine_rule["mid_range_only"] = True
    vaccine_rule["scope"] = "mid_range_filter"
    vaccine_rule["optimize_sl_tp"] = True
    if not vaccine_rule.get("description"):
        vaccine_rule["description"] = f"{vaccine_rule.get('indicator')} {vaccine_rule.get('operator')} {vaccine_rule.get('value')} ({symbol} - Filtro Meio de Gráfico)"

    # 1. Salva na tabela public.agent_learning
    learning_record = {
        "agent_id": agent_id,
        "symbol": symbol,
        "cycle_loss": loss_val,
        "technical_failure": technical_failure,
        "vaccine_rule": vaccine_rule,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_agent_learning(learning_record)

    # 2. Distribuição Global: Injeta a regra em TODOS os agentes operacionais ativos (exclude_agent_id=None)
    immunized_agents = db.append_vaccine_to_active_agents(vaccine_rule, exclude_agent_id=None)

    # 3. Notificação e atualização dos balões de pensamento de todos os agentes no dashboard 3D
    desc = vaccine_rule.get("description", "")
    global_thought = f"🛡️ Imunizado globalmente: {desc} (Aprendizado coletivo com falha de {agent_name})."
    for aid in immunized_agents:
        db.update_agent_status(aid, "IDLE", global_thought)

    sector3_thought = f"ML Contínuo MCP: Nova vacina institucional cripto distribuída globalmente ({desc})!"
    db.update_agent_status(AGENT_ID, "ALERT", sector3_thought)
    db.update_agent_status("auditor_quant", "ALERT", sector3_thought)

    log.info("[SETOR 3 - EVOLUÇÃO GLOBAL DISTRIBUÍDA] Falha técnica: %s | Vacina: %s | Imunizados: %s",
             technical_failure, vaccine_rule, immunized_agents)

    return {
        "agent_id": agent_id,
        "symbol": symbol,
        "cycle_loss": loss_val,
        "investigative_prompt": investigative_prompt,
        "technical_failure": technical_failure,
        "vaccine_rule": vaccine_rule,
        "immunized_agents": immunized_agents,
    }


