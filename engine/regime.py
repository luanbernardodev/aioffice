"""A1 REGIME — veto global.

bias (LONG/SHORT/NEUTRO) vem de features.build_features (MA100 H1 + inclinação + estrutura M15).
Aqui ficam os bloqueios: spread > k x ATR(M5), janela de notícias e sessão.
"""
from __future__ import annotations

import csv
import logging
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
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

    FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

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

    def refresh_from_forexfactory(self, timeout: float = 10.0) -> int:
        import requests  # import local: fora do caminho crítico
        resp = requests.get(self.FF_URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        n = 0
        with self._lock:
            known = {(w, t) for w, t in self._events}
        for ev in resp.json():
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

    def start_background_refresh(self, every_hours: float = 6.0) -> threading.Thread:
        def _loop():
            while True:
                try:
                    n = self.refresh_from_forexfactory()
                    log.info("[A1] Calendário atualizado (+%d eventos de alto impacto)", n)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[A1] Falha ao atualizar calendário: %s", exc)
                _time.sleep(every_hours * 3600)
        t = threading.Thread(target=_loop, name="NewsCalendar", daemon=True)
        t.start()
        return t

    def blocking_event(self, ts_utc: datetime) -> Optional[str]:
        with self._lock:
            for when, title in self._events:
                if abs(when - ts_utc) <= self.window:
                    return f"{title} @ {when:%Y-%m-%d %H:%M}Z"
        return None


def check_gates(ts_utc: datetime, scfg: Dict[str, Any], spread: float, atr_m5: float,
                calendar: Optional[NewsCalendar] = None) -> GateResult:
    """Bloqueios do A1 para NOVAS entradas (posições abertas continuam geridas pelo A5)."""
    if not in_session(ts_utc, scfg.get("sessions") or []):
        return GateResult(False, "fora de sessão")
    if atr_m5 is None or not atr_m5 > 0:
        return GateResult(False, "ATR indisponível")
    lim = float(scfg.get("max_spread_atr", 0.15))
    if spread > lim * atr_m5:
        return GateResult(False, f"spread {spread:.3f} > {lim}xATR ({lim * atr_m5:.3f})")
    if calendar is not None:
        ev = calendar.blocking_event(ts_utc)
        if ev:
            return GateResult(False, f"janela de notícia: {ev}")
    return GateResult(True)
