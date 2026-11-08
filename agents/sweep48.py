"""SWEEP48 — agente de scalp determinístico em BTCUSD M5 (magic exclusivo). Nenhum LLM no caminho.

Sinal (barra M5 fechada i, preços bid):
  COMPRA: low[i] < MIN48 e close[i] > MIN48 e close[i] > MA100 e close[i] > MA300
  VENDA:  high[i] > MAX48 e close[i] < MAX48 e close[i] < MA100 e close[i] < MA300
  MIN48/MAX48 = barras i-48..i-1; abertura da barra entre 15:00 e 20:59 do servidor XM.
Saídas: SL 3*A, TP 5*A (A = ATR14 Wilder da barra do sinal, fixo), stop móvel de 0.15*A ativado em +0.75*A,
saída por tempo em 240 min. Limite de perda acumulada do magic: -1500 USD por 1 BTC de exposição.

O stop vale em código a cada tick. O SL na corretora acompanha (no máx. 1 envio/s); se o broker recusar ou a
distância violar stops/freeze level, fica o stop virtual, que fecha a mercado ao ser atingido.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from engine import indicators as ind
from engine.config import ROOT
from engine.mt5_broker import verify_account

log = logging.getLogger("agents.sweep48")

BUY, SELL = 1, -1
CSV_FIELDS = ["ts_utc", "event", "ticket", "signal_bar_server", "side", "A", "spread", "requested", "executed",
              "slippage", "retcode", "sl", "tp", "exit_price", "profit", "reason", "detail"]
MIN_BARS = 2000                  # aquecimento do ATR de Wilder e da MA300


# ----------------------------------------------------------------- funções puras
def server_hour(epoch: int) -> int:
    """`time` das barras do MT5 é o relógio de parede do servidor."""
    return int(epoch) % 86400 // 3600


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["atr"] = ind.atr(d, 14)
    d["ma100"] = ind.sma(d["close"], 100)
    d["ma300"] = ind.sma(d["close"], 300)
    d["min48"] = d["low"].rolling(48).min().shift(1)
    d["max48"] = d["high"].rolling(48).max().shift(1)
    return d


def signal_at(row: Any, start_hour: int = 15, end_hour: int = 20) -> int:
    """+1 compra, -1 venda, 0 nada. `row` precisa de time (epoch servidor) e dos indicadores."""
    if not start_hour <= server_hour(row.time) <= end_hour:
        return 0
    if any(np.isnan(v) for v in (row.atr, row.ma100, row.ma300, row.min48, row.max48)):
        return 0
    if row.low < row.min48 and row.close > row.min48 and row.close > row.ma100 and row.close > row.ma300:
        return BUY
    if row.high > row.max48 and row.close < row.max48 and row.close < row.ma100 and row.close < row.ma300:
        return SELL
    return 0


def trail_stop(side: int, entry: float, sl: float, bid: float, ask: float, a: float,
               trigger: float = 0.75, dist: float = 0.15) -> float:
    """Novo SL (só a favor). Compra usa bid; venda usa ask."""
    if side == BUY:
        return max(sl, bid - dist * a) if bid - entry >= trigger * a else sl
    return min(sl, ask + dist * a) if entry - ask >= trigger * a else sl


def loss_limit_usd(per_btc: float, lot: float, contract_size: float) -> float:
    return -abs(per_btc) * lot * contract_size


# ----------------------------------------------------------------- agente
class Sweep48Agent:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], state_path: Optional[Path] = None,
                 csv_path: Optional[Path] = None) -> None:
        self.mt5, self.cfg = mt5, cfg
        self.g = cfg["sweep48"]
        self.symbol = self.g["symbol"]
        self.magic = int(self.g["magic"])
        self.lot = float(self.g["lot"])
        self.state_path = Path(state_path or ROOT / "state" / "sweep48.json")
        self.csv_path = Path(csv_path or ROOT / "logs" / "sweep48_trades.csv")
        self.state: Dict[str, Any] = {"halted": False, "halt_reason": "", "last_bar": 0, "trade": None}
        self.realized = 0.0
        self.limit = 0.0
        self.last_msc = 0
        self.last_head = 0
        self.last_sl_send = 0.0
        self.last_close_try = 0.0
        self.exit_reason = ""
        self.missing_deal_tries = 0

    # ------------------------------------------------------------ persistência e log
    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self.state.update(json.loads(self.state_path.read_text()))
            except (ValueError, OSError) as exc:
                log.error("[SWEEP48] estado ilegível (%s): seguindo só com dados do MT5", exc)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_path)

    def _csv(self, event: str, **kw: Any) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.csv_path.exists()
        row = {"ts_utc": datetime.now(timezone.utc).isoformat(), "event": event, **kw}
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    # ------------------------------------------------------------ inicialização
    def start(self) -> None:
        verify_account(self.mt5, self.cfg)
        self.mt5.symbol_select(self.symbol, True)
        si = self.mt5.symbol_info(self.symbol)
        self.point, self.digits = float(si.point), int(si.digits)
        self.stops_level, self.freeze_level = int(si.trade_stops_level), int(si.trade_freeze_level)
        self.contract = float(si.trade_contract_size)
        self.filling_mode = int(si.filling_mode)
        self.limit = loss_limit_usd(float(self.g["loss_limit_usd_per_btc"]), self.lot, self.contract)
        self._load()
        self.realized = self._realized()
        log.info("[SWEEP48] %s magic=%s lote=%s | contract_size=%s | stops_level=%s freeze_level=%s | "
                 "limite do magic=%.2f USD | acumulado realizado=%.2f USD", self.symbol, self.magic, self.lot,
                 self.contract, self.stops_level, self.freeze_level, self.limit, self.realized)
        if self.state["halted"]:
            log.warning("[SWEEP48] PARADO: %s", self.state["halt_reason"])
        self._recover()

    def _position(self) -> Optional[Any]:
        ps = [p for p in (self.mt5.positions_get(symbol=self.symbol) or []) if int(p.magic) == self.magic]
        return ps[0] if ps else None

    def _realized(self) -> float:
        deals = self.mt5.history_deals_get(datetime(2020, 1, 1), datetime.now() + timedelta(days=2)) or []
        return sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals
                   if int(d.magic) == self.magic and int(d.type) in (0, 1))

    def _bars(self, n: int) -> Optional[pd.DataFrame]:
        r = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_M5, 1, n)
        return pd.DataFrame(r) if r is not None and len(r) else None

    def _atr_of_bar(self, bar_time: int) -> Optional[float]:
        df = self._bars(5000)
        if df is None:
            return None
        hit = df.index[df["time"] == int(bar_time)]
        if len(hit) == 0:
            return None
        v = float(ind.atr(df, 14).iloc[hit[0]])
        return None if np.isnan(v) else v

    def _recover(self) -> None:
        pos = self._position()
        if pos is None:
            if self.state.get("trade"):
                self._finish(int(self.state["trade"].get("ticket") or 0))     # fechou com o agente desligado
            return
        side = BUY if pos.type == self.mt5.POSITION_TYPE_BUY else SELL
        tr = self.state.get("trade") or {}
        bar = tr.get("signal_bar")
        if not bar:                                 # sem arquivo: barra fechada imediatamente antes da abertura
            df = self._bars(5000)
            prior = df[df["time"] + 300 <= int(pos.time)] if df is not None else None
            bar = int(prior["time"].iloc[-1]) if prior is not None and len(prior) else None
        a = self._atr_of_bar(bar) if bar else None
        if a is None:
            a = tr.get("A")
        if not a:
            a = abs(float(pos.price_open) - float(pos.sl)) / 3.0 if pos.sl else None
            log.error("[SWEEP48] A estimado pelo SL da posição #%s (barra do sinal indisponível)", pos.ticket)
        if not a:
            log.error("[SWEEP48] posição #%s sem A e sem SL: fechando por segurança", pos.ticket)
            self.state["trade"] = {"ticket": int(pos.ticket), "A": 0.0, "signal_bar": bar, "side": side,
                                   "sl": float(pos.sl)}
            self._close(pos, "RECUPERACAO_SEM_A")
            return
        code_sl = float(pos.sl) if pos.sl else float(pos.price_open) - side * float(self.g["sl_atr"]) * a
        old = tr.get("sl")
        if old is not None:
            code_sl = max(code_sl, float(old)) if side == BUY else min(code_sl, float(old))
        self.state["trade"] = {"ticket": int(pos.ticket), "A": float(a), "signal_bar": bar, "side": side, "sl": code_sl}
        self._save()
        self._csv("RECOVER", ticket=pos.ticket, signal_bar_server=bar, side=side, A=a, sl=code_sl, tp=pos.tp,
                  executed=pos.price_open)
        log.warning("[SWEEP48] posição #%s recuperada: lado=%+d A=%.2f SL em código=%.2f", pos.ticket, side, a, code_sl)

    # ------------------------------------------------------------ ordens
    def _filling(self) -> int:
        if self.filling_mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        if self.filling_mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        return self.mt5.ORDER_FILLING_RETURN

    def build_entry(self, side: int, a: float, tick: Any) -> Dict[str, Any]:
        price = float(tick.ask if side == BUY else tick.bid)
        return {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.lot,
                "type": self.mt5.ORDER_TYPE_BUY if side == BUY else self.mt5.ORDER_TYPE_SELL, "price": price,
                "sl": round(price - side * float(self.g["sl_atr"]) * a, self.digits),
                "tp": round(price + side * float(self.g["tp_atr"]) * a, self.digits),
                "deviation": int(self.g["deviation_points"]), "magic": self.magic, "comment": "SWEEP48",
                "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling()}

    def _send(self, req: Dict[str, Any]) -> Any:
        verify_account(self.mt5, self.cfg)
        return self.mt5.order_send(req)

    def _enter(self, side: int, a: float, bar: int, tick: Any) -> None:
        req = self.build_entry(side, a, tick)
        # grava a barra do sinal ANTES do envio: uma queda logo após o fill ainda recupera A
        self.state["trade"] = {"ticket": 0, "A": a, "signal_bar": bar, "side": side, "sl": req["sl"]}
        self._save()
        res = self._send(req)
        rc = getattr(res, "retcode", None)
        ok = res is not None and rc == self.mt5.TRADE_RETCODE_DONE
        fill = float(res.price) if ok else ""
        slip = round((fill - req["price"]) * side, self.digits) if ok else ""
        self._csv("ORDER", ticket=getattr(res, "order", ""), signal_bar_server=bar, side=side, A=a,
                  spread=round(tick.ask - tick.bid, self.digits), requested=req["price"], executed=fill, slippage=slip,
                  retcode=rc, sl=req["sl"], tp=req["tp"], detail=getattr(res, "comment", str(self.mt5.last_error())))
        if not ok:
            log.error("[SWEEP48] ordem recusada: retcode=%s %s", rc, getattr(res, "comment", self.mt5.last_error()))
            self.state["trade"] = None
            self._save()
            return
        self.state["trade"]["ticket"] = int(res.order)
        self._save()
        log.info("[SWEEP48] ORDEM EXECUTADA ticket=%s lado=%+d pedido=%.2f executado=%.2f slippage=%s sl=%.2f tp=%.2f",
                 res.order, side, req["price"], fill, slip, req["sl"], req["tp"])

    def _close(self, pos: Any, reason: str) -> bool:
        if time.time() - self.last_close_try < 1.0:
            return False
        self.last_close_try = time.time()
        tick = self.mt5.symbol_info_tick(self.symbol)
        is_buy = pos.type == self.mt5.POSITION_TYPE_BUY
        res = self._send({"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(pos.volume),
                          "type": self.mt5.ORDER_TYPE_SELL if is_buy else self.mt5.ORDER_TYPE_BUY,
                          "position": int(pos.ticket), "price": float(tick.bid if is_buy else tick.ask),
                          "deviation": int(self.g["deviation_points"]), "magic": self.magic, "comment": "SWEEP48 close",
                          "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling()})
        rc = getattr(res, "retcode", None)
        ok = res is not None and rc == self.mt5.TRADE_RETCODE_DONE
        if ok:
            self.exit_reason = reason
        log.log(logging.INFO if ok else logging.ERROR, "[SWEEP48] fechamento #%s (%s): retcode=%s", pos.ticket, reason, rc)
        if not ok:
            self._csv("CLOSE_FAIL", ticket=pos.ticket, retcode=rc, reason=reason)
        return ok

    def _sync_broker_sl(self, pos: Any, tr: Dict[str, Any], tick: Any) -> None:
        side, sl = tr["side"], round(float(tr["sl"]), self.digits)
        better = sl > float(pos.sl) + self.point / 2 if side == BUY else (not pos.sl or sl < float(pos.sl) - self.point / 2)
        if not better or time.time() - self.last_sl_send < 1.0:
            return
        self.last_sl_send = time.time()
        ref = float(tick.bid if side == BUY else tick.ask)
        min_dist = max(self.stops_level, 0) * self.point
        frozen = bool(pos.sl) and self.freeze_level > 0 and abs(ref - float(pos.sl)) <= self.freeze_level * self.point
        if (ref - sl) * side <= min_dist or frozen:
            self._csv("SL_VIRTUAL", ticket=pos.ticket, A=tr["A"], sl=sl, tp=pos.tp,
                      reason="stops_level" if not frozen else "freeze_level")
            log.warning("[SWEEP48] #%s stop virtual em %.2f (%s)", pos.ticket, sl, "freeze" if frozen else "stops_level")
            return
        res = self._send({"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol, "position": int(pos.ticket),
                          "sl": sl, "tp": float(pos.tp), "magic": self.magic})
        rc = getattr(res, "retcode", None)
        ok = res is not None and rc == self.mt5.TRADE_RETCODE_DONE
        self._csv("SL_CHANGE" if ok else "SL_VIRTUAL", ticket=pos.ticket, A=tr["A"], sl=sl, tp=pos.tp, retcode=rc,
                  reason="" if ok else "broker_recusou", detail=getattr(res, "comment", ""))
        if not ok:
            log.warning("[SWEEP48] broker recusou SL %.2f (retcode=%s): mantendo stop virtual", sl, rc)

    # ------------------------------------------------------------ fim do trade
    def _finish(self, ticket: int) -> None:
        deals = self.mt5.history_deals_get(position=ticket) if ticket else None
        out = [d for d in (deals or []) if int(d.entry) in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_OUT_BY)]
        if ticket and not out and self.missing_deal_tries < 50:     # histórico ainda não atualizou
            self.missing_deal_tries += 1
            return
        self.missing_deal_tries = 0
        tr = self.state.get("trade") or {}
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in (deals or []))
        reasons = {self.mt5.DEAL_REASON_SL: "SL", self.mt5.DEAL_REASON_TP: "TP"}
        reason = self.exit_reason or (reasons.get(int(out[-1].reason), "EXTERNO") if out else "SEM_HISTORICO")
        self._csv("EXIT", ticket=ticket, signal_bar_server=tr.get("signal_bar"), side=tr.get("side"), A=tr.get("A"),
                  exit_price=out[-1].price if out else "", profit=round(profit, 2), reason=reason)
        log.info("[SWEEP48] SAÍDA #%s (%s) resultado=%.2f USD", ticket, reason, profit)
        self.state["trade"], self.exit_reason = None, ""
        self.realized = self._realized()
        self._save()

    def _halt(self, reason: str) -> None:
        self.state["halted"], self.state["halt_reason"] = True, reason
        self._save()
        self._csv("HALT", reason=reason)
        log.critical("[SWEEP48] AGENTE PARADO: %s", reason)

    # ------------------------------------------------------------ tick
    def _manage(self, pos: Any, tick: Any) -> None:
        tr = self.state.get("trade")
        if not tr or not tr.get("A"):
            self._recover()
            return
        if int(tr.get("ticket") or 0) != int(pos.ticket):
            tr["ticket"] = int(pos.ticket)
            self._save()
        side, a, entry = tr["side"], float(tr["A"]), float(pos.price_open)
        if float(tick.time_msc) / 1000 - int(pos.time) >= float(self.g["max_minutes"]) * 60:
            self._close(pos, "TEMPO_240MIN")
            return
        new = trail_stop(side, entry, float(tr["sl"]), float(tick.bid), float(tick.ask), a,
                         float(self.g["trail_trigger_atr"]), float(self.g["trail_dist_atr"]))
        if new != tr["sl"]:
            tr["sl"] = new
        px = float(tick.bid if side == BUY else tick.ask)
        if (px <= tr["sl"]) if side == BUY else (px >= tr["sl"]):
            self._close(pos, "STOP_EM_CODIGO")
            return
        self._sync_broker_sl(pos, tr, tick)

    def _on_new_bar(self, pos: Optional[Any], tick: Any) -> None:
        df = self._bars(MIN_BARS)
        if df is None or len(df) < 400:
            return
        row = add_indicators(df).iloc[-1]
        bar = int(row.time)
        if bar == int(self.state.get("last_bar") or 0):
            return
        self.state["last_bar"] = bar
        self._save()
        if float(tick.time) - (bar + 300) > float(self.g["signal_max_age_seconds"]):
            return                                  # reinício tardio: não opera sinal velho
        side = signal_at(row, int(self.g["start_hour"]), int(self.g["end_hour"]))
        if side == 0:
            return
        a = float(row.atr)
        ignored = pos is not None or bool(self.state.get("trade"))
        self._csv("SIGNAL", signal_bar_server=bar, side=side, A=round(a, self.digits),
                  spread=round(tick.ask - tick.bid, self.digits), reason="ignorado_posicao_aberta" if ignored else "")
        log.info("[SWEEP48] SINAL %+d barra=%s A=%.2f%s", side, bar, a, " (ignorado: posição aberta)" if ignored else "")
        if not ignored:
            self._enter(side, a, bar, tick)

    def step(self) -> None:
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None or int(tick.time_msc) == self.last_msc:
            return
        self.last_msc = int(tick.time_msc)
        pos = self._position()
        if pos is not None and self.realized + float(pos.profit) + float(pos.swap) <= self.limit:
            if not self.state["halted"]:
                self._halt(f"limite de perda atingido: {self.realized + float(pos.profit) + float(pos.swap):.2f} <= {self.limit:.2f} USD")
            self._close(pos, "LIMITE_PERDA")
            return
        if self.state["halted"]:
            if pos is not None:
                self._close(pos, "AGENTE_PARADO")
            elif self.state.get("trade"):
                self._finish(int(self.state["trade"].get("ticket") or 0))
            return
        if pos is not None:
            self._manage(pos, tick)
        elif self.state.get("trade") and int(self.state["trade"].get("ticket") or 0):
            self._finish(int(self.state["trade"]["ticket"]))
            if self.realized <= self.limit and not self.state.get("trade"):
                self._halt(f"limite de perda atingido: {self.realized:.2f} <= {self.limit:.2f} USD")
                return
        head = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_M5, 0, 1)
        if head is None or len(head) == 0 or int(head[0]["time"]) == self.last_head:
            return
        self.last_head = int(head[0]["time"])
        self._on_new_bar(pos, tick)

    def run_forever(self) -> None:
        pause = float(self.g.get("poll_ms", 50)) / 1000
        last_hb = 0.0
        while True:
            self.step()
            if time.time() - last_hb >= 60:
                last_hb = time.time()
                log.info("[SWEEP48 HEARTBEAT] trade=%s | acumulado=%.2f USD | parado=%s",
                         bool(self.state.get("trade")), self.realized, self.state["halted"])
            time.sleep(pause)
