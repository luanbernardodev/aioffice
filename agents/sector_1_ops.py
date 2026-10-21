"""Setor 1 — Operações: ops_alpha/beta/gamma (M15) e scalpers ops_delta/epsilon (M1/M5), além de clones.
Acordados só pelo Sentinela e só enviam ordens ao MT5 com o "OK macro" do Setor 3."""
import logging
from typing import Any, Dict, Optional

import pandas as pd

from agents.claude_client import ClaudeClient, ClaudeError
from config import settings
from config.prompts import OPS_PROMPTS, OPS_STYLES, SECTOR_1_OPS_PROMPT
from core.database import BLOCKED_STATES, DatabaseManager, parse_ts, strategy_of
from core.mt5_bridge import MT5Bridge

log = logging.getLogger("sector1")


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def run(trigger: Dict[str, Any], db: DatabaseManager, claude: ClaudeClient,
        bridge: MT5Bridge) -> Optional[Dict[str, Any]]:
    """Processa um gatilho do Sentinela para o agente indicado. Retorna dict com o resultado."""
    agent_id = trigger["agent_id"]
    symbol = trigger["symbol"]
    status = db.get_agent_status(agent_id) or {}
    if status.get("current_state") in BLOCKED_STATES:
        return None
    until = parse_ts(status.get("quarantine_until"))
    if until and until > pd.Timestamp.now(tz="UTC").to_pydatetime():
        return None
    weight = float(status.get("allocation_weight", 1.0))

    force_execute = bool(trigger.get("force_execute", False))

    context = db.get_latest_market_context() or {}
    if context.get("red_flag_pause_trading"):
        if force_execute:
            log.warning("[GOLDEN TICKET / BYPASS] Agente %s (force_execute=True) ignorou Red Flag de notícias do Setor 2!", agent_id)
        else:
            db.update_agent_status(agent_id, "IDLE", f"Red flag ativo: {symbol} fica de fora.")
            return {"agent_id": agent_id, "action": "HOLD", "reason": "red_flag"}
    if weight <= 0:
        return None
    # Gate macro: sem o OK (vigente) do Setor 3 nenhuma ordem chega ao MT5, exceto com Golden Ticket
    if not db.is_macro_ok(status):
        why = status.get("macro_reason") or "sem autorização macro vigente"
        if force_execute:
            log.warning("[GOLDEN TICKET / BYPASS] Agente %s (force_execute=True) ignorou Veto Macro do Setor 3 (%s)!", agent_id, why)
        else:
            db.update_agent_status(agent_id, "IDLE", f"Veto macro do Setor 3: {why}")
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "macro_veto"}

    strategy = trigger.get("strategy") or strategy_of(status or agent_id)
    params = db.get_strategy_params(agent_id)
    db.update_agent_status(agent_id, "THINKING", f"Analisando {symbol} ({trigger['trigger']})...")
    try:
        decision = claude.ask_json(settings.MODEL_FAST, OPS_PROMPTS.get(strategy, SECTOR_1_OPS_PROMPT), {
            "agent_id": agent_id, "strategy_style": OPS_STYLES.get(strategy, ""),
            "trigger": trigger,
            "macro_context": {
                "crypto_sentiment": context.get("crypto_sentiment", 0),
                "gold_sentiment": context.get("gold_sentiment", 0),
                "key_driver": context.get("key_driver", "sem dados"),
            },
            "current_params": params,
        }, max_tokens=1500)
    except ClaudeError as exc:
        log.error("%s: %s", agent_id, exc)
        db.update_agent_status(agent_id, "IDLE", "Cérebro offline, aguardando...")
        return None

    action = str(decision.get("action", "HOLD")).upper()
    confidence = _clamp(decision.get("confidence_score"), 0, 100, 0)
    thought = str(decision.get("office_bubble_thought", "Hmm..."))
    rationale = str(decision.get("technical_rationale", ""))
    min_conf = _clamp(params.get("min_confidence"), 0, 100, 60)

    if action not in ("BUY", "SELL") or confidence < min_conf:
        db.update_agent_status(agent_id, "IDLE", thought)
        return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "confidence": confidence}

    sl_mult = _clamp(decision.get("sl_atr_multiplier"), 0.5, 5, params.get("sl_atr_multiplier", 1.5))
    tp_mult = _clamp(decision.get("tp_atr_multiplier"), 0.5, 10, params.get("tp_atr_multiplier", 3.0))
    tp_mult = max(tp_mult, sl_mult * 1.2)  # garante assimetria mínima favorável

    db.update_agent_status(agent_id, "EXECUTING", thought)
    try:
        entry = bridge.get_price(symbol, action)
        atr_value = float(trigger["atr"])
        sign = 1 if action == "BUY" else -1
        sl = entry - sign * sl_mult * atr_value
        tp = entry + sign * tp_mult * atr_value
        sizing = bridge.calculate_lot(symbol, entry, sl, weight)
        if sizing["volume"] <= 0:
            db.update_agent_status(agent_id, "IDLE", "Lote mínimo excede meu risco. Passo.")
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "lot_too_small"}
        order = bridge.execute_order(symbol, action, sizing["volume"], sl, tp, comment=agent_id)
        if not order.get("success"):
            db.update_agent_status(agent_id, "IDLE", "Ordem rejeitada pela corretora.")
            log.error("Ordem rejeitada: %s", order)
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "order_rejected"}
        db.log_trade(agent_id, symbol, action, sizing["volume"], order.get("price", entry), sl, tp,
                     sizing["risk_amount"], confidence, rationale, order.get("ticket"),
                     dry_run=bool(order.get("mock")))
        db.update_agent_status(agent_id, "IDLE", thought)
        log.info("%s %s %s vol=%s conf=%s", agent_id, action, symbol, sizing["volume"], confidence)
        return {"agent_id": agent_id, "symbol": symbol, "action": action, "confidence": confidence,
                "volume": sizing["volume"], "sl": sl, "tp": tp}
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha ao executar %s: %s", agent_id, exc)
        db.update_agent_status(agent_id, "IDLE", "Algo deu errado na execução.")
        return None


def settle_open_trades(db: DatabaseManager, bridge: MT5Bridge) -> int:
    """Resolve trades abertos checando se candles posteriores tocaram SL ou TP (apenas modo simulação/mock).
    Em modo REAL com MT5 conectado, as ordens são acompanhadas pelo próprio terminal MT5 e liquidadas
    no Supabase via sync_account_and_positions() -> history_deals_get, sem fechamentos artificiais.
    """
    if bridge.connected and not bridge.mock:
        return 0

    closed = 0
    agents = {r["agent_id"]: r for r in db.get_ops_agents(include_fired=True)}
    for trade in db.get_open_trades():
        try:
            opened = pd.Timestamp(trade["opened_at"])
            opened = opened.tz_localize("UTC") if opened.tzinfo is None else opened.tz_convert("UTC")
            strategy = strategy_of(agents.get(trade.get("agent_id"), trade.get("agent_id") or ""))
            tf = settings.STRATEGY_SETTLE_TIMEFRAMES.get(strategy, settings.TIMEFRAME)
            df = bridge.get_rates(trade["symbol"], tf, 1000 if tf == "M1" else 500)
            df = df[df["time"] >= opened]
            is_buy = trade["action"] == "BUY"
            sl, tp, entry = float(trade["sl"]), float(trade["tp"]), float(trade["entry_price"])
            risk = float(trade.get("risk_amount") or 0)
            sl_dist = abs(entry - sl) or 1.0
            reward = risk * abs(tp - entry) / sl_dist
            for _, bar in df.iterrows():
                hit_sl = bar["low"] <= sl if is_buy else bar["high"] >= sl
                hit_tp = bar["high"] >= tp if is_buy else bar["low"] <= tp
                if hit_sl:
                    db.close_trade(trade["id"], -risk, sl, "SL")
                    closed += 1
                    break
                if hit_tp:
                    db.close_trade(trade["id"], reward, tp, "TP")
                    closed += 1
                    # Saída da Quarentena por Mérito: se acertar TP, cancela quarentena e zera losses
                    aid = trade.get("agent_id")
                    if aid:
                        agent_stat = db.get_agent_status(aid) or {}
                        if agent_stat.get("current_state") == "QUARANTINED" or (agent_stat.get("consecutive_losses", 0) or 0) > 0:
                            log.info("[SAÍDA POR MÉRITO - SETTLE] Agente %s bateu TP no laboratório! Promovido de volta ao Risco Real.", aid)
                            db.update_agent_status(
                                aid,
                                "IDLE",
                                "Saída da Quarentena por Mérito! Take Profit atingido no laboratório. Retornando ao Risco Real!",
                                weight=1.0,
                                extra={"quarantine_until": None, "consecutive_losses": 0}
                            )
                    break
        except Exception as exc:  # noqa: BLE001
            log.error("Falha ao liquidar trade %s: %s", trade.get("id"), exc)
    return closed


def execute_autonomous_trigger(trigger: Dict[str, Any], db: DatabaseManager,
                               bridge: MT5Bridge) -> Optional[Dict[str, Any]]:
    """Motor Operacional Autônomo (Loop 1):
    Execução matemática PURA (zero chamadas à API Claude para máxima velocidade e economia de tokens).
    Agentes em QUARANTINED continuam calculando e gerando gatilhos operando em Shadow Trading (DEMO).
    Verifica red flags e consulta o SEMÁFORO DO SETOR 3 (macro_viable vigente).
    Se liberado, calcula lotes e dispara ordem no MT5 com roteamento dinâmico."""
    agent_id = trigger["agent_id"]
    symbol = trigger["symbol"]
    action = trigger.get("bias", "BUY")

    status = db.get_agent_status(agent_id) or {}
    # Apenas demitidos ou em reunião não disparam ordens
    if status.get("current_state") in ("IN_MEETING", "FIRED"):
        return None

    is_quarantined = (status.get("current_state") == "QUARANTINED")

    weight = float(status.get("allocation_weight", 1.0) or 1.0)
    if weight <= 0:
        weight = 1.0

    force_execute = bool(trigger.get("force_execute", False))

    context = db.get_latest_market_context() or {}
    if context.get("red_flag_pause_trading"):
        if force_execute:
            log.warning("[GOLDEN TICKET / BYPASS] Agente %s (force_execute=True) ignorou Red Flag de notícias do Setor 2!", agent_id)
        else:
            db.update_agent_status(agent_id, "IDLE", f"Red flag de notícias ativo: {symbol} em espera.")
            return {"agent_id": agent_id, "action": "HOLD", "reason": "red_flag"}

    # --- O FILTRO (SEMÁFORO DO SETOR 3) ---
    if not db.is_macro_ok(status):
        why = status.get("macro_reason") or "Sem autorização macro do Setor 3"
        if force_execute:
            log.warning("[GOLDEN TICKET / BYPASS] Agente %s (force_execute=True) ignorou Veto Macro do Setor 3 (%s)!", agent_id, why)
        else:
            db.update_agent_status(agent_id, "IDLE", f"Veto macro do Setor 3: {why}")
            log.warning("[SEMÁFORO SETOR 3 - VETO] Operador %s abortado para %s: %s", agent_id, symbol, why)
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "macro_veto"}

    params = db.get_strategy_params(agent_id)
    sl_mult = float(params.get("sl_atr_multiplier", 1.5))

    mode_label = " (Shadow Trading - DEMO)" if is_quarantined else ""
    gt_label = " [GOLDEN TICKET / BYPASS]" if force_execute else ""
    thought = f"Gatilho autônomo {trigger.get('trigger')} em {symbol}! Disparando ordem {action}{mode_label}{gt_label}..."
    db.update_agent_status(agent_id, "EXECUTING", thought)

    try:
        entry = bridge.get_price(symbol, action)
        atr_value = float(trigger.get("atr", 10.0))
        sign = 1 if action == "BUY" else -1
        sl = entry - sign * sl_mult * atr_value
        tp = 0.0  # Take Profit Nulo: Fechamento dinâmico baseado em RSI

        sizing = bridge.calculate_lot(symbol, entry, sl, weight)
        if sizing["volume"] <= 0:
            db.update_agent_status(agent_id, "IDLE", "Lote calculado é zero (risco excede limites).")
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "lot_too_small"}

        order = bridge.execute_order(symbol, action, sizing["volume"], sl=sl, tp=0.0,
                                     comment=agent_id, agent_id=agent_id, db=db)
        if not order.get("success"):
            db.update_agent_status(agent_id, "IDLE", f"Ordem recusada pela corretora: {order.get('retcode')}")
            log.error("[AUTONOMOUS] Ordem rejeitada: %s", order)
            return {"agent_id": agent_id, "symbol": symbol, "action": "HOLD", "reason": "order_rejected"}

        ticket = order.get("ticket")
        exec_acc = order.get("execution_account", "DEMO" if is_quarantined else "REAL")
        final_sl = float(order.get("sl") or sl)
        final_tp = float(order.get("tp") or 0.0)
        db.log_trade(
            agent_id, symbol, action, sizing["volume"], order.get("price", entry),
            final_sl, final_tp, sizing["risk_amount"], confidence=88,
            rationale=f"Gatilho Puro Python {trigger.get('trigger')} (M{trigger.get('timeframe')}) [{exec_acc}]{gt_label}",
            ticket=ticket, dry_run=bool(order.get("mock")), execution_account=exec_acc
        )
        badge = f"[{exec_acc}]"
        if exec_acc == "DEMO" and is_quarantined:
            badge = "[SHADOW TRADING - DEMO]"
        db.update_agent_status(agent_id, "EXECUTING", f"{badge} Posição aberta: {action} {sizing['volume']} {symbol} | Ticket #{ticket}")
        log.info("[AUTONOMOUS EXECUTION SUCCESS] %s %s %s vol=%s entry=%s sl=%s tp=%s ticket=%s [%s]",
                 agent_id, action, symbol, sizing["volume"], entry, sl, tp, ticket, exec_acc)
        return {
            "agent_id": agent_id, "symbol": symbol, "action": action,
            "volume": sizing["volume"], "sl": sl, "tp": tp, "ticket": ticket,
            "execution_account": exec_acc,
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha ao executar ordem autônoma para %s: %s", agent_id, exc)
        db.update_agent_status(agent_id, "IDLE", "Falha inesperada no motor de ordens.")
        return None
