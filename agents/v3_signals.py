"""Sinais e regras de saída dos agentes v3 (competição 11/2026). MESMO código no backtest
(backtest/agentes_v3) e ao vivo (agents/v3_agent.py). Só numpy/pandas, sem numba.

Convenções
- `df`: barras de BID fechadas, colunas time (UTC, abertura da barra), open, high, low, close.
- Sinal avaliado no FECHAMENTO da barra i: +1 compra, -1 venda, 0 nada. Entrada na abertura da barra i+1.
- Todos os níveis "N barras" usam só barras anteriores (shift(1)); nada olha para frente.

Famílias (derivadas dos agentes que deram lucro na demo):
  ST     SuperTrend(p, m) vira de lado, filtro opcional EMA200                       (btcflip)
  CHAN   SAR chandelier por fechamento (k x ATR) vira de lado, filtro de tendência   (goldflip / goldnight)
  SWEEP  varre a mínima/máxima de N barras e fecha de volta, filtro MA100/MA300      (sweep48)
  RSIX   RSI(14) entra na zona extrema (<= x compra / >= 100-x venda)                (rsi20 / capitulation)
  RSIPB  RSI(n) cruza de volta o nível L a favor da tendência (close vs MA200)       (A2 pullback)
  DON    rompimento de Donchian N                                                    (referência)
  EMAX   cruzamento de médias exponenciais                                           (referência)
  BB     fecha de volta para dentro da Bollinger(20, k)                              (referência)
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from engine import indicators as ind

# ----------------------------------------------------------------- sessões (filtro só da ENTRADA)
SESSIONS = {
    "all": None,
    "day": [("Europe/London", 7 * 60, 16 * 60 + 30), ("America/New_York", 8 * 60, 17 * 60)],
    "ny": [("America/New_York", 9 * 60 + 30, 16 * 60)],
    "us": [("America/New_York", 8 * 60, 17 * 60)],
}


def session_mask(time_open: pd.Series, name: str, bar_minutes: int) -> np.ndarray:
    """True se o FECHAMENTO da barra (momento da decisão) cai dentro da sessão. night = fora de day, seg-sex NY."""
    t = pd.to_datetime(time_open, utc=True) + pd.Timedelta(minutes=bar_minutes)
    if name == "all":
        return np.ones(len(t), dtype=bool)
    if name == "night":
        day = session_mask(time_open, "day", bar_minutes)
        return ~day & (t.dt.tz_convert("America/New_York").dt.weekday.to_numpy() < 5)
    ok = np.zeros(len(t), dtype=bool)
    for tz, a, b in SESSIONS[name]:
        loc = t.dt.tz_convert(tz)
        hm = (loc.dt.hour * 60 + loc.dt.minute).to_numpy()
        ok |= (loc.dt.weekday.to_numpy() < 5) & (hm >= a) & (hm < b)
    return ok


# ----------------------------------------------------------------- indicadores (uma vez por série)
def indicators(df: pd.DataFrame) -> Dict[str, Any]:
    c = df["close"]
    x: Dict[str, Any] = {"o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float),
                         "l": df["low"].to_numpy(float), "c": c.to_numpy(float), "_cache": {}}
    x["atr"] = ind.atr(df, 14).to_numpy(float)
    for n in (100, 200, 300):
        x[f"ma{n}"] = c.rolling(n).mean().to_numpy(float)
    for n in (9, 20, 21, 50, 200):
        x[f"ema{n}"] = c.ewm(span=n, adjust=False).mean().to_numpy(float)
    for n in (2, 7, 14):
        x[f"rsi{n}"] = ind.rsi(c, n).to_numpy(float)
    return x


def _cross_up(a: np.ndarray, lvl) -> np.ndarray:
    prev = np.r_[np.nan, a[:-1]]
    lv_prev = np.r_[np.nan, lvl[:-1]] if isinstance(lvl, np.ndarray) else lvl
    return (a > lvl) & (prev <= lv_prev)


def _cross_dn(a: np.ndarray, lvl) -> np.ndarray:
    prev = np.r_[np.nan, a[:-1]]
    lv_prev = np.r_[np.nan, lvl[:-1]] if isinstance(lvl, np.ndarray) else lvl
    return (a < lvl) & (prev >= lv_prev)


def supertrend_dir(h, l, c, period: int, mult: float) -> np.ndarray:
    """Direção da SuperTrend (+1/-1) com ATR de Wilder (mesma recursão do EA BTCTrendFlip)."""
    n = len(c)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
    a = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb, d = ub.copy(), lb.copy(), np.ones(n, dtype=np.int64)
    for i in range(1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        d[i] = 1 if c[i] > fub[i - 1] else (-1 if c[i] < flb[i - 1] else d[i - 1])
    d[:period] = 0
    return d


def chandelier_dir(c, a, k: float) -> np.ndarray:
    """SAR por fechamento: comprado -> stop = max(stop, maior fechamento desde a virada - k*ATR); fecha abaixo vira."""
    n = len(c)
    d = np.zeros(n, dtype=np.int64)
    side, ext, stop = 0, 0.0, 0.0
    for i in range(1, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if side == 0:
            side, ext = (1 if c[i] >= c[max(0, i - 20)] else -1), c[i]
            stop = ext - side * k * a[i]
        elif side == 1:
            if c[i] < stop:
                side, ext, stop = -1, c[i], c[i] + k * a[i]
            else:
                ext = max(ext, c[i])
                stop = max(stop, ext - k * a[i])
        else:
            if c[i] > stop:
                side, ext, stop = 1, c[i], c[i] - k * a[i]
            else:
                ext = min(ext, c[i])
                stop = min(stop, ext + k * a[i])
        d[i] = side
    return d


def _flip(d: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    prev = np.r_[0, d[:-1]]
    return (d == 1) & (prev == -1), (d == -1) & (prev == 1)


def _trend_ok(x: Dict[str, Any], filt: str) -> Tuple[np.ndarray, np.ndarray]:
    c = x["c"]
    if filt == "none":
        t = np.ones(len(c), dtype=bool)
        return t, t
    if filt == "ema200":
        return c > x["ema200"], c < x["ema200"]
    if filt == "ma200":
        return c > x["ma200"], c < x["ma200"]
    if filt == "ma100_300":
        return (c > x["ma100"]) & (c > x["ma300"]), (c < x["ma100"]) & (c < x["ma300"])
    if filt == "slope":       # supervisor do goldflip: |close - MA100| >= 1 ATR e inclinação >= 0.3 ATR em 10 barras
        a, m = x["atr"], x["ma100"]
        dist = (c - m) / a
        slope = (m - np.r_[np.full(10, np.nan), m[:-10]]) / a
        return (dist >= 1.0) & (slope >= 0.3), (dist <= -1.0) & (slope <= -0.3)
    raise ValueError(filt)


def signal(x: Dict[str, Any], spec: Dict[str, Any]) -> np.ndarray:
    """Vetor de sinais (+1/-1/0) para a especificação `spec` (sem filtro de sessão)."""
    fam = spec["family"]
    c, h, l, a = x["c"], x["h"], x["l"], x["atr"]
    up, dn = _trend_ok(x, spec.get("filter", "none"))
    cache = x["_cache"]
    if fam == "ST":
        key = ("ST", spec["p"], spec["m"])
        if key not in cache:
            cache[key] = supertrend_dir(h, l, c, int(spec["p"]), float(spec["m"]))
        L, S = _flip(cache[key])
    elif fam == "CHAN":
        key = ("CHAN", spec["k"])
        if key not in cache:
            cache[key] = chandelier_dir(c, a, float(spec["k"]))
        L, S = _flip(cache[key])
    elif fam == "SWEEP":
        n = int(spec["n"])
        mn = pd.Series(l).rolling(n).min().shift(1).to_numpy()
        mx = pd.Series(h).rolling(n).max().shift(1).to_numpy()
        L, S = (l < mn) & (c > mn), (h > mx) & (c < mx)
    elif fam == "RSIX":
        r, z = x["rsi14"], float(spec["x"])
        prev = np.r_[np.nan, r[:-1]]
        L, S = (r <= z) & (prev > z), (r >= 100 - z) & (prev < 100 - z)
    elif fam == "RSIPB":
        r, lv = x[f"rsi{int(spec['n'])}"], float(spec["lvl"])
        L, S = _cross_up(r, lv), _cross_dn(r, 100 - lv)
    elif fam == "DON":
        n = int(spec["n"])
        mx = pd.Series(h).rolling(n).max().shift(1).to_numpy()
        mn = pd.Series(l).rolling(n).min().shift(1).to_numpy()
        L, S = _cross_up(c, mx), _cross_dn(c, mn)
    elif fam == "EMAX":
        f, s = x[f"ema{int(spec['f'])}"], x[f"ema{int(spec['s'])}"]
        L, S = _cross_up(f, s), _cross_dn(f, s)
    elif fam == "BB":
        key = ("BB", spec["k"])
        if key not in cache:
            m = pd.Series(c).rolling(20).mean().to_numpy()
            sd = pd.Series(c).rolling(20).std(ddof=0).to_numpy()
            cache[key] = (m - float(spec["k"]) * sd, m + float(spec["k"]) * sd)
        lo, hi = cache[key]
        L, S = _cross_up(c, lo), _cross_dn(c, hi)
    else:
        raise ValueError(fam)
    L = np.nan_to_num(L, nan=0).astype(bool) & up
    S = np.nan_to_num(S, nan=0).astype(bool) & dn
    side = spec.get("side", "both")
    if side == "long":
        S = np.zeros_like(S)
    elif side == "short":
        L = np.zeros_like(L)
    out = np.zeros(len(c), dtype=np.int64)
    out[L] = 1
    out[S & ~L] = -1
    out[:300] = 0                       # aquecimento dos indicadores (MA300)
    return out


def entry_signal_now(df: pd.DataFrame, spec: Dict[str, Any], bar_minutes: int) -> Tuple[int, float]:
    """Ao vivo: sinal da ÚLTIMA barra fechada de `df` (com filtro de sessão) e o ATR dela."""
    x = indicators(df)
    s = signal(x, spec)
    ok = session_mask(df["time"], spec.get("session", "all"), bar_minutes)
    return (int(s[-1]) if ok[-1] else 0), float(x["atr"][-1])


# ----------------------------------------------------------------- saídas (mesma regra no backtest)
def initial_levels(side: int, entry: float, a0: float, ex: Dict[str, float]) -> Tuple[float, float]:
    sl = entry - side * float(ex["sl"]) * a0
    tp = entry + side * float(ex["tp"]) * a0 if float(ex.get("tp", 0)) > 0 else 0.0
    return sl, tp


def trail_after_close(side: int, entry: float, sl: float, best: float, a0: float, ex: Dict[str, float]) -> float:
    """Stop depois do fechamento de uma barra: `best` = melhor preço (bid máx p/ compra, ask mín p/ venda) desde a
    entrada. Ativa quando o ganho >= act x ATR(sinal); stop = best -/+ trail x ATR(sinal); só a favor."""
    tr = float(ex.get("trail", 0))
    if tr <= 0:
        return sl
    if (best - entry) * side < float(ex.get("act", 0)) * a0:
        return sl
    new = best - side * tr * a0
    return max(sl, new) if side == 1 else min(sl, new)
