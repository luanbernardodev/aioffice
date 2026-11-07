"""Backtest do GoldFlipTrail (stop-and-reverse com trailing ATR) sob o gate do supervisor.

Regras (iguais ao EA mql5/Experts/GoldFlipTrail.mq5):
- SAR "virtual" sempre ativo: comprado -> stop = max(stop, maior fechamento desde a virada - k*ATR);
  vendido -> stop = min(stop, menor fechamento + k*ATR). Toque intrabar no stop -> vira de lado.
- Posição real acompanha o SAR quando permitido:
    A = todas as pernas;  B = só pernas a favor da direção de tendência do supervisor.
- Gate do supervisor (decidido no fechamento da barra): sessão Londres/NY, tendência (MA100 + inclinação),
  ATR >= min_atr, spread <= 0.15 x ATR. Lateral -> não abre. Fora de sessão -> ZERA (flatten).
- Kill switch opcional: perda do dia (realizada + flutuante) >= 3% de US$100 -> zera e para até o dia seguinte.
- Custos: spread da barra x1.5; stop executa no preço do stop (ou pior se abrir em gap).
Lote fixo 0.01 => US$1 por US$1 de movimento no ouro.

  python -m backtest.goldflip_bt
"""
from __future__ import annotations

import itertools
from typing import Dict, List

import numpy as np
import pandas as pd

from backtest.research import load_tf
from engine import indicators as ind

OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
VPU_LOT = 100.0 * 0.01      # GOLD: US$100 por 1.0 de preço por lote -> 0.01 lote


def session_mask(t: pd.Series) -> np.ndarray:
    lon = t.dt.tz_convert("Europe/London")
    ny = t.dt.tz_convert("America/New_York")
    lhm = lon.dt.hour * 60 + lon.dt.minute
    nhm = ny.dt.hour * 60 + ny.dt.minute
    wk = lon.dt.weekday < 5
    return (wk & (((lhm >= 7 * 60) & (lhm < 16 * 60 + 30)) | ((nhm >= 8 * 60) & (nhm < 17 * 60)))).to_numpy()


def gate(df: pd.DataFrame, bar_minutes: int, min_atr: float = 1.5) -> Dict[str, np.ndarray]:
    """Mesma classificação do supervisor (dist/inclinação da MA100 em ATR), no timeframe do teste."""
    ma = ind.sma(df["close"], 100)
    atr = ind.atr(df)
    k = max(1, 10 * 5 // bar_minutes)          # 10 barras M5 = 50 min
    dist = (df["close"] - ma) / atr
    slope = (ma - ma.shift(k)) / atr
    direction = np.where((dist >= 1.0) & (slope >= 0.3), 1, np.where((dist <= -1.0) & (slope <= -0.3), -1, 0))
    close_t = df["time"] + pd.Timedelta(minutes=bar_minutes)
    sess = session_mask(close_t)
    ok = sess & (atr.to_numpy() >= min_atr) & (df["spread"].to_numpy() <= 0.15 * atr.to_numpy()) & (direction != 0)
    return {"atr": atr.to_numpy(), "dir": direction, "sess": sess, "enabled": ok}


def simulate(df: pd.DataFrame, g: Dict[str, np.ndarray], k_trail: float, mode: str, kill: bool,
             kill_usd: float = 3.0) -> pd.DataFrame:
    o, h, l, c, sp = (df[x].to_numpy() for x in ("open", "high", "low", "close", "spread"))
    t = df["time"].to_numpy()
    days = df["time"].dt.tz_convert("UTC").dt.date.to_numpy()
    atr, dirn, sess, en = g["atr"], g["dir"], g["sess"], g["enabled"]
    trades: List[dict] = []
    sar, ext, stop = 0, np.nan, np.nan      # SAR virtual
    pos, entry, t_in = 0, 0.0, None         # posição real
    day, day_pnl, killed = None, 0.0, False

    def close_pos(px, ti, why):
        nonlocal pos, day_pnl
        pnl = (px - entry) * pos * VPU_LOT
        trades.append({"t_in": t_in, "t_out": ti, "side": pos, "entry": entry, "exit": px, "usd": pnl, "why": why})
        day_pnl += pnl
        pos = 0

    def allowed(i, side):
        if not en[i] or killed:
            return False
        return mode == "A" or side == dirn[i]

    start = 300
    for j in range(start, len(df)):
        i = j - 1                                   # decisão da barra anterior vale nesta
        if days[j] != day:
            day, day_pnl, killed = days[j], 0.0, False
        # inicializa SAR
        if sar == 0:
            if np.isnan(atr[i]):
                continue
            sar = 1 if c[i] >= c[i - 20] else -1
            ext = c[i]
            stop = ext - sar * k_trail * atr[i]
        # entrada a mercado na abertura (estava flat e agora é permitido)
        if pos == 0 and allowed(i, sar):
            pos, t_in = sar, t[j]
            entry = o[j] + (sp[j] if sar == 1 else 0.0)
        # toque intrabar no stop do SAR
        hit = (l[j] <= stop) if sar == 1 else (h[j] + sp[j] >= stop)
        if hit:
            px_bid = min(stop, o[j]) if sar == 1 else max(stop, o[j] + sp[j]) - sp[j]
            if pos == sar:
                close_pos(px_bid if sar == 1 else px_bid + sp[j], t[j], "STOP")
            sar = -sar
            ext = c[j]
            stop = ext - sar * k_trail * atr[i]
            if allowed(i, sar):                     # flip: nova perna no preço do stop
                pos, t_in = sar, t[j]
                entry = px_bid + (sp[j] if sar == 1 else 0.0)
        # fechamento: trailing do SAR
        if sar == 1:
            ext = max(ext, c[j])
            stop = max(stop, ext - k_trail * atr[j])
        else:
            ext = min(ext, c[j])
            stop = min(stop, ext + k_trail * atr[j])
        # kill switch (perda do dia realizada + flutuante)
        if pos != 0 and kill:
            flt = ((c[j] - entry) if pos == 1 else (entry - c[j] - sp[j])) * VPU_LOT
            if day_pnl + flt <= -kill_usd:
                close_pos(c[j] if pos == 1 else c[j] + sp[j], t[j], "KILL")
                killed = True
        elif kill and day_pnl <= -kill_usd:
            killed = True
        # fora de sessão -> zera (sem swap)
        if pos != 0 and not sess[j]:
            close_pos(c[j] if pos == 1 else c[j] + sp[j], t[j], "FLATTEN")
    return pd.DataFrame(trades)


def report(tr: pd.DataFrame, cut: pd.Timestamp = OOS_START) -> str:
    if tr.empty:
        return "sem trades"
    out = []
    tr = tr.assign(t_out=pd.to_datetime(tr.t_out, utc=True))
    for part, g in (("IS ", tr[tr.t_out < cut]), ("OOS", tr[tr.t_out >= cut])):
        if g.empty:
            out.append(f"{part}: -")
            continue
        eq = g.usd.cumsum()
        dd = (eq.cummax().clip(lower=0) - eq).max()
        pf = g.usd[g.usd > 0].sum() / max(-g.usd[g.usd < 0].sum(), 1e-9)
        out.append(f"{part}: n={len(g):5d} win={100 * (g.usd > 0).mean():5.1f}% net=${g.usd.sum():+8.1f} "
                   f"PF={pf:.2f} med/trade=${g.usd.mean():+.2f} maxDD=${dd:6.1f}")
    return " | ".join(out)


def main() -> None:
    # M5 só tem ~17 meses: corte em 2026-02-01 (~60/40); M15 (4 anos): corte em 2025-01-01
    for tf, mins, cut in (("M5", 5, pd.Timestamp("2026-02-01", tz="UTC")), ("M15", 15, OOS_START)):
        df = load_tf("GOLD", tf)
        g = gate(df, mins)
        print(f"\n===== GOLD {tf}: {df.time.iloc[0]:%Y-%m-%d} -> {df.time.iloc[-1]:%Y-%m-%d} | "
              f"barras habilitadas {100 * g['enabled'].mean():.1f}%")
        for mode, k, kill in itertools.product(("A", "B"), (1.0, 1.5, 2.0, 3.0), (False, True)):
            tr = simulate(df, g, k, mode, kill)
            print(f"  {mode} trail={k:.1f}xATR kill={'on ' if kill else 'off'} -> {report(tr, cut)}")


if __name__ == "__main__":
    main()
