import numpy as np, pandas as pd, itertools, time
from engine import *

SPLIT = pd.Timestamp('2026-07-01')
EXITS = list(itertools.product([1.0, 1.5, 2.0, 3.0], [1.0, 2.0, 3.0], [0.0, 1.0], [0.0, 3.0]))

def cross_up(x, lvl): return (x > lvl) & (np.roll(x, 1) <= lvl)
def cross_dn(x, lvl): return (x < lvl) & (np.roll(x, 1) >= lvl)

def signals(b):
    o, h, l, c = b.open.values, b.high.values, b.low.values, b.close.values
    A = atr(h, l, c, 14)
    ma = {n: sma(c, n) for n in (50, 100, 200)}
    R = {n: rsi(c, n) for n in (7, 14)}
    E = {n: ema(c, n) for n in (9, 20, 21, 50, 100)}
    ADX = adx(h, l, c, 14)
    filt = {'none': (np.ones(len(c), bool), np.ones(len(c), bool))}
    for n in (100, 200): filt[f'ma{n}'] = (c > ma[n], c < ma[n])
    out = {}
    def add(name, L, S):
        s = np.zeros(len(c), np.int64); s[L] = 1; s[S & ~L] = -1; s[:200] = 0
        out[name] = s
    # F1 reversão RSI (família do agente atual)
    for rn, lo, f in itertools.product((7, 14), (20, 25, 30), filt):
        fl, fs = filt[f]; add(f'RSIREV_r{rn}_{lo}/{100-lo}_{f}', cross_up(R[rn], lo) & fl, cross_dn(R[rn], 100-lo) & fs)
    # F2 pullback RSI a favor da tendência
    for rn, x, n in itertools.product((7, 14), (30, 40, 45), (50, 100, 200)):
        add(f'RSIPULL_r{rn}_{x}_ma{n}', cross_up(R[rn], x) & (c > ma[n]), cross_dn(R[rn], 100-x) & (c < ma[n]))
    # F3 Donchian / BOS
    for n, f in itertools.product((20, 40, 55, 100), filt):
        fl, fs = filt[f]; H, Lw = hh(h, n), ll(l, n)
        add(f'DONCH_{n}_{f}', (c > H) & (np.roll(c, 1) <= np.roll(H, 1)) & fl, (c < Lw) & (np.roll(c, 1) >= np.roll(Lw, 1)) & fs)
    # F4 cruzamento de EMAs
    for f_, s_ in ((9, 21), (20, 50), (21, 100), (50, 100)):
        d = E[f_] - E[s_]; add(f'EMAX_{f_}/{s_}', cross_up(d, 0), cross_dn(d, 0))
    # F5 pullback Fibonacci na tendência (MA100)
    for L, r in itertools.product((24, 48, 96), (0.5, 0.618, 0.786)):
        H, Lw = hh(h, L), ll(l, L); rng = H - Lw
        lvl_l = H - r*rng; lvl_s = Lw + r*rng
        add(f'FIB_{L}_{r}', (c > ma[100]) & (l <= lvl_l) & (c > lvl_l) & (c > o),
                            (c < ma[100]) & (h >= lvl_s) & (c < lvl_s) & (c < o))
    # F6 ADX + pullback na EMA20
    for t, n in itertools.product((20, 25, 30), (50, 100)):
        add(f'ADXPB_{t}_ema{n}', (ADX > t) & (E[20] > E[n]) & cross_up(c - E[20], 0),
                                 (ADX > t) & (E[20] < E[n]) & cross_dn(c - E[20], 0))
    # F7 Keltner breakout
    for m, f in itertools.product((1.5, 2.0, 2.5), filt):
        fl, fs = filt[f]; up = E[20] + m*A; dn = E[20] - m*A
        add(f'KELT_{m}_{f}', cross_up(c - up, 0) & fl, cross_dn(c - dn, 0) & fs)
    return out, A

def stats(p):
    if len(p) == 0: return 0, 0., 0., 0., 0.
    g = p[p > 0].sum(); ls = -p[p < 0].sum(); eq = np.cumsum(p)
    dd = (np.maximum.accumulate(np.maximum(eq, 0)) - eq).max()
    return len(p), p.sum(), g/ls if ls > 0 else 99., (p > 0).mean(), dd

if __name__ == '__main__':
    rows = []
    for tf in ('15min', '1h', '4h'):
        t0 = time.time(); b = load(tf); sig, A = signals(b)
        o, h, l, c, sp = (b[k].values.astype(np.float64) for k in ('open', 'high', 'low', 'close', 'spread'))
        split_i = np.searchsorted(b.index.values, SPLIT.to_datetime64())
        for name, s in sig.items():
            for sl, tr, act, tp in EXITS:
                p, ei, _, _ = bt(o, h, l, c, sp, A, s, sl, tr, act, tp, 0)
                ins, oos = p[ei < split_i], p[ei >= split_i]
                n, net, pf, wr, dd = stats(p); n1, net1, pf1, _, _ = stats(ins); n2, net2, pf2, _, _ = stats(oos)
                rows.append((tf, name, sl, tr, act, tp, n, net, pf, wr, dd, n1, net1, pf1, n2, net2, pf2))
        print(tf, len(sig), 'sinais', f'{time.time()-t0:.0f}s', flush=True)

    df = pd.DataFrame(rows, columns=['tf', 'strat', 'sl', 'trail', 'act', 'tp', 'n', 'net_pts', 'pf', 'wr', 'dd_pts',
                                     'n_is', 'net_is', 'pf_is', 'n_oos', 'net_oos', 'pf_oos'])
    df.to_parquet('/home/claude/bt/results.parquet'); print(len(df), 'backtests')
