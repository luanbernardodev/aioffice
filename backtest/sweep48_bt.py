"""Backtest do SWEEP48 em barras M5 (mesmas funções de sinal do agente).

O stop móvel de 0.15*A é por tick e o histórico é M5, então o resultado é dado em dois limites:
  otimista:   o stop arrasta até o extremo da barra e só é atingido em barras seguintes;
  pessimista: ao ativar (+0.75*A) sai na mesma barra em +0.60*A (recuo de 0.15*A logo após a ativação).
Custos: spread da barra x1.5 no modo padrão. Lote 0.01 => US$0.01 por US$1. Corte IS/OOS em 60% do período.

  python -m backtest.sweep48_bt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents.sweep48 import add_indicators, signal_at
from backtest.research import load_tf
from engine.features import TF_SECONDS  # noqa: F401  (documenta a base M5)

VPU_LOT = 0.01


def to_server_epoch(t: pd.Series) -> np.ndarray:
    """UTC -> relógio do servidor XM (New York + 7h), como o `time` das barras do MT5."""
    ny = t.dt.tz_convert("America/New_York").dt.tz_localize(None) + pd.Timedelta(hours=7)
    return (ny - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)


def run(df: pd.DataFrame, pessimistic: bool) -> pd.DataFrame:
    d = add_indicators(df.assign(time=to_server_epoch(df["time"]).to_numpy()))
    o, h, l, c, sp = (d[x].to_numpy() for x in ("open", "high", "low", "close", "spread"))
    t = d["time"].to_numpy()
    sig = np.zeros(len(d), dtype=int)
    for row in d.itertuples(index=True):
        sig[row.Index] = signal_at(row)
    out, i = [], 0
    while i < len(d) - 1:
        if sig[i] == 0:
            i += 1
            continue
        side, a, j = int(sig[i]), float(d["atr"].iat[i]), i + 1
        entry = o[j] + (sp[j] if side == 1 else 0.0)
        sl, tp, t0, res = entry - side * 3 * a, entry + side * 5 * a, t[j], None
        while j < len(d):
            bid_l, bid_h, ask_l, ask_h = l[j], h[j], l[j] + sp[j], h[j] + sp[j]
            if t[j] - t0 >= 240 * 60:
                res = (o[j] + (sp[j] if side == -1 else 0.0), "TEMPO")
            elif side == 1 and bid_l <= sl:
                res = (min(sl, o[j]), "SL")
            elif side == -1 and ask_h >= sl:
                res = (max(sl, o[j] + sp[j]), "SL")
            elif side == 1 and bid_h >= tp:
                res = (tp, "TP")
            elif side == -1 and ask_l <= tp:
                res = (tp, "TP")
            elif side == 1 and bid_h - entry >= 0.75 * a:
                if pessimistic:
                    res = (entry + 0.60 * a, "TRAIL")
                else:
                    sl = max(sl, bid_h - 0.15 * a)
            elif side == -1 and entry - ask_l >= 0.75 * a:
                if pessimistic:
                    res = (entry - 0.60 * a, "TRAIL")
                else:
                    sl = min(sl, ask_l + 0.15 * a)
            if res:
                break
            j += 1
        if res is None:
            break
        out.append({"t": t[j], "side": side, "usd": (res[0] - entry) * side * VPU_LOT, "r": (res[0] - entry) * side / (3 * a), "why": res[1]})
        i = j
    return pd.DataFrame(out)


def show(name: str, tr: pd.DataFrame) -> None:
    cut = tr["t"].quantile(0.6)
    for part, g in (("IS ", tr[tr.t < cut]), ("OOS", tr[tr.t >= cut])):
        eq = g.usd.cumsum()
        pf = g.usd[g.usd > 0].sum() / max(-g.usd[g.usd < 0].sum(), 1e-9)
        print(f"  {name:10s} {part}: n={len(g):4d} win={100 * (g.usd > 0).mean():5.1f}% PF={pf:.2f} "
              f"exp={g.r.mean():+.3f}R net=${g.usd.sum():+7.2f} maxDD=${(eq.cummax().clip(lower=0) - eq).max():.2f}")
    print("   saídas:", tr.groupby("why").usd.agg(["size", "mean"]).round(2).to_dict("index"))


def main() -> None:
    m5 = load_tf("BTCUSD", "M5")           # load_tf já aplica spread x1.5
    print(f"BTCUSD M5 {m5.time.iloc[0]:%Y-%m-%d} -> {m5.time.iloc[-1]:%Y-%m-%d}")
    for pess in (False, True):
        show("pessimista" if pess else "otimista", run(m5, pess))
    print("sem custo de spread:")
    for pess in (False, True):
        show("pessimista" if pess else "otimista", run(m5.assign(spread=0.0), pess))


if __name__ == "__main__":
    main()
