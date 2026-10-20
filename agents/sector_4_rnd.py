"""Setor 4 — P&D: recalibra strategy_parameters dos agentes com falhas diagnosticadas."""
import logging
from typing import Any, Dict, List

from agents.claude_client import ClaudeClient, ClaudeError
from config import settings
from config.prompts import SECTOR_4_RND_PROMPT
from core.database import DatabaseManager

log = logging.getLogger("sector4")
AGENT_ID = "rnd"

BOUNDS = {"sl_atr_multiplier": (0.5, 5.0), "tp_atr_multiplier": (0.5, 10.0), "min_confidence": (50.0, 90.0)}


def _sanitize(current: Dict[str, Any], proposed: Dict[str, Any]) -> Dict[str, Any]:
    """Mantém as chaves atuais, aplica limites e garante tp/sl >= 1.2."""
    merged = dict(current)
    for key, value in proposed.items():
        if key not in current:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        low, high = BOUNDS.get(key, (float("-inf"), float("inf")))
        merged[key] = round(max(low, min(high, value)), 3)
    if "sl_atr_multiplier" in merged and "tp_atr_multiplier" in merged:
        merged["tp_atr_multiplier"] = round(max(merged["tp_atr_multiplier"], merged["sl_atr_multiplier"] * 1.2), 3)
    return merged


def run(db: DatabaseManager, claude: ClaudeClient, analytics_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    diagnostics = analytics_report.get("agent_diagnostics") or []
    if not diagnostics:
        db.update_agent_status(AGENT_ID, "IDLE", "Sem falhas pra otimizar. Hoje é dia de paper.")
        return []
    applied: List[Dict[str, Any]] = []
    metrics = analytics_report.get("metrics", {})
    for diag in diagnostics:
        target = diag["agent_id"]
        current = db.get_strategy_params(target)
        db.update_agent_status(AGENT_ID, "RESEARCHING", f"Recalibrando {target}...")
        try:
            result = claude.ask_json(settings.MODEL_SMART, SECTOR_4_RND_PROMPT, {
                "diagnostic": diag, "current_params": current, "metrics": metrics.get(target, {}),
            }, max_tokens=2500)
        except ClaudeError as exc:
            log.error("Setor 4 (%s): %s", target, exc)
            continue
        proposed = result.get("new_optimized_params")
        if result.get("target_agent_id") != target or not isinstance(proposed, dict):
            log.warning("Resposta do P&D inválida para %s: %s", target, result)
            continue
        new_params = _sanitize(current, proposed)
        db.update_strategy_params(target, new_params)
        db.update_agent_status(target, (db.get_agent_status(target) or {}).get("current_state", "IDLE"),
                               f"Novos parâmetros do P&D: {result.get('hypothesis', '')[:120]}")
        db.update_agent_status(AGENT_ID, "RESEARCHING", str(result.get("office_bubble_thought", "Eureka!")))
        applied.append({"agent_id": target, "old": current, "new": new_params,
                        "hypothesis": result.get("hypothesis", "")})
        log.info("P&D recalibrou %s: %s -> %s", target, current, new_params)
    db.update_agent_status(AGENT_ID, "IDLE", f"{len(applied)} estratégia(s) recalibrada(s).")
    return applied
