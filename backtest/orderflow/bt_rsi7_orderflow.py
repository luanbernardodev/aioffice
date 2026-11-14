"""BTC RSI(7) 25/75 + SMA100 H1 (SL 1.5 ATR, trailing 3 ATR) com e sem filtro de orderflow da Binance.

Estratégia: regras do agente RSI7_H1 (agents/rsi7_h1_rules.py, bloco "fallback" do config): compra quando o RSI(7)
cruza para cima de 25 com close > SMA100; venda quando cruza para baixo de 75 com close < SMA100. Entrada na
abertura da barra seguinte (compra no ASK), SL inicial 1.5 x ATR(14) do sinal, trailing 3 x ATR(14) da barra a partir
do extremo (venda usa mínima + spread), atualizado no fechamento, só aperta. Sem TP. Uma posição por vez.
Preços: barras H1 da XM montadas dos ticks (spread real ~US$50). Lote 0.01 + swap por noite.

Filtros (definidos ANTES de rodar), sobre o orderflow da barra do sinal (janela w = 1) ou das 3 últimas (w = 3):
  CONF   entra só com absorção ou exaustão a favor, OU stacked imbalance a favor
  VETO   veta compra com divergência de CVD (preço subiu 3 barras e o CVD caiu)
  VETO2  veto também na venda (espelho)
  CONF+VETO
Corte: IS até 2026-06-30, OOS depois. Regra de integração: PF OOS melhor que o da base E trades OOS >= 50% da base.

  python -m backtest.orderflow.bt_rsi7_orderflow
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents import rsi7_h1_rules as R
from backtest.agentes_v3.bt import SPECS, bars as xm_bars
from orderflow.footprint import load
from orderflow.metrics import map_to_xm, per_bar, series_features
from engine.config import ROOT

P = {"rsi_period": 7, "rsi_level": 25, "ma_type": "sma", "ma_period": 100, "atr_period": 14}
SL_ATR, TRAIL_ATR = 1.5, 3.0
CUT = pd.Timestamp("2026-07-01", tz="UTC")
OUT = ROOT / "backtest" / "orderflow"
BUCKET = 10.0


def dataset() -> pd.DataFrame:
    x = xm_bars("BTCUSD", "H1").copy()
    x["hour"] = ((pd.to_datetime(x["time"], utc=True) - pd.Timestamp("1970-01-01", tz="UTC"))
                 // pd.Timedelta(milliseconds=1)).astype("int64")          # independe da resolução (ms/ns)
    x = R.add_indicators(x, P)
    bars, fp = load("BTCUSDT", BUCKET)
    cache = OUT / "features_BTCUSDT_H1.pkl"
    if cache.exists():
        f = pd.read_pickle(cache)
    else:
        f = map_to_xm(series_features(bars, per_bar(fp, BUCKET)), x.set_index("hour")["close"])
        f.to_pickle(cache)
    cols = ["hour", "delta", "cvd", "dz", "poc_xm", "vah_xm", "val_xm", "offset", "absorb_bull", "absorb_bear",
            "exh_bull", "exh_bear", "stacked_bull", "stacked_bear", "cvd_div_buy", "cvd_div_sell"]
    d = x.merge(f[cols], on="hour", how="left")
    for c in cols[8:]:
        d[c] = d[c].fillna(False).astype(bool)
    d["has_of"] = d["delta"].notna()
    return d


def raw_signals(d: pd.DataFrame) -> np.ndarray:
    r, c, m = d["rsi"].to_numpy(), d["close"].to_numpy(), d["ma"].to_numpy()
    s = np.zeros(len(d), np.int64)
    for i in range(1, len(d)):
        s[i] = R.signal(r[i - 1], r[i], c[i], m[i], P["rsi_level"])
    s[:150] = 0
    return s


def filtered(d: pd.DataFrame, s: np.ndarray, mode: str, w: int) -> np.ndarray:
    roll = lambda col: d[col].rolling(w, min_periods=1).max().astype(bool).to_numpy()   # noqa: E731
    bull = roll("absorb_bull") | roll("exh_bull") | roll("stacked_bull")
    bear = roll("absorb_bear") | roll("exh_bear") | roll("stacked_bear")
    out = s.copy()
    out[~d["has_of"].to_numpy()] = 0                  # sem orderflow nesta barra: fora da comparação (todas as variantes)
    if "CONF" in mode:
        out[(out == 1) & ~bull] = 0
        out[(out == -1) & ~bear] = 0
    if "VETO" in mode:
        out[(out == 1) & d["cvd_div_buy"].to_numpy()] = 0
    if "VETO2" in mode:
        out[(out == -1) & d["cvd_div_sell"].to_numpy()] = 0
    return out


def simulate(d: pd.DataFrame, sig: np.ndarray) -> pd.DataFrame:
    o, h, l, c, sp, a = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "spread", "atr"))
    sday, t = d["sday"].to_numpy(), d["time"].to_numpy()
    usd_pp, (sw_l, sw_s) = SPECS["BTCUSD"]["usd_pp"], SPECS["BTCUSD"]["swap"]
    out, i, n = [], 0, len(d)
    while i < n - 2:
        side = int(sig[i])
        if side == 0 or not a[i] > 0:
            i += 1
            continue
        j = i + 1
        entry = o[j] + sp[j] if side == 1 else o[j]
        st = R.initial_stop(side, entry, a[i], SL_ATR)
        ext, k, px = entry, j, None
        while k < n:
            if side == 1 and l[k] <= st:
                px = min(st, o[k]) if k > j else st
            elif side == -1 and h[k] + sp[k] >= st:
                px = max(st, o[k] + sp[k]) if k > j else st
            if px is not None:
                break
            if side == 1:
                ext = max(ext, h[k])
                st = max(st, ext - TRAIL_ATR * a[k])
            else:
                ext = min(ext, l[k] + sp[k])
                st = min(st, ext + TRAIL_ATR * a[k])
            k += 1
        if px is None:
            break
        nights = int(sday[k] - sday[j])
        out.append({"t_in": t[j], "t_out": t[k], "side": side,
                    "usd": (px - entry) * side * usd_pp + (sw_l if side == 1 else sw_s) * nights})
        i = k
    return pd.DataFrame(out)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0, "pf": 0.0, "wr": 0.0, "net": 0.0, "dd": 0.0}
    u = tr["usd"].to_numpy()
    eq = np.cumsum(u)
    gl = -u[u < 0].sum()
    return {"n": len(u), "pf": round(u[u > 0].sum() / gl, 2) if gl > 0 else 99.0, "wr": round(100 * (u > 0).mean(), 1),
            "net": round(u.sum(), 2), "dd": round(float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max()), 2)}


VARIANTS = [("BASE", 1), ("CONF", 1), ("CONF", 3), ("VETO", 1), ("VETO+VETO2", 1), ("CONF+VETO", 1), ("CONF+VETO", 3)]


def main() -> pd.DataFrame:
    d = dataset()
    s = raw_signals(d)
    rows = []
    for mode, w in VARIANTS:
        tr = simulate(d, filtered(d, s, mode, w))
        t_out = pd.to_datetime(tr["t_out"], utc=True) if len(tr) else pd.Series(dtype="datetime64[ns, UTC]")
        a, b = stats(tr[t_out < CUT]), stats(tr[t_out >= CUT])
        rows.append({"variante": f"{mode} (w={w})" if mode != "BASE" else "BASE (sem filtro)",
                     **{f"IS_{k}": v for k, v in a.items()}, **{f"OOS_{k}": v for k, v in b.items()}})
    df = pd.DataFrame(rows)
    base = df.iloc[0]
    df["passa"] = (df["OOS_pf"] > base["OOS_pf"]) & (df["OOS_n"] >= 0.5 * base["OOS_n"])
    df.loc[0, "passa"] = False
    print(df.to_string(index=False))
    df.to_csv(OUT / "resultado.csv", index=False)
    cov = d.loc[d["has_of"], "time"]
    print(f"\nbarras XM {len(d)} | com orderflow {int(d['has_of'].sum())} ({cov.min()} -> {cov.max()}) | "
          f"offset XM-Binance: mediana {d.get('offset', pd.Series(dtype=float)).median():.1f}")
    return df


if __name__ == "__main__":
    main()
