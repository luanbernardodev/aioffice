"""Setor 5 — Gerência de Risco.

1. `process_closed_trades`: máquina de estados de perdas consecutivas (avalia cada trade fechado uma única vez):
     Win -> zera o contador | Loss -> consecutive_losses += 1 e aplica a escada abaixo:
       1 loss  -> QUARANTINED por 1h (quarantine_until = agora + 1h)
       2 losses-> evento para o Setor 3 (correlaciona parâmetros com o melhor agente)
       3 losses-> IN_MEETING: reunião geral (Setor 6) + calibração extrema do Setor 3
       4 losses-> FIRED + clone mutado do agente com melhor Profit Factor (ex.: ops_beta_v2)
2. `run`: alocação diária de capital (allocation_weight) via Claude.
"""
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agents import sector_3_analytics, sector_6_boardroom
from agents.claude_client import ClaudeClient, ClaudeError
from agents.sector_4_rnd import _sanitize
from config import settings
from config.prompts import SECTOR_5_MANAGER_PROMPT
from core.database import DatabaseManager, parse_ts, strategy_of

log = logging.getLogger("sector5")
AGENT_ID = "manager"
VALID_WEIGHTS = (0.0, 0.5, 1.0, 1.5)


def _snap_weight(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(VALID_WEIGHTS, key=lambda w: abs(w - v))


def _quarantine_until() -> str:
    """Calcula timestamp UTC de 1 hora a partir de agora para o relógio de quarentena."""
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _risk_locked(row: dict) -> bool:
    """Agente sob controle da gerência de risco (quarentena vigente, reunião ou demissão)."""
    until = parse_ts(row.get("quarantine_until"))
    return (row.get("current_state") in ("IN_MEETING", "FIRED")
            or bool(until and until > datetime.now(timezone.utc)))


# ============================================================ máquina de estados
def process_closed_trades(db: DatabaseManager, claude: ClaudeClient) -> List[Dict[str, Any]]:
    """Avalia trades fechados ainda não processados e aplica a escada de risco. Retorna os eventos disparados.
    
    DIRETRIZES RÍGIDAS DE RISCO:
    1. A contagem de `consecutive_losses` DEVE IGNORAR completamente operações com status = 'OPEN'.
    2. Um agente só toma 1 Loss (e vai para QUARANTINED) se, e somente se, a operação for FECHADA
       (status = 'CLOSED') E o resultado final for negativo (profit_usd < 0 ou exit_reason == 'SL_HIT').
    3. Enquanto a ordem estiver rolando no MT5 (aberta), o agente continua com o status anterior
       operando normalmente na sua mesa, independentemente do rebaixamento flutuante (Drawdown aberto).
    """
    trades = db.get_unprocessed_closed_trades()
    if not trades:
        return []

    # Obtém tickets de ordens abertas no banco para dupla garantia
    open_tickets = {int(t.get("ticket_mt5") or t.get("id")) for t in db.get_open_trades() if t.get("ticket_mt5") or t.get("id")}

    ops_ids = set(db.get_ops_agent_ids())
    counters: Dict[str, int] = {}
    new_losses: set = set()

    for t in trades:
        ticket = int(t.get("ticket_mt5") or t.get("id") or 0)
        status = str(t.get("status") or "").upper()

        # REGRA 1: Ignora completamente operações abertas
        if status != "CLOSED" or ticket in open_tickets:
            log.debug("Trade #%s ignorado pela gerência de risco: operação ainda aberta (status=%s).", ticket, status)
            continue

        aid = t.get("agent_id")
        if not aid or aid not in ops_ids:
            db.mark_trade_processed(t["id"])
            continue

        profit_usd = float(t.get("profit_usd") if t.get("profit_usd") is not None else (t.get("pnl") or 0.0))
        exit_reason = str(t.get("exit_reason") or "").upper()

        # REGRA 2: Apenas operação FECHADA com prejuízo efetivo conta como perda
        is_loss = (profit_usd < 0.0) or (exit_reason == "SL_HIT")
        is_win = (profit_usd > 0.0) or (exit_reason == "TP_HIT")

        if aid not in counters:
            counters[aid] = int((db.get_agent_status(aid) or {}).get("consecutive_losses") or 0)

        if is_loss:
            counters[aid] += 1
            new_losses.add(aid)
            log.warning("Gerência de Risco: Trade #%s FECHADO com LOSS para %s (PnL: $%.2f | Motivo: %s). Perdas consecutivas: %d",
                        ticket, aid, profit_usd, exit_reason, counters[aid])
        elif is_win:
            counters[aid] = 0
            new_losses.discard(aid)
            agent_stat = db.get_agent_status(aid) or {}
            was_quarantined = (agent_stat.get("current_state") == "QUARANTINED" or bool(agent_stat.get("quarantine_until")))
            if was_quarantined:
                log.info("[SAÍDA POR MÉRITO - GESTÃO DE RISCO] Agente %s acertou TP no Shadow Trading! Quarentena cancelada e promovido a Risco Real.", aid)
                db.update_agent_status(
                    aid,
                    "IDLE",
                    "Saída da Quarentena por Mérito! Take Profit atingido no laboratório. Retornando ao Risco Real!",
                    weight=1.0,
                    extra={"quarantine_until": None, "consecutive_losses": 0}
                )
            else:
                db.set_agent_fields(aid, {"consecutive_losses": 0})
                log.info("Gerência de Risco: Trade #%s FECHADO com WIN para %s (PnL: $%.2f | Motivo: %s). Contador zerado.",
                         ticket, aid, profit_usd, exit_reason)

        db.mark_trade_processed(t["id"])  # após persistir o contador: nunca conta duas vezes

    events = []
    for aid in new_losses:
        n = counters[aid]
        log.warning("Gerência: %s com %d perda(s) consecutiva(s) confirmada(s) em trades fechados.", aid, n)
        events.append(_apply_loss_tier(db, claude, aid, n))
    return events


def _apply_loss_tier(db: DatabaseManager, claude: ClaudeClient, agent_id: str, losses: int) -> Dict[str, Any]:
    event: Dict[str, Any] = {"agent_id": agent_id, "consecutive_losses": losses}
    db.update_agent_status(AGENT_ID, "ALERT", f"{agent_id}: {losses} stop loss fechado(s)!")

    # 4 Losses Consecutivos: DEMISSÃO E CLONAGEM DO MELHOR OPERADOR
    if losses >= 4:
        event["action"] = "FIRE_AND_CLONE"
        event.update(fire_and_clone(db, claude, agent_id, losses))
        return event

    # Quarentena de 1 hora obrigatória para perdas consecutivas (1, 2 ou 3)
    q_time = _quarantine_until()

    if losses == 3:
        # 3 losses: reunião geral convocada + vacina pós-morte do Setor 3 + calibração extrema + quarentena
        event["action"] = "MEETING_EXTREME_CALIBRATION"
        db.update_agent_status(agent_id, "IN_MEETING", f"3 perdas consecutivas: reunião geral convocada!",
                               extra={"quarantine_until": q_time})
        
        # 1. Análise Pós-Morte do Setor 3: descobre o padrão tóxico e imuniza os agentes ativos
        event["vaccine"] = sector_3_analytics.generate_post_mortem_vaccine(db, claude, agent_id)

        metrics = sector_3_analytics.build_metrics(db)
        meeting = sector_6_boardroom.run(
            db, claude, f"Reunião geral: {agent_id} acumulou {losses} perdas consecutivas.", metrics, None)
        notes = (meeting or {}).get("meeting_minutes") or []
        event["calibration"] = sector_3_analytics.handle_loss_event(db, claude, agent_id, "EXTREME", notes)
        if (db.get_agent_status(agent_id) or {}).get("current_state") != "FIRED":
            db.update_agent_status(agent_id, "QUARANTINED", "Calibração extrema concluída. Quarentena de 1 hora.",
                                   extra={"quarantine_until": q_time})
    elif losses == 2:
        # 2 losses: recalibração Setor 3 + quarentena de 1 hora
        event["action"] = "CALIBRATE_VIA_SECTOR_3"
        event["calibration"] = sector_3_analytics.handle_loss_event(db, claude, agent_id, "CORRELATE")
        db.update_agent_status(agent_id, "QUARANTINED", "2 losses consecutivos: recalibrando parâmetros e 1h de quarentena.",
                               extra={"quarantine_until": q_time})
    else:
        # 1 loss: 1 hora de quarentena na Sala de Jogos / Lounge
        event["action"] = "QUARANTINE"
        db.update_agent_status(agent_id, "QUARANTINED", "1 stop loss fechado: 1 hora de quarentena no Lounge.",
                               extra={"quarantine_until": q_time})

    return event


def _mutate_params(winner_params: Dict[str, Any], llm_mutation: Any) -> Dict[str, Any]:
    """Leve mutação (±CLONE_MUTATION_PCT) dos parâmetros do vencedor; usa a sugestão do Claude se válida."""
    pct = settings.CLONE_MUTATION_PCT
    mutation = llm_mutation if isinstance(llm_mutation, dict) else {}
    proposed: Dict[str, Any] = {}
    for key, value in winner_params.items():
        if not isinstance(value, (int, float)):
            continue
        try:
            hint = float(mutation.get(key))
        except (TypeError, ValueError):
            hint = None
        if key == "min_confidence":
            delta = max(-3.0, min(3.0, hint)) if hint else random.uniform(-2.0, 2.0)
            proposed[key] = value + delta
        else:
            factor = max(1 - pct, min(1 + pct, hint)) if hint and abs(hint - 1) > 1e-6 \
                else random.uniform(1 - pct, 1 + pct)
            proposed[key] = value * factor
    return _sanitize(winner_params, proposed)


def fire_and_clone(db: DatabaseManager, claude: ClaudeClient, agent_id: str, losses: int) -> Dict[str, Any]:
    """4 losses: demite `agent_id`, identifica o operador com MAIOR Net PnL em trades_history e contrata clone."""
    # 1. Identificar o agente com MAIOR Lucro Líquido (Net PnL) em trades_history
    best = db.get_best_ops_by_net_pnl(exclude=[agent_id])
    metrics = sector_3_analytics.build_metrics(db)
    if not best:
        best = sector_3_analytics.best_agent(db, metrics, exclude=[agent_id])

    if not best:
        # Nunca demite o último operador se não houver referência
        log.error("Sem agente de referência para clonar; %s permanece em quarentena.", agent_id)
        db.update_agent_status(agent_id, "QUARANTINED", "4 perdas, mas não há operador para clonar.",
                               extra={"quarantine_until": _quarantine_until()})
        return {"fired": None, "reason": "no_clone_source"}

    log.info("Processo de demissão: %s atingiu %d losses. Agente campeão identificado para clonagem: %s",
             agent_id, losses, best)

    candidates = [{"agent_id": a, "strategy": strategy_of(db.get_agent_status(a) or a),
                   "params": db.get_strategy_params(a), "metrics": metrics.get(a, {})}
                  for a in db.get_ops_agent_ids() if a != agent_id]
    llm: Dict[str, Any] = {}
    try:
        llm = claude.ask_json(settings.MODEL_SMART, SECTOR_5_MANAGER_PROMPT, {
            "mode": "FIRE_AND_CLONE",
            "fire_candidate": {"agent_id": agent_id, "consecutive_losses": losses, "metrics": metrics.get(agent_id, {})},
            "candidates": candidates, "metrics_by_agent": metrics,
            "best_net_pnl_agent": best,
        }, max_tokens=1200)
    except ClaudeError as exc:
        log.error("Setor 5 (demissão): %s — decisão determinística aplicada com base no melhor Net PnL (%s).", exc, best)

    # 1) Análise Pós-Morte do Setor 3: sintetiza vacina matemática e imuniza os agentes ativos
    post_mortem = sector_3_analytics.generate_post_mortem_vaccine(db, claude, agent_id)

    # 2) Demissão do agente falho
    db.update_agent_status(agent_id, "FIRED", f"Demitido após 4 perdas consecutivas.", 0.0,
                           extra={"quarantine_until": None})

    # 2) Contratação (Clonagem) do campeão de Net PnL com novo ID
    best_row = db.get_agent_status(best) or {}
    base = re.sub(r"_v\d+$", "", agent_id)
    taken = {r["agent_id"] for r in db.get_ops_agents(include_fired=True)}
    version = 2
    while f"{base}_v{version}" in taken:
        version += 1
    new_id = f"{base}_v{version}"
    label = settings.AGENTS.get(base, (1, base))[1].split(" — ")[0]
    
    # Copia configurações do agente vencedor, com leve mutação e reset de lucros para zero
    winner_params = db.get_strategy_params(best)
    params = _mutate_params(winner_params, llm.get("clone_mutation")) if winner_params else {}
    
    # Cria o novo agente na tabela agents_status e strategy_parameters com saldo/lucro zerado
    db.create_agent(new_id, f"{label} v{version} — clone de {best}", strategy_of(best_row or best), params, best)
    
    # Herda a autorização macro vigente do agente clonado
    db.set_agent_fields(new_id, {
        "macro_viable": bool(best_row.get("macro_viable")),
        "macro_valid_until": best_row.get("macro_valid_until"),
        "macro_reason": best_row.get("macro_reason"),
        "consecutive_losses": 0,
        "current_state": "IDLE"
    })
    
    thought = str(llm.get("office_bubble_thought") or f"Operador {agent_id} demitido por 4 losses. Contratado {new_id} clonado de {best}!")
    db.update_agent_status(AGENT_ID, "ALERT", thought)
    log.warning("DEMISSÃO E CONTRATAÇÃO: %s demitido -> Novo agente %s (clonado de %s com maior Net PnL).", agent_id, new_id, best)
    return {"fired": agent_id, "cloned_from": best, "new_agent": new_id, "params": params,
            "reason": str(llm.get("reason", ""))}


# ============================================================ alocação diária
def run(db: DatabaseManager, claude: ClaudeClient, metrics: Dict[str, Dict[str, Any]],
        analytics_report: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    db.update_agent_status(AGENT_ID, "REVIEWING", "Revisando a alocação de capital...")
    ops = {r["agent_id"]: r for r in db.get_ops_agents()}
    status = {a: {"state": r.get("current_state"), "weight": r.get("allocation_weight")} for a, r in ops.items()}
    metrics = {a: m for a, m in metrics.items() if a in ops}
    try:
        result = claude.ask_json(settings.MODEL_SMART, SECTOR_5_MANAGER_PROMPT, {
            "mode": "ALLOCATION", "metrics_by_agent": metrics, "current_status": status,
            "analytics_health": (analytics_report or {}).get("overall_health", "UNKNOWN"),
        }, max_tokens=2500)
    except ClaudeError as exc:
        log.error("Setor 5: %s", exc)
        db.update_agent_status(AGENT_ID, "IDLE", "Sem acesso ao cofre. Mantenho tudo como está.")
        return None

    quarantined = 0
    for upd in result.get("agent_updates") or []:
        agent_id = upd.get("agent_id") if isinstance(upd, dict) else None
        if agent_id not in ops:
            continue
        if _risk_locked(ops[agent_id]):  # quarentena/reunião/demissão de risco não são sobrescritas
            continue
        weight = _snap_weight(upd.get("allocation_weight"))
        state = "QUARANTINED" if weight == 0.0 or upd.get("new_state") == "QUARANTINED" else "IDLE"
        if state == "QUARANTINED":
            weight, quarantined = 0.0, quarantined + 1
        upd["allocation_weight"], upd["new_state"] = weight, state
        db.update_agent_status(agent_id, state, str(upd.get("reason", ""))[:200], weight)
        log.info("Gerência: %s -> %s (peso %.1f)", agent_id, state, weight)

    result["trigger_boardroom"] = bool(result.get("trigger_boardroom", False)) or quarantined > 0
    db.update_agent_status(AGENT_ID, "ALERT" if result["trigger_boardroom"] else "IDLE",
                           str(result.get("office_bubble_thought", "Capital realocado.")))
    return result
