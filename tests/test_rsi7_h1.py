import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import agents.auditor_mt5 as aud
from agents import rsi7_h1_rules as R
from agents.rsi7_h1 import DAILY_LOSS_PCT, MAX_POSITIONS, Rsi7H1Agent, load_agent_config
from engine.mt5_broker import AccountGuardError

ROOT = Path(__file__).resolve().parent.parent
P = {"rsi_period": 7, "rsi_level": 30, "ma_type": "ema", "ma_period": 50, "atr_period": 14, "sl_atr": 1.0,
     "trail_atr": 3.0, "trail_activate_r": 0.0, "breakeven_r": 0.0, "tp_atr": 0.0}


def walk(n=1200, seed=3, start=1_700_000_000):
    rng = np.random.default_rng(seed)
    c = 60000 + np.cumsum(rng.normal(0, 250, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(10, 200, n)
    l = np.minimum(o, c) - rng.uniform(10, 200, n)
    t = start - start % 3600 + 3600 * np.arange(n)
    return pd.DataFrame({"time": t, "open": o, "high": h, "low": l, "close": c})


# ----------------------------------------------------------------- regras = backtest
def backtest_engine():
    """backtest/claude_code/engine.py, carregado uma vez só pelo engine2 (o cache do numba exige o mesmo nome)."""
    pytest.importorskip("numba")
    sys.path.insert(0, str(ROOT / "backtest" / "claude_code" / "fase1"))
    import engine2
    return engine2.cc


def test_indicators_match_backtest_engine():
    cc = backtest_engine()
    df = walk()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    assert np.allclose(R.rsi(c, 7), cc.rsi(c, 7))
    assert np.allclose(R.atr(h, l, c, 14), cc.atr(h, l, c, 14))
    assert np.allclose(R.ema(c, 50), cc.ema(c, 50))
    assert np.allclose(R.sma(c, 100), cc.sma(c, 100), equal_nan=True)


def test_signal_cross_and_trend_filter():
    assert R.signal(29.0, 31.0, 100.0, 90.0, 30) == R.BUY
    assert R.signal(29.0, 31.0, 80.0, 90.0, 30) == 0            # abaixo da MA: não compra
    assert R.signal(31.0, 32.0, 100.0, 90.0, 30) == 0           # sem cruzamento
    assert R.signal(71.0, 69.0, 80.0, 90.0, 30) == R.SELL
    assert R.signal(71.0, 69.0, 100.0, 90.0, 30) == 0
    assert R.signal(float("nan"), 31.0, 100.0, 90.0, 30) == 0


def test_trailing_only_tightens():
    st = R.trailing_stop(R.BUY, 100.0, 90.0, 10.0, [105, 120, 110], [95, 100, 100], [5, 5, 5], 0.0, 3.0, 0.0)
    assert st == pytest.approx(120 - 15)                         # extremo 120 - 3*ATR, não volta com a queda
    st = R.trailing_stop(R.SELL, 100.0, 110.0, 10.0, [100, 95, 99], [95, 80, 90], [5, 5, 5], 1.0, 3.0, 0.0)
    assert st == pytest.approx(81 + 15)                          # mínima + spread + 3*ATR
    be = R.trailing_stop(R.BUY, 100.0, 90.0, 10.0, [111], [99], [10], 0.0, 3.0, 1.5, be_r=1.0)
    assert be == 100.0                                           # breakeven antes da ativação do trailing


def test_live_rules_reproduce_backtest_exits():
    """Simula ao vivo com as regras (stop recalculado nas barras fechadas, saída ao tocar) e compara com o bt."""
    cc = backtest_engine()
    df = walk(5000, seed=11)
    d = R.add_indicators(df, P)
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = d["atr"].to_numpy()
    sp = np.full(len(c), 30.0)
    sig = np.zeros(len(c), np.int64)
    for i in range(200, len(c)):
        sig[i] = R.signal(d["rsi"].iat[i - 1], d["rsi"].iat[i], c[i], d["ma"].iat[i], 30)
    pnl, ei, xi, sd = cc.bt(o, h, l, c, sp, a, sig, 1.0, 3.0, 0.0, 0.0, 0)
    assert len(pnl) > 10
    for p, e, x, s in zip(pnl, ei, xi, sd):
        s = int(s)
        entry = o[e] + sp[e] if s == R.BUY else o[e]
        stop0 = R.initial_stop(s, entry, a[e - 1], 1.0)
        for j in range(e, len(c)):
            st = R.trailing_stop(s, entry, stop0, a[e - 1], h[e:j], l[e:j], a[e:j], 30.0, 3.0, 0.0)
            gap = o[j] <= st if s == R.BUY else o[j] + 30 >= st
            touch = l[j] <= st if s == R.BUY else h[j] + 30 >= st
            if gap or touch:
                exitp = (o[j] if s == R.BUY else o[j] + 30) if gap else st
                assert j == x and (exitp - entry) * s == pytest.approx(p)
                break


# ----------------------------------------------------------------- agente com MT5 falso
class FakeMT5:
    TIMEFRAME_H1 = 16385
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009
    DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY = 1, 3
    DEAL_REASON_SL, DEAL_REASON_TP = 4, 5
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, bars: pd.DataFrame, trade_mode=0, balance=1000.0):
        self.bars, self.trade_mode, self.balance = bars, trade_mode, balance
        self.positions, self.sent, self.deals = [], [], []
        self.next_ticket = 500

    def account_info(self):
        return types.SimpleNamespace(login=309673774, trade_mode=self.trade_mode, balance=self.balance)

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01, digits=2, trade_stops_level=0, trade_freeze_level=0,
                                     trade_contract_size=1.0, filling_mode=1, volume_min=0.01)

    def symbol_info_tick(self, s):
        last = int(self.bars["time"].iat[-1])
        return types.SimpleNamespace(bid=float(self.bars["close"].iat[-1]), ask=float(self.bars["close"].iat[-1]) + 30,
                                     time=last + 3600 + 5, time_msc=(last + 3605) * 1000)

    def positions_get(self, symbol=None):
        return list(self.positions)

    def copy_rates_from_pos(self, s, tf, pos, n):
        if pos == 0:
            return np.array([(int(self.bars["time"].iat[-1]) + 3600,)], dtype=[("time", "i8")])
        return self.bars.tail(n).to_records(index=False)

    def history_deals_get(self, *a, **k):
        return list(self.deals)

    def last_error(self):
        return (1, "ok")

    def order_send(self, req):
        self.sent.append(req)
        if req["action"] == self.TRADE_ACTION_DEAL and "position" not in req:
            self.next_ticket += 1
            self.positions.append(types.SimpleNamespace(
                ticket=self.next_ticket, type=req["type"], volume=req["volume"], price_open=req["price"], sl=req["sl"],
                tp=req["tp"], profit=0.0, swap=0.0, magic=req["magic"], time=int(self.bars["time"].iat[-1]) + 3600 + 5))
            return types.SimpleNamespace(retcode=10009, order=self.next_ticket, price=req["price"], comment="done")
        if req["action"] == self.TRADE_ACTION_DEAL:
            self.positions = [p for p in self.positions if p.ticket != req["position"]]
            return types.SimpleNamespace(retcode=10009, order=0, price=req["price"], comment="closed")
        for p in self.positions:
            if p.ticket == req["position"]:
                p.sl = req["sl"]
        return types.SimpleNamespace(retcode=10009, order=0, price=0.0, comment="sltp")


def bars_ending_in_signal(side):
    df = walk(3000, seed=5)
    d = R.add_indicators(df, P)
    for i in range(1600, len(d)):
        if R.signal_last(d.iloc[: i + 1], P) == side:
            return df.iloc[: i + 1].reset_index(drop=True)
    raise AssertionError("sem sinal no passeio aleatório")


def make_agent(tmp_path, cfg, fake, **g_over):
    g = load_agent_config()
    g = {**g, "strategy": dict(P), **g_over}
    return Rsi7H1Agent(fake, cfg, g, state_path=tmp_path / "s.json", csv_path=tmp_path / "t.csv",
                       kill_file=tmp_path / "KILL", config_path=ROOT / "config" / "agente_rsi7_h1.yaml")


@pytest.mark.parametrize("side", [R.BUY, R.SELL])
def test_enters_on_signal_with_atr_stop_and_magic(tmp_path, cfg, side):
    fake = FakeMT5(bars_ending_in_signal(side))
    ag = make_agent(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    entries = [r for r in fake.sent if r["action"] == 1 and "position" not in r]
    assert len(entries) == 1
    req = entries[0]
    a = float(R.add_indicators(fake.bars, P)["atr"].iat[-1])
    assert req["magic"] == 20261114 and req["volume"] == 0.01 and req["tp"] == 0.0
    assert req["type"] == (0 if side == R.BUY else 1)
    assert req["sl"] == pytest.approx(req["price"] - side * 1.0 * a, abs=0.01)
    ag.last_head = 0
    ag.state["last_bar"] = 0
    ag.step()                                                    # mesma barra de novo: não abre a 2ª posição
    assert len([r for r in fake.sent if r["action"] == 1 and "position" not in r]) == MAX_POSITIONS


def test_kill_file_closes_and_blocks(tmp_path, cfg):
    fake = FakeMT5(bars_ending_in_signal(R.BUY))
    ag = make_agent(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    assert len(fake.positions) == 1
    (tmp_path / "KILL").write_text("")
    ag.step()
    assert fake.positions == [] and fake.sent[-1].get("comment") == "RSI7_H1 close"
    ag.last_head, ag.state["last_bar"] = 0, 0
    ag.step()
    assert fake.positions == []                                  # com kill ativo não reabre


def test_daily_loss_flattens_and_blocks_new_entries(tmp_path, cfg):
    fake = FakeMT5(bars_ending_in_signal(R.BUY), balance=1000.0)
    ag = make_agent(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    fake.positions[0].profit = -(DAILY_LOSS_PCT / 100 * 1000.0) - 0.01
    ag.step()
    assert fake.positions == [] and ag.state["blocked_day"] == ag._today()
    ag.last_head, ag.state["last_bar"] = 0, 0
    ag.step()
    assert fake.positions == []


def test_refuses_real_account(tmp_path, cfg):
    fake = FakeMT5(bars_ending_in_signal(R.BUY), trade_mode=2)
    with pytest.raises(AccountGuardError):
        make_agent(tmp_path, cfg, fake).start()


def test_adopts_existing_position_after_restart(tmp_path, cfg):
    fake = FakeMT5(bars_ending_in_signal(R.BUY))
    t_open = int(fake.bars["time"].iat[-50]) + 10
    fake.positions.append(types.SimpleNamespace(ticket=77, type=0, volume=0.01, price_open=float(fake.bars["close"].iat[-51]),
                                                sl=float(fake.bars["close"].iat[-51]) - 500, tp=0.0, profit=0.0, swap=0.0,
                                                magic=20261114, time=t_open))
    ag = make_agent(tmp_path, cfg, fake)
    ag.start()
    tr = ag.state["trades"]["77"]
    assert tr["entry_bar"] == t_open - t_open % 3600 and tr["A"] > 0
    assert fake.positions[0].sl >= tr["stop0"]                   # stop só aperta


def test_auditor_maps_new_magic(cfg):
    names = aud.agent_names(cfg)
    assert names[20261114] == "agente_rsi7_h1" and names[20261113] == "goldnight"
