"""engine2 (Fase 1) = bt original quando BE/slippage/swap estão desligados; extras funcionam como descrito."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("numba")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest" / "claude_code" / "fase1"))
import engine2 as E  # noqa: E402
from run_fase1 import neighbor_frac  # noqa: E402


def data(n=3000, seed=2):
    rng = np.random.default_rng(seed)
    c = 60000 + np.cumsum(rng.normal(0, 200, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(5, 150, n)
    l = np.minimum(o, c) - rng.uniform(5, 150, n)
    sp = rng.uniform(20, 60, n)
    a = E.atr(h, l, c, 14)
    r = E.rsi(c, 7)
    s = np.zeros(n, np.int64)
    s[(r > 30) & (np.roll(r, 1) <= 30)] = 1
    s[(r < 70) & (np.roll(r, 1) >= 70)] = -1
    s[:100] = 0
    return o, h, l, c, sp, a, s


@pytest.mark.parametrize("ex", [(1.0, 3.0, 0.0, 0.0, 0), (1.5, 2.0, 1.0, 3.0, 0), (3.0, 5.0, 1.5, 0.0, 72)])
def test_bt2_equals_original(ex):
    o, h, l, c, sp, a, s = data()
    p1, e1, x1, d1 = E.bt_original(o, h, l, c, sp, a, s, *ex)
    p2, e2, x2, d2 = E.bt2(o, h, l, c, sp, a, s, *ex[:4], 0.0, ex[4])
    assert len(p1) > 20 and np.allclose(p1, p2) and (e1 == e2).all() and (x1 == x2).all()


def test_grid_metrics_match_trade_list():
    o, h, l, c, sp, a, s = data()
    ex = np.array([[1.0, 3.0, 0.0, 0.0, 0.0, 0.0], [2.0, 4.0, 1.0, 3.0, 1.0, 48.0]])
    roll = np.arange(len(c)) // 24.0
    wf = np.array([[500, 1200], [1200, 2000], [2000, 3000]])
    res = E.grid(o, h, l, c, sp, a, s[None, :], ex, 1500, wf, 0.5, roll, -32.2, -21.5, 0.0, 0.0)
    for k, e in enumerate(ex):
        p, ei, _, _ = E.bt2(o, h, l, c, sp, a, s, *e[:5], int(e[5]), 0.5, roll, (-32.2, -21.5, 0.0, 0.0))
        m = res[0, k]
        assert m[E.M_N] == len(p) and m[E.M_NET] == pytest.approx(p.sum(), rel=1e-4)
        assert m[E.M_NIS] == (ei < 1500).sum() and m[E.M_MAXW] == pytest.approx(p.max(), rel=1e-4)
        assert m[E.M_WF0] == ((ei >= 500) & (ei < 1200)).sum()


def test_costs_reduce_pnl_and_breakeven_caps_loss():
    o, h, l, c, sp, a, s = data()
    base = E.bt2(o, h, l, c, sp, a, s, 1.0, 3.0, 0.0, 0.0)[0].sum()
    roll = np.arange(len(c)) // 24.0
    assert E.bt2(o, h, l, c, sp * 1.5, a, s, 1.0, 3.0, 0.0, 0.0, 0.0, 0, 0.1)[0].sum() < base
    assert E.bt2(o, h, l, c, sp, a, s, 1.0, 3.0, 0.0, 0.0, 0.0, 0, 0.0, roll, (-32.2, -21.5, 0, 0))[0].sum() < base


def test_rollovers_count_server_midnights():
    t = pd.Series(pd.date_range("2026-03-02 20:00", periods=8, freq="h", tz="UTC"))    # 22:00 UTC = 00:00 servidor (UTC+2)
    r = E.rollovers(t, 7)
    assert list(r) == [0, 0, 1, 1, 1, 1, 1, 1]


def test_neighbor_fraction():
    pos = np.array([[True, False, True], [True, True, True]])
    nb = neighbor_frac(pos)
    assert nb[0, 0] == pytest.approx(0.5) and nb[1, 1] == pytest.approx(2 / 3) and nb[1, 2] == pytest.approx(1.0)
