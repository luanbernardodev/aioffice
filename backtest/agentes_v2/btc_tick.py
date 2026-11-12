"""BTCUSD tick a tick: SWEEP48 e RSI20 com o código de sinal dos agentes e saídas por tick (bid/ask reais).

- Sinal na M5 fechada (barras de BID montadas dos ticks); entrada no 1º tick da barra seguinte (ask compra / bid venda).
- SL inicial, TP (sweep48), stop móvel por tick (vale a partir do tick seguinte ao que o move), tempo máximo.
- Lote 0.01 => US$0.01 por US$1. Corte IS/OOS em 2026-06-01.

  python -m backtest.agentes_v2.btc_tick
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from agents.capitulation_rules import rsi_state, rsi_with_partial
from agents.sweep48 import add_indicators, signal_at
from backtest import ticks as T
from engine import indicators as ind

CUT = pd.Timestamp("2026-06-01", tz="UTC")
VPU = 0.01


def server_epoch(t: pd.Series) -> np.ndarray:
    ny = t.dt.tz_convert("America/New_York").dt.tz_localize(None) + pd.Timedelta(hours=7)
    return ((ny - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy()


def exit_scan(tk, i_in, side, entry, sl, tp, a, trigger, dist, max_ms):
    """Primeiro tick que fecha a posição. Retorna (índice, preço, motivo)."""
    t, bid, ask = tk["t"], tk["bid"], tk["ask"]
    end = int(np.searchsorted(t, t[i_in] + max_ms))
    i, chunk = i_in + 1, 20000
    cur_sl = sl
    while i < end:
        j = min(end, i + chunk)
        px = bid[i:j] if side == 1 else ask[i:j]          # preço de saída
        fav = (bid[i:j] - entry) if side == 1 else (entry - ask[i:j])
        if trigger > 0:
            act = fav >= trigger * a
            cand = np.where(act, (bid[i:j] - dist * a) if side == 1 else (ask[i:j] + dist * a),
                            -np.inf if side == 1 else np.inf)
            run = np.maximum.accumulate(np.r_[cur_sl, cand]) if side == 1 else np.minimum.accumulate(np.r_[cur_sl, cand])
            eff = run[:-1]                                  # stop movido no tick k vale a partir de k+1
        else:
            eff = np.full(j - i, cur_sl)
        hit_sl = (px <= eff) if side == 1 else (px >= eff)
        hit_tp = ((bid[i:j] >= tp) if side == 1 else (ask[i:j] <= tp)) if tp else np.zeros(j - i, bool)
        hits = np.flatnonzero(hit_sl | hit_tp)
        if len(hits):
            k = int(hits[0])
            if hit_sl[k]:
                why = "TRAIL" if (eff[k] - entry) * side > 0 else "SL"
                return i + k, float(px[k]), why
            return i + k, float(px[k]), "TP"
        if trigger > 0:
            cur_sl = float(run[-1])
        i = j
    k = min(end, len(t) - 1)
    return k, float(bid[k] if side == 1 else ask[k]), "TEMPO"


def stats(tr: pd.DataFrame) -> str:
    if tr.empty:
        return "n=   0"
    u = tr.usd
    eq = u.cumsum()
    pf = u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9)
    return (f"n={len(u):4d} win={100 * (u > 0).mean():5.1f}% PF={pf:5.2f} net=${u.sum():+7.2f} "
            f"maxDD=${(eq.cummax().clip(lower=0) - eq).max():6.2f} sp/A={tr.sp_atr.median():.2f}")


def split(tr):
    return tr[tr.t_out < CUT], tr[tr.t_out >= CUT]


# ------------------------------------------------------------------ SWEEP48
def sweep48(tk, b5, sl_atr=3.0, tp_atr=5.0, trigger=0.75, dist=0.15, max_min=240, max_sp_atr=9.9, hours=(15, 20)):
    d = add_indicators(b5[["open", "high", "low", "close"]].assign(time=server_epoch(b5.time)))
    out, busy_until = [], -1
    for row in d.itertuples(index=True):
        j = row.Index
        if j + 1 >= len(b5) or int(b5.i0.iat[j + 1]) <= busy_until:
            continue
        side = signal_at(row, *hours)
        if side == 0:
            continue
        a = float(row.atr)
        i_in = int(b5.i0.iat[j + 1])
        sp = tk["ask"][i_in] - tk["bid"][i_in]
        if sp > max_sp_atr * a:
            continue
        entry = tk["ask"][i_in] if side == 1 else tk["bid"][i_in]
        sl, tp = entry - side * sl_atr * a, (entry + side * tp_atr * a) if tp_atr else 0.0
        k, px, why = exit_scan(tk, i_in, side, entry, sl, tp, a, trigger, dist, max_min * 60_000)
        busy_until = k
        out.append({"t_in": b5.time.iat[j + 1], "t_out": pd.Timestamp(tk["t"][k], unit="ms", tz="UTC"), "side": side,
                    "usd": (px - entry) * side * VPU, "why": why, "sp_atr": sp / a})
    return pd.DataFrame(out)


# ------------------------------------------------------------------ RSI20 (só compra)
def rsi_buy(tk, b5, trigger_rsi=20.0, add_rsi=30.0, sl_atr=2.0, trigger=0.5, dist=0.25, max_min=240, trend=False):
    """RSI(14) M15 com a barra em formação, avaliado a cada M5 fechada; 1 compra por episódio (lock_after_entry)."""
    m15 = b5.set_index("time").resample("15min", label="left", closed="left").agg(
        {"close": "last"}).dropna().reset_index()
    g, l = rsi_state(m15.close)
    atr = ind.atr(b5, 14).to_numpy()
    ema = b5.close.ewm(span=200 * 12, adjust=False).mean().to_numpy()    # ~EMA200 H1 em M5
    m15_start = m15.time.astype("int64").to_numpy()
    b5_close_ns = (b5.time + pd.Timedelta(minutes=5)).astype("int64").to_numpy()
    out, busy_until, armed_lock = [], -1, False
    for j in range(300, len(b5) - 1):
        k = int(np.searchsorted(m15_start, b5_close_ns[j], side="right")) - 1   # M15 em formação
        if k < 1:
            continue
        r = rsi_with_partial(g[k - 1], l[k - 1], float(m15.close.iat[k - 1]), float(b5.close.iat[j]))
        if np.isnan(r):
            continue
        if r >= add_rsi:
            armed_lock = False
            continue
        if armed_lock or r > trigger_rsi:
            continue
        i_in = int(b5.i0.iat[j + 1])
        if i_in <= busy_until:
            continue
        if trend and b5.close.iat[j] < ema[j]:
            continue
        a = atr[j]
        entry = tk["ask"][i_in]
        sp = tk["ask"][i_in] - tk["bid"][i_in]
        kx, px, why = exit_scan(tk, i_in, 1, entry, entry - sl_atr * a, 0.0, a, trigger, dist, max_min * 60_000)
        busy_until, armed_lock = kx, True
        out.append({"t_in": b5.time.iat[j + 1], "t_out": pd.Timestamp(tk["t"][kx], unit="ms", tz="UTC"), "side": 1,
                    "usd": (px - entry) * VPU, "why": why, "sp_atr": sp / a})
    return pd.DataFrame(out)


def main_rsi() -> None:
    tk = T.load("BTCUSD")
    b5 = T.bars(tk, 5)
    print("== RSI20 (ao vivo: rsi<=20, rearma >=30, sl 2, gatilho 0.5, dist 0.25)")
    for rsi, sl, trig, dist, trend in itertools.product((20, 15), (2.0, 3.0), (0.5, 1.0), (0.25, 0.75), (False, True)):
        tr = rsi_buy(tk, b5, rsi, 30, sl, trig, dist, trend=trend)
        a, b = split(tr)
        print(f"rsi<={rsi} sl={sl} trig={trig} dist={dist} trend={trend} | IS {stats(a)} | OOS {stats(b)}", flush=True)


def main() -> None:
    tk = T.load("BTCUSD")
    b5 = T.bars(tk, 5)
    print(f"BTCUSD ticks {b5.time.iloc[0]:%Y-%m-%d} -> {b5.time.iloc[-1]:%Y-%m-%d} | spread mediano "
          f"{np.median(tk['ask'] - tk['bid']):.1f}")
    print("\n== SWEEP48 (ao vivo: sl 3, tp 5, gatilho 0.75, dist 0.15, 15-20h servidor)")
    for sl, tp, trig, dist in itertools.product((3.0,), (5.0, 0.0), (0.75, 1.0, 1.5), (0.15, 0.5, 1.0)):
        tr = sweep48(tk, b5, sl, tp, trig, dist)
        a, b = split(tr)
        print(f"sl={sl} tp={tp} trig={trig} dist={dist} | IS {stats(a)} | OOS {stats(b)}", flush=True)
    print("\n== RSI20 (ao vivo: rsi<=20, rearma >=30, sl 2, gatilho 0.5, dist 0.25)")
    for rsi, sl, trig, dist, trend in itertools.product((20, 15), (2.0, 3.0), (0.5, 1.0), (0.25, 0.75), (False, True)):
        tr = rsi_buy(tk, b5, rsi, 30, sl, trig, dist, trend=trend)
        a, b = split(tr)
        print(f"rsi<={rsi} sl={sl} trig={trig} dist={dist} trend={trend} | IS {stats(a)} | OOS {stats(b)}", flush=True)


if __name__ == "__main__":
    import sys
    main_rsi() if "--rsi" in sys.argv else main()
