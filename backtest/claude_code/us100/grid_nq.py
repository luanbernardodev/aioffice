import sys, itertools, time, numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/bt')
from engine import bt, ema, sma, rsi, atr, hh, ll, adx

SPLIT = pd.Timestamp('2026-06-01', tz='UTC')
SLIP = 0.5  # pts por lado
EXITS = list(itertools.product([1.0, 1.5, 2.0, 3.0], [1.5, 2.0, 3.0, 4.0], [0.0, 1.0], [0.0, 3.0]))

def load(tf):
    d = pd.read_parquet(f'/home/claude/nq/{tf}.parquet').set_index('time')
    d['sp'] = d.spread/100 + 2*SLIP
    return d

def xu(x, v): return (x > v) & (np.roll(x, 1) <= v)
def xd(x, v): return (x < v) & (np.roll(x, 1) >= v)

def signals(b):
    o, h, l, c = (b[k].values for k in ('open', 'high', 'low', 'close'))
    hr = b.index.hour.values
    A = atr(h, l, c, 14)
    MA = {}
    for n in (50, 100, 200):
        MA[f's{n}'] = sma(c, n); MA[f'e{n}'] = ema(c, n)
    R = {n: rsi(c, n) for n in (2, 5, 7, 9, 14)}
    ones = np.ones(len(c), bool)
    out = {}
    def add(name, L, S, dirs=('both', 'long')):
        for dr in dirs:
            s = np.zeros(len(c), np.int64); s[L] = 1
            if dr == 'both': s[S & ~L] = -1
            s[:200] = 0; out[f'{name}|{dr}'] = s
    filts = {'none': (ones, ones)}
    for k, v in MA.items(): filts[k] = (c > v, c < v)
    # 1) Reversão RSI (família vencedora no BTC)
    for rn, lo, f in itertools.product((5, 7, 9, 14), (20, 25, 30, 35), filts):
        fl, fs = filts[f]; add(f'RSIREV_r{rn}_{lo}_{f}', xu(R[rn], lo) & fl, xd(R[rn], 100-lo) & fs)
    # 2) Connors RSI(2) a favor da MA200/100
    for th, f in itertools.product((5, 10, 15), ('s200', 'e200', 's100')):
        fl, fs = filts[f]; add(f'RSI2_{th}_{f}', (R[2] < th) & fl, (R[2] > 100-th) & fs)
    # 3) Pullback Fibonacci + candle de confirmação
    for L, r, f in itertools.product((12, 24, 48, 96, 120), (0.382, 0.5, 0.618, 0.786), ('s50', 's100', 's200', 'e100')):
        fl, fs = filts[f]; H, Lw = hh(h, L), ll(l, L); rg = H - Lw
        lv, sv = H - r*rg, Lw + r*rg
        add(f'FIB_{L}_{r}_{f}', fl & (l <= lv) & (c > lv) & (c > o), fs & (h >= sv) & (c < sv) & (c < o))
    # 4) Confluência Fibo (zona 0.5–0.786) + RSI sobrevendido/sobrecomprado
    for L, rn, th, f in itertools.product((24, 48, 96), (7, 14), (30, 35, 40), ('s100', 's200')):
        fl, fs = filts[f]; H, Lw = hh(h, L), ll(l, L); rg = H - Lw
        zl = (l <= H - 0.5*rg) & (l >= H - 0.786*rg); zs = (h >= Lw + 0.5*rg) & (h <= Lw + 0.786*rg)
        add(f'FIBRSI_{L}_r{rn}_{th}_{f}', fl & zl & xu(R[rn], th), fs & zs & xd(R[rn], 100-th))
    # 5) Filtro de sessão NY (13–20 UTC) nas reversões RSI com MA100
    ny = (hr >= 13) & (hr < 20)
    for rn, lo in itertools.product((5, 7, 9, 14), (25, 30, 35)):
        add(f'RSIREV_NY_r{rn}_{lo}_s100', xu(R[rn], lo) & (c > MA['s100']) & ny, xd(R[rn], 100-lo) & (c < MA['s100']) & ny)
    return out, A

def stats(p):
    if len(p) == 0: return 0, 0., 0., 0., 0.
    g = p[p > 0].sum(); ls = -p[p < 0].sum(); eq = np.cumsum(p)
    return len(p), p.sum(), (g/ls if ls > 0 else 99.), (p > 0).mean(), (np.maximum.accumulate(np.maximum(eq, 0)) - eq).max()

if __name__ == '__main__':
    rows = []
    for tf in ('m15', 'h1', 'h4'):
        t0 = time.time(); b = load(tf); sig, A = signals(b)
        o, h, l, c, sp = (b[k].values.astype(np.float64) for k in ('open', 'high', 'low', 'close', 'sp'))
        si = np.searchsorted(b.index.values, SPLIT.to_datetime64())
        for name, s in sig.items():
            for sl, tr, act, tp in EXITS:
                p, ei, _, _ = bt(o, h, l, c, sp, A, s, sl, tr, act, tp, 0)
                a = stats(p); i1 = stats(p[ei < si]); i2 = stats(p[ei >= si])
                rows.append((tf, name, sl, tr, act, tp, *a, i1[0], i1[1], i1[2], i2[0], i2[1], i2[2]))
        print(tf, len(sig), 'sinais', f'{time.time()-t0:.0f}s', flush=True)
    df = pd.DataFrame(rows, columns=['tf', 'strat', 'sl', 'trail', 'act', 'tp', 'n', 'net', 'pf', 'wr', 'dd',
                                     'n_is', 'net_is', 'pf_is', 'n_oos', 'net_oos', 'pf_oos'])
    df.to_parquet('/home/claude/nq/res_nq.parquet'); print(len(df), 'backtests')
