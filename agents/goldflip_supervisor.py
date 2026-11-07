"""6º agente — Supervisor do EA GoldFlipTrail (MQL5, magic 20261108).

O EA executa no terminal; este supervisor (Python, determinístico, sem LLM) decide SE e COMO ele opera:
  - a cada 5 min lê M1/M5 de GOLD, classifica o regime (tendência/lateral por ATR e MA100)
    e grava MQL5/Files/goldflip_control.json {enabled, trail_atr, min_atr, max_spread, ...};
  - desliga ±15 min de CPI/FOMC/NFP e fora das sessões Londres/NY;
  - lê goldflip_status.json escrito pelo EA (posição, PnL do dia, trades/hora, spread médio) para log;
  - o kill switch do A5 (AccountGuard: DD diário >= 3%, exposição GOLD de todos os magics)
    força enabled=false imediatamente e trava até o dia seguinte (UTC).

Fail-safe: o JSON carrega valid_until; se o Python parar, o EA trata o controle vencido como desligado.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from engine import indicators as ind
from engine.config import ROOT
from engine.features import server_to_utc
from engine.regime import NewsCalendar, in_session
from engine.risk import AccountGuard

log = logging.getLogger("agents.goldflip")

CONTROL_FILE = "goldflip_control.json"
STATUS_FILE = "goldflip_status.json"


# ----------------------------------------------------------------- funções puras (testáveis)
def classify_regime(m1: pd.DataFrame, m5: pd.DataFrame, rcfg: Dict[str, Any]) -> Dict[str, Any]:
    """TENDÊNCIA se, no M5, o preço está >= trend_dist_atr x ATR da MA100 com a MA100 inclinada
    >= trend_slope_atr x ATR na mesma direção, e o M1 confirma (fechamento do mesmo lado da MA100 M1).
    Caso contrário LATERAL. Dados insuficientes -> UNKNOWN."""
    n = int(rcfg.get("ma_period", 100))
    k = int(rcfg.get("slope_bars", 10))
    ap = int(rcfg.get("atr_period", 14))
    if m5 is None or m1 is None or len(m5) < n + k + 1 or len(m1) < n + 1:
        return {"regime": "unknown", "direction": 0, "atr_m5": float("nan")}
    ma5 = ind.sma(m5["close"], n)
    atr5 = ind.atr(m5, ap)
    ma1 = ind.sma(m1["close"], n)
    c5, m_now, m_prev, a5 = float(m5["close"].iat[-1]), float(ma5.iat[-1]), float(ma5.iat[-1 - k]), float(atr5.iat[-1])
    c1, m1_now = float(m1["close"].iat[-1]), float(ma1.iat[-1])
    if not (a5 > 0) or np.isnan(m_prev) or np.isnan(m1_now):
        return {"regime": "unknown", "direction": 0, "atr_m5": a5}
    dist = (c5 - m_now) / a5
    slope = (m_now - m_prev) / a5
    td, ts = float(rcfg.get("trend_dist_atr", 1.0)), float(rcfg.get("trend_slope_atr", 0.3))
    direction = 0
    if dist >= td and slope >= ts and c1 > m1_now:
        direction = 1
    elif dist <= -td and slope <= -ts and c1 < m1_now:
        direction = -1
    return {"regime": "trend" if direction else "lateral", "direction": direction, "atr_m5": round(a5, 4),
            "atr_m1": round(float(ind.atr(m1, ap).iat[-1]), 4), "ma100_m5": round(m_now, 4),
            "dist_atr": round(dist, 3), "slope_atr": round(slope, 3)}


def decide_control(reg: Dict[str, Any], now: datetime, gcfg: Dict[str, Any], point: float,
                   calendar: Optional[NewsCalendar] = None, kill_reason: str = "") -> Dict[str, Any]:
    params = gcfg.get("params", {}).get(reg.get("regime"), {"enabled": False, "trail_atr": 1.0})
    atr = reg.get("atr_m5")
    atr_ok = atr is not None and not (isinstance(atr, float) and np.isnan(atr)) and atr > 0
    enabled = bool(params.get("enabled", False))
    reason = f"regime={reg.get('regime')}"
    min_atr = float(gcfg.get("min_atr", 1.5))
    if kill_reason:
        enabled, reason = False, f"KILL SWITCH A5: {kill_reason}"
    elif not in_session(now, gcfg.get("sessions") or []):
        enabled, reason = False, "fora de sessão Londres/NY"
    elif calendar is not None and calendar.blocking_event(now):
        enabled, reason = False, f"janela de notícia: {calendar.blocking_event(now)}"
    elif not atr_ok:
        enabled, reason = False, "ATR indisponível"
    elif atr < min_atr:
        enabled, reason = False, f"ATR(M5) {atr:.2f} < min_atr {min_atr}"
    elif not enabled:
        reason = f"regime={reg.get('regime')} (desligado por config)"
    max_spread = int(float(gcfg.get("max_spread_atr", 0.15)) * atr / point) if atr_ok and point > 0 else 0
    ts = int(now.timestamp())
    return {"enabled": enabled, "trail_atr": float(params.get("trail_atr", 1.0)), "min_atr": min_atr,
            "max_spread": max_spread, "regime": reg.get("regime"), "direction": int(reg.get("direction", 0)),
            "atr_m5": float(atr) if atr_ok else 0.0, "reason": reason, "updated_at": ts,
            "valid_until": ts + int(gcfg.get("control_ttl_seconds", 900)), "source": "quant-office/goldflip_supervisor"}


def write_json_atomic(path: Path, obj: Dict[str, Any], retries: int = 5) -> None:
    """Escreve em .tmp e troca atomicamente (o EA nunca lê arquivo pela metade)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=True, separators=(",", ":")), encoding="ascii")
    for i in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # EA lendo o arquivo neste instante
            time.sleep(0.05 * (i + 1))
    raise PermissionError(f"não consegui substituir {path}")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


# ----------------------------------------------------------------- agente
class GoldFlipSupervisor:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], files_dir: Optional[str] = None,
                 calendar: Optional[NewsCalendar] = None, guard: Optional[AccountGuard] = None) -> None:
        self.mt5 = mt5
        self.cfg = cfg
        self.g = cfg["goldflip"]
        self.symbol = self.g.get("symbol", "GOLD")
        self.magic = int(self.g.get("magic", 20261108))
        self.interval = int(self.g.get("interval_seconds", 300))
        self.check_every = int(cfg.get("risk", {}).get("account_guard", {}).get("check_seconds", 30))
        self.guard = guard or AccountGuard(cfg)
        self.calendar = calendar or NewsCalendar(self.g.get("news_keywords", []),
                                                 int(self.g.get("news_window_minutes", 15)),
                                                 str(ROOT / "config" / "news_events.csv"))
        self.dir = Path(files_dir) if files_dir else self._resolve_dir()
        self.last_cycle = 0.0
        self.last_check = 0.0
        self.control: Dict[str, Any] = {}
        self.status: Optional[Dict[str, Any]] = None
        self.exposure: Dict[str, Any] = {}

    def _resolve_dir(self) -> Path:
        d = self.g.get("files_dir", "auto")
        if d and d != "auto":
            return Path(d)
        info = self.mt5.terminal_info()
        return Path(info.data_path) / "MQL5" / "Files"

    def start(self, refresh_calendar: bool = True) -> None:
        self.mt5.symbol_select(self.symbol, True)
        if refresh_calendar:
            self.calendar.start_background_refresh()
        log.info("[GOLDFLIP] Supervisor ativo | magic=%s | controle em %s", self.magic, self.dir / CONTROL_FILE)

    # ------------------------------------------------------------ loop
    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        t = time.time()
        if t - self.last_check >= self.check_every:
            self.last_check = t
            self.check_risk(now)
        if t - self.last_cycle >= self.interval:
            self.last_cycle = t
            self.run_cycle(now)

    def _rates(self, tf_name: str, n: int) -> Optional[pd.DataFrame]:
        tf = {"M1": self.mt5.TIMEFRAME_M1, "M5": self.mt5.TIMEFRAME_M5}[tf_name]
        r = self.mt5.copy_rates_from_pos(self.symbol, tf, 1, n)
        return pd.DataFrame(r) if r is not None and len(r) else None

    def run_cycle(self, now: datetime) -> Dict[str, Any]:
        reg = classify_regime(self._rates("M1", 300), self._rates("M5", 300), self.g.get("regime", {}))
        si = self.mt5.symbol_info(self.symbol)
        point = float(getattr(si, "point", 0.01) or 0.01)
        ctl = decide_control(reg, now, self.g, point, self.calendar, self.guard.kill_reason)
        write_json_atomic(self.dir / CONTROL_FILE, ctl)
        changed = ctl.get("enabled") != self.control.get("enabled") or ctl.get("regime") != self.control.get("regime")
        self.control = ctl
        self.status = read_json(self.dir / STATUS_FILE)
        (log.warning if changed else log.info)(
            "[GOLDFLIP] enabled=%s regime=%s dir=%+d trail=%.2fxATR min_atr=%.2f max_spread=%dpts ATR=%.2f | %s",
            ctl["enabled"], ctl["regime"], ctl["direction"], ctl["trail_atr"], ctl["min_atr"], ctl["max_spread"],
            ctl["atr_m5"], ctl["reason"])
        self._log_status()
        return ctl

    def force_disable(self, reason: str, now: datetime) -> None:
        ctl = dict(self.control) if self.control else decide_control({"regime": "unknown"}, now, self.g, 0.01)
        ts = int(now.timestamp())
        ctl.update({"enabled": False, "reason": f"KILL SWITCH A5: {reason}", "updated_at": ts,
                    "valid_until": ts + int(self.g.get("control_ttl_seconds", 900))})
        write_json_atomic(self.dir / CONTROL_FILE, ctl)
        self.control = ctl
        log.warning("[GOLDFLIP] FORÇADO enabled=false -> %s", reason)

    # ------------------------------------------------------------ A5: exposição + kill switch
    def _realized_today(self, now: datetime) -> float:
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        deals = self.mt5.history_deals_get(start - timedelta(days=1), now + timedelta(days=1)) or []
        srv = self.cfg["account"].get("server_time", "ny_plus_7")
        total = 0.0
        for d in deals:
            if int(d.type) not in (0, 1):            # ignora depósitos/créditos (DEAL_TYPE_BALANCE etc.)
                continue
            if server_to_utc([int(d.time)], srv).iloc[0] >= pd.Timestamp(start):
                total += float(d.profit) + float(d.swap) + float(d.commission)
        return total

    def check_risk(self, now: datetime) -> None:
        info = self.mt5.account_info()
        if info is None:
            return
        self.exposure = AccountGuard.exposure(self.mt5.positions_get() or [], self.symbol)
        was_killed = bool(self.guard.kill_reason)
        killed, dd = self.guard.evaluate(now, float(info.balance), float(info.equity), self._realized_today(now))
        if killed and (not was_killed or self.control.get("enabled")):
            self.force_disable(self.guard.kill_reason, now)

    # ------------------------------------------------------------ logs
    def _log_status(self) -> None:
        e = self.exposure
        if e:
            log.info("[A5 EXPOSIÇÃO %s] net=%.2f lotes | bruto=%.2f | PnL flutuante=%.2f | por magic=%s | DD dia=%s%%",
                     self.symbol, e["net_lots"], e["gross_lots"], e["floating_pnl"],
                     {m: round(v["net_lots"], 2) for m, v in e["by_magic"].items()}, self.guard.last.get("dd_pct"))
        s = self.status
        if s is None:
            log.warning("[GOLDFLIP] %s ainda não existe: o EA está anexado ao gráfico GOLD com a versão nova?",
                        STATUS_FILE)
            return
        age = int(time.time()) - int(s.get("updated_at", 0) or 0)
        log.info("[GOLDFLIP STATUS] pos=%s %.2f lotes | PnL dia=%.2f | trades/h=%s | spread médio=%s pts | "
                 "EA vê enabled=%s | atualizado há %ds", s.get("position"), float(s.get("volume", 0) or 0),
                 float(s.get("day_pnl", 0) or 0), s.get("trades_last_hour"), s.get("avg_spread_points"),
                 s.get("control_enabled"), age)
        if age > 180:
            log.warning("[GOLDFLIP] status do EA parado há %ds (EA desanexado ou Algo Trading desligado?)", age)

    def summary(self) -> str:
        c = self.control or {}
        return f"GoldFlip: enabled={c.get('enabled')} {c.get('regime')} ({c.get('reason', '-')})"
