"""Métricas de orderflow por barra H1 (funções puras: mesmo código no backtest e num feed ao vivo).

Por barra (a partir do footprint, níveis de `bucket` US$):
  delta        volume comprador - vendedor (agressão)
  poc          centro do nível com mais volume
  vah / val    limites da área de valor (70% do volume), expandida a partir do POC pelo lado de maior volume
  stk_buy      maior sequência de níveis com desequilíbrio comprador diagonal: buy[k] >= ratio x sell[k-1]
  stk_sell     idem vendedor: sell[k] >= ratio x buy[k+1]        (stacked = sequência >= 3, ratio 300%)
  low_share    fração do volume da barra nos 2 níveis mais baixos (pouco volume na mínima = venda esgotando)
  high_share   idem nos 2 níveis mais altos
Na série (só barras ANTERIORES nas janelas):
  cvd          delta acumulado
  dz           z-score do delta contra as 100 barras anteriores
  absorb_bull  dz <= -2 sem nova mínima (low >= mínima das 3 barras anteriores): venda forte absorvida
  absorb_bear  dz >= +2 sem nova máxima
  exh_bull     nova mínima de 10 barras com low_share <= 5%: venda esgotada na mínima
  exh_bear     nova máxima de 10 barras com high_share <= 5%
  cvd_div_buy  preço subiu nas últimas 3 barras e o CVD caiu (compra sem agressão compradora) -> veta compra
  cvd_div_sell preço caiu nas últimas 3 barras e o CVD subiu
Mapeamento Binance -> XM: offset = fechamento XM - fechamento Binance na mesma barra; nível_xm = nível + offset.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

RATIO, STACK, VALUE_AREA = 3.0, 3, 0.70


def _max_run(mask: np.ndarray) -> int:
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def bar_metrics(lvl: np.ndarray, buy: np.ndarray, sell: np.ndarray, bucket: float, ratio: float = RATIO,
                va: float = VALUE_AREA) -> Dict[str, float]:
    """lvl/buy/sell de UMA barra (qualquer ordem). Preenche os níveis vazios entre a mínima e a máxima."""
    lo, hi = int(lvl.min()), int(lvl.max())
    n = hi - lo + 1
    B, S = np.zeros(n), np.zeros(n)
    np.add.at(B, lvl - lo, buy)
    np.add.at(S, lvl - lo, sell)
    V = B + S
    tot = V.sum()
    p = int(np.argmax(V))
    a = b = p
    acc = V[p]
    while acc < va * tot and (a > 0 or b < n - 1):
        up = V[b + 1] if b < n - 1 else -1.0
        dn = V[a - 1] if a > 0 else -1.0
        if up >= dn:
            b += 1
            acc += up
        else:
            a -= 1
            acc += dn
    floor = 0.002 * tot                        # denominador mínimo: nível vazio não gera desequilíbrio com volume ínfimo
    imb_b = np.zeros(n, bool)
    imb_s = np.zeros(n, bool)
    if n > 1:
        imb_b[1:] = (B[1:] > 0) & (B[1:] >= ratio * np.maximum(S[:-1], floor))
        imb_s[:-1] = (S[:-1] > 0) & (S[:-1] >= ratio * np.maximum(B[1:], floor))
    k = min(2, n)
    return {"delta": float(B.sum() - S.sum()), "vol": float(tot),
            "poc": (lo + p + 0.5) * bucket, "vah": (lo + b + 1) * bucket, "val": (lo + a) * bucket,
            "stk_buy": _max_run(imb_b), "stk_sell": _max_run(imb_s),
            "low_share": float(V[:k].sum() / tot) if tot else 0.0, "high_share": float(V[-k:].sum() / tot) if tot else 0.0}


def per_bar(fp: pd.DataFrame, bucket: float) -> pd.DataFrame:
    rows = []
    for hour, g in fp.groupby("hour", sort=True):
        m = bar_metrics(g["lvl"].to_numpy(), g["buy"].to_numpy(), g["sell"].to_numpy(), bucket)
        m["hour"] = hour
        rows.append(m)
    return pd.DataFrame(rows)


def series_features(bars: pd.DataFrame, m: pd.DataFrame, stack: int = STACK) -> pd.DataFrame:
    """bars (Binance OHLC por hour) + métricas por barra -> sinais de orderflow (só passado nas janelas)."""
    d = bars.merge(m, on="hour", how="inner").sort_values("hour").reset_index(drop=True)
    d["cvd"] = d["delta"].cumsum()
    mu = d["delta"].rolling(100).mean().shift(1)
    sd = d["delta"].rolling(100).std().shift(1)
    d["dz"] = (d["delta"] - mu) / sd
    low3, high3 = d["low"].rolling(3).min().shift(1), d["high"].rolling(3).max().shift(1)
    low10, high10 = d["low"].rolling(10).min().shift(1), d["high"].rolling(10).max().shift(1)
    d["absorb_bull"] = (d["dz"] <= -2) & (d["low"] >= low3)
    d["absorb_bear"] = (d["dz"] >= 2) & (d["high"] <= high3)
    d["exh_bull"] = (d["low"] < low10) & (d["low_share"] <= 0.05)
    d["exh_bear"] = (d["high"] > high10) & (d["high_share"] <= 0.05)
    d["stacked_bull"] = d["stk_buy"] >= stack
    d["stacked_bear"] = d["stk_sell"] >= stack
    dc, dv = d["close"] - d["close"].shift(3), d["cvd"] - d["cvd"].shift(3)
    d["cvd_div_buy"] = (dc > 0) & (dv < 0)
    d["cvd_div_sell"] = (dc < 0) & (dv > 0)
    return d


def map_to_xm(feat: pd.DataFrame, xm_close: pd.Series) -> pd.DataFrame:
    """xm_close indexado por hour (ms). Acrescenta offset e os níveis já no preço da XM."""
    d = feat.copy()
    d["xm_close"] = d["hour"].map(xm_close)
    d["offset"] = d["xm_close"] - d["close"]
    for c in ("poc", "vah", "val"):
        d[f"{c}_xm"] = d[c] + d["offset"]
    return d
