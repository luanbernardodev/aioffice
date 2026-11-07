import json
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from agents.goldflip_supervisor import (CONTROL_FILE, STATUS_FILE, GoldFlipSupervisor, classify_regime,
                                        decide_control, read_json, write_json_atomic)
from engine.regime import NewsCalendar
from engine.risk import AccountGuard

WED_LONDON = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)   # quarta 10:00 UTC (Londres aberta)
WED_ASIA = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)


def ohlc(n, drift, noise=0.3, seed=0, start=2000.0):
    rng = np.random.default_rng(seed)
    close = start + np.cumsum(drift + rng.normal(0, noise, n))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "high": np.maximum(op, close) + 0.5, "low": np.minimum(op, close) - 0.5,
                         "close": close})


# ----------------------------------------------------------------- regime
def test_regime_trend_up_and_down(cfg):
    r = classify_regime(ohlc(300, 0.6), ohlc(300, 0.6), cfg["goldflip"]["regime"])
    assert r["regime"] == "trend" and r["direction"] == 1
    r = classify_regime(ohlc(300, -0.6), ohlc(300, -0.6), cfg["goldflip"]["regime"])
    assert r["regime"] == "trend" and r["direction"] == -1


def test_regime_lateral(cfg):
    x = np.arange(300)
    flat = pd.DataFrame({"close": 2000 + 2 * np.sin(x / 5)})
    flat["open"] = flat["close"].shift(1).fillna(2000)
    flat["high"] = flat[["open", "close"]].max(axis=1) + 0.5
    flat["low"] = flat[["open", "close"]].min(axis=1) - 0.5
    assert classify_regime(flat, flat, cfg["goldflip"]["regime"])["regime"] == "lateral"


def test_regime_m1_must_confirm(cfg):
    r = classify_regime(ohlc(300, -0.6), ohlc(300, 0.6), cfg["goldflip"]["regime"])   # M1 caindo, M5 subindo
    assert r["regime"] == "lateral"


def test_regime_unknown_with_little_data(cfg):
    assert classify_regime(ohlc(50, 0.5), ohlc(50, 0.5), cfg["goldflip"]["regime"])["regime"] == "unknown"


# ----------------------------------------------------------------- controle
def reg(regime="trend", atr=4.0, d=1):
    return {"regime": regime, "direction": d, "atr_m5": atr}


def test_control_trend_in_session(cfg):
    c = decide_control(reg(), WED_LONDON, cfg["goldflip"], point=0.01)
    assert c["enabled"] is True and c["trail_atr"] == 1.5
    assert c["max_spread"] == int(0.15 * 4.0 / 0.01)          # 60 pontos
    assert c["valid_until"] - c["updated_at"] == 900


def test_control_off_outside_session_lateral_lowatr_news_kill(cfg):
    g = cfg["goldflip"]
    assert decide_control(reg(), WED_ASIA, g, 0.01)["enabled"] is False
    assert decide_control(reg("lateral", d=0), WED_LONDON, g, 0.01)["enabled"] is False
    assert decide_control(reg(atr=1.0), WED_LONDON, g, 0.01)["enabled"] is False
    assert decide_control(reg("unknown", atr=float("nan"), d=0), WED_LONDON, g, 0.01)["enabled"] is False
    cal = NewsCalendar(g["news_keywords"], g["news_window_minutes"])
    cal.add_event(datetime(2026, 11, 4, 10, 10, tzinfo=timezone.utc), "Non-Farm Employment Change")
    assert decide_control(reg(), WED_LONDON, g, 0.01, cal)["enabled"] is False             # NFP em 10 min
    assert decide_control(reg(), datetime(2026, 11, 4, 10, 30, tzinfo=timezone.utc), g, 0.01, cal)["enabled"]  # +20 min
    k = decide_control(reg(), WED_LONDON, g, 0.01, kill_reason="DD diário 3.2%")
    assert k["enabled"] is False and "KILL" in k["reason"]


def test_json_atomic_roundtrip_ascii(tmp_path):
    p = tmp_path / CONTROL_FILE
    write_json_atomic(p, {"enabled": True, "reason": "fora de sessão"})
    raw = p.read_bytes()
    assert raw.isascii() and b'"enabled":true' in raw
    assert read_json(p)["reason"] == "fora de sessão"
    assert not (tmp_path / (CONTROL_FILE + ".tmp")).exists()


# ----------------------------------------------------------------- A5 kill switch + exposição
def P(symbol="GOLD", magic=20261108, typ=0, vol=0.01, profit=-1.0):
    return types.SimpleNamespace(symbol=symbol, magic=magic, type=typ, volume=vol, profit=profit)


def test_exposure_sums_all_magics():
    e = AccountGuard.exposure([P(magic=20261108, vol=0.02), P(magic=20261107, typ=1, vol=0.01),
                               P(magic=777777, vol=0.01, profit=2.0), P(symbol="BTCUSD", vol=1.0)], "GOLD")
    assert e["net_lots"] == pytest.approx(0.02) and e["gross_lots"] == pytest.approx(0.04)
    assert e["floating_pnl"] == pytest.approx(0.0) and set(e["by_magic"]) == {20261108, 20261107, 777777}


def test_kill_switch_at_3pct_and_latches_until_next_day(cfg):
    g = AccountGuard(cfg)
    t = WED_LONDON
    assert g.evaluate(t, balance=100.0, equity=98.0, realized_today=0.0) == (False, pytest.approx(2.0))
    killed, dd = g.evaluate(t, balance=99.0, equity=97.0, realized_today=-1.0)   # início 100 -> 3%
    assert killed and dd == pytest.approx(3.0)
    assert g.evaluate(t, balance=99.0, equity=99.5, realized_today=-1.0)[0]       # recuperou, mas segue travado
    assert not g.evaluate(datetime(2026, 11, 5, 0, 1, tzinfo=timezone.utc), 99.0, 99.0, 0.0)[0]


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5 = 1, 5

    def __init__(self, tmp, equity=100.0, balance=100.0):
        self.tmp, self._eq, self._bal = tmp, equity, balance

    def terminal_info(self):
        return types.SimpleNamespace(data_path=str(self.tmp))

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01)

    def account_info(self):
        return types.SimpleNamespace(balance=self._bal, equity=self._eq)

    def positions_get(self):
        return [P(magic=20261108, vol=0.01, profit=self._eq - self._bal)]

    def history_deals_get(self, *a):
        return []

    def copy_rates_from_pos(self, sym, tf, start, n):
        df = ohlc(n, 0.6)
        return df.to_records(index=False)


def test_supervisor_writes_control_and_kill_forces_disable(cfg, tmp_path):
    mt5 = FakeMT5(tmp_path)
    sup = GoldFlipSupervisor(mt5, cfg, calendar=NewsCalendar([], 15))
    assert sup.dir == tmp_path / "MQL5" / "Files"
    ctl = sup.run_cycle(WED_LONDON)
    on_disk = json.loads((sup.dir / CONTROL_FILE).read_text())
    assert on_disk["enabled"] is True and ctl["regime"] == "trend"
    mt5._eq = 96.5                                         # DD 3.5%
    sup.check_risk(WED_LONDON)
    assert json.loads((sup.dir / CONTROL_FILE).read_text())["enabled"] is False
    sup.run_cycle(WED_LONDON)                              # novo ciclo não religa durante o dia
    assert json.loads((sup.dir / CONTROL_FILE).read_text())["enabled"] is False


def test_supervisor_reads_ea_status(cfg, tmp_path):
    sup = GoldFlipSupervisor(FakeMT5(tmp_path), cfg, calendar=NewsCalendar([], 15))
    sup.dir.mkdir(parents=True)
    (sup.dir / STATUS_FILE).write_text('{"updated_at":1,"position":"LONG","volume":0.01,"day_pnl":-0.4,'
                                       '"trades_last_hour":3,"avg_spread_points":31.5,"control_enabled":true}',
                                       encoding="latin-1")
    sup.run_cycle(WED_LONDON)
    assert sup.status["trades_last_hour"] == 3


# ----------------------------------------------------------------- travas de magic (nenhum agente fecha 20261108)
def test_engine_broker_ignores_goldflip_positions(cfg):
    from engine.mt5_broker import MT5Broker

    class M:
        ACCOUNT_TRADE_MODE_DEMO, POSITION_TYPE_BUY, DEAL_ENTRY_OUT = 0, 0, 1

        def account_info(self):
            return types.SimpleNamespace(login=309673774, trade_mode=0)

        def orders_get(self, **k):
            return []

        def positions_get(self):
            return [types.SimpleNamespace(ticket=1, identifier=1, magic=20261108, symbol="GOLD", type=0,
                                          volume=0.01, price_open=2000, sl=1990, tp=2020, time=0)]

    b = MT5Broker.__new__(MT5Broker)
    b.mt5, b.cfg, b.specs, b.magic = M(), cfg, {}, int(cfg["account"]["magic"])
    b.on_fill = b.on_close = None
    b.meta, b.pending_map, b.positions = {}, {}, {}
    b._save_state = lambda: None
    b.sync()
    assert b.positions == {}                     # posição do EA não foi adotada -> nunca será modificada


def test_legacy_close_position_refuses_other_magic(monkeypatch):
    import core.mt5_bridge as mb

    sent = []
    fake = types.SimpleNamespace(
        positions_get=lambda ticket=None: [types.SimpleNamespace(ticket=ticket, magic=20261108, symbol="GOLD",
                                                                 volume=0.01, type=0)],
        order_send=lambda req: sent.append(req), ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
        last_error=lambda: (0, ""))
    monkeypatch.setattr(mb, "mt5", fake)
    bridge = mb.MT5Bridge.__new__(mb.MT5Bridge)
    bridge.mock = False
    res = bridge.close_position(ticket=42, symbol="GOLD")
    assert res["success"] is False and not sent
