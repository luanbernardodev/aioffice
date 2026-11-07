"""A5 RISCO/EXECUÇÃO — toda ordem passa por aqui.

- Normaliza SL/TP: SL mínimo 1 x ATR(M5) (alarga se menor), descarta SL > max_sl_atr x ATR,
  TP1 = 1.5R, alvo final = max(extensão Fib, TP1).
- Exposição: máx. 6 (posições + pendentes) no total, 3 por ativo.
- Stop diário (USD realizado no dia UTC) -> pausa até o dia seguinte.
- N perdas seguidas -> pausa de 2h.
- Trailing: ativa em max(1R, 3 x spread) -> SL = entrada ± spread (breakeven travado),
  depois trailing de 1 x ATR(M5), só a favor, nunca recua.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from engine.types import BUY, ClosedTrade, OrderIntent, Position

log = logging.getLogger("engine.risk")


class RiskManager:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        r = cfg.get("risk", {})
        self.max_total = int(r.get("max_positions_total", 6))
        self.max_symbol = int(r.get("max_positions_per_symbol", 3))
        self.daily_stop = float(r.get("daily_stop_usd", 30.0))
        self.max_streak = int(r.get("max_consecutive_losses", 4))
        self.streak_pause = timedelta(minutes=float(r.get("streak_pause_minutes", 120)))
        self.min_sl_atr = float(r.get("min_sl_atr", 1.0))
        self.max_sl_atr = float(r.get("max_sl_atr", 6.0))
        self.tp1_r = float(r.get("tp1_r", 1.5))
        t = r.get("trailing", {})
        self.trail_activate_r = float(t.get("activate_r", 1.0))
        self.trail_activate_spread = float(t.get("activate_spread_mult", 3.0))
        self.trail_atr = float(t.get("atr_mult", 1.0))
        # estado
        self.day = None
        self.day_pnl = 0.0
        self.streak = 0
        self.paused_until: Optional[datetime] = None
        self.pause_reason = ""

    # ------------------------------------------------------------ pausas
    def _roll_day(self, now: datetime) -> None:
        d = now.date()
        if self.day != d:
            self.day = d
            self.day_pnl = 0.0
            if self.pause_reason == "daily_stop":
                self.paused_until, self.pause_reason = None, ""

    def trading_allowed(self, now: datetime) -> Tuple[bool, str]:
        self._roll_day(now)
        if self.paused_until and now < self.paused_until:
            return False, f"pausa ({self.pause_reason}) até {self.paused_until:%Y-%m-%d %H:%M}Z"
        if self.paused_until and now >= self.paused_until:
            self.paused_until, self.pause_reason = None, ""
        return True, ""

    def on_trade_closed(self, t: ClosedTrade) -> None:
        now = t.closed_at.to_pydatetime() if hasattr(t.closed_at, "to_pydatetime") else t.closed_at
        self._roll_day(now)
        self.day_pnl += t.pnl_usd
        self.streak = self.streak + 1 if t.pnl_usd < 0 else 0
        if self.day_pnl <= -self.daily_stop:
            nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
            self.paused_until, self.pause_reason = nxt, "daily_stop"
            log.warning("[A5] STOP DIÁRIO: %.2f USD <= -%.2f. Pausado até %s", self.day_pnl, self.daily_stop, nxt)
        elif self.streak >= self.max_streak:
            self.paused_until, self.pause_reason = now + self.streak_pause, "loss_streak"
            log.warning("[A5] %d perdas seguidas. Pausa de %s", self.streak, self.streak_pause)
            self.streak = 0

    # ------------------------------------------------------------ exposição
    def exposure_ok(self, symbol: str, open_total: int, open_symbol: int) -> Tuple[bool, str]:
        if open_total >= self.max_total:
            return False, f"exposição total {open_total}/{self.max_total}"
        if open_symbol >= self.max_symbol:
            return False, f"exposição {symbol} {open_symbol}/{self.max_symbol}"
        return True, ""

    # ------------------------------------------------------------ níveis
    def finalize(self, it: OrderIntent, entry: Optional[float] = None) -> Optional[OrderIntent]:
        """Aplica SL mínimo/máximo e TP1/alvo final. Retorna None se o setup for descartado."""
        entry = float(entry if entry is not None else it.price)
        atr = it.atr
        if not atr or atr <= 0:
            return None
        side = it.side
        sl = it.sl
        if (entry - sl) * side <= 0:          # SL do lado errado
            return None
        dist = abs(entry - sl)
        min_d = self.min_sl_atr * atr
        if dist < min_d:
            sl = entry - side * min_d
            dist = min_d
        if dist > self.max_sl_atr * atr:
            return None
        tp1 = entry + side * self.tp1_r * dist
        tp = entry + side * it.tp_r * dist if it.tp_r > 0 else it.tp
        if (tp - tp1) * side < 0:             # alvo final nunca abaixo de 1.5R
            tp = tp1
        return replace(it, price=entry if it.kind == "LIMIT" else it.price, sl=sl, tp=tp, tp1=tp1)

    # ------------------------------------------------------------ trailing
    def trail(self, pos: Position, bid: float, ask: float, atr: float, spread: float) -> Optional[float]:
        """Novo SL (ou None). Só move a favor; trava breakeven em entrada ± spread."""
        r = pos.initial_risk
        if r <= 0 or not atr or atr <= 0:
            return None
        activation = max(self.trail_activate_r * r, self.trail_activate_spread * spread)
        if pos.side == BUY:
            profit = bid - pos.entry
            if profit < activation:
                return None
            new = max(pos.entry + spread, bid - self.trail_atr * atr)
            if new > pos.sl + 1e-9 and new < bid:
                return new
        else:
            profit = pos.entry - ask
            if profit < activation:
                return None
            new = min(pos.entry - spread, ask + self.trail_atr * atr)
            if new < pos.sl - 1e-9 and new > ask:
                return new
        return None


# ============================================================ kill switch de conta (todos os magics)
class AccountGuard:
    """Soma a exposição de um símbolo em TODOS os magics e dispara o kill switch por DD diário.

    DD diário = (saldo de início do dia UTC - equity) / saldo de início do dia.
    Saldo de início do dia = saldo atual - P&L realizado hoje (todos os magics) -> sobrevive a restart.
    Disparado, fica travado até a virada do dia UTC.
    """

    def __init__(self, cfg: Dict[str, Any]) -> None:
        g = cfg.get("risk", {}).get("account_guard", {})
        self.dd_limit_pct = float(g.get("daily_dd_pct", 3.0))
        self.killed_until: Optional[datetime] = None
        self.kill_reason = ""
        self.last: Dict[str, Any] = {}

    @staticmethod
    def exposure(positions: list, symbol: str) -> Dict[str, Any]:
        """positions: objetos com symbol, magic, type (0=buy,1=sell), volume, profit."""
        by_magic: Dict[int, Dict[str, float]] = {}
        net = gross = pnl = 0.0
        for p in positions or []:
            if str(p.symbol) != symbol:
                continue
            sgn = 1.0 if int(p.type) == 0 else -1.0
            vol = float(p.volume)
            m = by_magic.setdefault(int(p.magic), {"net_lots": 0.0, "gross_lots": 0.0, "pnl": 0.0, "count": 0})
            m["net_lots"] += sgn * vol
            m["gross_lots"] += vol
            m["pnl"] += float(p.profit)
            m["count"] += 1
            net += sgn * vol
            gross += vol
            pnl += float(p.profit)
        return {"symbol": symbol, "net_lots": round(net, 2), "gross_lots": round(gross, 2),
                "floating_pnl": round(pnl, 2), "by_magic": by_magic}

    def evaluate(self, now: datetime, balance: float, equity: float, realized_today: float) -> Tuple[bool, float]:
        """Retorna (kill_ativo, dd_pct). Trava até o próximo dia UTC quando dd >= limite."""
        if self.killed_until and now >= self.killed_until:
            self.killed_until, self.kill_reason = None, ""
        start = balance - realized_today
        dd_pct = max(0.0, (start - equity) / start * 100.0) if start > 0 else 0.0
        if dd_pct >= self.dd_limit_pct and self.killed_until is None:
            self.killed_until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(),
                                                 tzinfo=now.tzinfo)
            self.kill_reason = f"DD diário {dd_pct:.2f}% >= {self.dd_limit_pct}%"
            log.warning("[A5 KILL SWITCH] %s (início do dia %.2f, equity %.2f). GoldFlip desligado até %s",
                        self.kill_reason, start, equity, self.killed_until)
        self.last = {"dd_pct": round(dd_pct, 2), "day_start_balance": round(start, 2), "equity": round(equity, 2)}
        return self.killed_until is not None, dd_pct
