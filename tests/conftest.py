import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402


@pytest.fixture
def cfg():
    return load_config()


class FakeState:
    def __init__(self, groups=None, filled=None):
        self.groups = groups or {}
        self.filled = set(filled or [])

    def group_entries(self, agent, symbol, group):
        return self.groups.get((agent, symbol, group), 0)

    def is_filled(self, key):
        return key in self.filled


@pytest.fixture
def state():
    return FakeState()


def bars(ohlc, start="2026-03-02 10:00", freq="5min", **cols):
    """DataFrame M5 a partir de lista [(o,h,l,c), ...] + colunas extras (escalares ou listas)."""
    t = pd.date_range(start, periods=len(ohlc), freq=freq, tz="UTC")
    df = pd.DataFrame(ohlc, columns=["open", "high", "low", "close"])
    df.insert(0, "time", t)
    df["close_time"] = df["time"] + pd.Timedelta(freq)
    df["spread"] = 0.0
    for k, v in cols.items():
        df[k] = v
    return df


def random_walk(n=6000, seed=1, start="2026-03-02 00:00", drift=0.0):
    rng = np.random.default_rng(seed)
    t = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    ret = rng.normal(drift, 1.0, n)
    close = 1000 + np.cumsum(ret)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 0.8, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.8, n)
    return pd.DataFrame({"time": t, "open": open_, "high": high, "low": low, "close": close,
                         "spread": np.full(n, 0.1)})


def resample(m5, rule):
    g = m5.set_index("time").resample(rule, label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "spread": g["spread"].min()}).dropna().reset_index()
    return out
