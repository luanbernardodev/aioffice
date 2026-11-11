"""Correções de 11/11: risco agrupado A2, trailing sem spam 10025, filtro de spread BTC, cache do calendário,
log de não-entrada do BTCFLIP e registro do motivo dos reinícios."""
import time
import types
from datetime import datetime, timezone

import pandas as pd
import pytest

from agents.goldflip_supervisor import control_mismatch
from engine import lifecycle
from engine.core import Engine
from engine.live import loss_streak
from engine.mt5_broker import MT5Broker
from engine.regime import CalendarFeed, NewsCalendar, check_gates, spread_limit
from engine.risk import RiskManager, split_volume
from engine.sim_broker import SimBroker
from engine.types import BUY, SELL, ClosedTrade, OrderIntent, Position

T = datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ 1. A2: LIMITs FIB dividem 1R
def test_split_volume():
    assert split_volume(0.03, 3, 0.01, 0.01) == (0.01, 3)
    assert split_volume(0.10, 3, 0.01, 0.01) == (0.03, 3)          # 0.09 no total, nunca acima de 1R
    assert split_volume(0.01, 3, 0.01, 0.01) == (0.01, 1)          # não cabe dividir: só 1 ordem
    assert split_volume(0.10, 3, 0.10, 0.01) == (0.10, 1)          # US500Cash: volume_min 0.1
    assert split_volume(0.20, 3, 0.10, 0.01) == (0.10, 2)
    assert split_volume(0.005, 3, 0.01, 0.01) == (0.0, 0)


def fib(key, group="imp1", level="0.5"):
    return OrderIntent(key, "A2_PULLBACK", "GOLD", BUY, "LIMIT", 100.0, 98.0, 106.0, f"FIB_LIMIT_{level}", group,
                       atr=2.0, spread=0.1)


def engine_with(cfg, lot, vmin, step=0.01):
    cfg["symbols"]["GOLD"]["lot"] = lot
    b = SimBroker({"GOLD": {"value_per_unit": 100.0, "volume_min": vmin, "volume_step": step}})
    return Engine(cfg, b), b


def test_fib_limits_share_one_r(cfg):
    eng, b = engine_with(cfg, 0.03, 0.01)
    now = pd.Timestamp(T)
    eng._reconcile("GOLD", [fib("a", level="0.5"), fib("b", level="0.559"), fib("c", level="0.618")], now, None)
    vols = [p.volume for p in b.pending.values()]
    assert len(vols) == 3 and sum(vols) == pytest.approx(0.03)


def test_fib_limits_reduced_when_lot_cannot_be_split(cfg):
    eng, b = engine_with(cfg, 0.10, 0.10)                          # US500Cash: lote = volume mínimo
    now = pd.Timestamp(T)
    eng._reconcile("GOLD", [fib("a", level="0.5"), fib("b", level="0.559"), fib("c", level="0.618")], now, None)
    assert list(b.pending) == ["a"] and b.pending["a"].volume == pytest.approx(0.10)
    # a primeira executou: as outras do mesmo impulso não entram mais (1R já usado)
    eng.fib_fills[("A2_PULLBACK", "GOLD", "imp1")] = 1
    eng._reconcile("GOLD", [fib("b", level="0.559"), fib("c", level="0.618")], now, None)
    assert "b" not in b.pending and "c" not in b.pending


def closed(pnl, setup="FIB_LIMIT_0.5", group="imp1"):
    ts = pd.Timestamp(T)
    return ClosedTrade("A2_PULLBACK", setup, "GOLD", BUY, 0.01, 100, 99, 102, 101.5, 99, ts, ts, "SL", pnl, -1.0,
                       0.1, 1.0, group=group)


def test_fib_group_counts_as_one_loss(cfg):
    rm = RiskManager(cfg)
    rm.daily_stop = 1e9
    for _ in range(3):
        rm.on_trade_closed(closed(-1))                              # 3 LIMITs do mesmo impulso no SL
    assert rm.streak == 1
    rm.on_trade_closed(closed(-1, group="imp2"))
    rm.on_trade_closed(closed(-1, setup="BOS_RETEST", group="bos1"))
    assert rm.streak == 3
    rm.on_trade_closed(closed(+1, group="imp3"))
    assert rm.streak == 0


def test_seed_streak_groups_fib_closed_together():
    r = [(-1, 1000, "US500Cash", False), (-1, 2000, "US500Cash", True), (-1, 2010, "US500Cash", True),
         (-1, 2020, "US500Cash", True)]
    assert loss_streak(r) == 2
    assert loss_streak(r + [(+1, 3000, "US500Cash", False)]) == 0


# ------------------------------------------------------------------ 2. trailing: digits, 1 tick, 10025
class FakeMT5:
    TRADE_ACTION_SLTP, TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED = 6, 10009, 10008
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, retcode=10009):
        self.sent, self.retcode = [], retcode

    def account_info(self):
        return types.SimpleNamespace(login=309673774, trade_mode=0)

    def symbol_info(self, s):
        return types.SimpleNamespace(digits=2, trade_tick_size=0.25)

    def order_send(self, req):
        self.sent.append(req)
        return types.SimpleNamespace(retcode=self.retcode, comment="")

    def last_error(self):
        return (0, "")


def mt5_broker(cfg, mt5, sl=100.0, side=BUY):
    b = MT5Broker.__new__(MT5Broker)
    b.mt5, b.cfg, b.specs = mt5, cfg, {"US500Cash": {"digits": 2}}
    b.positions = {"7": Position("7", "k", "A2_PULLBACK", "US500Cash", side, 0.1, 105.0, sl, 120.0, 110.0, 100.0,
                                 "S", "g", pd.Timestamp(T))}
    return b


def test_trailing_rounds_to_tick_and_skips_small_moves(cfg):
    mt5 = FakeMT5()
    b = mt5_broker(cfg, mt5)
    assert not b.modify_sl("7", 100.1)            # arredonda p/ 100.0: melhora 0 < 1 tick -> nada enviado
    assert b.modify_sl("7", 100.2)                # arredonda p/ 100.25: melhora = 1 tick -> envia
    assert mt5.sent[-1]["sl"] == 100.25
    mt5.sent.clear()
    b.positions["7"].sl = 100.0
    assert b.modify_sl("7", 100.30)                # 100.25
    assert mt5.sent[-1]["sl"] == 100.25 and b.positions["7"].sl == 100.25
    assert not b.modify_sl("7", 100.36)            # 100.25 de novo: sem melhora -> nada enviado
    assert not b.modify_sl("7", 100.10)            # pior -> nada enviado
    assert len(mt5.sent) == 1


def test_trailing_sell_side(cfg):
    mt5 = FakeMT5()
    b = mt5_broker(cfg, mt5, sl=110.0, side=SELL)
    assert not b.modify_sl("7", 109.9)             # 110.0 arredondado: sem melhora
    assert b.modify_sl("7", 109.7)                 # 109.75
    assert mt5.sent[-1]["sl"] == 109.75


def test_retcode_10025_is_noop_without_retry(cfg, caplog):
    mt5 = FakeMT5(retcode=10025)
    b = mt5_broker(cfg, mt5)
    with caplog.at_level("ERROR"):
        assert not b.modify_sl("7", 101.0)
        assert not b.modify_sl("7", 101.0)        # SL já gravado como 101.0: não reenvia
    assert len(mt5.sent) == 1 and not caplog.records


# ------------------------------------------------------------------ 3. filtro de spread
def test_spread_limit_prefers_fixed_then_h1():
    assert spread_limit({"max_spread": 60, "max_spread_atr_h1": 0.25}, 20.0, 300.0) == (60.0, "fixo")
    assert spread_limit({"max_spread_atr_h1": 0.25, "max_spread_atr": 0.5}, 20.0, 300.0)[0] == pytest.approx(75.0)
    assert spread_limit({"max_spread_atr_h1": 0.25, "max_spread_atr": 0.5}, 20.0, float("nan"))[0] == 10.0
    assert spread_limit({"max_spread_atr": 0.5}, 20.0, None)[0] == 10.0


def test_btc_gate_uses_h1_atr(cfg):
    g = cfg["symbols"]["BTCUSD"]
    assert not check_gates(T, g, spread=40.0, atr_m5=24.5).ok             # regra antiga: 0.5 x ATR M5 = 12
    assert check_gates(T, g, spread=40.0, atr_m5=24.5, atr_h1=355.0).ok   # 0.25 x ATR H1 = 88
    r = check_gates(T, g, spread=40.0, atr_m5=24.5, atr_h1=120.0)
    assert not r.ok and "ATR_H1" in r.reason


def test_spread_blocked_entries_are_counted_per_day(cfg):
    eng = Engine(cfg, SimBroker({"BTCUSD": {"value_per_unit": 1.0}}))
    eng._roll_block_day(T)
    a = OrderIntent("x", "A4_RSI_REVERSAL", "BTCUSD", BUY, "MARKET", 1, 0, 2, "RSI_OVERSOLD", "g", atr=1.0)
    eng._count_spread_block("BTCUSD", [a], "spread")
    eng._count_spread_block("BTCUSD", [a], "spread")                     # mesmo sinal na barra seguinte
    assert eng.spread_block_summary() == "BTCUSD=1" and eng.spread_blocked_bars["BTCUSD"] == 2
    eng._roll_block_day(datetime(2026, 11, 12, 0, 5, tzinfo=timezone.utc))
    assert eng.spread_block_summary() == ""


# ------------------------------------------------------------------ 4. BTCFLIP: EA recebe enabled?
def test_control_mismatch_detects_ea_not_receiving():
    now = int(time.time())
    ctl = {"enabled": True, "updated_at": now - 200}
    assert "NÃO recebeu" in control_mismatch(ctl, {"updated_at": now - 10, "control_enabled": False, "control_age_s": 900})
    assert control_mismatch(ctl, {"updated_at": now - 10, "control_enabled": True}) == ""
    assert control_mismatch({"enabled": True, "updated_at": now - 5}, {"updated_at": now, "control_enabled": False}) == ""
    assert control_mismatch(ctl, {"updated_at": now - 999, "control_enabled": False}) == ""


# ------------------------------------------------------------------ 5. calendário: cache em disco + 429
EV = [{"country": "USD", "impact": "High", "title": "CPI m/m", "date": "2026-11-12T08:30:00-05:00"}]


def test_calendar_disk_cache_survives_restart(tmp_path):
    clock = [1_000_000.0]
    calls = []
    path = tmp_path / "ff.json"
    f1 = CalendarFeed(fetch=lambda: calls.append(1) or EV, cache_path=path, clock=lambda: clock[0])
    assert f1.cycle() == CalendarFeed.OK_SECONDS and len(calls) == 1
    clock[0] += 3600                                                       # "reinício" 1 h depois
    f2 = CalendarFeed(fetch=lambda: calls.append(1) or EV, cache_path=path, clock=lambda: clock[0])
    cal = NewsCalendar(["CPI"], 30)
    f2._subs.append(cal)
    assert f2.cycle() == pytest.approx(5 * 3600) and len(calls) == 1 and cal._events
    clock[0] += 6 * 3600                                                   # cache vencido -> baixa
    f2.cycle()
    assert len(calls) == 2


def test_calendar_429_honors_retry_after_and_uses_stale_cache(tmp_path):
    path = tmp_path / "ff.json"
    CalendarFeed(fetch=lambda: EV, cache_path=path, clock=lambda: 0.0).cycle()

    class Http429(Exception):
        response = types.SimpleNamespace(status_code=429, headers={"Retry-After": "1800"})

    def fail():
        raise Http429("429 Too Many Requests")

    feed = CalendarFeed(fetch=fail, cache_path=path, clock=lambda: 10 * 3600.0)
    cal = NewsCalendar(["CPI"], 30)
    feed._subs.append(cal)
    assert feed.cycle() == 1800 and cal._events                           # vencido, mas melhor que nada


# ------------------------------------------------------------------ 6. motivo dos reinícios
def test_lifecycle_records_exit_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "STATE_FILE", tmp_path / "life.json")
    monkeypatch.setattr(lifecycle, "RESTARTS_LOG", tmp_path / "restarts.log")
    assert lifecycle.on_start() == "primeira execução registrada"
    try:
        raise RuntimeError("MT5 sem conta conectada")
    except RuntimeError as exc:
        lifecycle.record_exit(f"exceção não tratada: {exc}", exc)
    why = lifecycle.on_start()
    assert "saiu em" in why and "MT5 sem conta conectada" in why
    why2 = lifecycle.on_start()                                            # anterior não registrou saída
    assert "SEM registro de saída" in why2
    assert (tmp_path / "restarts.log").read_text(encoding="utf-8").count("start") == 3
