"""Setor 6 — Sala de Reunião: crise simulada em chamada única e aplicação das ações de emergência."""
import logging
from typing import Any, Dict, Optional

from agents.claude_client import ClaudeClient, ClaudeError
from config import settings
from config.prompts import SECTOR_6_BOARDROOM_PROMPT
from core.database import DatabaseManager

log = logging.getLogger("sector6")
AGENT_ID = "boardroom"


def _apply_action(db: DatabaseManager, act: Dict[str, Any]) -> bool:
    action = str(act.get("action", "")).upper()
    agent_id = act.get("agent_id")
    reason = str(act.get("reason", "Decisão da diretoria"))[:200]
    if action == "PAUSE_ALL_TRADING":
        ctx = db.get_latest_market_context() or {}
        db.save_market_context(ctx.get("crypto_sentiment", 0), ctx.get("gold_sentiment", 0),
                               True, f"Boardroom: {reason}", ctx.get("headlines"))
        return True
    if agent_id not in db.get_ops_agent_ids():  # exclui demitidos
        return False
    if action == "QUARANTINE_AGENT":
        db.update_agent_status(agent_id, "QUARANTINED", reason, 0.0)
    elif action == "REDUCE_WEIGHT":
        db.update_agent_status(agent_id, "IDLE", reason, 0.5)
    elif action == "RESTORE_AGENT":
        db.update_agent_status(agent_id, "IDLE", reason, 0.5, extra={"quarantine_until": None})
    else:
        return False
    return True


def run(db: DatabaseManager, claude: ClaudeClient, trigger_reason: str,
        metrics: Dict[str, Any], analytics_report: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    db.update_agent_status(AGENT_ID, "MEETING", "Reunião de crise convocada!")
    for row in db.get_all_agents_status():
        if row["agent_id"] != AGENT_ID and row.get("current_state") not in ("QUARANTINED", "FIRED", "IN_MEETING"):
            db.update_agent_status(row["agent_id"], "MEETING", "Correndo pra sala de reunião!")
    try:
        status = {a["agent_id"]: {"state": a.get("current_state"), "weight": a.get("allocation_weight")}
                  for a in db.get_ops_agents()}
        context = db.get_latest_market_context() or {}
        result = claude.ask_json(settings.MODEL_SMART, SECTOR_6_BOARDROOM_PROMPT, {
            "trigger_reason": trigger_reason, "metrics_by_agent": metrics, "current_status": status,
            "analytics_report": {k: v for k, v in (analytics_report or {}).items() if k != "metrics"},
            "macro_context": {k: context.get(k) for k in
                              ("crypto_sentiment", "gold_sentiment", "red_flag_pause_trading", "key_driver")},
        }, max_tokens=2000)
    except ClaudeError as exc:
        log.error("Setor 6: %s", exc)
        result = None
    # Encerra a reunião: devolve os participantes ao estado IDLE (IN_MEETING/QUARANTINED/FIRED são preservados)
    for row in db.get_all_agents_status():
        if row.get("current_state") == "MEETING":
            db.update_agent_status(row["agent_id"], "IDLE", "De volta à mesa.")
    if result is None:
        db.update_agent_status(AGENT_ID, "IDLE", "Reunião cancelada: sem conexão.")
        return None

    applied = [a for a in (result.get("emergency_actions") or [])
               if isinstance(a, dict) and _apply_action(db, a)]
    result["applied_actions"] = applied
    db.update_agent_status(AGENT_ID, "IDLE", str(result.get("office_bubble_thought", "Reunião encerrada.")))
    log.info("Boardroom: %d ação(ões) aplicada(s)", len(applied))
    return result
