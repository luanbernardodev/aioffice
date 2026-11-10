"""AGENTE_RSI7_H1 — BTCUSD H1, magic exclusivo, determinístico (sem LLM). Regras em agents/rsi7_h1_rules.py.

A cada H1 fechada:
  * posição aberta: recalcula o stop móvel (trail x ATR a partir do extremo desde a barra de entrada, só aperta)
    e envia ao broker; se o broker recusar, o stop fica virtual e fecha a mercado ao ser tocado;
  * sem posição: RSI(n) cruza acima de lo com close > MA -> BUY; cruza abaixo de 100-lo com close < MA -> SELL,
    a mercado (= open da barra seguinte do backtest), SL inicial sl_atr x ATR, TP opcional.

Limites FIXOS no código (não configuráveis): máx. 1 posição; só conta DEMO; kill switch pelo arquivo
state/KILL_AGENTE_RSI7_H1 ou kill_switch: true no YAML (zera e não abre novas).
Trava de perda diária DESLIGADA (DAILY_LOSS_PCT = 0) desde 2026-11-10: com saldo demo ~US$137, 2% (~US$2,75) era
menor que um stop de 1xATR H1 (~US$5,8 com 0.01 lote) e cortava os perdedores antes do SL, fugindo do backtest.
Para religar, ponha um valor > 0 (perda do dia deste magic, realizada + flutuante, em % do saldo do início do dia).
"""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from agents import rsi7_h1_rules as R
from engine.config import ROOT
from engine.features import server_to_utc
from engine.mt5_broker import AccountGuardError, verify_account

log = logging.getLogger("agents.rsi7_h1")

# ----------------------------------------------------------------- limites fixos
MAX_POSITIONS = 1
DAILY_LOSS_PCT = 0.0             # 0 = trava de perda diária desligada (ver docstring)
DEMO_ONLY = True
H1 = 3600

TAG = "[AGENTE_RSI7_H1]"
CONFIG_PATH = ROOT / "config" / "agente_rsi7_h1.yaml"
SECTION = "agente_rsi7_h1"
KILL_FILE = ROOT / "state" / "KILL_AGENTE_RSI7_H1"
CSV_FIELDS = ["ts_utc", "event", "ticket", "signal_bar_server", "side", "A", "spread", "requested", "executed",
              "slippage", "retcode", "sl", "tp", "exit_price", "profit", "reason", "detail"]


def load_agent_config(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)[SECTION]


class Rsi7H1Agent:
    def __init__(self, mt5: Any, cfg: Dict[str, Any], g: Dict[str, Any], state_path: Optional[Path] = None,
                 csv_path: Optional[Path] = None, kill_file: Optional[Path] = None,
                 config_path: Optional[Path] = None) -> None:
        self.mt5, self.cfg, self.g = mt5, cfg, g
        self.p = g["strategy"]
        self.name = g.get("name", SECTION)
        self.symbol = g["symbol"]
        self.magic = int(g["magic"])
        self.lot = float(g["lot"])
        self.server_time = cfg.get("account", {}).get("server_time", "ny_plus_7")
        self.state_path = Path(state_path or ROOT / "state" / f"{self.name}.json")
        self.csv_path = Path(csv_path or ROOT / "logs" / f"{self.name}_trades.csv")
        self.kill_file = Path(kill_file or KILL_FILE)
        self.config_path = config_path
        self.state: Dict[str, Any] = {"last_bar": 0, "trades": {}, "day": "", "day_start_balance": 0.0,
                                      "blocked_day": ""}
        self.last_head = 0
        self.last_cfg_read = 0.0
        self.last_realized_read = 0.0
        self.realized_today = 0.0
        self.last_close_try: Dict[str, float] = {}
        self.missing: Dict[str, int] = {}
        self.kill_logged = False

    # ------------------------------------------------------------ persistência e log
    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self.state.update(json.loads(self.state_path.read_text()))
            except (ValueError, OSError) as exc:
                log.error("%s estado ilegível (%s): seguindo só com dados do MT5", TAG, exc)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_path)

    def _csv(self, event: str, **kw: Any) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"ts_utc": datetime.now(timezone.utc).isoformat(), "event": event, **kw})

    # ------------------------------------------------------------ inicialização
    def _check_account(self) -> Any:
        info = self.mt5.account_info()
        if info is None:
            raise AccountGuardError("MT5 sem conta conectada")
        if DEMO_ONLY and int(info.trade_mode) != int(getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)):
            raise AccountGuardError(f"{self.name} roda só em conta DEMO; conta #{info.login} recusada")
        return verify_account(self.mt5, self.cfg)

    def start(self) -> None:
        self._check_account()
        self.mt5.symbol_select(self.symbol, True)
        si = self.mt5.symbol_info(self.symbol)
        self.point, self.digits = float(si.point), int(si.digits)
        self.stops_level, self.freeze_level = int(si.trade_stops_level), int(si.trade_freeze_level)
        self.contract, self.filling_mode = float(si.trade_contract_size), int(si.filling_mode)
        if self.lot < float(si.volume_min):
            raise ValueError(f"lote {self.lot} abaixo do mínimo {si.volume_min} de {self.symbol}")
        self._load()
        self._roll_day(force_read=True)
        log.info("%s %s magic=%s lote=%s contract=%s | RSI(%s) %s/%s + %s%s | SL %sxATR trail %sxATR ativ %sR BE %sR "
                 "TP %sxATR | máx %d posição, perda diária %s (saldo início do dia %.2f), só DEMO", TAG,
                 self.symbol, self.magic, self.lot, self.contract, self.p["rsi_period"], self.p["rsi_level"],
                 100 - float(self.p["rsi_level"]), self.p["ma_type"].upper(), self.p["ma_period"], self.p["sl_atr"],
                 self.p["trail_atr"], self.p["trail_activate_r"], self.p["breakeven_r"], self.p["tp_atr"],
                 MAX_POSITIONS, f"{DAILY_LOSS_PCT:.1f}%" if DAILY_LOSS_PCT > 0 else "DESLIGADA",
                 self.state["day_start_balance"])
        for pos in self._positions():
            if str(pos.ticket) not in self.state["trades"]:
                self._adopt(pos)
        self._save()

    # ------------------------------------------------------------ leitura do MT5
    def _positions(self) -> List[Any]:
        return [p for p in (self.mt5.positions_get(symbol=self.symbol) or []) if int(p.magic) == self.magic]

    def _bars(self) -> Optional[pd.DataFrame]:
        r = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_H1, 1, int(self.g.get("bars", 1500)))
        if r is None or len(r) < 300:
            return None
        return R.add_indicators(pd.DataFrame(r), self.p)

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _read_realized_today(self) -> float:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        deals = self.mt5.history_deals_get(now - timedelta(days=2), now + timedelta(days=2)) or []
        mine = [d for d in deals if int(d.magic) == self.magic and int(d.type) in (0, 1)]
        if not mine:
            return 0.0
        utc = server_to_utc([int(d.time) for d in mine], self.server_time)
        return float(sum(float(d.profit) + float(d.swap) + float(d.commission)
                         for d, t in zip(mine, utc) if t >= pd.Timestamp(start)))

    def _roll_day(self, force_read: bool = False) -> None:
        today = self._today()
        if force_read or self.state.get("day") != today or time.time() - self.last_realized_read >= 60:
            self.realized_today = self._read_realized_today()
            self.last_realized_read = time.time()
        if self.state.get("day") != today:
            bal = float(self.mt5.account_info().balance)
            # reinício no meio do dia: o saldo atual já inclui o realizado de hoje
            self.state["day"] = today
            self.state["day_start_balance"] = bal - self.realized_today if force_read else bal
            self._save()

    def _reload_config(self) -> None:
        if time.time() - self.last_cfg_read < 60:
            return
        self.last_cfg_read = time.time()
        try:
            g = load_agent_config(self.config_path)
            self.g["kill_switch"] = bool(g.get("kill_switch", False))
        except Exception as exc:  # noqa: BLE001 — YAML quebrado não derruba o agente; mantém o último valor
            log.error("%s não consegui reler o config (%s); mantendo kill_switch=%s", TAG, exc, self.g.get("kill_switch"))

    def killed(self) -> bool:
        return self.kill_file.exists() or bool(self.g.get("kill_switch", False))

    # ------------------------------------------------------------ ordens
    def _filling(self) -> int:
        if self.filling_mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        if self.filling_mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: Dict[str, Any]) -> Any:
        self._check_account()
        return self.mt5.order_send(req)

    def _ok(self, res: Any) -> bool:
        return res is not None and getattr(res, "retcode", None) == self.mt5.TRADE_RETCODE_DONE

    def build_entry(self, side: int, a: float, tick: Any) -> Dict[str, Any]:
        price = float(tick.ask if side == R.BUY else tick.bid)
        return {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": self.lot,
                "type": self.mt5.ORDER_TYPE_BUY if side == R.BUY else self.mt5.ORDER_TYPE_SELL, "price": price,
                "sl": round(R.initial_stop(side, price, a, float(self.p["sl_atr"])), self.digits),
                "tp": round(R.take_profit(side, price, a, float(self.p["tp_atr"])), self.digits),
                "deviation": int(self.g["deviation_points"]), "magic": self.magic, "comment": "RSI7_H1",
                "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling()}

    def _enter(self, side: int, a: float, bar: int, tick: Any) -> None:
        if len(self._positions()) >= MAX_POSITIONS:
            log.warning("%s sinal ignorado: já há %d posição(ões) deste magic", TAG, MAX_POSITIONS)
            return
        req = self.build_entry(side, a, tick)
        res = self._send(req)
        rc = getattr(res, "retcode", None)
        ok = self._ok(res)
        fill = float(res.price) if ok else ""
        self._csv("ORDER", ticket=getattr(res, "order", ""), signal_bar_server=bar, side=side, A=round(a, 2),
                  spread=round(tick.ask - tick.bid, self.digits), requested=req["price"], executed=fill,
                  slippage=round((fill - req["price"]) * side, self.digits) if ok else "", retcode=rc, sl=req["sl"],
                  tp=req["tp"], detail=getattr(res, "comment", str(self.mt5.last_error())))
        if not ok:
            log.error("%s ordem recusada: retcode=%s %s", TAG, rc, getattr(res, "comment", self.mt5.last_error()))
            return
        risk = float(self.p["sl_atr"]) * a
        self.state["trades"][str(int(res.order))] = {
            "ticket": int(res.order), "side": side, "entry": fill or req["price"], "A": a, "risk": risk,
            "stop0": req["sl"], "stop": req["sl"], "entry_bar": int(bar) + H1, "signal_bar": int(bar)}
        self._save()
        log.info("%s %s ticket=%s pedido=%.2f executado=%.2f SL=%.2f TP=%.2f A=%.2f", TAG,
                 "COMPRA" if side == R.BUY else "VENDA", res.order, req["price"], fill, req["sl"], req["tp"], a)

    def _close(self, pos: Any, reason: str) -> bool:
        key = str(pos.ticket)
        if time.time() - self.last_close_try.get(key, 0.0) < 1.0:
            return False
        self.last_close_try[key] = time.time()
        tick = self.mt5.symbol_info_tick(self.symbol)
        is_buy = int(pos.type) == int(self.mt5.POSITION_TYPE_BUY)
        res = self._send({"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(pos.volume),
                          "type": self.mt5.ORDER_TYPE_SELL if is_buy else self.mt5.ORDER_TYPE_BUY,
                          "position": int(pos.ticket), "price": float(tick.bid if is_buy else tick.ask),
                          "deviation": int(self.g["deviation_points"]), "magic": self.magic,
                          "comment": "RSI7_H1 close", "type_time": self.mt5.ORDER_TIME_GTC,
                          "type_filling": self._filling()})
        ok = self._ok(res)
        if ok and key in self.state["trades"]:
            self.state["trades"][key]["exit_reason"] = reason
            self._save()
        log.log(logging.INFO if ok else logging.ERROR, "%s fechamento #%s (%s): retcode=%s", TAG, pos.ticket, reason,
                getattr(res, "retcode", None))
        if not ok:
            self._csv("CLOSE_FAIL", ticket=pos.ticket, retcode=getattr(res, "retcode", None), reason=reason)
        return ok

    def _set_sl(self, pos: Any, tr: Dict[str, Any], tick: Any) -> None:
        side, sl = int(tr["side"]), round(float(tr["stop"]), self.digits)
        if not R.tighter(side, sl, float(pos.sl) or None):
            return
        ref = float(tick.bid if side == R.BUY else tick.ask)
        frozen = bool(pos.sl) and self.freeze_level > 0 and abs(ref - float(pos.sl)) <= self.freeze_level * self.point
        if (ref - sl) * side <= max(self.stops_level, 0) * self.point or frozen:
            self._csv("SL_VIRTUAL", ticket=pos.ticket, A=tr["A"], sl=sl, reason="freeze_level" if frozen else "stops_level")
            log.warning("%s #%s stop virtual em %.2f", TAG, pos.ticket, sl)
            return
        res = self._send({"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol, "position": int(pos.ticket),
                          "sl": sl, "tp": float(pos.tp), "magic": self.magic})
        ok = self._ok(res)
        self._csv("SL_CHANGE" if ok else "SL_VIRTUAL", ticket=pos.ticket, A=tr["A"], sl=sl, tp=pos.tp,
                  retcode=getattr(res, "retcode", None), reason="" if ok else "broker_recusou",
                  detail=getattr(res, "comment", ""))
        if ok:
            log.info("%s #%s SL -> %.2f", TAG, pos.ticket, sl)
        else:
            log.warning("%s broker recusou SL %.2f (retcode=%s): stop virtual", TAG, sl, getattr(res, "retcode", None))

    # ------------------------------------------------------------ recuperação e fim do trade
    def _adopt(self, pos: Any) -> None:
        side = R.BUY if int(pos.type) == int(self.mt5.POSITION_TYPE_BUY) else R.SELL
        entry_bar = int(pos.time) - int(pos.time) % H1
        d = self._bars()
        a = None
        if d is not None:
            prev = d[d["time"] < entry_bar]
            a = float(prev["atr"].iat[-1]) if len(prev) else None
        if not a and pos.sl:
            a = abs(float(pos.price_open) - float(pos.sl)) / float(self.p["sl_atr"])
        if not a:
            log.error("%s posição #%s sem ATR e sem SL: fechando por segurança", TAG, pos.ticket)
            self.state["trades"][str(pos.ticket)] = {"ticket": int(pos.ticket), "side": side, "entry": float(pos.price_open),
                                                     "A": 0.0, "risk": 0.0, "stop0": 0.0, "stop": 0.0,
                                                     "entry_bar": entry_bar, "signal_bar": entry_bar - H1}
            self._close(pos, "RECUPERACAO_SEM_ATR")
            return
        risk = float(self.p["sl_atr"]) * a
        stop0 = float(pos.sl) or R.initial_stop(side, float(pos.price_open), a, float(self.p["sl_atr"]))
        self.state["trades"][str(pos.ticket)] = {"ticket": int(pos.ticket), "side": side, "entry": float(pos.price_open),
                                                 "A": a, "risk": risk, "stop0": stop0, "stop": stop0,
                                                 "entry_bar": entry_bar, "signal_bar": entry_bar - H1}
        self._csv("RECOVER", ticket=pos.ticket, side=side, A=round(a, 2), sl=stop0, executed=pos.price_open)
        log.warning("%s posição #%s adotada: lado=%+d A=%.2f stop=%.2f", TAG, pos.ticket, side, a, stop0)
        if d is not None:
            self._trail(pos, d, self.mt5.symbol_info_tick(self.symbol))

    def _finish(self, key: str) -> None:
        deals = self.mt5.history_deals_get(position=int(key)) or []
        out = [d for d in deals if int(d.entry) in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_OUT_BY)]
        if not out and self.missing.get(key, 0) < 50:      # histórico ainda não atualizou
            self.missing[key] = self.missing.get(key, 0) + 1
            return
        tr = self.state["trades"].pop(key)
        self.missing.pop(key, None)
        profit = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in deals)
        reasons = {self.mt5.DEAL_REASON_SL: "SL", self.mt5.DEAL_REASON_TP: "TP"}
        reason = tr.get("exit_reason") or (reasons.get(int(out[-1].reason), "EXTERNO") if out else "SEM_HISTORICO")
        self._csv("EXIT", ticket=key, signal_bar_server=tr.get("signal_bar"), side=tr.get("side"), A=tr.get("A"),
                  exit_price=out[-1].price if out else "", profit=round(profit, 2), reason=reason)
        log.info("%s SAÍDA #%s (%s) resultado=%.2f USD", TAG, key, reason, profit)
        self.last_realized_read = 0.0
        self._save()

    # ------------------------------------------------------------ barra H1 fechada
    def _trail(self, pos: Any, d: pd.DataFrame, tick: Any) -> None:
        tr = self.state["trades"].get(str(pos.ticket))
        if not tr or not tr.get("A") or tick is None:
            return
        since = d[d["time"] >= int(tr["entry_bar"])]
        new = R.trailing_stop(int(tr["side"]), float(tr["entry"]), float(tr["stop0"]), float(tr["risk"]),
                              since["high"].to_numpy(), since["low"].to_numpy(), since["atr"].to_numpy(),
                              float(tick.ask - tick.bid), float(self.p["trail_atr"]), float(self.p["trail_activate_r"]),
                              float(self.p["breakeven_r"]))
        if R.tighter(int(tr["side"]), new, float(tr["stop"])):
            tr["stop"] = new
            self._save()
        self._set_sl(pos, tr, tick)

    def _on_new_bar(self, tick: Any) -> None:
        d = self._bars()
        if d is None:
            return
        bar = int(d["time"].iat[-1])
        if bar == int(self.state.get("last_bar") or 0):
            return
        self.state["last_bar"] = bar
        self._save()
        positions = self._positions()
        for pos in positions:
            self._trail(pos, d, tick)
        side = R.signal_last(d, self.p)
        if side == 0:
            return
        a = float(d["atr"].iat[-1])
        age = float(tick.time) - (bar + H1)
        busy = len(positions) >= MAX_POSITIONS
        late = age > float(self.g["signal_max_age_seconds"])
        blocked = self.state.get("blocked_day") == self._today() or self.killed()
        why = "posicao_aberta" if busy else "sinal_atrasado" if late else "bloqueado" if blocked else ""
        self._csv("SIGNAL", signal_bar_server=bar, side=side, A=round(a, 2), spread=round(tick.ask - tick.bid, self.digits),
                  reason=f"RSI={d['rsi'].iat[-1]:.1f} MA={d['ma'].iat[-1]:.2f}", detail=f"ignorado_{why}" if why else "")
        log.info("%s SINAL %+d barra=%s RSI=%.1f close=%.2f MA=%.2f A=%.2f%s", TAG, side, bar, d["rsi"].iat[-1],
                 d["close"].iat[-1], d["ma"].iat[-1], a, f" (ignorado: {why})" if why else "")
        if not why:
            self._enter(side, a, bar, tick)

    # ------------------------------------------------------------ loop
    def step(self) -> None:
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return
        self._reload_config()
        self._roll_day()
        positions = self._positions()
        live = {str(p.ticket) for p in positions}
        for key in [k for k in self.state["trades"] if k not in live]:
            self._finish(key)
        for p in positions:
            if str(p.ticket) not in self.state["trades"]:
                self._adopt(p)

        if self.killed():
            if not self.kill_logged:
                self.kill_logged = True
                self._csv("KILL", reason="arquivo" if self.kill_file.exists() else "config")
                log.critical("%s KILL SWITCH ativo: zerando e sem novas entradas", TAG)
            for p in positions:
                self._close(p, "KILL_SWITCH")
            return
        if self.kill_logged:
            self.kill_logged = False
            log.warning("%s kill switch desligado: agente volta a operar", TAG)

        today = self._today()
        floating = sum(float(p.profit) + float(p.swap) for p in positions)
        day_pnl = self.realized_today + floating
        if self.state.get("blocked_day") != today and R.daily_loss_hit(day_pnl, float(self.state["day_start_balance"]),
                                                                        DAILY_LOSS_PCT):
            self.state["blocked_day"] = today
            self._save()
            self._csv("DAILY_LOSS", profit=round(day_pnl, 2),
                      reason=f">= {DAILY_LOSS_PCT}% de {self.state['day_start_balance']:.2f}")
            log.critical("%s PERDA DIÁRIA %.2f USD >= %.1f%% do saldo: zerando e bloqueado até 00:00 UTC", TAG,
                         day_pnl, DAILY_LOSS_PCT)
        if self.state.get("blocked_day") == today:
            for p in positions:
                self._close(p, "PERDA_DIARIA")
            return

        for p in sorted(positions, key=lambda x: int(x.time))[MAX_POSITIONS:]:    # nunca deveria acontecer
            self._close(p, "EXCESSO_DE_POSICOES")
        for p in positions[:MAX_POSITIONS]:
            tr = self.state["trades"].get(str(p.ticket))
            if tr and tr.get("stop") and R.stop_hit(int(tr["side"]), float(tick.bid), float(tick.ask), float(tr["stop"])):
                self._close(p, "STOP_EM_CODIGO")

        head = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_H1, 0, 1)
        if head is None or len(head) == 0 or int(head[0]["time"]) == self.last_head:
            return
        self.last_head = int(head[0]["time"])
        self._on_new_bar(tick)

    def run_forever(self) -> None:
        pause = float(self.g.get("poll_seconds", 1.0))
        last_hb = 0.0
        while True:
            self.step()
            if time.time() - last_hb >= 300:
                last_hb = time.time()
                log.info("%s HEARTBEAT posições=%d | dia=%.2f USD (saldo início %.2f) | bloqueado=%s | kill=%s", TAG,
                         len(self.state["trades"]), self.realized_today, self.state["day_start_balance"],
                         self.state.get("blocked_day") == self._today(), self.killed())
            time.sleep(pause)
