"""Setor 2 — Notícias: lê RSS e grava sentimento macro em market_context."""
import logging
from typing import Any, Dict, List, Optional

from agents.claude_client import ClaudeClient, ClaudeError
from config import settings
from config.prompts import SECTOR_2_NEWS_PROMPT
from core.database import DatabaseManager
from core.news_collector import NewsCollector, fetch_latest_headlines

log = logging.getLogger("sector2")
AGENT_ID = "news_desk"


def _clamp_int(value: Any) -> int:
    try:
        return int(max(-10, min(10, round(float(value)))))
    except (TypeError, ValueError):
        return 0


def run(db: DatabaseManager, claude: ClaudeClient,
        context_or_headlines: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Recebe o contexto do news_collector, resume o macro-sentimento e devolve o resumo para o Setor 3."""
    db.update_agent_status(AGENT_ID, "READING", "Folheando as manchetes e o radar macro...")
    try:
        headlines: List[Dict[str, Any]] = []
        macro_calendar: List[Dict[str, Any]] = []
        calendar_summary: str = ""

        if isinstance(context_or_headlines, dict):
            headlines = context_or_headlines.get("headlines") or []
            macro_calendar = context_or_headlines.get("macro_calendar") or []
            calendar_summary = context_or_headlines.get("calendar_summary") or ""
        elif isinstance(context_or_headlines, list):
            headlines = context_or_headlines
        elif context_or_headlines is None:
            collector = NewsCollector(db)
            ctx = collector.get_global_market_context()
            headlines = ctx.get("headlines") or []
            macro_calendar = ctx.get("macro_calendar") or []
            calendar_summary = ctx.get("calendar_summary") or ""

        if not headlines and not macro_calendar:
            db.update_agent_status(AGENT_ID, "IDLE", "Nenhuma notícia nova. Café time.")
            return None

        db.update_agent_status(AGENT_ID, "THINKING", f"Digerindo {len(headlines)} notícias e {len(macro_calendar)} eventos macro...")
        slim = [{k: h.get(k) for k in ("source", "category", "kind", "title", "headline", "summary", "published")}
                for h in headlines]
        
        prompt_input = {
            "headlines": slim,
            "macro_calendar": macro_calendar,
            "calendar_summary": calendar_summary,
        }
        result = claude.ask_json(settings.MODEL_FAST, SECTOR_2_NEWS_PROMPT,
                                 prompt_input, max_tokens=1500)
        crypto, gold = _clamp_int(result.get("crypto_sentiment")), _clamp_int(result.get("gold_sentiment"))
        red_flag = bool(result.get("red_flag_pause_trading", False))
        driver = str(result.get("key_driver", ""))
        db.save_market_context(crypto, gold, red_flag, driver, headlines)
        thought = str(result.get("office_bubble_thought", "Mercado digerido."))
        db.update_agent_status(AGENT_ID, "ALERT" if red_flag else "IDLE", thought)
        log.info("Notícias: cripto=%s ouro=%s redflag=%s | %s", crypto, gold, red_flag, driver)
        events = result.get("high_impact_events")
        return {"crypto_sentiment": crypto, "gold_sentiment": gold,
                "red_flag_pause_trading": red_flag, "key_driver": driver,
                "macro_summary": str(result.get("macro_summary") or driver),
                "high_impact_events": events if isinstance(events, list) else [],
                "macro_calendar": macro_calendar}
    except ClaudeError as exc:
        log.error("Setor 2: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Setor 2 falhou: %s", exc)
    db.update_agent_status(AGENT_ID, "IDLE", "Perdi o sinal do feed...")
    return None
