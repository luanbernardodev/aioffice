"""Pesquisa de estratégias de tendência para BTCUSD (H1/H4) — variantes PRÉ-DEFINIDAS.

IS = 2017-01-01 .. 2023-12-31 | OOS = 2024-01-01 em diante.
Custos: spread da barra x1.5, entrada na abertura seguinte, stop intrabar no preço do stop (ou pior em gap),
swap por rollover (17:00 NY) PROPORCIONAL ao valor da posição, calibrado no swap atual da XM
(US$0.322 comprado / US$0.215 vendido por noite com 0.01 lote a ~US$76k => ~0.0424%/0.0283% ao dia).
Lote 0.01 => US$0.01 por US$1 de movimento.

Regra de seleção (definida antes de rodar): a melhor variante por PF no IS (>= 40 trades) é a candidata;
ela só é aprovada se o OOS também tiver PF >= 1.2 e expectativa positiva.

  python -m backtest.btc_research
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from backtest.research import load_tf
from engine import indicators as ind

IS_START = pd.Timestamp("2017-01-01", tz="UTC")
OOS_START = pd.Timestamp("2024-01-01", tz="UTC")
VPU = 1.0 * 0.01                    # BTCUSD: US$1 por 1.0 de preço por lote -> 0.01 lote
SWAP_LONG_PCT, SWAP_SHORT_PCT = 0.322 / 760.0, 0.215 / 760.0   # fração do valor nocional por noite


# ----------------------------------------------------------------- dados
def to_h4(h1: pd.DataFrame) -> pd.DataFrame:
    g = h1.set_index("time").resample("4h", label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "spread": g["spread"].max()}).dropna().reset_index()
    return out


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df["high"].diff(), -df["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = ind.atr(df, n)
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def supertrend_dir(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> np.ndarray:
    a = ind.atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    c = df["close"].to_numpy()
    ub, lb = hl2 + mult * a, hl2 - mult * a
    d = np.zeros(len(df), dtype=int)
    fub, flb = ub.copy(), lb.copy()
    for i in range(1, len(df)):
        if np.isnan(a[i]):
            continue
        if np.isnan(fub[i - 1]):
            fub[i], flb[i], d[i] = ub[i], lb[i], 1
            continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        prev = d[i - 1] if d[i - 1] != 0 else 1
        d[i] = 1 if c[i] > fub[i - 1] else (-1 if c[i] < flb[i - 1] else prev)
    return d


# ----------------------------------------------------------------- sinais (no fechamento da barra i)
def signals(df: pd.DataFrame, family: str, long_only: bool) -> Tuple[np.ndarray, np.ndarray]:
    c = df["close"]
    e200 = ema(c, 200)
    up, dn = (c > e200).to_numpy(), (c < e200).to_numpy()
    if family == "SUPERTREND":
        d = supertrend_dir(df)
        flip_up = (d == 1) & (np.r_[0, d[:-1]] == -1)
        flip_dn = (d == -1) & (np.r_[0, d[:-1]] == 1)
        L, S = flip_up & up, flip_dn & dn
    elif family == "EMA_PULLBACK":
        e20, e50 = ema(c, 20), ema(c, 50)
        a = adx(df).to_numpy()
        r = ind.rsi(c, 14)
        trend_up = ((e50 > e200) & (c > e200)).to_numpy() & (a > 20)
        trend_dn = ((e50 < e200) & (c < e200)).to_numpy() & (a > 20)
        touched_up = (df["low"] <= e20).rolling(3).max().fillna(0).astype(bool).to_numpy()
        touched_dn = (df["high"] >= e20).rolling(3).max().fillna(0).astype(bool).to_numpy()
        rsi_up = ((r > 50) & (r.shift(1) <= 50)).to_numpy()
        rsi_dn = ((r < 50) & (r.shift(1) >= 50)).to_numpy()
        L = trend_up & touched_up & rsi_up & (c > e20).to_numpy()
        S = trend_dn & touched_dn & rsi_dn & (c < e20).to_numpy()
    elif family.startswith("DONCHIAN"):
        n = int(family.split("_")[1])
        hh = df["high"].rolling(n).max().shift(1).to_numpy()
        ll = df["low"].rolling(n).min().shift(1).to_numpy()
        L = (c.to_numpy() > hh) & up
        S = (c.to_numpy() < ll) & dn
    elif family == "MACD_RSI":
        macd = ema(c, 12) - ema(c, 26)
        hist = (macd - ema(macd, 9)).to_numpy()
        r = ind.rsi(c, 14).to_numpy()
        prev_h = np.r_[0, hist[:-1]]
        L = (hist > 0) & (prev_h <= 0) & (r > 55) & up
        S = (hist < 0) & (prev_h >= 0) & (r < 45) & dn
    else:
        raise ValueError(family)
    if long_only:
        S = np.zeros_like(S)
    return L.astype(bool), S.astype(bool)


# ----------------------------------------------------------------- simulação
def simulate(df: pd.DataFrame, L: np.ndarray, S: np.ndarray, init_atr: float = 2.0, trail_atr: float = 3.0) -> pd.DataFrame:
    o, h, l, c, sp = (df[x].to_numpy() for x in ("open", "high", "low", "close", "spread"))
    a = ind.atr(df).to_numpy()
    t = df["time"]
    ny = t.dt.tz_convert("America/New_York")
    hrs = (ny.dt.hour + ny.dt.minute / 60).to_numpy()
    bar_h = (t.iloc[1] - t.iloc[0]).total_seconds() / 3600
    # rollover (17:00 NY) dentro da barra [abertura, abertura+bar_h)
    roll = ((hrs <= 17) & (hrs + bar_h > 17)) | ((hrs > 17) & (hrs + bar_h > 41))
    tt = t.to_numpy()
    trades: List[dict] = []
    pos, entry, stop, ext, t_in, swaps, risk = 0, 0.0, 0.0, 0.0, None, 0.0, 0.0
    pending = 0
    for j in range(201, len(df)):
        # entrada pendente da barra anterior
        if pos == 0 and pending != 0:
            pos = pending
            entry = o[j] + (sp[j] if pos == 1 else 0.0)
            stop = entry - pos * init_atr * a[j - 1]
            ext = entry
            risk = abs(entry - stop)
            t_in, swaps = tt[j], 0.0
        pending = 0
        if pos != 0:
            if roll[j]:
                swaps += c[j] * VPU * (SWAP_LONG_PCT if pos == 1 else SWAP_SHORT_PCT)
            hit = (l[j] <= stop) if pos == 1 else (h[j] + sp[j] >= stop)
            if hit:
                px = min(stop, o[j]) if pos == 1 else max(stop, o[j] + sp[j])
                usd = (px - entry) * pos * VPU - swaps
                trades.append({"t_in": t_in, "t_out": tt[j], "side": pos, "usd": usd,
                               "r": ((px - entry) * pos) / risk, "risk_usd": risk * VPU})
                pos = 0
            else:
                if pos == 1:
                    ext = max(ext, h[j])
                    stop = max(stop, ext - trail_atr * a[j])
                else:
                    ext = min(ext, l[j])
                    stop = min(stop, ext + trail_atr * a[j])
                # sinal contrário fecha e inverte (só se a direção oposta for permitida)
                opp = S[j] if pos == 1 else L[j]
                if opp:
                    px = c[j] if pos == 1 else c[j] + sp[j]
                    usd = (px - entry) * pos * VPU - swaps
                    trades.append({"t_in": t_in, "t_out": tt[j], "side": pos, "usd": usd,
                                   "r": ((px - entry) * pos) / risk, "risk_usd": risk * VPU})
                    pos = 0
                    pending = -1 if S[j] else 1
                continue
        if pos == 0:
            pending = 1 if L[j] else (-1 if S[j] else 0)
    out = pd.DataFrame(trades)
    if len(out):
        out["t_out"] = pd.to_datetime(out["t_out"], utc=True)
    return out


def stats(tr: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    res = {}
    for part, g in (("IS", tr[(tr.t_out >= IS_START) & (tr.t_out < OOS_START)] if len(tr) else tr),
                    ("OOS", tr[tr.t_out >= OOS_START] if len(tr) else tr)):
        if g is None or len(g) == 0:
            res[part] = {"n": 0}
            continue
        eq = g.usd.cumsum()
        res[part] = {"n": len(g), "win": 100 * (g.usd > 0).mean(), "expR": g.r.mean(),
                     "pf": g.usd[g.usd > 0].sum() / max(-g.usd[g.usd < 0].sum(), 1e-9),
                     "net": g.usd.sum(), "dd": (eq.cummax().clip(lower=0) - eq).max(),
                     "risk": g.risk_usd.median(),
                     "years": {int(y): round(v, 1) for y, v in g.groupby(g.t_out.dt.year).r.sum().items()}}
    return res


def fmt(s: Dict[str, float]) -> str:
    if not s.get("n"):
        return "-"
    return (f"n={s['n']:4d} win={s['win']:5.1f}% expR={s['expR']:+.3f} PF={s['pf']:.2f} net=${s['net']:+8.1f} "
            f"DD=${s['dd']:6.1f} risco~${s['risk']:.1f}")


def main() -> None:
    h1 = load_tf("BTCUSD", "H1")
    frames = {"H1": h1, "H4": to_h4(h1)}
    families = ["SUPERTREND", "EMA_PULLBACK", "DONCHIAN_20", "DONCHIAN_55", "MACD_RSI"]
    rows = []
    for tf, fam, lo in itertools.product(frames, families, (False, True)):
        df = frames[tf]
        L, S = signals(df, fam, lo)
        st = stats(simulate(df, L, S))
        rows.append((tf, fam, lo, st))
        print(f"{tf:3s} {fam:13s} {'long-only ' if lo else 'long+short'}\n   IS : {fmt(st['IS'])}\n   OOS: {fmt(st['OOS'])}")
        if st["OOS"].get("n"):
            print(f"   R por ano: {({**st['IS'].get('years', {}), **st['OOS']['years']})}")
    cands = [r for r in rows if r[3]["IS"].get("n", 0) >= 40]
    best = max(cands, key=lambda r: r[3]["IS"]["pf"])
    tf, fam, lo, st = best
    ok = st["OOS"].get("pf", 0) >= 1.2 and st["OOS"].get("expR", -1) > 0
    print(f"\nCANDIDATA (melhor PF no IS): {tf} {fam} {'long-only' if lo else 'long+short'} -> "
          f"OOS PF={st['OOS'].get('pf', 0):.2f} expR={st['OOS'].get('expR', 0):+.3f} => {'APROVADA' if ok else 'REPROVADA'}")


if __name__ == "__main__":
    main()
