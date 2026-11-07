"""Log de cada trade (agente, setup, entrada, SL, TP, spread, ATR, resultado em R) em CSV.

Espelho opcional no Supabase em thread de fundo (nunca bloqueia o loop de execução).
"""
from __future__ import annotations

import csv
import logging
import queue
import threading
from pathlib import Path
from typing import Optional

from engine.types import ClosedTrade, side_name

log = logging.getLogger("engine.trades")

FIELDS = ["closed_at", "opened_at", "agent", "setup", "symbol", "side", "volume", "entry", "initial_sl",
          "tp1", "tp", "exit", "reason", "spread", "atr", "r", "pnl_usd", "ticket"]


class TradeLogger:
    def __init__(self, path: Optional[str] = None, supabase_sink: bool = False, account_label: str = "DEMO") -> None:
        self.path = Path(path) if path else None
        self.account_label = account_label
        self._q: Optional[queue.Queue] = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                with open(self.path, "w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow(FIELDS)
        if supabase_sink:
            self._q = queue.Queue(maxsize=1000)
            threading.Thread(target=self._sink_loop, name="SupabaseSink", daemon=True).start()

    def log(self, t: ClosedTrade) -> None:
        row = [t.closed_at, t.opened_at, t.agent, t.setup, t.symbol, side_name(t.side), t.volume,
               round(t.entry, 5), round(t.initial_sl, 5), round(t.tp1, 5), round(t.tp, 5), round(t.exit, 5),
               t.reason, round(t.spread_at_entry, 5), round(t.atr_at_entry, 5), round(t.r, 3),
               round(t.pnl_usd, 2), t.ticket]
        log.info("[TRADE] %s %s %s %s entry=%.5f sl=%.5f tp=%.5f exit=%.5f -> %+.2fR (%+.2f USD) [%s]",
                 t.agent, t.setup, t.symbol, side_name(t.side), t.entry, t.initial_sl, t.tp, t.exit,
                 t.r, t.pnl_usd, t.reason)
        if self.path:
            with open(self.path, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(row)
        if self._q is not None:
            try:
                self._q.put_nowait(t)
            except queue.Full:
                log.warning("Fila do Supabase cheia; trade não espelhado.")

    def _sink_loop(self) -> None:
        try:
            from core.database import DatabaseManager
            db = DatabaseManager()
        except Exception as exc:  # noqa: BLE001
            log.warning("Supabase sink desativado: %s", exc)
            return
        while True:
            t: ClosedTrade = self._q.get()
            try:
                db.upsert_trade({
                    "ticket_mt5": int(str(t.ticket).lstrip("S") or 0) or abs(hash(t.ticket)) % 10**12,
                    "agent_id": t.agent, "symbol": t.symbol, "order_type": side_name(t.side),
                    "volume": t.volume, "entry_price": t.entry, "sl": t.initial_sl, "tp": t.tp,
                    "close_price": t.exit, "current_price": t.exit, "profit_usd": round(t.pnl_usd, 2),
                    "status": "CLOSED", "exit_reason": t.reason, "opened_at": str(t.opened_at),
                    "closed_at": str(t.closed_at), "execution_account": self.account_label,
                })
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao espelhar trade no Supabase: %s", exc)
