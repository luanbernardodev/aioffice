import numpy as np
import pandas as pd

from engine import indicators as ind
from engine.features import build_features, server_to_utc
from tests.conftest import random_walk, resample


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).iloc[-1] == 100.0
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] < 1.0


def test_atr_constant_range():
    df = pd.DataFrame({"open": [10.0] * 40, "high": [11.0] * 40, "low": [9.0] * 40, "close": [10.0] * 40})
    assert abs(ind.atr(df).iloc[-1] - 2.0) < 1e-9


def test_swing_confirmed_only_after_k_bars():
    high = np.array([1, 2, 3, 9, 3, 2, 1, 1, 1], dtype=float)
    low = high - 0.5
    sw = ind.swings(high, low, k=3)
    assert sw["sh_idx"][5] == -1          # pivô em 3 ainda não confirmado
    assert sw["sh_idx"][6] == 3 and sw["sh_price"][6] == 9


def test_structure_bos_and_choch():
    close = np.array([5, 6, 7, 6, 5, 4, 3, 2, 8, 9])
    sw = {"sh_price": np.r_[[np.nan] * 4, [7] * 6], "sh_idx": np.r_[[-1] * 4, [2] * 6],
          "sl_price": np.r_[[np.nan] * 4, [np.nan] * 2, [3.5] * 4], "sl_idx": np.r_[[-1] * 6, [5] * 4]}
    st = ind.structure(close.astype(float), sw)
    assert st["break_dir"][6] == -1 and not st["choch"][6]    # primeiro rompimento (sem tendência prévia)
    assert st["break_dir"][7] == 0                            # mesmo swing não rompe duas vezes
    assert st["break_dir"][8] == 1 and st["choch"][8]         # inversão = CHoCH
    assert st["trend"][9] == 1


def test_candle_confirmations():
    assert ind.bullish_confirmation(10, 10.2, 8, 10.1, 10.5, 10.0)          # pin bar de compra
    assert ind.bullish_confirmation(9.9, 11, 9.8, 10.8, 10.6, 10.0)         # engolfo de alta
    assert not ind.bullish_confirmation(10, 10.5, 9.9, 10.1, 9.9, 10.0)
    assert ind.bearish_confirmation(10, 12, 9.8, 9.9, 9.5, 10.0)            # pin bar de venda
    assert ind.bearish_confirmation(10.1, 10.2, 9.0, 9.2, 9.5, 10.0)        # engolfo de baixa


def test_server_time_ny_plus_7():
    # 2026-07-15 12:00 servidor (verão: UTC+3) -> 09:00 UTC ; 2026-01-15 12:00 (inverno: UTC+2) -> 10:00 UTC
    summer = int(pd.Timestamp("2026-07-15 12:00").timestamp())
    winter = int(pd.Timestamp("2026-01-15 12:00").timestamp())
    out = server_to_utc([summer, winter])
    assert out.iloc[0] == pd.Timestamp("2026-07-15 09:00", tz="UTC")
    assert out.iloc[1] == pd.Timestamp("2026-01-15 10:00", tz="UTC")


def test_features_have_no_lookahead(cfg):
    """O painel calculado só com o passado tem que bater com o painel completo na mesma barra."""
    m5 = random_walk(9000, seed=7, drift=0.05)
    m15, h1 = resample(m5, "15min"), resample(m5, "1h")
    full = build_features(m5, m15, h1, cfg)["m5"]
    cols = ["atr", "sma", "sh_price", "sl_price", "trend", "brk_level", "bias", "m15_trend", "h1_side",
            "h1_above_ma", "m15_new"]
    for cut in (8000, 8003, 8500, 8999):
        T = m5["time"].iloc[cut] + pd.Timedelta("5min")      # fechamento da barra `cut`
        p5 = m5.iloc[:cut + 1]
        p15 = m15[m15["time"] + pd.Timedelta("15min") <= T]
        ph = h1[h1["time"] + pd.Timedelta("1h") <= T]
        part = build_features(p5, p15, ph, cfg)["m5"]
        a, b = part.iloc[-1], full.iloc[cut]
        for c in cols:
            va, vb = a[c], b[c]
            if isinstance(va, float) and np.isnan(va):
                assert np.isnan(vb), c
            else:
                assert np.isclose(va, vb, rtol=1e-6, atol=1e-8) if isinstance(va, float) else va == vb, (cut, c, va, vb)


def test_bias_long_in_uptrend_short_in_downtrend(cfg):
    up = random_walk(9000, seed=3, drift=0.25)
    f = build_features(up, resample(up, "15min"), resample(up, "1h"), cfg)["m5"]
    assert (f["bias"].iloc[-2000:] == 1).mean() > 0.6
    assert (f["bias"].iloc[-2000:] == -1).mean() < 0.05
    dn = random_walk(9000, seed=3, drift=-0.25)
    f = build_features(dn, resample(dn, "15min"), resample(dn, "1h"), cfg)["m5"]
    assert (f["bias"].iloc[-2000:] == -1).mean() > 0.6
