"""Agentes de setup — funções puras sobre o painel causal (mesmo código no backtest e ao vivo).

Cada função recebe o painel M5 (`d5`), o índice `i` da última barra FECHADA, as configs e um
`state` com o histórico de entradas por grupo; devolve a lista de ordens DESEJADAS nesta barra.
O motor reconcilia: LIMITs não reemitidas são canceladas; MARKETs são enviadas uma vez.

A2 PULLBACK (M5)      — a favor do bias: LIMITs escalonadas na zona Fib 0.5–0.618 do último impulso;
                        MARKET só após candle de rejeição/engolfo na zona Fib ou na MA100 M5.
A3 BOS-RETEST (M5)    — após BOS/CHoCH a favor do bias: LIMIT no reteste do nível rompido;
                        invalida se alguma barra fechar de volta dentro da estrutura.
A4 RSI REVERSAL (M15) — RSI(14) <= 25 compra / >= 75 vende + gatilho de price action na zona.
                        trend_filter=ON: compra só acima da MA100 H1, venda só abaixo.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Protocol

import numpy as np
import pandas as pd

from engine.indicators import bearish_confirmation, bullish_confirmation
from engine.types import BUY, SELL, OrderIntent


class EntryState(Protocol):
    def group_entries(self, agent: str, symbol: str, group: str) -> int: ...
    def is_filled(self, key: str) -> bool: ...


def _ts_id(ts: pd.Timestamp) -> str:
    return str(int(pd.Timestamp(ts).timestamp()))


def _ok(x: float) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


# ===================================================================== A2
def a2_pullback(d5: pd.DataFrame, i: int, symbol: str, acfg: Dict[str, Any], state: EntryState,
                spread: float = 0.0) -> List[OrderIntent]:
    agent = "A2_PULLBACK"
    bias = int(d5["bias"].iat[i])
    atr = float(d5["atr"].iat[i])
    if bias == 0 or not _ok(atr) or atr <= 0:
        return []
    side = BUY if bias > 0 else SELL
    hi, lo, op, cl = (d5[c].to_numpy() for c in ("high", "low", "open", "close"))

    # origem do impulso = último swing contrário confirmado
    o_idx = int(d5["sl_idx"].iat[i] if side == BUY else d5["sh_idx"].iat[i])
    if o_idx < 0 or o_idx >= i:
        return []
    origin = lo[o_idx] if side == BUY else hi[o_idx]
    seg_h, seg_l = hi[o_idx + 1:i + 1], lo[o_idx + 1:i + 1]
    if side == BUY:
        if seg_l.min() < origin:          # impulso invalidado (rompeu a origem)
            return []
        ext_idx = o_idx + 1 + int(np.argmax(seg_h))
        extreme = hi[ext_idx]
        imp = extreme - origin
    else:
        if seg_h.max() > origin:
            return []
        ext_idx = o_idx + 1 + int(np.argmin(seg_l))
        extreme = lo[ext_idx]
        imp = origin - extreme
    if imp < float(acfg.get("impulse_min_atr", 2.0)) * atr:
        return []
    if i - ext_idx > int(acfg.get("limit_expiry_bars", 24)):
        return []                          # impulso velho: pullback não aconteceu a tempo

    group = f"imp{_ts_id(d5['time'].iat[o_idx])}"
    max_e = int(acfg.get("max_entries_per_impulse", 3))
    used = state.group_entries(agent, symbol, group)
    if used >= max_e:
        return []

    levels = sorted(float(f) for f in acfg.get("fib_levels", [0.5, 0.559, 0.618]))
    lvl_price = {f: extreme - side * f * imp for f in levels}
    buf = float(acfg.get("sl_buffer_atr", 0.2)) * atr
    sl = origin - side * buf
    tp = origin + side * float(acfg.get("tp_extension", 1.272)) * imp
    out: List[OrderIntent] = []
    close = cl[i]
    slots = max_e - used

    # MARKET: candle de confirmação na zona Fib ou na MA100
    zone_near, zone_far = lvl_price[levels[0]], lvl_price[levels[-1]]
    confirm = (bullish_confirmation if side == BUY else bearish_confirmation)(
        op[i], hi[i], lo[i], cl[i], op[i - 1], cl[i - 1])
    if confirm and slots > 0:
        touched_fib = (lo[i] <= zone_near and cl[i] > zone_far) if side == BUY else \
                      (hi[i] >= zone_near and cl[i] < zone_far)
        ma = float(d5["sma"].iat[i])
        tol = float(acfg.get("ma_touch_atr", 0.15)) * atr
        touched_ma = _ok(ma) and (
            (lo[i] <= ma + tol and cl[i] > ma and origin < ma < extreme) if side == BUY else
            (hi[i] >= ma - tol and cl[i] < ma and extreme < ma < origin))
        if touched_fib or touched_ma:
            m_sl = sl if touched_fib else (lo[i] - buf if side == BUY else hi[i] + buf)
            key = f"{agent}|{symbol}|{group}|mkt{_ts_id(d5['time'].iat[i])}"
            if not state.is_filled(key):
                out.append(OrderIntent(key, agent, symbol, side, "MARKET", float(close), float(m_sl), float(tp),
                                       "FIB_CONFIRM" if touched_fib else "MA100_CONFIRM", group,
                                       atr=atr, spread=spread))
                slots -= 1

    # LIMITs escalonadas (só se o preço ainda não chegou ao nível)
    for f in levels:
        if slots <= 0:
            break
        key = f"{agent}|{symbol}|{group}|fib{f}"
        if state.is_filled(key):
            continue
        px = lvl_price[f]
        valid = (px < close - spread) if side == BUY else (px > close + spread)
        if not valid:
            continue
        out.append(OrderIntent(key, agent, symbol, side, "LIMIT", float(px), float(sl), float(tp),
                               f"FIB_LIMIT_{f}", group, atr=atr, spread=spread))
        slots -= 1
    return out


# ===================================================================== A3
def a3_bos_retest(d5: pd.DataFrame, i: int, symbol: str, acfg: Dict[str, Any], state: EntryState,
                  spread: float = 0.0) -> List[OrderIntent]:
    agent = "A3_BOS_RETEST"
    bias = int(d5["bias"].iat[i])
    atr = float(d5["atr"].iat[i])
    if bias == 0 or not _ok(atr) or atr <= 0:
        return []
    b = int(d5["brk_idx"].iat[i])
    bdir = int(d5["brk_dir"].iat[i])
    if b < 0 or bdir != bias or i - b > int(acfg.get("max_bars_after_bos", 24)):
        return []
    side = BUY if bias > 0 else SELL
    level = float(d5["brk_level"].iat[i])
    origin = float(d5["pre_brk_swing"].iat[i])
    if not (_ok(level) and _ok(origin)):
        return []
    cl = d5["close"].to_numpy()
    # invalida se alguma barra após o rompimento fechou de volta dentro da estrutura
    after = cl[b + 1:i + 1]
    if len(after) and ((after < level).any() if side == BUY else (after > level).any()):
        return []
    hi, lo = d5["high"].to_numpy(), d5["low"].to_numpy()
    extreme = hi[b:i + 1].max() if side == BUY else lo[b:i + 1].min()
    leg = abs(extreme - origin)
    if leg < float(acfg.get("min_break_leg_atr", 1.5)) * atr:
        return []
    group = f"bos{_ts_id(d5['time'].iat[b])}"
    if state.group_entries(agent, symbol, group) >= 1:
        return []
    key = f"{agent}|{symbol}|{group}|retest"
    if state.is_filled(key):
        return []
    px = level + side * float(acfg.get("retest_offset_atr", 0.05)) * atr
    close = cl[i]
    if not ((px < close - spread) if side == BUY else (px > close + spread)):
        return []
    sl = level - side * float(acfg.get("sl_beyond_level_atr", 1.0)) * atr
    tp = origin + side * float(acfg.get("tp_extension", 1.272)) * leg
    expiry = d5["close_time"].iat[b] + pd.Timedelta(minutes=5 * int(acfg.get("max_bars_after_bos", 24)))
    return [OrderIntent(key, agent, symbol, side, "LIMIT", float(px), float(sl), float(tp),
                        "BOS_RETEST" if not bool(d5["choch"].iat[b]) else "CHOCH_RETEST", group,
                        expiry=expiry, atr=atr, spread=spread)]


# ===================================================================== A4
def a4_rsi_reversal(d15: pd.DataFrame, j: int, symbol: str, acfg: Dict[str, Any], state: EntryState,
                    atr_m5: float, spread: float = 0.0) -> List[OrderIntent]:
    """Avaliado no fechamento de cada M15 (índice j do painel M15)."""
    agent = "A4_RSI_REVERSAL"
    if j < 2:
        return []
    rsi = d15["rsi"].to_numpy()
    look = int(acfg.get("zone_lookback_bars", 3))
    win = rsi[max(0, j - look + 1):j + 1]
    if np.isnan(win).all():
        return []
    op, hi, lo, cl = (d15[c].to_numpy() for c in ("open", "high", "low", "close"))
    oversold, overbought = float(acfg.get("oversold", 25)), float(acfg.get("overbought", 75))
    side = 0
    if np.nanmin(win) <= oversold and bullish_confirmation(op[j], hi[j], lo[j], cl[j], op[j - 1], cl[j - 1]):
        side = BUY
    elif np.nanmax(win) >= overbought and bearish_confirmation(op[j], hi[j], lo[j], cl[j], op[j - 1], cl[j - 1]):
        side = SELL
    if side == 0:
        return []
    if bool(acfg.get("trend_filter", True)) and int(d15["h1_above_ma"].iat[j]) != side:
        return []

    # episódio = sequência contínua de barras na zona; 1 entrada por episódio
    in_zone = (lambda v: v <= oversold) if side == BUY else (lambda v: v >= overbought)
    z = max(k for k in range(max(0, j - look + 1), j + 1) if not np.isnan(rsi[k]) and in_zone(rsi[k]))
    e = z
    while e - 1 >= 0 and not np.isnan(rsi[e - 1]) and in_zone(rsi[e - 1]):
        e -= 1
    group = f"rsi{_ts_id(d15['time'].iat[e])}"
    if state.group_entries(agent, symbol, group) >= 1:
        return []
    key = f"{agent}|{symbol}|{group}"
    if state.is_filled(key):
        return []
    atr15 = float(d15["atr"].iat[j])
    n = int(acfg.get("sl_lookback_bars", 5))
    buf = float(acfg.get("sl_buffer_atr", 0.2)) * (atr15 if _ok(atr15) else atr_m5)
    sl = lo[max(0, j - n + 1):j + 1].min() - buf if side == BUY else hi[max(0, j - n + 1):j + 1].max() + buf
    entry = float(cl[j])
    risk = abs(entry - sl)
    tp = entry + side * float(acfg.get("tp_r", 2.0)) * risk
    return [OrderIntent(key, agent, symbol, side, "MARKET", entry, float(sl), float(tp),
                        "RSI_OVERSOLD" if side == BUY else "RSI_OVERBOUGHT", group,
                        atr=float(atr_m5), spread=spread, tp_r=float(acfg.get("tp_r", 2.0)))]
