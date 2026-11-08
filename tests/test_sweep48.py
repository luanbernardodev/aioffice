import types

import numpy as np
import pandas as pd
import pytest

from agents.sweep48 import BUY, SELL, Sweep48Agent, add_indicators, loss_limit_usd, server_hour, signal_at, trail_stop
from engine.mt5_broker import AccountGuardError

BASE = 1793800800 - 1793800800 % 86400        # meia-noite do servidor


def row(hour=16, **kw):
    v = dict(time=BASE + hour * 3600, atr=100.0, ma100=900.0, ma300=890.0, min48=950.0, max48=1100.0,
             low=940.0, high=1000.0, close=960.0)
    v.update(kw)
    return types.SimpleNamespace(**v)


def test_buy_sell_and_window():
    assert signal_at(row()) == BUY
    assert signal_at(row(low=950.0)) == 0                    # não varreu o MIN48
    assert signal_at(row(close=945.0)) == 0                  # não fechou de volta acima
    assert signal_at(row(ma100=970.0)) == 0
    assert signal_at(row(ma300=970.0)) == 0
    sell = dict(high=1110.0, low=1000.0, close=1050.0, ma100=1060.0, ma300=1070.0)
    assert signal_at(row(**sell)) == SELL
    assert signal_at(row(**{**sell, "ma300": 1040.0})) == 0
    assert signal_at(row(hour=14)) == 0 and signal_at(row(hour=21)) == 0
    assert signal_at(row(hour=15)) == BUY and signal_at(row(hour=20)) == BUY
    assert server_hour(BASE + 20 * 3600 + 59 * 60) == 20


def test_min48_excludes_current_bar():
    n = 400
    df = pd.DataFrame({"time": np.arange(n) * 300 + BASE, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    df.loc[n - 1, "low"] = 50.0
    d = add_indicators(df)
    assert d["min48"].iat[-1] == 99.0
    assert d["min48"].isna().sum() == 48


def test_trailing():
    assert trail_stop(BUY, 1000, 700, 1074, 1075, 100) == 700         # abaixo de 0.75A
    assert trail_stop(BUY, 1000, 700, 1075, 1076, 100) == pytest.approx(1060)
    assert trail_stop(BUY, 1000, 1060, 1070, 1071, 100) == 1060       # nunca recua
    assert trail_stop(SELL, 1000, 1300, 924, 925, 100) == pytest.approx(940)
    assert trail_stop(SELL, 1000, 1300, 925, 926, 100) == 1300        # usa o ask


def test_loss_limit():
    assert loss_limit_usd(1500, 0.01, 1.0) == -15.0


class FakeMT5:
    TIMEFRAME_M5, ACCOUNT_TRADE_MODE_DEMO = 5, 0
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 0, 1, 2
    TRADE_RETCODE_DONE = 10009
    DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_REASON_SL, DEAL_REASON_TP = 1, 3, 4, 5

    def __init__(self, login=309673774):
        self.login, self.sent, self.pos, self.deals = login, [], None, []
        self.bid, self.ask, self.now, self.reject_sltp = 1000.0, 1040.0, BASE + 16 * 3600, False
        self.other = []

    def account_info(self):
        return types.SimpleNamespace(login=self.login, trade_mode=0)

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01, digits=2, trade_stops_level=0, trade_freeze_level=0,
                                     trade_contract_size=1.0, filling_mode=2)

    def positions_get(self, symbol=None):
        return ([self.pos] if self.pos else []) + self.other

    def history_deals_get(self, *a, **k):
        return self.deals

    def last_error(self):
        return (0, "")

    def symbol_info_tick(self, s):
        self.now += 1
        return types.SimpleNamespace(bid=self.bid, ask=self.ask, time=self.now, time_msc=self.now * 1000)

    def copy_rates_from_pos(self, s, tf, start, n):
        return None

    def order_send(self, req):
        self.sent.append(req)
        if req["action"] == self.TRADE_ACTION_SLTP and self.reject_sltp:
            return types.SimpleNamespace(retcode=10016, comment="Invalid stops", order=0, price=0.0)
        if req["action"] == self.TRADE_ACTION_SLTP:
            self.pos.sl = req["sl"]
        elif "position" in req:
            self.pos = None
        else:
            self.pos = types.SimpleNamespace(ticket=77, identifier=77, magic=20261110, symbol="BTCUSD", type=req["type"],
                                             volume=req["volume"], price_open=req["price"] + 2, sl=req["sl"], tp=req["tp"],
                                             time=self.now, profit=0.0, swap=0.0)
        return types.SimpleNamespace(retcode=10009, comment="done", order=77, price=req.get("price", 0.0) + 2)


@pytest.fixture
def agent(cfg, tmp_path):
    a = Sweep48Agent(FakeMT5(), cfg, tmp_path / "s.json", tmp_path / "t.csv")
    a.start()
    return a


def open_buy(a, atr=100.0):
    tick = a.mt5.symbol_info_tick("BTCUSD")
    a._enter(BUY, atr, BASE + 16 * 3600, tick)


def test_entry_levels_and_csv(agent):
    open_buy(agent)
    r = agent.mt5.sent[0]
    assert r["sl"] == pytest.approx(1040 - 300) and r["tp"] == pytest.approx(1040 + 500) and r["magic"] == 20261110
    log = pd.read_csv(agent.csv_path)
    assert log.iloc[0].event == "ORDER" and log.iloc[0].slippage == 2.0 and log.iloc[0].retcode == 10009


def test_trail_sent_to_broker(agent):
    open_buy(agent)
    agent.mt5.bid, agent.mt5.ask = 1120.0, 1160.0
    agent.last_sl_send = 0
    agent.step()
    assert agent.mt5.pos.sl == pytest.approx(1105.0)
    assert "SL_CHANGE" in set(pd.read_csv(agent.csv_path).event)


def test_rejected_sl_becomes_virtual_and_closes(agent):
    open_buy(agent)
    agent.mt5.reject_sltp = True
    agent.mt5.bid, agent.mt5.ask = 1120.0, 1160.0
    agent.last_sl_send = 0
    agent.step()
    assert agent.mt5.pos is not None and agent.state["trade"]["sl"] == pytest.approx(1105.0)
    assert "SL_VIRTUAL" in set(pd.read_csv(agent.csv_path).event)
    agent.mt5.bid, agent.mt5.ask = 1104.0, 1144.0
    agent.last_close_try = 0
    agent.step()
    assert agent.mt5.pos is None and agent.exit_reason == "STOP_EM_CODIGO"


def test_time_exit(agent):
    open_buy(agent)
    agent.mt5.now += 240 * 60
    agent.last_close_try = 0
    agent.step()
    assert agent.mt5.pos is None and agent.exit_reason == "TEMPO_240MIN"


def test_loss_limit_closes_and_halts_only_this_agent(agent):
    open_buy(agent)
    agent.mt5.pos.profit = -15.0
    agent.last_close_try = 0
    agent.step()
    assert agent.mt5.pos is None and agent.state["halted"] and "limite" in agent.state["halt_reason"]


def test_recovery_by_magic_continues_managing(cfg, tmp_path):
    a = Sweep48Agent(FakeMT5(), cfg, tmp_path / "s.json", tmp_path / "t.csv")
    a.start()
    open_buy(a)
    mt5 = a.mt5
    b = Sweep48Agent(mt5, cfg, tmp_path / "s.json", tmp_path / "t.csv")   # A vem do arquivo (sem barras no fake)
    b.start()
    assert b.state["trade"]["ticket"] == 77 and b.state["trade"]["A"] == 100.0
    mt5.bid, mt5.ask = 1120.0, 1160.0
    b.step()
    assert mt5.pos.sl == pytest.approx(1105.0)


def test_ignores_other_magics(agent):
    agent.mt5.other = [types.SimpleNamespace(ticket=5, magic=20261109, symbol="BTCUSD", type=0, volume=0.01,
                                             price_open=900.0, sl=800.0, tp=0.0, time=BASE, profit=-99.0, swap=0.0)]
    assert agent._position() is None
    agent.step()
    assert agent.mt5.sent == []


def test_refuses_other_account(cfg, tmp_path):
    with pytest.raises(AccountGuardError):
        Sweep48Agent(FakeMT5(login=410574578), cfg, tmp_path / "s.json", tmp_path / "t.csv").start()
