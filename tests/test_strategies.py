import numpy as np
import pytest

from engine.strategies import a2_pullback, a3_bos_retest, a4_rsi_reversal
from engine.types import BUY, SELL
from tests.conftest import FakeState, bars

# ----------------------------------------------------------------- A2
# origem do impulso (swing low) em idx 2 = 100; topo em idx 8 = 110; ATR 2 -> impulso 10 = 5 ATR
A2_OHLC = [(103, 104, 102, 103), (102, 103, 101, 101.5), (101, 101.5, 100, 101), (101, 103, 100.8, 102.8),
           (102.8, 105, 102.5, 104.8), (104.8, 107, 104.5, 106.8), (106.8, 108, 106, 107.5),
           (107.5, 109, 107, 108.8), (108.8, 110, 108.5, 109.5), (109.5, 109.6, 108, 108.2),
           (108.2, 108.4, 107.5, 108.0)]


def a2_frame(ohlc=A2_OHLC, bias=1, sma=np.nan):
    n = len(ohlc)
    return bars(ohlc, bias=bias, atr=2.0, sma=sma, sl_idx=[-1] * 5 + [2] * (n - 5), sh_idx=-1)


def test_a2_places_staggered_limits_in_fib_zone(cfg):
    out = a2_pullback(a2_frame(), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState())
    assert [o.kind for o in out] == ["LIMIT"] * 3
    prices = sorted(o.price for o in out)
    assert prices == pytest.approx([110 - 0.618 * 10, 110 - 0.559 * 10, 105.0])
    o = out[0]
    assert o.side == BUY and o.sl == pytest.approx(100 - 0.2 * 2) and o.tp == pytest.approx(100 + 1.272 * 10)
    assert len({o.group for o in out}) == 1


def test_a2_neutral_bias_does_nothing(cfg):
    assert a2_pullback(a2_frame(bias=0), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState()) == []


def test_a2_never_against_bias(cfg):
    # bias SHORT com impulso de alta: não deve comprar (e não há impulso de baixa válido)
    out = a2_pullback(a2_frame(bias=-1), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState())
    assert all(o.side == SELL for o in out)


def test_a2_invalidated_when_origin_broken(cfg):
    ohlc = A2_OHLC[:-1] + [(108, 108.2, 99.5, 100.2)]
    assert a2_pullback(a2_frame(ohlc), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState()) == []


def test_a2_market_only_after_confirmation_candle(cfg):
    # barra 10 toca 0.5 (105) e fecha engolfando acima da zona
    ohlc = A2_OHLC[:-2] + [(106.8, 107.0, 105.6, 105.8), (105.7, 107.2, 104.8, 107.0)]
    out = a2_pullback(a2_frame(ohlc), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState())
    mk = [o for o in out if o.kind == "MARKET"]
    assert len(mk) == 1 and mk[0].setup == "FIB_CONFIRM" and mk[0].side == BUY
    # sem confirmação (candle de baixa) -> nenhuma ordem a mercado
    ohlc2 = A2_OHLC[:-2] + [(108.5, 108.6, 105.6, 105.8), (105.8, 106.0, 104.8, 105.1)]
    assert not [o for o in a2_pullback(a2_frame(ohlc2), 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState())
                if o.kind == "MARKET"]


def test_a2_max_three_entries_per_impulse(cfg):
    acfg = cfg["agents"]["A2_PULLBACK"]
    first = a2_pullback(a2_frame(), 10, "GOLD", acfg, FakeState())
    g = first[0].group
    st = FakeState(groups={("A2_PULLBACK", "GOLD", g): 2}, filled=[first[0].key, first[1].key])
    out = a2_pullback(a2_frame(), 10, "GOLD", acfg, st)
    assert len(out) == 1
    st3 = FakeState(groups={("A2_PULLBACK", "GOLD", g): 3})
    assert a2_pullback(a2_frame(), 10, "GOLD", acfg, st3) == []


def test_a2_ma100_confirmation(cfg):
    # MA100 em 107.6 (dentro do impulso); candle de rejeição tocando a média
    ohlc = A2_OHLC[:-1] + [(108.0, 108.3, 107.5, 108.2)]
    df = a2_frame(ohlc, sma=107.6)
    out = a2_pullback(df, 10, "GOLD", cfg["agents"]["A2_PULLBACK"], FakeState())
    mk = [o for o in out if o.kind == "MARKET"]
    assert len(mk) == 1 and mk[0].setup == "MA100_CONFIRM"


# ----------------------------------------------------------------- A3
def a3_frame(closes, bias=1, b=3, level=105.0, origin=100.0, choch=False):
    ohlc = [(c - 0.3, c + 0.5, c - 0.5, c) for c in closes]
    n = len(ohlc)
    return bars(ohlc, bias=bias, atr=2.0, brk_idx=[-1] * b + [b] * (n - b),
                brk_dir=[0] * b + [1 if bias >= 0 else -1] * (n - b),
                brk_level=[np.nan] * b + [level] * (n - b), pre_brk_swing=[np.nan] * b + [origin] * (n - b),
                choch=choch)


def test_a3_limit_on_retest_after_bos(cfg):
    df = a3_frame([103, 104, 104.5, 106.5, 107.5, 107.0])
    out = a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], FakeState())
    assert len(out) == 1
    o = out[0]
    assert o.kind == "LIMIT" and o.side == BUY and o.price == pytest.approx(105 + 0.05 * 2)
    assert o.sl == pytest.approx(105 - 2.0) and o.expiry is not None


def test_a3_invalid_when_close_back_inside_structure(cfg):
    df = a3_frame([103, 104, 104.5, 106.5, 104.8, 106.0])
    assert a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], FakeState()) == []


def test_a3_requires_bias_alignment(cfg):
    df = a3_frame([103, 104, 104.5, 106.5, 107.5, 107.0])
    df["bias"] = 0
    assert a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], FakeState()) == []
    df["bias"] = -1   # rompimento de alta com bias de baixa
    assert a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], FakeState()) == []


def test_a3_one_entry_per_bos(cfg):
    df = a3_frame([103, 104, 104.5, 106.5, 107.5, 107.0])
    g = a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], FakeState())[0].group
    st = FakeState(groups={("A3_BOS_RETEST", "GOLD", g): 1})
    assert a3_bos_retest(df, 5, "GOLD", cfg["agents"]["A3_BOS_RETEST"], st) == []


# ----------------------------------------------------------------- A4
def a4_frame(rsi_vals, last_candle, h1_above=1):
    base = [(100, 100.5, 99.5, 100)] * (len(rsi_vals) - 2)
    ohlc = base + [(100.0, 100.2, 98.8, 99.0), last_candle]
    return bars(ohlc, freq="15min", rsi=rsi_vals, atr=1.5, h1_above_ma=h1_above)


ENGULF_UP = (98.9, 100.4, 98.5, 100.2)
ENGULF_DN = (101.0, 101.4, 99.6, 99.7)


def test_a4_buy_on_oversold_with_price_action(cfg):
    acfg = cfg["agents"]["A4_RSI_REVERSAL"]
    df = a4_frame([50, 40, 30, 24, 27], ENGULF_UP)
    out = a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(), atr_m5=0.8)
    assert len(out) == 1 and out[0].side == BUY and out[0].kind == "MARKET" and out[0].tp_r == 2.0
    assert out[0].sl < df["low"].iloc[-5:].min()


def test_a4_no_trade_without_price_action(cfg):
    df = a4_frame([50, 40, 30, 24, 27], (99.0, 99.2, 98.0, 98.2))
    assert a4_rsi_reversal(df, 4, "BTCUSD", cfg["agents"]["A4_RSI_REVERSAL"], FakeState(), atr_m5=0.8) == []


def test_a4_trend_filter_on_off(cfg):
    acfg = dict(cfg["agents"]["A4_RSI_REVERSAL"])
    df = a4_frame([50, 40, 30, 24, 27], ENGULF_UP, h1_above=-1)  # abaixo da MA100 H1
    acfg["trend_filter"] = True
    assert a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(), atr_m5=0.8) == []
    acfg["trend_filter"] = False
    assert len(a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(), atr_m5=0.8)) == 1


def test_a4_sell_on_overbought(cfg):
    acfg = dict(cfg["agents"]["A4_RSI_REVERSAL"], trend_filter=False)
    df = a4_frame([50, 60, 70, 78, 74], (101.3, 101.4, 99.6, 99.7))
    df.loc[df.index[-2], ["open", "close"]] = [100.0, 101.2]
    out = a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(), atr_m5=0.8)
    assert len(out) == 1 and out[0].side == SELL


def test_a4_one_entry_per_episode(cfg):
    acfg = cfg["agents"]["A4_RSI_REVERSAL"]
    df = a4_frame([50, 40, 30, 24, 27], ENGULF_UP)
    g = a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(), atr_m5=0.8)[0].group
    assert a4_rsi_reversal(df, 4, "BTCUSD", acfg, FakeState(groups={("A4_RSI_REVERSAL", "BTCUSD", g): 1}),
                           atr_m5=0.8) == []
