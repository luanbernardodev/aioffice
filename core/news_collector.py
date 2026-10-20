"""Módulo híbrido de coleta de notícias e inteligência macroeconômica.

Combina a API da Finnhub (cripto e geral) com feeds RSS nativos (CoinTelegraph para cripto
e Investing.com para Ouro/Commodities) e o calendário econômico semanal do ForexFactory
para detecção de gatilhos de alto impacto do FED / USD.
"""
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import feedparser
import requests

from config import settings
from core.database import DatabaseManager

log = logging.getLogger("news_collector")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
}

DEFAULT_TIMEOUT = 10

# Cache em memória para o calendário do ForexFactory (evita 429 Rate Limiting)
_CALENDAR_CACHE: Dict[str, Any] = {"ts": 0.0, "events": []}
CALENDAR_CACHE_TTL_SEC = 1800  # 30 minutos


def _clean_html(raw_html: str) -> str:
    """Remove tags HTML e espaços duplicados de descrições e resumos."""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())


class NewsCollector:
    """Coletor híbrido de notícias (Finnhub API + RSS CoinTelegraph/Investing + Calendário ForexFactory)."""

    def __init__(self, db: Optional[DatabaseManager] = None, api_key: Optional[str] = None) -> None:
        self.db = db or DatabaseManager()
        self.api_key = api_key or settings.FINNHUB_API_KEY or os.getenv("FINNHUB_API_KEY", "")
        self.timeout = DEFAULT_TIMEOUT
        self.headers = BROWSER_HEADERS

    # ------------------------------------------------------------------ 1. Finnhub API
    def fetch_finnhub_news(self) -> List[Dict[str, Any]]:
        """Faz um GET na API da Finnhub para as categorias 'crypto' e 'general'.

        Filtra as 5 notícias mais recentes de cada categoria, extraindo headline e summary.
        """
        if not self.api_key or self.api_key == "insira_sua_chave_finnhub_aqui":
            log.warning(
                "FINNHUB_API_KEY ausente ou não configurada no .env. "
                "Cadastre sua chave gratuita em https://finnhub.io para ativar o feed Finnhub."
            )
            return []

        categories = ["crypto", "general"]
        collected: List[Dict[str, Any]] = []

        for category in categories:
            url = f"https://finnhub.io/api/v1/news?category={category}&token={self.api_key}"
            try:
                resp = requests.get(url, headers=self.headers, timeout=self.timeout)
                if resp.status_code == 401:
                    log.error("Finnhub API Key inválida (401 Unauthorized). Verifique o .env.")
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    log.warning("Finnhub [%s] retornou formato inesperado (não é lista).", category)
                    continue

                # Ordena pelas mais recentes (datetime decrescente) e seleciona as top 5
                sorted_items = sorted(data, key=lambda x: x.get("datetime", 0), reverse=True)[:5]
                for item in sorted_items:
                    headline = (item.get("headline") or "").strip()
                    summary = _clean_html(item.get("summary") or "")
                    if not headline:
                        continue
                    dt_ts = float(item.get("datetime") or time.time())
                    collected.append({
                        "source": f"Finnhub/{item.get('source') or category.capitalize()}",
                        "category": category,
                        "headline": headline,
                        "title": headline,  # compatibilidade com consumidores de notícias
                        "summary": summary[:300],
                        "url": item.get("url") or "",
                        "published_ts": dt_ts,
                        "published": datetime.fromtimestamp(dt_ts, timezone.utc).isoformat(),
                        "kind": "finnhub_api",
                    })
                log.info("Finnhub [%s]: %d notícias coletadas com sucesso.", category, len(sorted_items))
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao obter notícias Finnhub [%s]: %s", category, exc)

        return collected

    # ------------------------------------------------------------------ 2. RSS Cripto (CoinTelegraph)
    def fetch_crypto_rss(self) -> List[Dict[str, Any]]:
        """Lê o feed RSS https://cointelegraph.com/rss e extrai as 5 manchetes mais recentes."""
        url = os.getenv("COINTELEGRAPH_RSS", "https://cointelegraph.com/rss")
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            items: List[Dict[str, Any]] = []
            for entry in parsed.entries[:5]:
                headline = (entry.get("title") or "").strip()
                summary = _clean_html(entry.get("summary") or "")
                ts_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                ts = time.mktime(ts_struct) if ts_struct else time.time()
                items.append({
                    "source": "CoinTelegraph",
                    "category": "crypto",
                    "headline": headline,
                    "title": headline,
                    "summary": summary[:300],
                    "url": entry.get("link") or "",
                    "published_ts": ts,
                    "published": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                    "kind": "rss_crypto",
                })
            log.info("CoinTelegraph RSS: %d manchetes coletadas.", len(items))
            return items
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao ler feed RSS CoinTelegraph (%s): %s", url, exc)
            return []

    # ------------------------------------------------------------------ 3. RSS Ouro (Investing.com)
    def fetch_gold_rss(self) -> List[Dict[str, Any]]:
        """Lê o feed RSS https://br.investing.com/rss/news_11.rss (foco em Ouro e Commodities)."""
        url = os.getenv("INVESTING_GOLD_RSS", "https://br.investing.com/rss/news_11.rss")
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            items: List[Dict[str, Any]] = []
            for entry in parsed.entries[:5]:
                headline = (entry.get("title") or "").strip()
                summary = _clean_html(entry.get("summary") or "")
                ts_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                ts = time.mktime(ts_struct) if ts_struct else time.time()
                items.append({
                    "source": "Investing.com",
                    "category": "macro_gold",
                    "headline": headline,
                    "title": headline,
                    "summary": summary[:300],
                    "url": entry.get("link") or "",
                    "published_ts": ts,
                    "published": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                    "kind": "rss_gold",
                })
            log.info("Investing.com RSS (Ouro): %d manchetes coletadas.", len(items))
            return items
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao ler feed RSS Investing.com Ouro (%s): %s", url, exc)
            return []

    # ------------------------------------------------------------------ 4. Calendário ForexFactory
    def fetch_macro_calendar(self) -> List[Dict[str, Any]]:
        """Baixa o XML de https://nfs.faireconomy.media/ff_calendar_thisweek.xml.

        Filtra eventos do dia atual com <impact>High</impact> e <currency>USD</currency>
        (ou <country>USD</country>). Extrai <title> (ex: FOMC Statement) e <time>.
        """
        global _CALENDAR_CACHE
        now = time.time()
        # Se temos cache válido e recente, reaproveita para evitar 429
        if _CALENDAR_CACHE["events"] and (now - _CALENDAR_CACHE["ts"]) < CALENDAR_CACHE_TTL_SEC:
            log.debug("Usando eventos do calendário ForexFactory do cache em memória.")
            return list(_CALENDAR_CACHE["events"])

        url = os.getenv("FOREXFACTORY_CALENDAR", "https://nfs.faireconomy.media/ff_calendar_thisweek.xml")
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            # Datas de hoje nos fusos de NY e UTC
            try:
                today_ny = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d-%Y")
            except Exception:
                today_ny = datetime.now(timezone.utc).strftime("%m-%d-%Y")
            today_utc = datetime.now(timezone.utc).strftime("%m-%d-%Y")

            high_impact_usd_events: List[Dict[str, Any]] = []
            for ev in root.iter("event"):
                impact = (ev.findtext("impact") or "").strip()
                currency = (ev.findtext("currency") or ev.findtext("country") or "").strip().upper()
                date_str = (ev.findtext("date") or "").strip()

                # Verifica se é alto impacto e moeda USD
                if impact.lower() != "high" or currency != "USD":
                    continue

                # Filtra apenas eventos do dia atual
                if date_str and date_str not in (today_ny, today_utc):
                    continue

                title = (ev.findtext("title") or "").strip()
                event_time = (ev.findtext("time") or "").strip()
                if not title:
                    continue

                event_dict = {
                    "source": "ForexFactory Calendar",
                    "category": "macro_calendar",
                    "kind": "macro_event",
                    "headline": f"[FED/USD High Impact] {title} às {event_time}",
                    "title": title,
                    "time": event_time,
                    "date": date_str,
                    "currency": currency,
                    "impact": impact,
                    "forecast": (ev.findtext("forecast") or "").strip(),
                    "previous": (ev.findtext("previous") or "").strip(),
                    "url": (ev.findtext("url") or "").strip(),
                }
                high_impact_usd_events.append(event_dict)

            _CALENDAR_CACHE = {"ts": now, "events": high_impact_usd_events}
            log.info("Calendário ForexFactory: %d eventos de alto impacto USD identificados para hoje.",
                     len(high_impact_usd_events))
            return high_impact_usd_events
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao obter calendário ForexFactory (%s): %s", url, exc)
            if _CALENDAR_CACHE["events"]:
                log.info("Utilizando %d eventos do calendário em fallback (cache anterior).",
                         len(_CALENDAR_CACHE["events"]))
                return list(_CALENDAR_CACHE["events"])
            return []

    # ------------------------------------------------------------------ 5. Orquestrador
    def get_global_market_context(self) -> Dict[str, Any]:
        """Orquestra todas as fontes acima (com try/except individual para resiliência).

        Reúne notícias em um contexto enxuto e atualiza a tabela `market_context` no Supabase.
        """
        log.info("Iniciando coleta híbrida de notícias e contexto de mercado...")

        # 1. Finnhub
        finnhub_news: List[Dict[str, Any]] = []
        try:
            finnhub_news = self.fetch_finnhub_news()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado em fetch_finnhub_news: %s", exc)

        # 2. Crypto RSS
        crypto_rss: List[Dict[str, Any]] = []
        try:
            crypto_rss = self.fetch_crypto_rss()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado em fetch_crypto_rss: %s", exc)

        # 3. Gold RSS
        gold_rss: List[Dict[str, Any]] = []
        try:
            gold_rss = self.fetch_gold_rss()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado em fetch_gold_rss: %s", exc)

        # 4. Macro Calendar (Gatilho do FED)
        macro_calendar: List[Dict[str, Any]] = []
        try:
            macro_calendar = self.fetch_macro_calendar()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado em fetch_macro_calendar: %s", exc)

        # Consolidação de todas as notícias
        all_headlines = finnhub_news + crypto_rss + gold_rss

        # Montagem do resumo macro preliminar e motor de mercado
        cal_summary_parts = [f"{ev['title']} ({ev['time']})" for ev in macro_calendar]
        calendar_str = "; ".join(cal_summary_parts) if cal_summary_parts else "Nenhum evento USD High Impact hoje"

        key_driver = (
            f"Fontes: {len(finnhub_news)} Finnhub, {len(crypto_rss)} CoinTelegraph, "
            f"{len(gold_rss)} Investing. Radar USD: {calendar_str}"
        )
        if len(key_driver) > 240:
            key_driver = key_driver[:237] + "..."

        # Mantém ou atualiza o contexto na tabela market_context do Supabase
        try:
            latest = self.db.get_latest_market_context() or {}
            crypto_sent = latest.get("crypto_sentiment", 0)
            gold_sent = latest.get("gold_sentiment", 0)
            red_flag = latest.get("red_flag_pause_trading", False)
            self.db.save_market_context(
                crypto_sentiment=crypto_sent,
                gold_sentiment=gold_sent,
                red_flag=red_flag,
                key_driver=key_driver,
                headlines=all_headlines,
            )
            log.info("Tabela market_context atualizada no Supabase.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao salvar market_context no Supabase: %s", exc)

        context_payload: Dict[str, Any] = {
            "headlines": all_headlines,
            "finnhub_news": finnhub_news,
            "crypto_rss": crypto_rss,
            "gold_rss": gold_rss,
            "macro_calendar": macro_calendar,
            "calendar_summary": calendar_str,
            "key_driver": key_driver,
            "has_high_impact_usd_today": len(macro_calendar) > 0,
            "total_items": len(all_headlines),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return context_payload


# ---------------------------------------------------------------------- Compatibilidade
def fetch_latest_headlines(limit: int = 10, window_hours: Optional[float] = None) -> List[Dict[str, Any]]:
    """Função legada de conveniência que instancia o NewsCollector e retorna os top itens."""
    collector = NewsCollector()
    ctx = collector.get_global_market_context()
    return ctx.get("headlines", [])[:limit]
