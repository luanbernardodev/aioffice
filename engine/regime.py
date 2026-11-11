"""A1 REGIME — veto global.

bias (LONG/SHORT/NEUTRO) vem de features.build_features (MA100 H1 + inclinação + estrutura M15).
Aqui ficam os bloqueios: spread > k x ATR(M5), janela de notícias e sessão.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger("engine.regime")

LONG, SHORT, NEUTRAL = 1, -1, 0
BIAS_NAME = {LONG: "LONG", SHORT: "SHORT", NEUTRAL: "NEUTRO"}


@dataclass
class GateResult:
    ok: bool
    reason: str = ""


def in_session(ts_utc: datetime, sessions: List[Dict[str, str]]) -> bool:
    """sessions vazia = 24/7. Cada janela: {tz, start 'HH:MM', end 'HH:MM'} em horário local (seg-sex)."""
    if not sessions:
        return True
    for s in sessions:
        local = ts_utc.astimezone(ZoneInfo(s["tz"]))
        if local.weekday() >= 5:
            continue
        hm = local.hour * 60 + local.minute
        sh, sm = map(int, s["start"].split(":"))
        eh, em = map(int, s["end"].split(":"))
        if sh * 60 + sm <= hm < eh * 60 + em:
            return True
    return False


class NewsCalendar:
    """Eventos de alto impacto (USD): CPI/FOMC/NFP/PCE. Fontes: CSV local e/ou ForexFactory (thread de fundo)."""

    def __init__(self, keywords: Iterable[str], window_minutes: int = 30, csv_path: Optional[str] = None) -> None:
        self.keywords = [k.lower() for k in keywords]
        self.window = timedelta(minutes=window_minutes)
        self._events: List[Tuple[datetime, str]] = []
        self._lock = threading.Lock()
        if csv_path and Path(csv_path).exists():
            self.load_csv(csv_path)

    def matches(self, title: str) -> bool:
        t = title.lower()
        return any(k in t for k in self.keywords)

    def add_event(self, when_utc: datetime, title: str) -> None:
        with self._lock:
            self._events.append((when_utc.astimezone(timezone.utc), title))
            self._events.sort()

    def load_csv(self, path: str) -> None:
        """CSV com colunas: datetime_utc (ISO), title."""
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if self.matches(row["title"]):
                    when = pd.Timestamp(row["datetime_utc"])
                    when = when.tz_localize("UTC") if when.tzinfo is None else when.tz_convert("UTC")
                    self.add_event(when.to_pydatetime(), row["title"])

    def ingest(self, raw_events: List[Dict[str, Any]]) -> int:
        """Aplica o filtro deste calendário (USD, alto impacto, palavras-chave) aos eventos baixados."""
        n = 0
        with self._lock:
            known = {(w, t) for w, t in self._events}
        for ev in raw_events:
            if str(ev.get("country")).upper() != "USD" or str(ev.get("impact")).lower() != "high":
                continue
            title = str(ev.get("title", ""))
            if not self.matches(title):
                continue
            when = pd.Timestamp(ev["date"]).tz_convert("UTC").to_pydatetime()
            if (when, title) not in known:
                self.add_event(when, title)
                n += 1
        return n

    def start_background_refresh(self) -> None:
        """Inscreve este calendário no download único compartilhado."""
        _FEED.subscribe(self)

    def blocking_event(self, ts_utc: datetime) -> Optional[str]:
        with self._lock:
            for when, title in self._events:
                if abs(when - ts_utc) <= self.window:
                    return f"{title} @ {when:%Y-%m-%d %H:%M}Z"
        return None


class CalendarFeed:
    """Um único download do ForexFactory por processo, repassado a todos os calendários inscritos.

    - Cache de 6 h em memória e, opcionalmente, em disco (cache_path): um reinício do processo dentro
      das 6 h reaproveita o arquivo em vez de baixar de novo (cada download extra arrisca 429).
    - Falha -> nova tentativa em 5, 10, 20... até 60 min; em 429 respeita o Retry-After se for maior.
      Enquanto falha, o cache vencido (se houver) continua alimentando os calendários.
    """

    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    OK_SECONDS = 6 * 3600
    RETRY_SECONDS = 300
    MAX_RETRY_SECONDS = 3600

    def __init__(self, fetch: Optional[Callable[[], List[Dict[str, Any]]]] = None,
                 cache_path: Optional[Path] = None, clock: Callable[[], float] = _time.time) -> None:
        self._fetch = fetch or self._download
        self._subs: List["NewsCalendar"] = []
        self._raw: Optional[List[Dict[str, Any]]] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._failures = 0
        self.cache_path = Path(cache_path) if cache_path else None
        self._clock = clock

    def _download(self) -> List[Dict[str, Any]]:
        import requests  # import local: fora do caminho crítico
        resp = requests.get(self.URL, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------ cache em disco
    def _read_cache(self) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
        if not self.cache_path or not self.cache_path.exists():
            return None
        try:
            obj = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return float(obj["fetched_at"]), list(obj["events"])
        except Exception as exc:  # noqa: BLE001
            log.warning("[A1] Cache do calendário ilegível (%s); ignorado.", exc)
            return None

    def _write_cache(self, raw: List[Dict[str, Any]]) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": self._clock(), "events": raw}), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("[A1] Cache do calendário não gravado (%s).", exc)

    def _publish(self, raw: List[Dict[str, Any]]) -> List[int]:
        with self._lock:
            self._raw = raw
            subs = list(self._subs)
        return [c.ingest(raw) for c in subs]

    @staticmethod
    def _retry_after(exc: Exception) -> Tuple[bool, float]:
        """(é 429?, segundos do Retry-After ou 0)."""
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        is_429 = code == 429 or (code is None and "429" in str(exc))
        try:
            ra = float((getattr(resp, "headers", None) or {}).get("Retry-After", 0) or 0)
        except (TypeError, ValueError):
            ra = 0.0
        return is_429, ra

    def subscribe(self, calendar: "NewsCalendar") -> None:
        with self._lock:
            self._subs.append(calendar)
            raw = self._raw
            start = self._thread is None
            if start:
                self._thread = threading.Thread(target=self._loop, name="CalendarFeed", daemon=True)
        if raw is not None:                 # inscrito depois do download já recebe os eventos
            calendar.ingest(raw)
        if start:
            self._thread.start()

    def cycle(self) -> float:
        """Um ciclo (cache ou download). Retorna quantos segundos esperar até o próximo."""
        cached = self._read_cache()
        if cached is not None:
            age = self._clock() - cached[0]
            if 0 <= age < self.OK_SECONDS:
                added = self._publish(cached[1])
                log.info("[A1] Calendário do cache em disco (%.0f min): novos eventos por filtro=%s", age / 60, added)
                return self.OK_SECONDS - age
        try:
            raw = self._fetch()
        except Exception as exc:  # noqa: BLE001
            self._failures += 1
            wait = min(self.RETRY_SECONDS * 2 ** (self._failures - 1), self.MAX_RETRY_SECONDS)
            is_429, ra = self._retry_after(exc)
            if is_429 and ra > wait:
                wait = min(ra, self.MAX_RETRY_SECONDS * 6)
            if cached is not None and self._raw is None:
                self._publish(cached[1])    # melhor um calendário vencido do que nenhum
            log.warning("[A1] Falha ao atualizar calendário (%s%s). Nova tentativa em %d min.",
                        "429 " if is_429 else "", exc, wait // 60)
            return wait
        self._failures = 0
        self._write_cache(raw)
        added = self._publish(raw)
        log.info("[A1] Calendário atualizado: novos eventos por filtro=%s", added)
        return self.OK_SECONDS

    def _loop(self) -> None:
        time_to_wait = 2.0                  # deixa todos os componentes se inscreverem antes do 1º download
        while True:
            _time.sleep(time_to_wait)
            try:
                time_to_wait = self.cycle()
            except Exception as exc:  # noqa: BLE001  (a thread do calendário nunca pode morrer)
                log.exception("[A1] Erro inesperado no ciclo do calendário: %s", exc)
                time_to_wait = self.RETRY_SECONDS


_FEED = CalendarFeed(cache_path=Path(__file__).resolve().parent.parent / "state" / "ff_calendar_cache.json")


def spread_limit(scfg: Dict[str, Any], atr_m5: float, atr_h1: Optional[float] = None) -> Tuple[float, str]:
    """Limite de spread para novas entradas e a descrição da referência usada.

    Prioridade: max_spread (preço, fixo) > max_spread_atr_h1 x ATR(14) H1 > max_spread_atr x ATR(14) M5.
    """
    fixed = scfg.get("max_spread")
    if fixed is not None:
        return float(fixed), "fixo"
    k_h1 = scfg.get("max_spread_atr_h1")
    if k_h1 is not None and atr_h1 is not None and atr_h1 > 0:
        return float(k_h1) * float(atr_h1), f"{float(k_h1)}xATR_H1"
    k = float(scfg.get("max_spread_atr", 0.15))
    return k * atr_m5, f"{k}xATR"


def check_gates(ts_utc: datetime, scfg: Dict[str, Any], spread: float, atr_m5: float,
                calendar: Optional[NewsCalendar] = None, atr_h1: Optional[float] = None) -> GateResult:
    """Bloqueios do A1 para NOVAS entradas (posições abertas continuam geridas pelo A5)."""
    if not in_session(ts_utc, scfg.get("sessions") or []):
        return GateResult(False, "fora de sessão")
    if atr_m5 is None or not atr_m5 > 0:
        return GateResult(False, "ATR indisponível")
    lim, ref = spread_limit(scfg, atr_m5, atr_h1)
    if spread > lim:
        return GateResult(False, f"spread {spread:.3f} > {ref} ({lim:.3f})")
    if calendar is not None:
        ev = calendar.blocking_event(ts_utc)
        if ev:
            return GateResult(False, f"janela de notícia: {ev}")
    return GateResult(True)
