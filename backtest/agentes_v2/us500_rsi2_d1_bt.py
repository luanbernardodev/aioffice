"""Backtest do agente US500_RSI2_D1 usando as MESMAS regras do agente (agents/us500_rsi2_d1_rules.py).

Dados: data/US500Cash_H1.csv (UTC) -> relógio do servidor (NY+7) -> dia NY. 2016-09 -> 2026-11.
Execução: entrada/saída na abertura do dia seguinte; stop de 3% tocado pela mínima do dia (sai no stop ou na
abertura, se abrir abaixo). Custos: spread da barra (mín 0.8) + 0.25 pt por lado; swap -1.32/lote/noite (x3 sexta).
  python -m backtest.agentes_v2.us500_rsi2_d1_bt
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents import us500_rsi2_d1_rules as R
from backtest.agentes_v2.us500_classic import LOT, OOS, SLIP, SWAP, nights

P = {"rsi_period": 2, "rsi_threshold": 10, "trend_sma": 200, "exit_sma": 5, "max_days": 10, "stop_pct": 3.0}


def load_daily() -> pd.DataFrame:
    h = pd.read_csv("data/US500Cash_H1.csv")
    h["time"] = pd.to_datetime(h.time, utc=True)
    h = h[h.time >= "2016-09-01"].reset_index(drop=True)
    h["spread"] = np.maximum(h.spread, 0.8)
    ny = h.time.dt.tz_convert("America/New_York").dt.tz_localize(None)
    srv = ((ny + pd.Timedelta(hours=7)) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    d = R.daily_bars(h, R.ny_day_from_server(srv.to_numpy()))
    d["time"] = pd.to_datetime(d.day, unit="D", utc=True)
    return R.add_indicators(d, P)


def run(d: pd.DataFrame, p: dict = P) -> pd.DataFrame:
    out, i, n = [], 200, len(d)
    rows = list(d.itertuples(index=False))
    while i < n - 1:
        if not R.entry_signal(rows[i], p):
            i += 1
            continue
        j = i + 1
        entry = rows[j].open
        stop = R.stop_price(entry, p)
        k, px, why = j, None, ""
        while k < n:
            r = rows[k]
            if r.low <= stop:
                px, why = min(stop, r.open) if k > j else stop, "STOP"
                break
            reason = R.exit_signal(r, k - j, p)
            if reason and k + 1 < n:
                px, why, k = rows[k + 1].open, reason, k + 1
                break
            k += 1
        if px is None:
            break
        pts = (px - entry) - rows[j].spread - 2 * SLIP
        t_in, t_out = d.time.iat[j], d.time.iat[k]
        out.append({"t_in": t_in, "t_out": t_out, "entry": entry, "exit": px, "why": why,
                    "usd": pts * LOT + SWAP * LOT * nights(t_in, t_out)})
        i = k
    return pd.DataFrame(out)


def main() -> None:
    d = load_daily()
    tr = run(d)
    for lab, x in (("IS ", tr[tr.t_out < OOS]), ("OOS", tr[tr.t_out >= OOS]), ("ALL", tr)):
        u = x.usd
        eq = u.cumsum()
        pf = u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9)
        print(f"{lab}: n={len(u):4d} win={100 * (u > 0).mean():4.1f}% PF={pf:4.2f} net=${u.sum():+8.2f} "
              f"maxDD=${(eq.cummax().clip(lower=0) - eq).max():6.2f} pior=${u.min():+.2f}")
    print("por ano:", " ".join(f"{k}:{v:+.1f}" for k, v in tr.groupby(tr.t_out.dt.year).usd.sum().items()))
    print("saídas:", tr.groupby("why").usd.agg(["size", "sum"]).round(1).to_dict("index"))


if __name__ == "__main__":
    main()
