"""US500Cash: candidatos clássicos de índice definidos ANTES de rodar (sem ajuste), 2016-09 -> 2026-11.

C1 Connors RSI(2) diário: fechamento > SMA200 e RSI2 < 10 -> compra na abertura seguinte; sai quando
   fecha > SMA5 (na abertura seguinte) ou após 10 dias.
C2 Rompimento de 20 dias (só compra) com filtro SMA200; sai no fechamento abaixo da mínima de 10 dias.
C3 Noite: compra na última H1 antes do fechamento de NY, vende na 1ª H1 após a abertura seguinte.
Custos: spread da barra (mín. 0.8 pt) + 0.25 pt de slippage por lado; swap -1.32/lote/noite (x3 na sexta).
Lote 0.1 => US$0.10 por ponto. IS 2016-09..2022-12 / OOS 2023-01..
  python -m backtest.agentes_v2.us500_classic
"""
import numpy as np
import pandas as pd

from engine import indicators as ind

LOT, SWAP, SLIP = 0.1, -1.32, 0.25
OOS = pd.Timestamp("2023-01-01", tz="UTC")


def load():
    h = pd.read_csv("data/US500Cash_H1.csv")
    h["time"] = pd.to_datetime(h.time, utc=True)
    h = h[h.time >= "2016-09-01"].reset_index(drop=True)
    h["spread"] = np.maximum(h.spread, 0.8)
    ny = h.time.dt.tz_convert("America/New_York")
    h["day"] = ny.dt.date
    d = h.groupby("day").agg(time=("time", "first"), open=("open", "first"), high=("high", "max"),
                             low=("low", "min"), close=("close", "last"), spread=("spread", "median")).reset_index()
    return h, d


def nights(t_in, t_out):
    days = pd.date_range(t_in.normalize(), t_out.normalize(), freq="D", inclusive="left")
    return sum(3 if x.weekday() == 4 else (0 if x.weekday() >= 5 else 1) for x in days)


def trade(t_in, t_out, p_in, p_out, sp_in, sp_out):
    pts = (p_out - p_in) - sp_in - 2 * SLIP
    return {"t_in": t_in, "t_out": t_out, "usd": pts * LOT + SWAP * LOT * nights(t_in, t_out)}


def c1(d):
    rsi2, s200, s5 = ind.rsi(d.close, 2), d.close.rolling(200).mean(), d.close.rolling(5).mean()
    out, i = [], 200
    while i < len(d) - 1:
        if d.close[i] > s200[i] and rsi2[i] < 10:
            j = i + 1
            k = j
            while k < len(d) - 1 and not (d.close[k] > s5[k] or k - j >= 10):
                k += 1
            out.append(trade(d.time[j], d.time[min(k + 1, len(d) - 1)], d.open[j], d.open[min(k + 1, len(d) - 1)],
                             d.spread[j], 0))
            i = k + 1
        else:
            i += 1
    return pd.DataFrame(out)


def c2(d):
    hi20, lo10, s200 = d.high.rolling(20).max().shift(1), d.low.rolling(10).min().shift(1), d.close.rolling(200).mean()
    out, i = [], 200
    while i < len(d) - 1:
        if d.close[i] > hi20[i] and d.close[i] > s200[i]:
            j = i + 1
            k = j
            while k < len(d) - 1 and not d.close[k] < lo10[k]:
                k += 1
            out.append(trade(d.time[j], d.time[k + 1], d.open[j], d.open[k + 1], d.spread[j], 0))
            i = k + 1
        else:
            i += 1
    return pd.DataFrame(out)


def c3(h):
    ny = h.time.dt.tz_convert("America/New_York")
    hr = ny.dt.hour.to_numpy()
    out, i = [], 0
    while i < len(h) - 1:
        if hr[i] == 15:                            # barra 15:00-16:00 NY: compra na abertura dela (aprox.)
            j = i + 1
            while j < len(h) and not (hr[j] == 10 and ny.dt.date.iat[j] != ny.dt.date.iat[i]):
                j += 1
            if j >= len(h):
                break
            out.append(trade(h.time[i], h.time[j], h.open[i], h.open[j], h.spread[i], 0))
            i = j
        else:
            i += 1
    return pd.DataFrame(out)


def show(name, tr):
    for lab, x in (("IS ", tr[tr.t_out < OOS]), ("OOS", tr[tr.t_out >= OOS])):
        u = x.usd
        eq = u.cumsum()
        pf = u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9)
        print(f"{name} {lab}: n={len(u):4d} win={100 * (u > 0).mean():4.1f}% PF={pf:4.2f} net=${u.sum():+8.2f} "
              f"maxDD=${(eq.cummax().clip(lower=0) - eq).max():6.2f}")
    y = tr.groupby(tr.t_out.dt.year).usd.sum().round(1)
    print("   por ano:", " ".join(f"{k}:{v:+}" for k, v in y.items()))


if __name__ == "__main__":
    h, d = load()
    print(f"US500Cash H1 {h.time.iloc[0]:%Y-%m-%d} -> {h.time.iloc[-1]:%Y-%m-%d}, {len(d)} dias")
    show("C1 Connors RSI2", c1(d))
    show("C2 Rompe 20d   ", c2(d))
    show("C3 Noite       ", c3(h))
