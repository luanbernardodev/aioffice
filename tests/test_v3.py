"""Agentes v3: causalidade dos sinais (ao vivo == backtest), motor de backtest e o agente com MT5 falso."""
import types

import numpy as np
import pandas as pd
import pytest

from agents import v3_signals as V
from agents.v3_agent import V3Agent
from backtest.agentes_v3.bt import run_bt
from backtest.agentes_v3.grid import signal_specs
from tests.conftest import random_walk


@pytest.fixture(scope="module")
def walk():
    df = random_walk(n=1400, seed=7)
    return df[["time", "open", "high", "low", "close"]]


@pytest.mark.parametrize("spec", signal_specs(), ids=lambda s: "_".join(f"{v}" for v in s.values()))
def test_signal_is_causal(walk, spec):
    full = V.signal(V.indicators(walk), spec)
    for k in (700, 950, 1200, 1400):
        part = V.signal(V.indicators(walk.iloc[:k].reset_index(drop=True)), spec)
        assert part[-1] == full[k - 1], f"barra {k - 1}"


def test_session_masks():
    t = pd.Series(pd.to_datetime(["2026-11-11 15:00", "2026-11-11 03:00", "2026-11-15 03:00"], utc=True))
    assert V.session_mask(t, "ny", 5).tolist() == [True, False, False]          # 10:05 NY qua / madrugada / sábado à noite em NY
    assert V.session_mask(t, "night", 5).tolist() == [False, True, False]
    assert V.session_mask(t, "all", 5).all()


def arr(*v):
    return np.array(v, dtype=float)


def bt(o, h, l, c, sig, sl=1.0, tr=0.0, act=0.0, tp=0.0, maxb=96, sp=0.0):
    n = len(o)
    return run_bt(arr(*o), arr(*h), arr(*l), arr(*c), np.full(n, sp), np.full(n, 1.0), np.array(sig, np.int64),
                  np.zeros(n, np.int64), sl, tr, act, tp, maxb, 1.0)


def test_bt_long_stop_and_target():
    E, X, S, P, R, N, W = bt([10, 10, 10, 10], [10, 10.5, 12.2, 10], [10, 9.5, 9.9, 10], [10] * 4, [1, 0, 0, 0], tp=2.0)
    assert (E[0], X[0], S[0], W[0]) == (1, 2, 1, 1) and P[0] == pytest.approx(2.0)
    E, X, S, P, R, N, W = bt([10, 10, 10, 10], [10, 10.5, 12.2, 10], [10, 8.9, 9.9, 10], [10] * 4, [1, 0, 0, 0], tp=2.0)
    assert W[0] == 0 and P[0] == pytest.approx(-1.0)                       # SL antes do TP na mesma barra


def test_bt_short_pays_spread_and_trails():
    o, h = [10, 10, 9, 8.2, 8.5], [10, 10.2, 9.1, 8.3, 9.6]
    l, c = [10, 9.0, 8.0, 8.1, 8.4], [10, 9.2, 8.2, 8.2, 8.5]
    E, X, S, P, R, N, W = bt(o, h, l, c, [-1, 0, 0, 0, 0], sl=2.0, tr=1.0, sp=0.1)
    # entra vendido a 10 (bid); melhor ask = 8.0+0.1 -> stop 9.1 a partir da barra 3; barra 4: ask máx 9.7 >= 9.1
    assert S[0] == -1 and X[0] == 4 and P[0] == pytest.approx(10 - 9.1)


def test_bt_time_exit_at_next_open():
    E, X, S, P, R, N, W = bt([10, 10, 11, 12, 13], [10, 10.4, 11.4, 12.4, 13.4], [10, 9.6, 10.6, 11.6, 12.6],
                             [10, 10.2, 11.2, 12.2, 13.2], [1, 0, 0, 0, 0], sl=5.0, maxb=2)
    assert W[0] == 2 and X[0] == 3 and P[0] == pytest.approx(2.0)


# ------------------------------------------------------------------ agente ao vivo com MT5 falso
class FakeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, TRADE_RETCODE_DONE = 1, 6, 10009
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, POSITION_TYPE_BUY = 0, 1, 0
    ORDER_TIME_GTC, ORDER_FILLING_IOC, ORDER_FILLING_FOK, ORDER_FILLING_RETURN = 0, 1, 0, 2
    ACCOUNT_TRADE_MODE_DEMO, TIMEFRAME_M5 = 0, 5

    def __init__(self, rates):
        self.rates, self.sent, self.pos, self.head = rates, [], [], 1_000_000

    def account_info(self):
        return types.SimpleNamespace(login=309673774, trade_mode=0, balance=100.0)

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01, digits=2, trade_tick_size=0.01, filling_mode=1, volume_min=0.01)

    def symbol_info_tick(self, s):
        return types.SimpleNamespace(bid=100.0, ask=100.2, time=int(self.rates["time"][-1]) + 300 + 5)

    def positions_get(self, symbol=None):
        return self.pos

    def copy_rates_from_pos(self, s, tf, start, n):
        if start == 0:
            return np.array([(self.head,)], dtype=[("time", "i8")])
        return self.rates

    def order_send(self, req):
        self.sent.append(req)
        return types.SimpleNamespace(retcode=10009, order=77, price=req.get("price"), comment="")

    def history_deals_get(self, *a, **k):
        return []

    def last_error(self):
        return (0, "")


def rates(n=500):
    t = 1_700_000_000 + np.arange(n) * 300
    r = np.zeros(n, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                           ("spread", "i8")])
    r["time"], r["open"], r["close"] = t, 100.0, 100.0
    r["high"], r["low"], r["spread"] = 100.5, 99.5, 20
    return r


G = {"name": "v3_teste", "symbol": "GOLD", "magic": 20261199, "timeframe": "M5", "enabled": True,
     "signal": {"family": "DON", "n": 20, "filter": "none", "session": "all"},
     "exit": {"sl": 2.0, "trail": 1.0, "act": 1.0, "tp": 3.0}, "max_bars": 3, "loss_limit_usd": 40}


def agent(tmp_path, monkeypatch, mt5):
    import agents.v3_agent as va
    monkeypatch.setattr(va, "ROOT", tmp_path)
    a = V3Agent(mt5, {"account": {"demo_login": 309673774, "server_time": "ny_plus_7"}}, "v3_teste", dict(G),
                state_dir=tmp_path)
    a.csv_path = tmp_path / "v3.csv"
    a.start()
    return a


def test_agent_enters_with_backtest_levels(tmp_path, monkeypatch):
    mt5 = FakeMT5(rates())
    a = agent(tmp_path, monkeypatch, mt5)
    monkeypatch.setattr(V, "entry_signal_now", lambda df, spec, m: (1, 2.0))
    a.step()
    req = mt5.sent[-1]
    assert req["type"] == 0 and req["price"] == 100.2 and req["magic"] == 20261199
    assert req["sl"] == pytest.approx(100.2 - 4.0) and req["tp"] == pytest.approx(100.2 + 6.0)
    assert a.state["trades"]["77"]["A"] == 2.0


def test_agent_trails_and_exits_by_time(tmp_path, monkeypatch):
    r = rates()
    mt5 = FakeMT5(r)
    a = agent(tmp_path, monkeypatch, mt5)
    entry_bar = int(r["time"][-2])
    a.state["trades"]["77"] = {"side": 1, "entry": 100.0, "A": 0.25, "sl": 99.5, "entry_bar": entry_bar}
    mt5.pos = [types.SimpleNamespace(ticket=77, type=0, volume=0.01, sl=99.5, tp=0.0, profit=0.0, swap=0.0,
                                     price_open=100.0, time=entry_bar, magic=20261199)]
    a.step()                                   # 2 barras desde a entrada: máx 100.5 >= +1 ATR -> stop 100.25
    assert mt5.sent[-1]["action"] == 6 and mt5.sent[-1]["sl"] == pytest.approx(100.25)
    a.state["trades"]["77"]["entry_bar"] = int(r["time"][-3])
    mt5.head += 300
    a.state["last_bar"] = 0
    a.step()                                   # 3 barras = max_bars -> fecha a mercado
    assert mt5.sent[-1]["action"] == 1 and mt5.sent[-1]["position"] == 77


def test_agent_halts_on_loss_limit(tmp_path, monkeypatch):
    mt5 = FakeMT5(rates())
    a = agent(tmp_path, monkeypatch, mt5)
    mt5.history_deals_get = lambda *x, **k: [types.SimpleNamespace(magic=20261199, type=0, profit=-41.0, swap=0.0,
                                                                     commission=0.0)]
    monkeypatch.setattr(V, "entry_signal_now", lambda df, spec, m: (1, 2.0))
    a.step()
    assert "perda acumulada" in a.state["halted"] and not mt5.sent


# ------------------------------------------------------------------ configuração da competição
def test_competition_config_is_consistent(cfg):
    import agents.auditor_mt5 as aud
    from agents.v3_agent import load_agents_config
    v3 = load_agents_config()
    assert len(v3) == 5 and all(g["enabled"] for g in v3.values())
    magics = [int(g["magic"]) for g in v3.values()]
    others = [int(v["magic"]) for k, v in cfg.items() if isinstance(v, dict) and "magic" in v]
    others += [a["magic"] for a in aud.standalone_agents() if a["magic"] not in magics]
    assert len(set(magics)) == 5 and not set(magics) & set(others)
    for g in v3.values():                                  # especificação válida para o código de sinais
        V.signal(V.indicators(random_walk(n=700, seed=1)), g["signal"])
        assert g["timeframe"] in ("M5", "M15", "H1") and g["loss_limit_usd"] > 0 and g["max_spread"] > 0
    comp = aud.competition_config()
    roster = aud.agent_roster(cfg)
    assert set(comp["novos"]) == {g["name"] for g in v3.values()}
    assert set(comp["antigos"]) | set(comp["novos"]) <= set(roster)
    assert all(roster[n]["ligado"] for n in comp["antigos"] + comp["novos"])
