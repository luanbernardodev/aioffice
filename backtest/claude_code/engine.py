import numpy as np, pandas as pd
from numba import njit

def load(tf):
    m = pd.read_parquet('/home/claude/bt/m1.parquet')
    b = m.resample(tf).agg({'open':'first','high':'max','low':'min','close':'last','spread':'mean'}).dropna()
    return b

# ---------- indicators ----------
def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values
def sma(x, n): return pd.Series(x).rolling(n).mean().values
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    au = pd.Series(up).ewm(alpha=1/n, adjust=False).mean().values
    ad = pd.Series(dn).ewm(alpha=1/n, adjust=False).mean().values
    return 100 - 100/(1 + au/np.maximum(ad, 1e-9))
def atr(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc)))
    return pd.Series(tr).ewm(alpha=1/n, adjust=False).mean().values
def hh(x, n): return pd.Series(x).rolling(n).max().shift(1).values
def ll(x, n): return pd.Series(x).rolling(n).min().shift(1).values
def adx(h, l, c, n=14):
    up = np.diff(h, prepend=h[0]); dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.); ndm = np.where((dn > up) & (dn > 0), dn, 0.)
    a = atr(h, l, c, n)
    pdi = 100*pd.Series(pdm).ewm(alpha=1/n, adjust=False).mean().values/np.maximum(a, 1e-9)
    ndi = 100*pd.Series(ndm).ewm(alpha=1/n, adjust=False).mean().values/np.maximum(a, 1e-9)
    dx = 100*abs(pdi-ndi)/np.maximum(pdi+ndi, 1e-9)
    return pd.Series(dx).ewm(alpha=1/n, adjust=False).mean().values

# ---------- backtest: 1 posição, entrada no open seguinte, stop móvel ATR ----------
@njit(cache=True)
def bt(o, h, l, c, sp, a, sig, sl_k, trail_k, act_k, tp_k, max_bars):
    """sig: +1 long, -1 short (avaliado no fechamento da barra i, entra no open i+1).
    sl_k: stop inicial em ATR; trail_k: distância do trailing em ATR;
    act_k: lucro em ATR para ativar trailing (0 = imediato); tp_k: alvo em ATR (0 = sem alvo).
    Preços = BID. Compra entra no ASK (bid+spread), venda sai/entra conforme lado."""
    n = len(c); pnl = np.zeros(n); ent_i = np.full(n, -1); ex_i = np.full(n, -1); side = np.zeros(n)
    k = 0; pos = 0; ep = 0.; st = 0.; tp = 0.; ext = 0.; risk = 0.; ib = 0
    for i in range(1, n):
        if pos != 0:
            s = sp[i]; exitp = 0.; done = False
            if pos == 1:
                if o[i] <= st: exitp = o[i]; done = True
                elif l[i] <= st: exitp = st; done = True
                elif tp > 0 and h[i] >= tp: exitp = tp; done = True
            else:
                if o[i] + s >= st: exitp = o[i] + s; done = True
                elif h[i] + s >= st: exitp = st; done = True
                elif tp > 0 and l[i] + s <= tp: exitp = tp; done = True
            if not done and max_bars > 0 and i - ib >= max_bars:
                exitp = c[i] if pos == 1 else c[i] + s; done = True
            if done:
                pnl[k] = (exitp - ep) * pos; ent_i[k] = ib; ex_i[k] = i; side[k] = pos; k += 1; pos = 0
            else:
                # atualiza trailing no fechamento
                if pos == 1:
                    ext = max(ext, h[i])
                    if ext - ep >= act_k * risk:
                        ns = ext - trail_k * a[i]
                        if ns > st: st = ns
                else:
                    ext = min(ext, l[i] + s)
                    if ep - ext >= act_k * risk:
                        ns = ext + trail_k * a[i]
                        if ns < st: st = ns
        if pos == 0 and i < n-1 and sig[i] != 0 and a[i] > 0:
            pos = sig[i]; ib = i+1; risk = sl_k * a[i]
            if pos == 1:
                ep = o[i+1] + sp[i+1]; st = ep - risk; tp = ep + tp_k*a[i] if tp_k > 0 else 0.; ext = ep
            else:
                ep = o[i+1]; st = ep + risk; tp = ep - tp_k*a[i] if tp_k > 0 else 0.; ext = ep
    return pnl[:k], ent_i[:k], ex_i[:k], side[:k]
