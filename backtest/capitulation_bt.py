"""Backtest do CAPITULATION em barras M5 (BTCUSD). Stop por tick em dois limites, como no SWEEP48:
otimista = arrasta até a máxima da barra; pessimista = ao ativar, sai na mesma barra em +(trigger-dist)*A.
Spread da barra x1.5 (load_tf). Lote 0.01. Corte IS/OOS em 60% do tempo.

  python -m backtest.capitulation_bt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents.capitulation_rules import episode_step, rsi_state, rsi_with_partial
from backtest.research import load_tf
from engine import indicators as ind

VPU = 0.01


def live_rsi(m5: pd.DataFrame, m15: pd.DataFrame) -> np.ndarray:
    g, l = rsi_state(m15["close"])
    closes = m15["close"].to_numpy()
    pos = {t: i for i, t in enumerate(m15["time"])}
    out = np.full(len(m5), np.nan)
    for j, (t, px) in enumerate(zip(m5["time"], m5["close"])):
        k = pos.get(t.floor("15min"))
        if k and k > 0:
            out[j] = rsi_with_partial(g[k - 1], l[k - 1], closes[k - 1], px)
    return out


def run(m5, rsi, trig=10.0, add=20.0, sl_a=2.0, t_a=0.5, d_a=0.25, max_n=3, pess=False, mins=240,
        lock_after_entry=False) -> pd.DataFrame:
    o, h, l, c, sp, t = (m5[x].to_numpy() for x in ("open", "high", "low", "close", "spread", "time"))
    atr = ind.atr(m5).to_numpy()
    pos, out, armed, locked, ep = [], [], False, False, 0
    for j in range(300, len(m5) - 1):
        for p in list(pos):                      # posições abertas na barra j
            res = None
            if (t[j] - p["t0"]) / np.timedelta64(1, "m") >= mins:
                res = (o[j], "TEMPO")
            elif l[j] <= p["sl"]:
                res = (min(p["sl"], o[j]), "TRAIL" if p["on"] else "SL")
            elif h[j] - p["e"] >= t_a * p["a"]:
                p["on"] = locked = True
                if pess:
                    res = (p["e"] + (t_a - d_a) * p["a"], "TRAIL")
                else:
                    p["sl"] = max(p["sl"], h[j] - d_a * p["a"])
            if res:
                out.append({"t": t[j], "usd": (res[0] - p["e"]) * VPU, "why": res[1], "ep": p["ep"], "a": p["a"]})
                pos.remove(p)
        r = rsi[j]
        if np.isnan(r) or np.isnan(atr[j]):
            continue
        was = armed
        armed, locked, buy = episode_step(armed, locked, r, trig, add, len(pos), max_n)
        ep += int(armed and not was)
        if buy:
            e = o[j + 1] + sp[j + 1]
            pos.append({"e": e, "sl": e - sl_a * atr[j], "a": atr[j], "t0": t[j + 1], "on": False, "ep": ep})
            locked = locked or lock_after_entry
    return pd.DataFrame(out)


def show(name, tr):
    if tr.empty:
        print(f"  {name}: sem trades"); return
    cut = tr.t.quantile(0.6)
    for part, g in (("IS ", tr[tr.t < cut]), ("OOS", tr[tr.t >= cut])):
        if g.empty:
            continue
        eq = g.usd.cumsum()
        pf = g.usd[g.usd > 0].sum() / max(-g.usd[g.usd < 0].sum(), 1e-9)
        print(f"  {name:24s} {part}: trades={len(g):3d} episodios={g.ep.nunique():3d} win={100*(g.usd>0).mean():5.1f}% PF={pf:5.2f} "
              f"net=${g.usd.sum():+7.2f} maxDD=${(eq.cummax().clip(lower=0)-eq).max():.2f}")
    print("     saidas:", tr.groupby("why").usd.agg(["size", "mean"]).round(2).to_dict("index"))


def main():
    m5, m15 = load_tf("BTCUSD", "M5"), load_tf("BTCUSD", "M15")
    print(f"M5 {m5.time.iloc[0]:%Y-%m-%d} -> {m5.time.iloc[-1]:%Y-%m-%d %H:%M}")
    rsi = live_rsi(m5, m15)
    print(f"barras M5 com RSI ao vivo <=10: {(rsi<=10).sum()} | <=15: {(rsi<=15).sum()} | <=20: {(rsi<=20).sum()} de {len(rsi)}")
    for trig in (10.0, 15.0):
        for pess in (False, True):
            show(f"RSI<={trig:.0f} {'pessimista' if pess else 'otimista'}", run(m5, rsi, trig=trig, pess=pess))
    print("agente RSI20 (1 compra por episodio, rearma com RSI>=30):")
    for pess in (False, True):
        show(f"RSI<=20 {'pessimista' if pess else 'otimista'}",
             run(m5, rsi, trig=20.0, add=30.0, max_n=1, pess=pess, lock_after_entry=True))


if __name__ == "__main__":
    main()
