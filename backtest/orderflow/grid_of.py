"""Grade com orderflow da Binance (BTCUSD H1): 84 sinais x 2 sessões x 14 filtros x 32 saídas = 75.264 estratégias.

Mesmo motor e custos da grade v4 (barras XM de ticks, spread real ~US$50, lote 0.01, swap). Corte: IS até
2026-06-30, OOS depois. Critérios (fixados ANTES de rodar), todos obrigatórios:
  1. acerto >= 70% no IS e no OOS
  2. PF >= 1.15 e resultado > 0 no IS e no OOS
  3. n_IS >= 30 e n_OOS >= 15
  4. spread x2: PF >= 1.05 e acerto >= 65%
  5. platô: >= 8 das 32 saídas do mesmo sinal/sessão/filtro com PF >= 1.05 e acerto >= 68%
  6. risco mediano <= US$15 por trade (BTC H1, lote 0.01)
  7. filtro de orderflow (não "none") e PF OOS maior que o da MESMA estratégia sem filtro
  8. (só para quem passa 1-7) filtro aleatório com a mesma taxa de corte supera o PF OOS em <= 10% de 1000 sorteios

  python -m backtest.orderflow.grid_of
"""
from __future__ import annotations

import json
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

from agents import v3_signals as V
from backtest.agentes_v3.bt import SPECS, TF_MIN, bars, run_bt
from backtest.agentes_v3.grid4 import EXITS, _stats, _t, signal_specs
from engine.config import ROOT
from orderflow import filters as OF

OUT = ROOT / "backtest" / "orderflow"
CUT = pd.Timestamp("2026-07-01", tz="UTC")
SESS = ["all", "us"]
SYM = "BTCUSD"


def dataset():
    b = bars(SYM, "H1").copy()
    b["hour"] = ((pd.to_datetime(b["time"], utc=True) - pd.Timestamp("1970-01-01", tz="UTC"))
                 // pd.Timedelta(milliseconds=1)).astype("int64")
    f = pd.read_pickle(OUT / "features_BTCUSDT_H1.pkl")
    cols = ["hour", "close", "delta", "cvd", "dz", "poc", "vah", "val", "absorb_bull", "absorb_bear", "exh_bull",
            "exh_bear", "stacked_bull", "stacked_bear", "cvd_div_buy", "cvd_div_sell"]
    fx = b[["hour"]].merge(f[cols], on="hour", how="left")
    has = fx["delta"].notna().to_numpy()
    return b, fx, has


def run_one(o, h, l, c, sp, a, sig, sday, ex, usd_pp, sw, mult=1.0):
    E, X, S, P, R, N, W = run_bt(o, h, l, c, sp, a, sig, sday, ex["sl"], 0.0, 0.0, ex["tp"], ex["max_bars"], mult)
    return X, P * usd_pp + np.where(S == 1, sw[0], sw[1]) * N, R * usd_pp


def job(chunk):
    b, fx, has = dataset()
    x = V.indicators(b)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    cut_i = int(np.searchsorted(b["hour"].to_numpy(), int(CUT.timestamp() * 1000)))
    usd_pp, sw = SPECS[SYM]["usd_pp"], SPECS[SYM]["swap"]
    fmask = {name: OF.masks(fx, name) for name in OF.FILTERS}
    rows = []
    for spec in chunk:
        base = V.signal(x, spec)
        for sess in SESS:
            s0 = np.where(V.session_mask(b["time"], sess, TF_MIN["H1"]), base, 0).astype(np.int64)
            s0[~has] = 0                                       # todas as variantes só onde há orderflow
            for fname in OF.FILTERS:
                bull, bear = fmask[fname]
                sig = s0.copy()
                sig[(sig == 1) & ~bull] = 0
                sig[(sig == -1) & ~bear] = 0
                for ei, ex in enumerate(EXITS):
                    X, u, R = run_one(o, h, l, c, sp, a, sig, sday, ex, usd_pp, sw)
                    ins = X < cut_i
                    n1, net1, pf1, wr1 = _stats(u[ins])
                    n2, net2, pf2, wr2 = _stats(u[~ins])
                    n, net, pf, wr = _stats(u)
                    row = [json.dumps(spec), sess, fname, ei, ex["sl"], ex["tp"], ex["max_bars"], n1, net1, pf1, wr1,
                           n2, net2, pf2, wr2, n, net, pf, wr, _t(u), float(np.median(R)) if n else 0.0,
                           int((sig != 0).sum()), np.nan, np.nan]
                    if wr1 >= 0.7 and wr2 >= 0.7 and pf1 >= 1.15 and pf2 >= 1.15 and n1 >= 30 and n2 >= 15:
                        _, u2, _ = run_one(o, h, l, c, sp, a, sig, sday, ex, usd_pp, sw, 2.0)
                        _, _, pfx, wrx = _stats(u2)
                        row[-2:] = [pfx, wrx]
                    rows.append(row)
    return rows


COLS = ["spec", "sess", "filtro", "exit", "ex_sl", "ex_tp", "ex_mb", "n_is", "net_is", "pf_is", "wr_is", "n_oos",
        "net_oos", "pf_oos", "wr_oos", "n", "net", "pf", "wr", "t", "risk_med", "n_sinais", "pf_x2", "wr_x2"]


def random_p(spec, sess, fname, ex, draws=1000, seed=7) -> float:
    """P(filtro aleatório com a mesma taxa de corte >= PF OOS do filtro de orderflow)."""
    b, fx, has = dataset()
    x = V.indicators(b)
    o, h, l, c, sp = (b[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread"))
    a, sday = x["atr"], b["sday"].to_numpy(np.int64)
    cut_i = int(np.searchsorted(b["hour"].to_numpy(), int(CUT.timestamp() * 1000)))
    usd_pp, sw = SPECS[SYM]["usd_pp"], SPECS[SYM]["swap"]
    s0 = np.where(V.session_mask(b["time"], sess, TF_MIN["H1"]), V.signal(x, spec), 0).astype(np.int64)
    s0[~has] = 0
    filt = OF.apply(s0, fx, fname)
    X, u, _ = run_one(o, h, l, c, sp, a, filt, sday, ex, usd_pp, sw)
    target = _stats(u[X >= cut_i])[2]
    keep = (filt != 0).sum() / max((s0 != 0).sum(), 1)
    idx = np.flatnonzero(s0)
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(draws):
        s = s0.copy()
        s[idx[rng.random(len(idx)) > keep]] = 0
        X2, u2, _ = run_one(o, h, l, c, sp, a, s, sday, ex, usd_pp, sw)
        hits += _stats(u2[X2 >= cut_i])[2] >= target
    return hits / draws


def main() -> None:
    t0 = time.time()
    specs = signal_specs()
    chunks = [specs[i::8] for i in range(8)]
    rows = []
    with Pool(8) as pool:
        for r in pool.imap_unordered(job, chunks):
            rows += r
    df = pd.DataFrame(rows, columns=COLS)
    good = (df.pf >= 1.05) & (df.wr >= 0.68)
    df["plateau"] = good.groupby([df.spec, df.sess, df.filtro]).transform("sum")
    base = df[df.filtro == "none"].set_index(["spec", "sess", "exit"])["pf_oos"]
    df["pf_oos_sem_filtro"] = df.set_index(["spec", "sess", "exit"]).index.map(base).to_numpy()
    df["aprovada_1a7"] = ((df.wr_is >= .7) & (df.wr_oos >= .7) & (df.pf_is >= 1.15) & (df.pf_oos >= 1.15)
                          & (df.net_is > 0) & (df.net_oos > 0) & (df.n_is >= 30) & (df.n_oos >= 15)
                          & (df.pf_x2 >= 1.05) & (df.wr_x2 >= .65) & (df.plateau >= 8) & (df.risk_med <= 15)
                          & (df.filtro != "none") & (df.pf_oos > df.pf_oos_sem_filtro))
    df.to_csv(OUT / "grid_of.csv", index=False)
    print(f"{len(df)} estratégias em {time.time() - t0:.0f}s | acerto >= 70% nos dois períodos: "
          f"{int(((df.wr_is >= .7) & (df.wr_oos >= .7)).sum())} | aprovadas nos critérios 1-7: {int(df.aprovada_1a7.sum())}",
          flush=True)
    ok = df[df.aprovada_1a7].sort_values("t", ascending=False).copy()
    ok["p_aleatorio"] = np.nan
    for k, r in ok.iterrows():                                  # critério 8 só para os aprovados
        ex = dict(sl=r.ex_sl, tp=r.ex_tp, max_bars=int(r.ex_mb))
        ok.loc[k, "p_aleatorio"] = random_p(json.loads(r.spec), r.sess, r.filtro, ex)
    ok["aprovada"] = ok.p_aleatorio <= 0.10
    ok.to_csv(OUT / "aprovadas_of.csv", index=False)
    show = ["spec", "sess", "filtro", "ex_sl", "ex_tp", "ex_mb", "n_is", "wr_is", "pf_is", "n_oos", "wr_oos", "pf_oos",
            "pf_oos_sem_filtro", "pf_x2", "wr_x2", "plateau", "risk_med", "p_aleatorio", "aprovada"]
    with pd.option_context("display.width", 320, "display.max_colwidth", 60):
        print(ok[show].round(3).to_string(index=False))
    print(f"\naprovadas nos 8 critérios: {int(ok.aprovada.sum())} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
