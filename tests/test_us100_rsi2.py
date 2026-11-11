import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import agents.auditor_mt5 as aud
from agents import us100_rsi2_rules as R
from agents.us100_rsi2_h1 import DAILY_LOSS_PCT, Us100Rsi2Agent, load_agent_config
from engine.mt5_broker import AccountGuardError
from tests.test_rsi7_h1 import FakeMT5 as BaseFake

ROOT = Path(__file__).resolve().parent.parent
P = {"rsi_period": 2, "rsi_threshold": 5, "ma_period": 100, "exit_rsi_period": 5, "exit_rsi_level": 60,
     "atr_period": 14, "sl_atr": 3.0, "trail_activate_atr": 1.5, "trail_atr": 1.5}
NOON = datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc)


def walk(n=4000, seed=7, start=1_700_000_000, drift=3.0):
    rng = np.random.default_rng(seed)
    c = 20000 + np.cumsum(rng.normal(drift, 40, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(2, 30, n)
    l = np.minimum(o, c) - rng.uniform(2, 30, n)
    t = start - start % 3600 + 3600 * np.arange(n)
    return pd.DataFrame({"time": t, "open": o, "high": h, "low": l, "close": c, "spread": np.full(n, 250)})


# ----------------------------------------------------------------- backtest
def core():
    pytest.importorskip("numba")
    sys.path.insert(0, str(ROOT / "backtest" / "claude_code" / "us100_validacao"))
    import rsi2_core
    return rsi2_core


def arrays(df):
    o, h, l, c = (df[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    return o, h, l, c, np.full(len(c), 3.5), R.atr(h, l, c, 14)


def test_bt3_equals_reference_bt2():
    K = core()
    df = walk()
    o, h, l, c, sp, A = arrays(df)
    sig = K.entry_signal(c, K.REF)
    xs = K.exit_signal(c, K.REF)
    p1, e1 = K.bt2_original(o, h, l, c, sp, A, sig, xs, 3.0, 0.0, 0.0, 1.5, 1.5)
    p2, e2, x2 = K.bt3(o, h, l, c, sp, A, sig, xs, 3.0, 0.0, 0.0, 1.5, 1.5)
    assert len(p1) > 20 and np.allclose(p1, p2) and (e1 == e2).all() and (x2 > e2).all()


def test_live_rules_reproduce_bt2_trades():
    """Regras do agente (sinal, SL, trailing recalculado nas barras fechadas, saída por RSI(5)) = bt2."""
    K = core()
    df = walk(seed=21)
    d = R.add_indicators(df, P)
    o, h, l, c, sp, A = arrays(df)
    assert np.allclose(A, d["atr"]) and np.allclose(K.rsi(c, 2), d["rsi_in"])
    sig = np.zeros(len(c), np.int64)
    for i in range(200, len(c)):
        sig[i] = R.entry_signal(d["rsi_in"].iat[i], c[i], d["ma"].iat[i], 5)
    xs = np.array([R.exit_signal(v, 60) for v in d["rsi_out"]])
    pnl, ei, xi = K.bt3(o, h, l, c, sp, A, sig, xs, 3.0, 0.0, 0.0, 1.5, 1.5)
    assert len(pnl) > 20
    for p, e, x in zip(pnl, ei, xi):
        entry, a0 = o[e] + sp[e], A[e - 1]
        stop0 = R.initial_stop(entry, a0, 3.0)
        for j in range(e + 1, len(c)):
            st = R.trailing_stop(entry, stop0, a0, h[e:j], A[e:j], 1.5, 1.5)
            if xs[j - 1]:
                exitp = o[j]
            elif o[j] <= st:
                exitp = o[j]
            elif l[j] <= st:
                exitp = st
            else:
                continue
            assert j == x and exitp - entry == pytest.approx(p)
            break


def test_swap_and_real_win_in_simulation():
    K = core()
    si = {"swap_mode": 3, "swap_long": -4.83, "trade_contract_size": 1.0, "point": 0.01, "swap_rollover3days": 5,
          "trade_tick_value": 0.01, "trade_tick_size": 0.01, "volume_min": 0.1}
    assert K.swap_per_roll_pts(si) == pytest.approx(-4.83)
    assert K.usd(100.0, si) == pytest.approx(10.0)                    # 100 pts x 0.1 lote = US$10
    t = pd.DataFrame({"pnl": [5.0, 0.5, -3.0], "a0": [10.0, 10.0, 10.0]})
    t["real_win"] = t.pnl > 0.1 * t.a0
    assert list(t.real_win) == [True, False, False]                   # +0.5 (< 0.1 ATR) não é ganho real


def test_guards_rules():
    assert R.in_blocked_window(datetime(2026, 1, 5, 20, 55, tzinfo=timezone.utc))
    assert R.in_blocked_window(datetime(2026, 1, 5, 21, 10, tzinfo=timezone.utc))
    assert not R.in_blocked_window(datetime(2026, 1, 5, 21, 11, tzinfo=timezone.utc))
    assert not R.in_blocked_window(datetime(2026, 1, 5, 20, 54, tzinfo=timezone.utc))
    assert R.spread_too_wide(9.1, 3.0) and not R.spread_too_wide(9.0, 3.0) and not R.spread_too_wide(5.0, 0.0)
    assert R.trailing_stop(100, 70, 10, [110, 116, 105], [10, 10, 10], 1.5, 1.5) == pytest.approx(101)
    assert R.trailing_stop(100, 70, 10, [114], [10], 1.5, 1.5) == 70  # ainda não ativou (< 1.5 ATR)


# ----------------------------------------------------------------- agente com MT5 falso
class FakeMT5(BaseFake):
    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01, digits=2, trade_stops_level=0, trade_freeze_level=0,
                                     trade_contract_size=1.0, filling_mode=2, volume_min=0.1)

    def symbol_info_tick(self, s):
        t = super().symbol_info_tick(s)
        t.ask = t.bid + getattr(self, "spread_px", 2.5)
        return t


def bars_where(pred, seed=7):
    df = walk(seed=seed)
    d = R.add_indicators(df, P)
    for i in range(1600, len(d)):
        if pred(d.iloc[i]):
            return df.iloc[: i + 1].reset_index(drop=True)
    raise AssertionError("sem barra que satisfaça o predicado")


def entry_bars():
    return bars_where(lambda r: R.entry_signal(r.rsi_in, r.close, r.ma, 5))


def make(tmp_path, cfg, fake, clock=lambda: NOON):
    g = {**load_agent_config(), "strategy": dict(P)}
    return Us100Rsi2Agent(fake, cfg, g, state_path=tmp_path / "s.json", csv_path=tmp_path / "t.csv",
                          kill_file=tmp_path / "KILL", config_path=ROOT / "config" / "agente_us100_rsi2_h1.yaml",
                          clock=clock)


def entries(fake):
    return [r for r in fake.sent if r["action"] == 1 and "position" not in r]


def test_buys_min_lot_with_3atr_stop_no_tp(tmp_path, cfg):
    fake = FakeMT5(entry_bars())
    ag = make(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    (req,) = entries(fake)
    a0 = float(R.add_indicators(fake.bars, P)["atr"].iat[-1])
    assert req["type"] == 0 and req["volume"] == 0.1 and req["magic"] == 20261115 and req["tp"] == 0.0
    assert req["sl"] == pytest.approx(req["price"] - 3.0 * a0, abs=0.01)
    ag.last_head, ag.state["last_bar"] = 0, 0
    ag.step()
    assert len(entries(fake)) == 1                                    # 1 posição por vez


def test_no_entry_in_utc_window_or_wide_spread(tmp_path, cfg):
    fake = FakeMT5(entry_bars())
    ag = make(tmp_path / "a", cfg, fake, clock=lambda: datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc))
    ag.start()
    ag.step()
    assert entries(fake) == []
    fake2 = FakeMT5(entry_bars())
    fake2.spread_px = 3 * 2.5 + 0.01                                  # mediana das barras = 250 pts = 2.5
    ag2 = make(tmp_path / "b", cfg, fake2)
    ag2.start()
    ag2.step()
    assert entries(fake2) == []


def test_exit_signal_closes_position(tmp_path, cfg):
    fake = FakeMT5(bars_where(lambda r: r.rsi_out > 60))
    t_open = int(fake.bars["time"].iat[-30]) + 10
    fake.positions.append(types.SimpleNamespace(ticket=91, type=0, volume=0.1, price_open=float(fake.bars["close"].iat[-31]),
                                                sl=float(fake.bars["close"].iat[-31]) - 300, tp=0.0, profit=0.0,
                                                swap=0.0, magic=20261115, time=t_open))
    ag = make(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    assert fake.positions == [] and fake.sent[-1]["comment"] == "US100_RSI2 close"


def test_kill_switch_and_daily_loss(tmp_path, cfg):
    fake = FakeMT5(entry_bars(), balance=1000.0)
    ag = make(tmp_path, cfg, fake)
    ag.start()
    ag.step()
    fake.positions[0].profit = -(DAILY_LOSS_PCT / 100 * 1000.0) - 0.01
    ag.step()
    assert fake.positions == [] and ag.state["blocked_day"] == "2026-11-10"
    fake2 = FakeMT5(entry_bars())
    ag2 = make(tmp_path / "k", cfg, fake2)
    ag2.start()
    ag2.step()
    (tmp_path / "k" / "KILL").write_text("")
    ag2.kill_file = tmp_path / "k" / "KILL"
    ag2.step()
    assert fake2.positions == []


def test_refuses_real_account(tmp_path, cfg):
    with pytest.raises(AccountGuardError):
        make(tmp_path, cfg, FakeMT5(entry_bars(), trade_mode=2)).start()


def test_auditor_maps_us100_magic(cfg):
    names = aud.agent_names(cfg)
    assert names[20261115] == "us100_rsi2_h1" and names[20261114] == "agente_rsi7_h1"
