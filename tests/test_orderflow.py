"""Módulo orderflow: métricas por barra, sinais da série (só passado), leitura dos aggTrades e mapeamento XM."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from orderflow import binance_data as BD
from orderflow.metrics import bar_metrics, map_to_xm, series_features


def test_bar_metrics_poc_value_area_and_stacked():
    lvl = np.array([100, 101, 102, 103, 104, 105])
    buy = np.array([1, 1, 9, 9, 9, 1.0])
    sell = np.array([2, 2, 2, 2, 1, 1.0])
    m = bar_metrics(lvl, buy, sell, 10.0)
    assert m["delta"] == pytest.approx(20.0) and m["vol"] == pytest.approx(40.0)
    assert m["poc"] == pytest.approx(1025.0)                       # nível 102 (11) empata com 103 -> primeiro
    assert m["val"] <= m["poc"] <= m["vah"]
    assert m["stk_buy"] == 3 and m["stk_sell"] == 0                # 102, 103, 104 com buy >= 3x sell do nível abaixo
    va = sum(b + s for l, b, s in zip(lvl, buy, sell) if m["val"] <= l * 10 < m["vah"])
    assert va >= 0.7 * m["vol"]


def test_bar_metrics_fills_gaps_and_handles_single_level():
    m = bar_metrics(np.array([10, 13]), np.array([1.0, 1.0]), np.array([0.0, 3.0]), 10.0)
    assert m["low_share"] == pytest.approx(0.2) and m["high_share"] == pytest.approx(0.8)   # 2 níveis mais baixos: 10, 11
    one = bar_metrics(np.array([7]), np.array([2.0]), np.array([1.0]), 10.0)
    assert one["poc"] == pytest.approx(75.0) and one["stk_buy"] == 0


def _bars(n=130, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    hour = np.arange(n) * 3_600_000
    b = pd.DataFrame({"hour": hour, "open": c, "high": c + 1, "low": c - 1, "close": c})
    m = pd.DataFrame({"hour": hour, "delta": rng.normal(0, 10, n), "stk_buy": rng.integers(0, 5, n),
                      "stk_sell": rng.integers(0, 5, n), "low_share": rng.uniform(0, .2, n),
                      "high_share": rng.uniform(0, .2, n), "poc": c, "vah": c + .5, "val": c - .5})
    return b, m


def test_series_features_use_only_the_past():
    b, m = _bars()
    full = series_features(b, m)
    for k in (110, 125):
        part = series_features(b.iloc[:k], m.iloc[:k])
        cols = ["dz", "absorb_bull", "absorb_bear", "exh_bull", "exh_bear", "cvd_div_buy", "stacked_bull"]
        pd.testing.assert_series_equal(part[cols].iloc[-1], full[cols].iloc[k - 1], check_names=False)


def test_absorption_definition():
    b, m = _bars()
    m.loc[120, "delta"] = -500.0                                   # venda enorme...
    b.loc[120, "low"] = b.loc[117:119, "low"].min() + 0.01         # ...sem nova mínima de 3 barras
    f = series_features(b, m)
    assert bool(f.loc[120, "absorb_bull"]) and f.loc[120, "dz"] <= -2


def test_iter_trades_converts_microseconds_and_aggressor(tmp_path):
    rows = "1,100.5,0.2,1,1,1762000000000123,True,True\n2,100.6,0.3,2,2,1762000000500000,False,True\n"
    p = tmp_path / "BTCUSDT-aggTrades-x.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x.csv", rows)
    ch = next(BD.iter_trades(p))
    assert ch["time"].tolist() == [1762000000000, 1762000000500]
    assert ch["sell"].tolist() == [True, False] and ch["qty"].sum() == pytest.approx(0.5)


def test_map_to_xm_shifts_levels_by_close_difference():
    f = pd.DataFrame({"hour": [0, 3_600_000], "close": [100.0, 110.0], "poc": [99.0, 108.0], "vah": [101.0, 111.0],
                      "val": [98.0, 107.0]})
    out = map_to_xm(f, pd.Series({0: 75.0, 3_600_000: 90.0}))
    assert out["offset"].tolist() == [-25.0, -20.0] and out["poc_xm"].tolist() == [74.0, 88.0]


def test_default_files_cover_requested_period():
    urls = BD.default_files()
    assert urls[0].endswith("BTCUSDT-aggTrades-2025-11.zip") and "monthly" in urls[0]
    assert urls[-1].endswith("BTCUSDT-aggTrades-2026-11-10.zip") and "daily" in urls[-1]
    assert len(urls) == 12 + 10
