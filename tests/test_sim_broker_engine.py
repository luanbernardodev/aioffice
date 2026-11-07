import types

import pandas as pd
import pytest

from backtest.simulate import metrics, run_portfolio
from engine.core import Engine
from engine.mt5_broker import AccountGuardError, verify_account
from engine.sim_broker import SimBroker
from engine.types import BUY, SELL, OrderIntent
from tests.conftest import random_walk, resample

T0 = pd.Timestamp("2026-11-04 10:00", tz="UTC")
T1 = T0 + pd.Timedelta("5min")


def it(key="k1", side=BUY, kind="LIMIT", price=100.0, sl=98.0, tp=104.0, expiry=None):
    return OrderIntent(key, "A2_PULLBACK", "GOLD", side, kind, price, sl, tp, "S", "g", tp1=103.0, expiry=expiry,
                       atr=2.0, spread=0.2)


def broker():
    return SimBroker({"GOLD": {"value_per_unit": 100.0}})


def test_buy_limit_fills_on_ask_and_hits_tp():
    b, closed = broker(), []
    b.on_close = closed.append
    b.place(it(), 0.01, T0)
    b.process_bar("GOLD", T0, T1, 101, 101.5, 99.9, 101, 0.2)      # ask mínima 100.1 > 100: não executa
    assert not b.positions
    b.process_bar("GOLD", T1, T1, 101, 101.2, 99.7, 100.5, 0.2)    # ask mínima 99.9 <= 100
    assert len(b.positions) == 1
    b.process_bar("GOLD", T1, T1, 102, 104.5, 101.5, 104, 0.2)
    assert closed and closed[0].reason == "TP" and closed[0].r == pytest.approx(2.0)
    assert closed[0].pnl_usd == pytest.approx(4.0 * 0.01 * 100)


def test_sl_has_priority_when_both_hit_same_bar():
    b, closed = broker(), []
    b.on_close = closed.append
    b.place(it(), 0.01, T0)
    b.process_bar("GOLD", T0, T1, 100.5, 105, 97, 101, 0.0)
    assert closed[0].reason == "SL" and closed[0].r == pytest.approx(-1.0)


def test_sell_exits_on_ask():
    b, closed = broker(), []
    b.on_close = closed.append
    b.place(it(side=SELL, price=100, sl=102, tp=96), 0.01, T0)
    b.process_bar("GOLD", T0, T1, 99.5, 100.1, 99.0, 99.5, 0.5)    # bid máx 100.1 >= 100: executa a 100
    b.process_bar("GOLD", T1, T1, 99.5, 101.6, 99.0, 101.0, 0.5)   # ask máx 102.1 >= SL 102
    assert closed[0].reason == "SL" and closed[0].exit == pytest.approx(102.0)


def test_market_fills_next_open_with_spread_and_expiry():
    b = broker()
    b.place(it(kind="MARKET", price=100, sl=98, tp=104), 0.01, T0)
    b.place(it(key="k2", price=95, sl=93, tp=99, expiry=T1), 0.01, T0)
    b.process_bar("GOLD", T1, T1, 100.3, 100.5, 100.1, 100.4, 0.2)
    p = list(b.positions.values())[0]
    assert p.entry == pytest.approx(100.5)
    assert "k2" not in b.pending


def test_engine_cancels_limits_when_gate_closes(cfg):
    m5 = random_walk(3000, seed=5, drift=0.2, start="2026-03-02 00:00")
    from engine.features import build_features
    feats = build_features(m5, resample(m5, "15min"), resample(m5, "1h"), cfg)
    b = broker()
    eng = Engine(cfg, b)
    b.place(it(key="A2_PULLBACK|GOLD|g|fib0.5"), 0.01, T0)
    sat = pd.Timestamp("2026-03-07 10:00", tz="UTC")              # sábado: fora de sessão
    eng.on_bar("GOLD", feats, len(feats["m5"]) - 1, sat, spread=0.1)
    assert not b.pending


def test_engine_exposure_cap_per_symbol(cfg):
    b = broker()
    eng = Engine(cfg, b)
    intents = [it(key=f"k{n}", price=100 - n * 0.1) for n in range(5)]
    sent = eng._reconcile("GOLD", intents, T0, None)
    assert len(sent) == 3 and len(b.pending) == 3


def test_engine_tracks_entries_per_group(cfg):
    b = broker()
    eng = Engine(cfg, b)
    eng._reconcile("GOLD", [it()], T0, None)
    b.process_bar("GOLD", T0, T1, 100.5, 100.6, 99.5, 100.2, 0.1)
    assert eng.group_entries("A2_PULLBACK", "GOLD", "g") == 1 and eng.is_filled("k1")


def test_portfolio_backtest_runs_end_to_end(cfg):
    data, specs = {}, {}
    for n, s in enumerate(["GOLD", "US500Cash", "BTCUSD"]):
        m5 = random_walk(8000, seed=10 + n, drift=0.08)
        data[s] = {"M5": m5, "M15": resample(m5, "15min"), "H1": resample(m5, "1h")}
        specs[s] = {"value_per_unit": 1.0}
    trades = run_portfolio(cfg, data, specs)
    m = metrics(trades)
    assert m["trades"] > 0
    for t in trades:
        assert abs(t.entry - t.initial_sl) > 0
        assert t.r >= -1.5      # perdas limitadas ao SL (folga para gap da abertura)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, login, mode):
        self._info = types.SimpleNamespace(login=login, trade_mode=mode)

    def account_info(self):
        return self._info


def test_account_guard(cfg, monkeypatch):
    assert verify_account(FakeMT5(309673774, 0), cfg).login == 309673774
    with pytest.raises(AccountGuardError):
        verify_account(FakeMT5(111, 0), cfg)                     # outra demo
    with pytest.raises(AccountGuardError):
        verify_account(FakeMT5(410574578, 2), cfg)               # REAL
    cfg["account"]["allow_real"] = True
    with pytest.raises(AccountGuardError):
        verify_account(FakeMT5(410574578, 2), cfg)               # REAL sem a variável de autorização
    monkeypatch.setenv("QUANT_ALLOW_REAL", "I_AUTHORIZE")
    assert verify_account(FakeMT5(410574578, 2), cfg)
