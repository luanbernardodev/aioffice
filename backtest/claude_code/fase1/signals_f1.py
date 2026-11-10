"""Fase 1 — famílias de sinais (todas avaliadas no FECHAMENTO da barra i; entrada no open i+1).

Cada família devolve "grupos": parâmetros categóricos fixos + eixos ordenados (para o teste de vizinhança) e uma
matriz de sinais (produto dos eixos em ordem C, n_barras). Depois cada grupo é cruzado com os filtros extras.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from numba import njit

from engine2 import adx, atr, ema, hh, ll, rsi, sma

WARM = 200


def cross_up(x, lvl):
    return (x > lvl) & (np.roll(x, 1) <= lvl)


def cross_dn(x, lvl):
    return (x < lvl) & (np.roll(x, 1) >= lvl)


def to_sig(L, S):
    s = np.zeros(len(L), np.int64)
    s[L] = 1
    s[S & ~L] = -1
    s[:WARM] = 0
    return s


# ----------------------------------------------------------------------------------- estrutura (pivôs fractais)
@njit(cache=True)
def structure(h, l, c, a, k, mode, retest_bars, retest_atr):
    """mode 0 = BOS a favor da estrutura, 1 = CHoCH (quebra contra a estrutura anterior), 2 = reteste do nível do BOS.

    Pivô de alta em j: h[j] > máximas de j-k..j-1 e >= de j+1..j+k; só é conhecido em j+k (sem lookahead)."""
    n = len(c)
    sig = np.zeros(n, np.int64)
    sh1 = np.nan; sh0 = np.nan; sl1 = np.nan; sl0 = np.nan     # último e penúltimo topo/fundo confirmados
    sh_used = True; sl_used = True
    rl_lvl = np.nan; rl_until = -1; rs_lvl = np.nan; rs_until = -1
    for i in range(2 * k + 1, n):
        j = i - k
        ph = True; pl = True
        for t in range(j - k, j + k + 1):
            if t == j:
                continue
            if t < j:
                if h[t] >= h[j]: ph = False
                if l[t] <= l[j]: pl = False
            else:
                if h[t] > h[j]: ph = False
                if l[t] < l[j]: pl = False
        if ph:
            sh0 = sh1; sh1 = h[j]; sh_used = False
        if pl:
            sl0 = sl1; sl1 = l[j]; sl_used = False
        if np.isnan(sh0) or np.isnan(sl0):
            continue
        bull = sh1 > sh0 and sl1 > sl0
        bear = sh1 < sh0 and sl1 < sl0
        up = (not sh_used) and c[i] > sh1 and c[i - 1] <= sh1
        dn = (not sl_used) and c[i] < sl1 and c[i - 1] >= sl1
        if up:
            sh_used = True
        if dn:
            sl_used = True
        if mode == 0:
            if up and bull: sig[i] = 1
            elif dn and bear: sig[i] = -1
        elif mode == 1:
            if up and bear: sig[i] = 1
            elif dn and bull: sig[i] = -1
        else:
            if up and bull:
                rl_lvl = sh1; rl_until = i + retest_bars
            if dn and bear:
                rs_lvl = sl1; rs_until = i + retest_bars
            if i <= rl_until and not up and l[i] <= rl_lvl + retest_atr * a[i] and c[i] > rl_lvl:
                sig[i] = 1; rl_until = -1
            elif i <= rs_until and not dn and h[i] >= rs_lvl - retest_atr * a[i] and c[i] < rs_lvl:
                sig[i] = -1; rs_until = -1
    return sig


@njit(cache=True)
def divergence(h, l, r, k, w, rsi_lo, rsi_hi):
    """Divergência regular de RSI entre dois pivôs fractais (k) a até w barras; sinal quando o 2º pivô confirma."""
    n = len(r)
    sig = np.zeros(n, np.int64)
    for i in range(2 * k + 1, n):
        j = i - k
        ph = True; pl = True
        for t in range(j - k, j + k + 1):
            if t == j:
                continue
            if t < j:
                if h[t] >= h[j]: ph = False
                if l[t] <= l[j]: pl = False
            else:
                if h[t] > h[j]: ph = False
                if l[t] < l[j]: pl = False
        if pl and r[j] < rsi_lo:
            for j2 in range(j - k - 1, max(k, j - w) - 1, -1):     # pivô de baixa anterior mais recente
                q = True
                for t in range(j2 - k, j2 + k + 1):
                    if t != j2 and ((t < j2 and l[t] <= l[j2]) or (t > j2 and l[t] < l[j2])):
                        q = False; break
                if q:
                    if l[j] < l[j2] and r[j] > r[j2]:
                        sig[i] = 1
                    break
        if ph and r[j] > rsi_hi and sig[i] == 0:
            for j2 in range(j - k - 1, max(k, j - w) - 1, -1):
                q = True
                for t in range(j2 - k, j2 + k + 1):
                    if t != j2 and ((t < j2 and h[t] >= h[j2]) or (t > j2 and h[t] > h[j2])):
                        q = False; break
                if q:
                    if h[j] > h[j2] and r[j] < r[j2]:
                        sig[i] = -1
                    break
    return sig


# ----------------------------------------------------------------------------------- famílias
RSI_N = (5, 7, 9, 14)
RSI_LO = (20, 25, 30, 35, 40)
MA_N = (50, 100, 150, 200)
MA_T = ("sma", "ema")
FIB_L = (24, 48, 72, 96, 120)
FIB_R = (0.5, 0.618, 0.786)
FIB_MA = ("sma100", "ema100", "sma200")
PIV_K = (2, 3, 5)
DIV_N = (7, 14)
DIV_K = (3, 5)
DIV_W = (30, 60)
TRF = ("none", "sma100", "sma200")
FILTERS = ("none", "adx20", "adx25", "ny", "asia", "atrp_mid", "atrp_hi", "slope100")


def base_groups(b: pd.DataFrame):
    o, h, l, c = (b[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    n = len(c)
    A = atr(h, l, c, 14)
    MA = {(t, m): (sma(c, m) if t == "sma" else ema(c, m)) for t in MA_T for m in MA_N}
    R = {m: rsi(c, m) for m in set(RSI_N) | set(DIV_N)}
    trend = {"none": (np.ones(n, bool), np.ones(n, bool)),
             "sma100": (c > MA["sma", 100], c < MA["sma", 100]),
             "sma200": (c > MA["sma", 200], c < MA["sma", 200]),
             "ema100": (c > MA["ema", 100], c < MA["ema", 100])}
    groups = []

    # 1) RSI reversão/pullback a favor da tendência: RSI(n) cruza acima de lo com close > MA -> BUY (espelho p/ SELL)
    for mt in MA_T:
        axes = [("rsi_n", RSI_N), ("rsi_lo", RSI_LO), ("ma_n", MA_N)]
        sigs = [to_sig(cross_up(R[rn], lo) & (c > MA[mt, mn]), cross_dn(R[rn], 100 - lo) & (c < MA[mt, mn]))
                for rn, lo, mn in itertools.product(RSI_N, RSI_LO, MA_N)]
        groups.append({"family": "RSIPB", "cat": {"ma_t": mt}, "axes": axes, "sigs": np.array(sigs)})

    # 2) Fibonacci em swing: perna de alta (fundo antes do topo) nas últimas L barras, mínima toca H - r*(H-L),
    #    fecha acima do nível e candle de alta, com close acima da MA (espelho p/ SELL)
    for fm in FIB_MA:
        tl, ts = trend[fm.replace("sma100", "sma100")]
        axes = [("fib_L", FIB_L), ("fib_r", FIB_R)]
        sigs = []
        for L in FIB_L:
            H, Lw = hh(h, L), ll(l, L)
            ih = pd.Series(h).rolling(L).apply(np.argmax, raw=True).shift(1).to_numpy()
            il = pd.Series(l).rolling(L).apply(np.argmin, raw=True).shift(1).to_numpy()
            upleg, dnleg = ih > il, il > ih
            rng = H - Lw
            for r in FIB_R:
                lv_l, lv_s = H - r * rng, Lw + r * rng
                sigs.append(to_sig(tl & upleg & (l <= lv_l) & (c > lv_l) & (c > o),
                                   ts & dnleg & (h >= lv_s) & (c < lv_s) & (c < o)))
        groups.append({"family": "FIB", "cat": {"trend": fm}, "axes": axes, "sigs": np.array(sigs)})

    # 3) Estrutura: BOS / CHoCH / reteste do nível rompido, pivôs fractais k
    for mode, name in ((0, "BOS"), (1, "CHOCH"), (2, "BOSRT")):
        for tf_ in TRF:
            tl, ts = trend[tf_]
            sigs = []
            for k in PIV_K:
                s = structure(h, l, c, A, k, mode, 24, 0.25)
                sigs.append(to_sig((s == 1) & tl, (s == -1) & ts))
            groups.append({"family": name, "cat": {"trend": tf_}, "axes": [("piv_k", PIV_K)], "sigs": np.array(sigs)})

    # 4) Divergência regular de RSI
    for tf_ in TRF:
        tl, ts = trend[tf_]
        axes = [("div_rsi", DIV_N), ("div_k", DIV_K), ("div_w", DIV_W)]
        sigs = []
        for rn, k, w in itertools.product(DIV_N, DIV_K, DIV_W):
            s = divergence(h, l, R[rn], k, w, 40.0, 60.0)
            sigs.append(to_sig((s == 1) & tl, (s == -1) & ts))
        groups.append({"family": "RSIDIV", "cat": {"trend": tf_}, "axes": axes, "sigs": np.array(sigs)})
    return groups, A


def filter_masks(b: pd.DataFrame):
    """Filtros extras: (máscara compra, máscara venda). Horário em UTC da abertura da barra do sinal."""
    h, l, c = (b[k].to_numpy(np.float64) for k in ("high", "low", "close"))
    n = len(c)
    A = atr(h, l, c, 14)
    X = adx(h, l, c, 14)
    hr = b["time"].dt.hour.to_numpy()
    pct = pd.Series(A).rolling(250, min_periods=100).rank(pct=True).to_numpy()
    m100 = sma(c, 100)
    slope = m100 - np.roll(m100, 10)
    one = np.ones(n, bool)
    f = {"none": (one, one),
         "adx20": (X > 20, X > 20),
         "adx25": (X > 25, X > 25),
         "ny": ((hr >= 13) & (hr < 21),) * 2,          # sessão NY ~ 13-21 UTC
         "asia": ((hr >= 0) & (hr < 8),) * 2,          # sessão Ásia ~ 00-08 UTC
         "atrp_mid": ((pct >= 0.2) & (pct <= 0.8),) * 2,
         "atrp_hi": (pct > 0.5, pct > 0.5),
         "slope100": (slope > 0, slope < 0)}
    return {k: (np.nan_to_num(v[0]).astype(bool), np.nan_to_num(v[1]).astype(bool)) for k, v in f.items()}


def all_groups(b: pd.DataFrame):
    base, A = base_groups(b)
    fm = filter_masks(b)
    out = []
    for g in base:
        for fname in FILTERS:
            fl, fs = fm[fname]
            s = g["sigs"].copy()
            s[(s == 1) & ~fl] = 0
            s[(s == -1) & ~fs] = 0
            out.append({**g, "cat": {**g["cat"], "filter": fname}, "sigs": s})
    return out, A
