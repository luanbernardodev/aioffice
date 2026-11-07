"""Pesquisa de estratégias para conta pequena — parâmetros PRÉ-DEFINIDOS (sem otimização).

Validação: IS = até 2024-12-31, OOS = 2025-01-01 em diante. Custos: spread da barra x1.5,
entrada a mercado na abertura da barra seguinte, SL antes de TP na mesma barra, swap por rollover.

  python -m backtest.research
"""
from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from backtest import data as bdata
from engine import indicators as ind

SPREAD_MULT = 1.5
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
LOTS = {"US500Cash": 0.1, "BTCUSD": 0.01, "GOLD": 0.01}


@dataclass
class T:
    sym: str
    strat: str
    side: int
    entry_t: pd.Timestamp
    entry: float
    sl0: float
    exit: float
    exit_t: pd.Timestamp
    reason: str
    swap_usd: float = 0.0

    @property
    def r(self) -> float:
        return (self.exit - self.entry) * self.side / abs(self.entry - self.sl0)


def load_tf(sym: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(bdata.DATA_DIR / f"{sym}_{tf}.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["spread"] = df["spread"] * SPREAD_MULT
    return df


def specs() -> Dict[str, dict]:
    return json.loads((bdata.DATA_DIR / "specs.json").read_text())


# =============================================================== 1) ORB
def orb(sym: str, df: pd.DataFrame, tz: str, open_hm: str, range_min: int, last_entry_hm: str,
        exit_hm: str, tp_r: float | None, trend: bool, h1: pd.DataFrame) -> List[T]:
    """Range = primeiros `range_min` min após a abertura local; entrada no 1º fechamento M15 fora do range
    (próxima abertura); SL no lado oposto do range; saída no TP (se houver) ou no horário de saída."""
    d = df.copy()
    loc = d["time"].dt.tz_convert(tz)
    d["date"] = loc.dt.date
    d["hm"] = loc.dt.hour * 60 + loc.dt.minute
    oh, om = map(int, open_hm.split(":"))
    o = oh * 60 + om
    le = sum(int(x) * m for x, m in zip(last_entry_hm.split(":"), (60, 1)))
    ex = sum(int(x) * m for x, m in zip(exit_hm.split(":"), (60, 1)))
    if trend:
        hh = h1.copy()
        hh["sma"] = ind.sma(hh["close"], 100)
        hh["ct"] = hh["time"] + pd.Timedelta("1h")
        d["ct"] = d["time"] + pd.Timedelta("15min")
        d = pd.merge_asof(d.sort_values("ct"), hh[["ct", "sma", "close"]].rename(columns={"close": "h1c"}),
                          on="ct", direction="backward")
    out: List[T] = []
    for date, g in d.groupby("date", sort=True):
        g = g.reset_index(drop=True)
        if g["time"].iloc[0].tz_convert(tz).weekday() >= 5:
            continue
        rng = g[(g["hm"] >= o) & (g["hm"] < o + range_min)]
        if len(rng) != range_min // 15:
            continue
        hi, lo = rng["high"].max(), rng["low"].min()
        after = g[g["hm"] >= o + range_min].reset_index(drop=True)
        k_entry = None
        for k in range(len(after) - 1):
            if after["hm"].iat[k] + 15 > le:
                break
            c = after["close"].iat[k]
            side = 1 if c > hi else (-1 if c < lo else 0)
            if side == 0:
                continue
            if trend and not (np.sign(after["h1c"].iat[k] - after["sma"].iat[k]) == side):
                break  # 1º rompimento contra a tendência: dia descartado
            k_entry = k + 1
            break
        if k_entry is None:
            continue
        b = after.iloc[k_entry]
        sp = b["spread"]
        entry = b["open"] + (sp if side == 1 else 0)
        sl = lo if side == 1 else hi
        risk = (entry - sl) * side
        if risk <= 0:
            continue
        tp = entry + side * tp_r * risk if tp_r else None
        res = None
        for k in range(k_entry, len(after)):
            r = after.iloc[k]
            sp = r["spread"]
            if side == 1:
                if r["low"] <= sl:
                    res = (sl, r["time"], "SL"); break
                if tp and r["high"] >= tp:
                    res = (tp, r["time"], "TP"); break
            else:
                if r["high"] + sp >= sl:
                    res = (sl, r["time"], "SL"); break
                if tp and r["low"] + sp <= tp:
                    res = (tp, r["time"], "TP"); break
            if r["hm"] + 15 >= ex:
                px = r["close"] + (sp if side == -1 else 0)
                res = (px, r["time"], "EOD"); break
        if res is None:
            r = after.iloc[-1]
            res = (r["close"] + (r["spread"] if side == -1 else 0), r["time"], "EOD")
        out.append(T(sym, "", side, b["time"], entry, sl, res[0], res[1], res[2]))
    return out


# =============================================================== 2) Donchian M15 (BTC)
def donchian(sym: str, df: pd.DataFrame, n_entry: int, n_exit: int, sl_atr: float, trail_atr: float,
             long_only: bool, swap_long_usd: float, swap_short_usd: float) -> List[T]:
    d = df.reset_index(drop=True)
    hi, lo, cl, op, sp = (d[c].to_numpy() for c in ("high", "low", "close", "open", "spread"))
    a = ind.atr(d).to_numpy()
    sma = ind.sma(d["close"], 200).to_numpy()
    up = pd.Series(hi).rolling(n_entry).max().shift(1).to_numpy()
    dn = pd.Series(lo).rolling(n_entry).min().shift(1).to_numpy()
    xup = pd.Series(hi).rolling(n_exit).max().shift(1).to_numpy()
    xdn = pd.Series(lo).rolling(n_exit).min().shift(1).to_numpy()
    roll = (d["time"].dt.tz_convert("America/New_York").dt.hour == 17) & \
           (d["time"].dt.tz_convert("America/New_York").dt.minute == 0)   # rollover servidor 00:00 = 17:00 NY
    roll = roll.to_numpy()
    out: List[T] = []
    pos = None
    for i in range(210, len(d) - 1):
        if pos is not None:
            side, entry, sl, sl0, t0, swaps = pos
            if roll[i]:
                swaps += swap_long_usd if side == 1 else swap_short_usd
            ask_h, ask_l = hi[i] + sp[i], lo[i] + sp[i]
            if (side == 1 and lo[i] <= sl) or (side == -1 and ask_h >= sl):
                out.append(T(sym, "", side, t0, entry, sl0, sl, d["time"].iat[i], "SL/TRAIL", swaps))
                pos = None
            else:
                exit_ch = (side == 1 and cl[i] < xdn[i]) or (side == -1 and cl[i] > xup[i])
                if exit_ch:
                    px = op[i + 1] + (sp[i + 1] if side == -1 else 0)
                    out.append(T(sym, "", side, t0, entry, sl0, px, d["time"].iat[i + 1], "CHANNEL", swaps))
                    pos = None
                else:
                    new = cl[i] - trail_atr * a[i] if side == 1 else cl[i] + sp[i] + trail_atr * a[i]
                    sl = max(sl, new) if side == 1 else min(sl, new)
                    pos = (side, entry, sl, sl0, t0, swaps)
            if pos is not None:
                continue
        if np.isnan(up[i]) or np.isnan(sma[i]) or np.isnan(a[i]):
            continue
        side = 1 if (cl[i] > up[i] and cl[i] > sma[i]) else (-1 if (cl[i] < dn[i] and cl[i] < sma[i]) else 0)
        if side == 0 or (long_only and side == -1):
            continue
        entry = op[i + 1] + (sp[i + 1] if side == 1 else 0)
        sl = entry - side * sl_atr * a[i]
        pos = (side, entry, sl, sl, d["time"].iat[i + 1], 0.0)
    return out


# =============================================================== relatório
def summarize(trades: List[T], vpu: float, lot: float) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame([{"t": t.exit_t, "r": t.r, "usd": (t.exit - t.entry) * t.side * vpu * lot - t.swap_usd,
                        "risk_usd": abs(t.entry - t.sl0) * vpu * lot} for t in trades])
    res = {}
    for part, g in (("IS", df[df.t < OOS_START]), ("OOS", df[df.t >= OOS_START])):
        if len(g) == 0:
            res[part] = None
            continue
        eq = g["usd"].cumsum()
        dd = (eq.cummax().clip(lower=0) - eq).max()
        w = g[g.r > 0]
        res[part] = {"n": len(g), "win": round(len(w) / len(g) * 100, 1), "expR": round(g.r.mean(), 3),
                     "PF_usd": round(g.usd[g.usd > 0].sum() / max(-g.usd[g.usd < 0].sum(), 1e-9), 2),
                     "net_usd": round(g.usd.sum(), 1), "maxDD_usd": round(dd, 1),
                     "med_risk_usd": round(g.risk_usd.median(), 2),
                     "per_year_R": {int(y): round(v, 1) for y, v in g.groupby(g.t.dt.year).r.sum().items()}}
    return res


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    sp = specs()
    rows = []
    h1 = {s: load_tf(s, "H1") for s in LOTS}
    m15 = {s: load_tf(s, "M15") for s in LOTS}

    # ORB: grade pré-definida 2x2x2 (range 15/30, saída EOD vs 2R, com/sem tendência)
    orb_defs = {"US500Cash": ("America/New_York", "09:30", "12:00", "15:45"),
                "GOLD": ("Europe/London", "08:00", "11:00", "16:00")}
    for s, (tz, op_, le, ex) in orb_defs.items():
        for rmin, tp, tr in itertools.product((15, 30), (None, 2.0), (False, True)):
            name = f"ORB {rmin}m {'TP2R' if tp else 'EOD'} {'trend' if tr else 'no-trend'}"
            tt = orb(s, m15[s], tz, op_, rmin, le, ex, tp, tr, h1[s])
            rows.append((s, name, summarize(tt, sp[s]["value_per_unit"], LOTS[s])))

    # BTC Donchian M15: grade pré-definida
    vpu = sp["BTCUSD"]["value_per_unit"]
    sw_l, sw_s = 3220 * 0.01 * vpu * LOTS["BTCUSD"], 2147 * 0.01 * vpu * LOTS["BTCUSD"]
    for n_e, lo_only in itertools.product((20, 55), (False, True)):
        name = f"Donchian M15 {n_e}/{n_e // 2} SL2ATR trail3ATR {'long-only' if lo_only else 'long+short'}"
        tt = donchian("BTCUSD", m15["BTCUSD"], n_e, n_e // 2, 2.0, 3.0, lo_only, sw_l, sw_s)
        rows.append(("BTCUSD", name, summarize(tt, vpu, LOTS["BTCUSD"])))

    for s, name, r in rows:
        def f(p):
            x = r.get(p) if r else None
            return "-" if not x else (f"n={x['n']:4d} win={x['win']:5.1f}% expR={x['expR']:+.3f} PF$={x['PF_usd']:.2f} "
                                      f"net=${x['net_usd']:+8.1f} DD=${x['maxDD_usd']:6.1f} risco~${x['med_risk_usd']}")
        print(f"{s:9s} | {name:48s}\n    IS : {f('IS')}\n    OOS: {f('OOS')}")
        if r and r.get("OOS"):
            print(f"    R por ano: {({**(r['IS'] or {}).get('per_year_R', {}), **r['OOS']['per_year_R']})}")


if __name__ == "__main__":
    main()
