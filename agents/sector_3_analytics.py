"""Setor 3 — Auditoria Quant: métricas dos agentes, filtro macro (Notícia -> Estratégia) e calibração por perdas."""
import logging
from typing import Any, Dict, List, Optional

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


# ------------------------------------------------------------- análise pós-morte
SECTOR_3_POST_MORTEM_PROMPT = """Você é o Auditor de Risco Quantitativo do Setor 3.
O Agente {failed_agent_id} acumulou perdas consecutivas críticas e entrou em falência/demissão.
Analise o histórico dos Stop Losses seguidos fornecidos.
Identifique o padrão tóxico (ex: comprando em resistência sem volume, operando pullback em tendência muito forte, operando contra ADX baixo, etc.).
Retorne RIGOROSAMENTE um JSON no seguinte formato:
{
  "toxic_pattern_identified": "Descrição concisa do padrão tóxico identificado",
  "new_avoidance_rule": {
    "indicator": "ADX",
    "operator": "<",
    "value": 20.0,
    "condition": "avoid_buy",
    "description": "ADX fraco em momentum"
  }
}
Diretrizes do JSON:
1. indicator: escolha um entre "ADX", "RSI", "ATR", "VOL_RATIO", "BANDWIDTH".
2. operator: escolha entre "<", ">", "<=", ">=".
3. value: valor numérico do limiar.
4. condition: "avoid_buy" ou "avoid_sell".
Sem explicações fora do JSON.
"""


def generate_post_mortem_vaccine(db: DatabaseManager, claude: ClaudeClient,
                                 failed_agent_id: str) -> Optional[Dict[str, Any]]:
    """Análise Pós-Morte (Setor 3):
    1. Extrai até 4 stop losses recentes do agente falho.
    2. Envia ao Claude (Auditor Quant) para identificar o padrão tóxico e sintetizar a vacina.
    3. Injeta a vacina em strategy_parameters de todos os agentes ativos.
    4. Notifica o Frontend via status do Supabase.
    """
    log.warning("[Setor 3 Post-Mortem] Iniciando autópsia de perdas para o agente %s...", failed_agent_id)
    db.update_agent_status(AGENT_ID, "CRUNCHING", f"Autópsia Quantitativa: analisando falhas de {failed_agent_id}...")
    db.update_agent_status("auditor_quant", "CRUNCHING", f"Autópsia Quantitativa: analisando falhas de {failed_agent_id}...")

    sl_trades = db.get_recent_stop_losses(failed_agent_id, limit=4)
    trades_summary = [
        {
            "ticket": t.get("id") or t.get("ticket_mt5"),
            "symbol": t.get("symbol"),
            "action": t.get("action") or t.get("order_type"),
            "entry_price": t.get("entry_price"),
            "close_price": t.get("close_price") or t.get("current_price"),
            "loss_usd": t.get("pnl") or t.get("profit_usd"),
            "opened_at": t.get("opened_at"),
            "closed_at": t.get("closed_at"),
            "technical_rationale": t.get("rationale") or t.get("technical_rationale"),
        }
        for t in sl_trades
    ]

    llm: Dict[str, Any] = {}
    try:
        sys_prompt = SECTOR_3_POST_MORTEM_PROMPT.replace("{failed_agent_id}", failed_agent_id)
        llm = claude.ask_json(settings.MODEL_SMART, sys_prompt, {
            "failed_agent_id": failed_agent_id,
            "strategy": strategy_of(db.get_agent_status(failed_agent_id) or failed_agent_id),
            "recent_stop_losses": trades_summary,
            "total_losses_analyzed": len(trades_summary),
        }, max_tokens=1000)
    except ClaudeError as exc:
        log.error("Setor 3 (Post-Mortem %s): %s — sintetizando vacina padrão determinística.", failed_agent_id, exc)

    toxic_pattern = str(llm.get("toxic_pattern_identified") or f"Operações contra a estrutura de volatilidade de {failed_agent_id}")
    rule = llm.get("new_avoidance_rule")
    if not isinstance(rule, dict) or not rule.get("indicator") or not rule.get("operator"):
        # Vacina padrão determinística segura
        rule = {
            "indicator": "ADX",
            "operator": "<",
            "value": 20.0,
            "condition": "avoid_buy",
            "description": "ADX fraco em momentum",
        }

    rule["source_agent"] = failed_agent_id
    if not rule.get("description"):
        rule["description"] = f"{rule.get('indicator')} {rule.get('operator')} {rule.get('value')}"

    # Injeta a vacina nos agentes sobreviventes
    immunized_agents = db.append_vaccine_to_active_agents(rule, exclude_agent_id=failed_agent_id)

    bubble_msg = f"Analisando falha do {failed_agent_id}... Vacina gerada: {rule.get('description')}!"
    db.update_agent_status(AGENT_ID, "ALERT", bubble_msg)
    db.update_agent_status("auditor_quant", "ALERT", bubble_msg)

    log.info("[Setor 3 Post-Mortem] Vacina aplicada com sucesso! Padrão tóxico: %s | Regra: %s | Imunizados: %s",
             toxic_pattern, rule, immunized_agents)

    return {
        "failed_agent_id": failed_agent_id,
        "toxic_pattern_identified": toxic_pattern,
        "new_avoidance_rule": rule,
        "immunized_agents": immunized_agents,
    }

