import sys, itertools, time, numpy as np, pandas as pd
from numba import njit
from grid_nq import load, signals, sma, rsi, SPLIT

@njit(cache=True)
def bt2(o, h, l, c, sp, a, sig, xs, sl_k, tp_k, be_k, act_k, tr_k):
    """Long-only. xs[i]=True -> sai no open i+1. be_k: move SL p/ entrada+custo ao atingir be_k*ATR.
    act_k/tr_k: trailing só após lucro de act_k*ATR, distância tr_k*ATR (act_k=0 -> sem trailing)."""
    n = len(c); pnl = np.zeros(n); ent = np.full(n, -1)
    k = 0; pos = 0; ep = 0.; st = 0.; tp = 0.; mx = 0.; a0 = 0.; ib = 0; xnext = False
    for i in range(1, n):
        if pos == 1:
            ex = 0.; done = False
            if xnext: ex = o[i]; done = True
            elif o[i] <= st: ex = o[i]; done = True
            elif l[i] <= st: ex = st; done = True
            elif tp > 0 and h[i] >= tp: ex = tp; done = True
            if done:
                pnl[k] = ex - ep; ent[k] = ib; k += 1; pos = 0; xnext = False
            else:
                mx = max(mx, h[i])
                if be_k > 0 and mx - ep >= be_k*a0 and st < ep + sp[i]: st = ep + sp[i]
                if act_k > 0 and mx - ep >= act_k*a0:
                    ns = mx - tr_k*a[i]
                    if ns > st: st = ns
                xnext = xs[i]
        if pos == 0 and i < n-1 and sig[i] == 1 and a[i] > 0:
            pos = 1; ib = i+1; a0 = a[i]; ep = o[i+1] + sp[i+1]
            st = ep - sl_k*a0; tp = ep + tp_k*a0 if tp_k > 0 else 0.; mx = ep; xnext = False
    return pnl[:k], ent[:k]

EX = [(sl, tp, be, at, xs) for sl, tp, be, (at), xs in itertools.product(
    [1.5, 2.0, 3.0, 4.0], [0.0, 0.75, 1.0, 1.5, 2.0], [0.0, 0.75], [(0., 0.), (1.0, 1.0), (1.5, 1.5)],
    ['none', 'rsi5_60', 'c>sma5', 'c>prevH'])]

if __name__ == '__main__':
    rows = []
    for tf in ('m15', 'h1', 'h4'):
        t0 = time.time(); b = load(tf); sig, A = signals(b)
        o, h, l, c, sp = (b[k].values.astype(np.float64) for k in ('open', 'high', 'low', 'close', 'sp'))
        XS = {'none': np.zeros(len(c), np.bool_), 'rsi5_60': rsi(c, 5) > 60,
              'c>sma5': c > sma(c, 5), 'c>prevH': c > np.roll(h, 1)}
        si = np.searchsorted(b.index.values, SPLIT.to_datetime64())
        for name, s in sig.items():
            if not name.endswith('|long'): continue
            for sl, tp, be, (at, tr), xn in EX:
                p, ei = bt2(o, h, l, c, sp, A, s, XS[xn], sl, tp, be, at, tr)
                if len(p) < 40: continue
                p1, p2 = p[ei < si], p[ei >= si]
                def pf(x):
                    g = x[x > 0].sum(); ls = -x[x < 0].sum(); return g/ls if ls > 0 else 99.
                eq = np.cumsum(p)
                rows.append((tf, name, sl, tp, be, at, tr, xn, len(p), p.sum(), pf(p), (p > 0).mean(),
                             (np.maximum.accumulate(np.maximum(eq, 0)) - eq).max(),
                             len(p1), pf(p1), (p1 > 0).mean() if len(p1) else 0, len(p2), pf(p2), (p2 > 0).mean() if len(p2) else 0))
        print(tf, f'{time.time()-t0:.0f}s', len(rows), flush=True)
    df = pd.DataFrame(rows, columns=['tf', 'strat', 'sl', 'tp', 'be', 'act', 'trail', 'xsig', 'n', 'net', 'pf', 'wr', 'dd',
                                     'n_is', 'pf_is', 'wr_is', 'n_oos', 'pf_oos', 'wr_oos'])
    df.to_parquet('/home/claude/nq/res_wr.parquet'); print(len(df))
