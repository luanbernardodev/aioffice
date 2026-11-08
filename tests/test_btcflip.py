import json
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from agents.goldflip_supervisor import GoldFlipSupervisor, classify_regime_h4, decide_control
from engine.regime import NewsCalendar

SAT = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)      # sábado de madrugada: BTC opera 24/7


def h4(n=400, drift=50.0, seed=1):
    rng = np.random.default_rng(seed)
    close = 60000 + np.cumsum(drift + rng.normal(0, 300, n))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "high": np.maximum(op, close) + 150, "low": np.minimum(op, close) - 150,
                         "close": close})


def test_regime_h4_direction(cfg):
    r = cfg["btcflip"]["regime"]
    assert classify_regime_h4(h4(drift=60), r)["direction"] == 1
    assert classify_regime_h4(h4(drift=-60), r)["direction"] == -1
    assert classify_regime_h4(h4(n=100), r)["regime"] == "unknown"


def test_btc_control_24_7_and_no_flatten_on_news_or_kill(cfg):
    g = dict(cfg["btcflip"], name="btcflip")
    reg = {"regime": "trend", "direction": 1, "atr": 800.0}
    c = decide_control(reg, SAT, g, point=0.01)
    assert c["enabled"] is True and c["flatten"] is False and c["trail_atr"] == 3.0
    assert c["max_spread"] == int(0.15 * 800 / 0.01) and c["source"] == "quant-office/btcflip_supervisor"
    cal = NewsCalendar(g["news_keywords"], g["news_window_minutes"])
    cal.add_event(datetime(2026, 11, 7, 3, 20, tzinfo=timezone.utc), "FOMC Statement")
    n = decide_control(reg, SAT, g, 0.01, cal)
    assert n["enabled"] is False and n["flatten"] is False                   # notícia: só não abre
    k = decide_control(reg, SAT, g, 0.01, kill_reason="DD diário 3.1%")
    assert k["enabled"] is False and k["flatten"] is False                   # kill: mantém a perna com SL


class FakeMT5:
    TIMEFRAME_H4 = 16388

    def __init__(self, tmp):
        self.tmp = tmp

    def terminal_info(self):
        return types.SimpleNamespace(data_path=str(self.tmp))

    def symbol_select(self, *a):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(point=0.01)

    def copy_rates_from_pos(self, sym, tf, start, n):
        assert sym == "BTCUSD" and tf == self.TIMEFRAME_H4
        return h4(n, 60).to_records(index=False)


def test_btc_supervisor_writes_its_own_files(cfg, tmp_path):
    sup = GoldFlipSupervisor(FakeMT5(tmp_path), cfg, calendar=NewsCalendar([], 30), section="btcflip")
    ctl = sup.run_cycle(SAT)
    f = sup.dir / "btcflip_control.json"
    assert f.exists() and not (sup.dir / "goldflip_control.json").exists()
    assert json.loads(f.read_text())["enabled"] is True and ctl["direction"] == 1
    assert sup.tag == "BTCFLIP" and sup.magic == 20261109


def test_guard_includes_btc_magic(cfg):
    from engine.risk import AccountGuard
    assert 20261109 in AccountGuard(cfg).magics
