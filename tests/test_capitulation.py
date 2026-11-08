import types

import numpy as np
import pandas as pd
import pytest

from agents.capitulation import CapitulationAgent
from agents.capitulation_rules import episode_step, rsi_state, rsi_with_partial, trail_buy
from engine import indicators as ind

BASE = 1793800800 - 1793800800 % 900


def step(armed, locked, r, n=0):
    return episode_step(armed, locked, r, 10.0, 20.0, n, 3)


def test_episode_rules():
    assert step(False, False, 12.0) == (False, False, False)      # entre 10 e 20 sem armar: nada
    assert step(False, False, 9.0) == (True, False, True)         # arma e compra
    assert step(True, False, 18.0, 1) == (True, False, True)      # RSI<20: nova compra
    assert step(True, False, 18.0, 3) == (True, False, False)     # limite de 3
    assert step(True, True, 18.0, 1) == (True, True, False)       # stop positivo encerra as compras
    assert step(True, True, 25.0, 1) == (False, False, False)     # saiu da zona: libera o próximo episódio
    assert step(False, False, 9.0)[2] is True


def test_partial_rsi_equals_full_rsi_on_bar_close():
    rng = np.random.default_rng(1)
    c = pd.Series(1000 + np.cumsum(rng.normal(0, 5, 300)))
    g, l = rsi_state(c.iloc[:-1])
    assert rsi_with_partial(g[-1], l[-1], c.iat[-2], c.iat[-1]) == pytest.approx(ind.rsi(c).iat[-1])


def test_trail_buy_only_moves_up_after_trigger():
    assert trail_buy(1000, 800, 1049, 100, 0.5, 0.25) == 800
    assert trail_buy(1000, 800, 1050, 100, 0.5, 0.25) == pytest.approx(1025)      # já no lucro
    assert trail_buy(1000, 1025, 1040, 100, 0.5, 0.25) == 1025


class FakeMT5:
    TIMEFRAME_M5, TIMEFRAME_M15, ACCOUNT_TRADE_MODE_DEMO = 5, 15, 0
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, POSITION_TYPE_BUY = 0, 1, 0
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 0, 1, 2
    TRADE_RETCODE_DONE = 10009
    DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_REASON_SL, DEAL_REASON_TP = 1, 3, 4, 5

    def __init__(self):
        self.sent, self.pos, self.deals, self.n = [], {}, [], 100
        self.bid, self.ask, self.now = 1000.0, 1040.0, BASE + 305
        self.other = []

    def account_info(self):
        return types.SimpleNamespace(login=309673774, trade_mode=0)

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01, digits=2, trade_stops_level=0, trade_freeze_level=0,
                                     trade_contract_size=1.0, filling_mode=2)

    def positions_get(self, symbol=None):
        return list(self.pos.values()) + self.other

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
        if req["action"] == self.TRADE_ACTION_SLTP:
            self.pos[req["position"]].sl = req["sl"]
        elif "position" in req:
            self.pos.pop(req["position"], None)
        else:
            self.n += 1
            self.pos[self.n] = types.SimpleNamespace(ticket=self.n, magic=20261111, symbol="BTCUSD", type=0,
                                                     volume=req["volume"], price_open=req["price"], sl=req["sl"], tp=0.0,
                                                     time=self.now, profit=0.0, swap=0.0)
        return types.SimpleNamespace(retcode=10009, comment="done", order=self.n, price=req.get("price", 0.0))


@pytest.fixture
def agent(cfg, tmp_path):
    a = CapitulationAgent(FakeMT5(), cfg, tmp_path / "c.json", tmp_path / "c.csv")
    a.start()
    return a


def buy(a, atr=100.0, rsi=8.0):
    a._enter(atr, BASE, a.mt5.symbol_info_tick("BTCUSD"), rsi)


def test_entries_have_sl_no_tp_and_own_magic(agent):
    buy(agent)
    r = agent.mt5.sent[0]
    assert r["sl"] == pytest.approx(1040 - 200) and r["tp"] == 0.0 and r["magic"] == 20261111


def test_each_position_trails_and_locks_episode(agent):
    buy(agent)
    agent.state["armed"] = True
    buy(agent)
    agent.mt5.bid, agent.mt5.ask = 1090.0, 1130.0
    agent.step()
    assert agent.state["locked"] is True
    assert all(p.sl == pytest.approx(1065.0) for p in agent.mt5.pos.values())    # stop no lucro nas duas


def test_stop_in_code_closes_at_market(agent):
    buy(agent)
    agent.mt5.bid, agent.mt5.ask = 1090.0, 1130.0
    agent.step()
    tk = next(iter(agent.mt5.pos))
    agent.state["trades"][str(tk)]["_close_try"] = 0.0
    agent.mt5.bid, agent.mt5.ask = 1064.0, 1104.0
    agent.mt5.pos[tk].sl = 840.0                                                  # broker atrasado
    agent.step()
    assert not agent.mt5.pos


def test_loss_limit_halts_and_closes_all(agent):
    buy(agent)
    buy(agent)
    for p in agent.mt5.pos.values():
        p.profit = -15.0
    agent.step()
    assert agent.state["halted"]
    assert not agent.mt5.pos


def test_recovery_keeps_managing(cfg, tmp_path):
    a = CapitulationAgent(FakeMT5(), cfg, tmp_path / "c.json", tmp_path / "c.csv")
    a.start()
    buy(a)
    b = CapitulationAgent(a.mt5, cfg, tmp_path / "c.json", tmp_path / "c.csv")
    b.start()
    tk = str(next(iter(a.mt5.pos)))
    assert b.state["trades"][tk]["A"] == 100.0
    a.mt5.bid, a.mt5.ask = 1090.0, 1130.0
    b.step()
    assert a.mt5.pos[int(tk)].sl == pytest.approx(1065.0)


def test_ignores_other_magics(agent):
    agent.mt5.other = [types.SimpleNamespace(ticket=5, magic=20261110, symbol="BTCUSD", type=0, volume=0.01,
                                             price_open=900.0, sl=800.0, tp=0.0, time=BASE, profit=-99.0, swap=0.0)]
    agent.step()
    assert agent.mt5.sent == [] and not agent.state["halted"]
