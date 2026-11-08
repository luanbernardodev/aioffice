"""Broker MT5 (DRY_RUN=False) com trava de conta.

- Só envia ordens se a conta conectada for a DEMO autorizada (login + trade_mode DEMO),
  verificado na inicialização e ANTES DE CADA envio.
- Conta REAL: recusada enquanto account.allow_real=false; mesmo com true exige a variável
  de ambiente QUANT_ALLOW_REAL=I_AUTHORIZE (autorização explícita do dono).
- Gerencia apenas ordens/posições com o magic do motor.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from engine.config import ROOT
from engine.features import server_to_utc
from engine.types import BUY, ClosedTrade, OrderIntent, Position

log = logging.getLogger("engine.mt5")

STATE_FILE = ROOT / "state" / "mt5_meta.json"


class AccountGuardError(RuntimeError):
    pass


def verify_account(mt5: Any, cfg: Dict[str, Any]) -> Any:
    acc = cfg.get("account", {})
    info = mt5.account_info()
    if info is None:
        raise AccountGuardError("MT5 sem conta conectada")
    is_demo = info.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
    if is_demo:
        if int(info.login) != int(acc.get("demo_login", -1)):
            raise AccountGuardError(f"conta demo #{info.login} não é a autorizada")
        return info
    if not acc.get("allow_real", False) or os.getenv("QUANT_ALLOW_REAL") != "I_AUTHORIZE":
        raise AccountGuardError(f"conta #{info.login} NÃO é DEMO — envio de ordens bloqueado")
    return info


def intent_to_dict(it: OrderIntent) -> dict:
    d = dict(it.__dict__)
    d["expiry"] = str(it.expiry) if it.expiry is not None else None
    return d


def intent_from_dict(d: dict) -> OrderIntent:
    d = dict(d)
    d["expiry"] = pd.Timestamp(d["expiry"]) if d.get("expiry") else None
    return OrderIntent(**d)


class MT5Broker:
    _last_state: Optional[str] = None

    def __init__(self, mt5: Any, cfg: Dict[str, Any], specs: Dict[str, Dict[str, float]]) -> None:
        self.mt5 = mt5
        self.cfg = cfg
        self.specs = specs
        self.magic = int(cfg["account"]["magic"])
        verify_account(mt5, cfg)
        self.on_fill: Optional[Callable[[Position], None]] = None
        self.on_close: Optional[Callable[[ClosedTrade], None]] = None
        self.meta: Dict[str, dict] = {}          # ticket da ordem -> intent
        self.pending_map: Dict[str, int] = {}    # key -> ticket da ordem pendente
        self.positions: Dict[str, Position] = {}
        self._load_state()

    # ------------------------------------------------------------ persistência (restart seguro)
    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                raw = json.loads(STATE_FILE.read_text())
                self.meta = raw.get("meta", {})
                self.pending_map = {k: int(v) for k, v in raw.get("pending", {}).items()}
            except Exception as exc:  # noqa: BLE001
                log.warning("Estado MT5 ilegível (%s); começando limpo.", exc)

    def _save_state(self) -> None:
        """Grava só se mudou e de forma atômica: uma queda no meio nunca deixa o arquivo vazio."""
        payload = json.dumps({"meta": self.meta, "pending": self.pending_map}, default=str)
        if payload == self._last_state:
            return
        STATE_FILE.parent.mkdir(exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.replace(tmp, STATE_FILE)
        except PermissionError as exc:              # arquivo momentaneamente em uso: tenta no próximo ciclo
            log.warning("Estado MT5 não gravado (%s); nova tentativa no próximo ciclo.", exc)
            return
        self._last_state = payload

    # ------------------------------------------------------------ consultas
    def pending_orders(self, symbol: Optional[str] = None) -> List[OrderIntent]:
        out = []
        for key, tk in self.pending_map.items():
            m = self.meta.get(str(tk))
            if m and (symbol is None or m["symbol"] == symbol):
                out.append(intent_from_dict(m))
        return out

    def open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        return [p for p in self.positions.values() if symbol is None or p.symbol == symbol]

    # ------------------------------------------------------------ helpers
    def _ts(self, server_epoch: int) -> pd.Timestamp:
        return server_to_utc([int(server_epoch)], self.cfg["account"].get("server_time", "ny_plus_7")).iloc[0]

    def _digits(self, symbol: str) -> int:
        return int(self.specs.get(symbol, {}).get("digits", 2))

    def _filling(self, symbol: str) -> int:
        info = self.mt5.symbol_info(symbol)
        fm = getattr(info, "filling_mode", 0) if info else 0
        if fm & 2:
            return self.mt5.ORDER_FILLING_IOC
        if fm & 1:
            return self.mt5.ORDER_FILLING_FOK
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: dict) -> Any:
        verify_account(self.mt5, self.cfg)  # trava antes de CADA envio
        res = self.mt5.order_send(req)
        if res is None or res.retcode not in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED):
            log.error("[MT5] recusado: %s | %s | req=%s", getattr(res, "retcode", None),
                      getattr(res, "comment", self.mt5.last_error()), {k: v for k, v in req.items() if k != "comment"})
            return None
        return res

    # ------------------------------------------------------------ ações
    def place(self, it: OrderIntent, volume: float, now: pd.Timestamp) -> bool:
        d = self._digits(it.symbol)
        comment = f"{it.agent[:2]}|{it.setup}"[:28]
        base = {"symbol": it.symbol, "volume": float(volume), "sl": round(it.sl, d), "tp": round(it.tp, d),
                "magic": self.magic, "comment": comment, "type_time": self.mt5.ORDER_TIME_GTC}
        if it.kind == "LIMIT":
            req = {**base, "action": self.mt5.TRADE_ACTION_PENDING, "price": round(it.price, d),
                   "type": self.mt5.ORDER_TYPE_BUY_LIMIT if it.side == BUY else self.mt5.ORDER_TYPE_SELL_LIMIT,
                   "type_filling": self.mt5.ORDER_FILLING_RETURN}
        else:
            tick = self.mt5.symbol_info_tick(it.symbol)
            price = tick.ask if it.side == BUY else tick.bid
            req = {**base, "action": self.mt5.TRADE_ACTION_DEAL, "price": price, "deviation": 20,
                   "type": self.mt5.ORDER_TYPE_BUY if it.side == BUY else self.mt5.ORDER_TYPE_SELL,
                   "type_filling": self._filling(it.symbol)}
        res = self._send(req)
        if res is None:
            return False
        tk = int(res.order)
        self.meta[str(tk)] = intent_to_dict(it)
        if it.kind == "LIMIT":
            self.pending_map[it.key] = tk
        self._save_state()
        log.info("[MT5] %s %s ticket=%s %s", it.kind, it.key, tk, req["price"])
        return True

    def cancel(self, key: str) -> None:
        tk = self.pending_map.get(key)
        if tk is None:
            return
        res = self._send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": tk})
        if res is not None or not self._order_exists(tk):
            self.pending_map.pop(key, None)
            self._save_state()

    def modify(self, it: OrderIntent) -> None:
        tk = self.pending_map.get(it.key)
        if tk is None:
            return
        d = self._digits(it.symbol)
        res = self._send({"action": self.mt5.TRADE_ACTION_MODIFY, "order": tk, "price": round(it.price, d),
                          "sl": round(it.sl, d), "tp": round(it.tp, d), "type_time": self.mt5.ORDER_TIME_GTC})
        if res is not None:
            self.meta[str(tk)] = intent_to_dict(it)
            self._save_state()

    def modify_sl(self, pos_id: str, sl: float) -> bool:
        p = self.positions.get(pos_id)
        if p is None:
            return False
        d = self._digits(p.symbol)
        res = self._send({"action": self.mt5.TRADE_ACTION_SLTP, "position": int(pos_id), "symbol": p.symbol,
                          "sl": round(sl, d), "tp": round(p.tp, d)})
        if res is None:
            return False
        p.sl = round(sl, d)
        p.be_locked = True
        return True

    def cancel_all_pending(self) -> None:
        for key in list(self.pending_map):
            self.cancel(key)

    def _order_exists(self, tk: int) -> bool:
        return bool(self.mt5.orders_get(ticket=tk))

    # ------------------------------------------------------------ sincronização (fills/fechamentos)
    def sync(self) -> None:
        orders = self.mt5.orders_get() or []
        live_orders = {int(o.ticket) for o in orders if o.magic == self.magic}
        for key, tk in list(self.pending_map.items()):
            if tk not in live_orders:
                self.pending_map.pop(key, None)   # executada (vira posição) ou expirada/cancelada
        poss = [p for p in (self.mt5.positions_get() or []) if p.magic == self.magic]
        seen = set()
        for p in poss:
            pid = str(p.ticket)
            seen.add(pid)
            if pid in self.positions:
                self.positions[pid].sl = float(p.sl)
                continue
            m = self.meta.get(str(p.identifier)) or self.meta.get(pid)
            it = intent_from_dict(m) if m else None
            side = BUY if p.type == self.mt5.POSITION_TYPE_BUY else -1
            pos = Position(pid, it.key if it else f"adopted|{pid}", it.agent if it else "UNKNOWN", p.symbol, side,
                           float(p.volume), float(p.price_open), float(p.sl), float(p.tp),
                           it.tp1 if it else 0.0, it.sl if it else float(p.sl), it.setup if it else "ADOPTED",
                           it.group if it else pid, self._ts(p.time),
                           atr_at_entry=it.atr if it else 0.0, spread_at_entry=it.spread if it else 0.0)
            self.positions[pid] = pos
            if self.on_fill:
                self.on_fill(pos)
        for pid in list(self.positions):
            if pid not in seen:
                self._finalize_closed(self.positions.pop(pid))
        self._save_state()

    def _finalize_closed(self, pos: Position) -> None:
        deals = self.mt5.history_deals_get(position=int(pos.id)) or []
        out = [d for d in deals if d.entry == getattr(self.mt5, "DEAL_ENTRY_OUT", 1)]
        pnl = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        exit_px = float(out[-1].price) if out else pos.sl
        reason_map = {getattr(self.mt5, "DEAL_REASON_SL", 4): "SL", getattr(self.mt5, "DEAL_REASON_TP", 5): "TP"}
        reason = reason_map.get(getattr(out[-1], "reason", -1), "CLOSE") if out else "UNKNOWN"
        if reason == "SL" and pos.be_locked:
            reason = "TRAIL"
        closed_at = self._ts(out[-1].time) if out else pd.Timestamp.now(tz="UTC")
        r = (exit_px - pos.entry) * pos.side / pos.initial_risk if pos.initial_risk > 0 else 0.0
        if self.on_close:
            self.on_close(ClosedTrade(pos.agent, pos.setup, pos.symbol, pos.side, pos.volume, pos.entry,
                                      pos.initial_sl, pos.tp, pos.tp1, exit_px, pos.opened_at, closed_at, reason,
                                      pnl, r, pos.spread_at_entry, pos.atr_at_entry, ticket=pos.id))
