from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from engine.risk import RiskManager
from engine.types import BUY, SELL, ClosedTrade, OrderIntent, Position


def intent(side=BUY, price=100.0, sl=98.0, tp=110.0, atr=2.0, kind="LIMIT", tp_r=0.0):
    return OrderIntent("k", "A2_PULLBACK", "GOLD", side, kind, price, sl, tp, "S", "g", atr=atr, tp_r=tp_r)


def closed(pnl, when):
    ts = pd.Timestamp(when)
    return ClosedTrade("A2", "S", "GOLD", BUY, 0.01, 100, 99, 102, 101.5, 99, ts, ts, "SL", pnl, -1.0, 0.1, 1.0)


def test_min_sl_is_one_atr(cfg):
    rm = RiskManager(cfg)
    f = rm.finalize(intent(sl=99.0, atr=2.0))          # SL 0.5 ATR -> alarga para 1 ATR
    assert f.sl == pytest.approx(98.0)
    assert f.tp1 == pytest.approx(103.0)               # 1.5R


def test_sl_too_wide_is_rejected(cfg):
    assert RiskManager(cfg).finalize(intent(sl=80.0, atr=2.0)) is None


def test_sl_wrong_side_rejected(cfg):
    assert RiskManager(cfg).finalize(intent(sl=101.0)) is None


def test_final_target_never_below_tp1(cfg):
    f = RiskManager(cfg).finalize(intent(sl=98.0, tp=101.0))
    assert f.tp == pytest.approx(f.tp1) == pytest.approx(103.0)
    s = RiskManager(cfg).finalize(intent(side=SELL, price=100, sl=102, tp=99.5))
    assert s.tp == pytest.approx(97.0)


def test_tp_r_recomputed_after_sl_widening(cfg):
    f = RiskManager(cfg).finalize(intent(sl=99.5, tp=0, tp_r=2.0, kind="MARKET"))
    assert f.sl == pytest.approx(98.0) and f.tp == pytest.approx(104.0)


def test_exposure_limits(cfg):
    rm = RiskManager(cfg)
    assert rm.exposure_ok("GOLD", 5, 2)[0]
    assert not rm.exposure_ok("GOLD", 6, 0)[0]
    assert not rm.exposure_ok("GOLD", 4, 3)[0]


def test_daily_stop_pauses_until_next_day(cfg):
    rm = RiskManager(cfg)
    t = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    rm.on_trade_closed(closed(-20, t))
    assert rm.trading_allowed(t)[0]
    rm.on_trade_closed(closed(5, t))
    rm.on_trade_closed(closed(-16, t))                 # dia: -31 <= -30
    assert not rm.trading_allowed(t + timedelta(hours=5))[0]
    assert rm.trading_allowed(datetime(2026, 11, 5, 0, 1, tzinfo=timezone.utc))[0]
    assert rm.day_pnl == 0.0


def test_four_losses_pause_two_hours(cfg):
    rm = RiskManager(cfg)
    rm.daily_stop = 1e9
    t = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    for _ in range(3):
        rm.on_trade_closed(closed(-1, t))
    assert rm.trading_allowed(t)[0]
    rm.on_trade_closed(closed(-1, t))
    assert not rm.trading_allowed(t + timedelta(minutes=119))[0]
    assert rm.trading_allowed(t + timedelta(minutes=121))[0]


def test_win_resets_streak(cfg):
    rm = RiskManager(cfg)
    t = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    for pnl in (-1, -1, -1, 2, -1):
        rm.on_trade_closed(closed(pnl, t))
    assert rm.streak == 1 and rm.trading_allowed(t)[0]


def pos(side=BUY, entry=100.0, sl=98.0):
    return Position("1", "k", "A2", "GOLD", side, 0.01, entry, sl, 110, 103, sl, "S", "g", pd.Timestamp.now(tz="UTC"))


def test_trailing_activation_breakeven_then_atr(cfg):
    rm = RiskManager(cfg)
    p = pos()                                          # R = 2
    assert rm.trail(p, bid=101.5, ask=101.6, atr=1.0, spread=0.1) is None      # +0.75R: ainda não
    new = rm.trail(p, bid=102.0, ask=102.1, atr=2.5, spread=0.1)               # +1R: BE travado
    assert new == pytest.approx(100.1)                 # entrada + spread (trail 99.5 fica abaixo)
    assert rm.trail(pos(), bid=102.0, ask=102.1, atr=1.5, spread=0.1) == pytest.approx(100.5)  # max(BE, trail)
    p.sl = new
    new2 = rm.trail(p, bid=104.0, ask=104.1, atr=1.0, spread=0.1)
    assert new2 == pytest.approx(103.0)                # 1 x ATR atrás do preço
    p.sl = new2
    assert rm.trail(p, bid=103.5, ask=103.6, atr=1.0, spread=0.1) is None      # nunca recua


def test_trailing_activation_uses_spread_x3_when_larger(cfg):
    rm = RiskManager(cfg)
    p = pos(entry=100.0, sl=99.0)                      # R = 1
    assert rm.trail(p, bid=101.2, ask=101.7, atr=1.0, spread=0.5) is None      # precisa de 1.5 (3 x spread)
    assert rm.trail(p, bid=101.6, ask=102.1, atr=1.0, spread=0.5) is not None


def test_trailing_sell(cfg):
    rm = RiskManager(cfg)
    p = pos(side=SELL, entry=100.0, sl=102.0)
    new = rm.trail(p, bid=97.9, ask=98.0, atr=1.0, spread=0.1)
    assert new == pytest.approx(99.0)                  # min(entrada - spread, ask + ATR)
    p.sl = new
    assert rm.trail(p, bid=98.4, ask=98.5, atr=1.0, spread=0.1) is None
