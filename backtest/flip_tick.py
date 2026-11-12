"""Backtest TICK A TICK dos EAs GoldFlipTrail / GoldNightFlip (mesma lógica do .mq5, preços reais bid/ask).

Diferenças em relação ao backtest em barras (backtest/goldflip_bt.py):
- stop executa no primeiro tick que o toca (bid p/ comprado, ask p/ vendido), com o spread daquele instante;
- ATR do EA = iATR do MT5 (média simples de 14 TR); ATR do supervisor = Wilder (engine.indicators.atr);
- regime do supervisor com a confirmação do M1 (fechamento M1 do lado da MA100 M1), como ao vivo;
- filtro de spread com o spread ao vivo do tick de entrada (não o mínimo da barra);
- proteção de lucro por tick (opcional) sem ambiguidade otimista/pessimista.
Lote 0.01 => US$1 por US$1 de movimento.

  python -m backtest.flip_tick            # validação contra os trades reais + grade de parâmetros
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backtest import ticks as T
from engine import indicators as ind

SESS = [("Europe/London", 7 * 60, 16 * 60 + 30), ("America/New_York", 8 * 60, 17 * 60)]


def in_session(t: pd.Series) -> np.ndarray:
    ok = np.zeros(len(t), dtype=bool)
    for tz, a, b in SESS:
        loc = t.dt.tz_convert(tz)
        hm = (loc.dt.hour * 60 + loc.dt.minute).to_numpy()
        ok |= (loc.dt.weekday.to_numpy() < 5) & (hm >= a) & (hm < b)
    return ok


def night_window(t: pd.Series) -> np.ndarray:
    return ~in_session(t) & (t.dt.tz_convert("America/New_York").dt.weekday.to_numpy() < 5)


@dataclass
class Cfg:
    name: str = "goldnight"
    window: str = "night"            # "night" | "day"
    trail: float = 3.0               # k x ATR (EA)
    mode: str = "B"                  # A = todas as pernas, B = só a favor da direção do supervisor
    min_atr: float = 1.5
    max_spread_atr: float = 0.15
    trend_dist: float = 1.0
    trend_slope: float = 0.3
    m1_confirm: bool = True
    lateral: bool = False            # True = também habilita no regime lateral
    protect_at: float = 0.0          # >0: ao ganhar protect_at x ATR, stop -> entrada+spread, depois trailing por tick
    protect_trail: float = 1.0       # distância do trailing da proteção (x ATR)
    max_risk_usd: float = 0.0        # >0: não abre se a distância do stop (US$ com 0.01) passar disso
    reentry: str = "flip"            # flip = vira na hora (EA atual) | bar = só na abertura da barra seguinte
                                     # episode = 1 entrada por episódio de tendência (direção do supervisor)
    extra: Dict = field(default_factory=dict)


def prepare(tk: Dict[str, np.ndarray]) -> Dict[str, object]:
    b5 = T.bars(tk, 5)
    b1 = T.bars(tk, 1)
    tr = pd.concat([b5.high - b5.low, (b5.high - b5.close.shift()).abs(), (b5.low - b5.close.shift()).abs()], axis=1).max(axis=1)
    b5["atr_ea"] = tr.rolling(14).mean()                       # iATR do MT5
    b5["atr_sup"] = ind.atr(b5, 14)                              # supervisor (Wilder)
    b5["ma100"] = ind.sma(b5.close, 100)
    b1["ma100"] = ind.sma(b1.close, 100)
    # M1 fechado mais recente antes da abertura de cada barra M5
    idx = np.searchsorted(b1.time.to_numpy(), b5.time.to_numpy(), side="left") - 1
    b5["m1_close"] = b1.close.to_numpy()[np.clip(idx, 0, None)]
    b5["m1_ma"] = b1.ma100.to_numpy()[np.clip(idx, 0, None)]
    b5.loc[idx < 0, ["m1_close", "m1_ma"]] = np.nan
    return {"tk": tk, "b5": b5, "night": night_window(b5.time), "day": in_session(b5.time)}


def control(P: Dict[str, object], c: Cfg) -> Dict[str, np.ndarray]:
    """Controle do supervisor válido DURANTE a barra j (decidido com as barras fechadas até j-1)."""
    b = P["b5"]
    a = b.atr_sup
    dist = (b.close - b.ma100) / a
    slope = (b.ma100 - b.ma100.shift(10)) / a
    up = (dist >= c.trend_dist) & (slope >= c.trend_slope)
    dn = (dist <= -c.trend_dist) & (slope <= -c.trend_slope)
    if c.m1_confirm:
        up &= b.m1_close.shift(-1) > b.m1_ma.shift(-1)          # M1 visto na abertura da barra seguinte
        dn &= b.m1_close.shift(-1) < b.m1_ma.shift(-1)
    direction = np.where(up, 1, np.where(dn, -1, 0))
    win = P[c.window]
    sh = lambda x: np.r_[np.zeros(1, dtype=np.asarray(x).dtype), np.asarray(x)[:-1]]   # decisão de j-1 vale em j
    enabled = (direction != 0) | c.lateral
    enabled = enabled & (a.to_numpy() >= c.min_atr)
    return {"enabled": sh(enabled) & win, "flatten": ~win, "dir": sh(direction),
            "max_spread": sh(np.floor(c.max_spread_atr * a.fillna(0).to_numpy() / 0.01 + 1e-9) * 0.01)}


def simulate(P: Dict[str, object], c: Cfg, t0: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    tk, b = P["tk"], P["b5"]
    t, bid, ask = tk["t"], tk["bid"], tk["ask"]
    ctl = control(P, c)
    en, fl, dirn, msp = ctl["enabled"], ctl["flatten"], ctl["dir"], ctl["max_spread"]
    atr_ea, close = b.atr_ea.to_numpy(), b.close.to_numpy()
    i0s, i1s = b.i0.to_numpy(), b.i1.to_numpy()
    lows, ahigh = b.low.to_numpy(), b.ask_high.to_numpy()
    k = c.trail
    start = 0 if t0 is None else int(np.searchsorted(b.time.to_numpy(), t0.to_datetime64()))
    start = max(start, 120)
    trades: List[dict] = []
    sar, ext, stop = 0, 0.0, 0.0
    pos, entry, ti, why_in, risk0, a_in = 0, 0.0, 0, "", 0.0, 0.0
    best, p_on, p_stop, blocked = 0.0, False, 0.0, False
    ep_used, ep_key = False, None

    def can_open(j, i, side, stp):
        if not en[j] or fl[j] or blocked:
            return False
        if c.reentry == "episode" and ep_used:
            return False
        if ask[i] - bid[i] > msp[j] + 1e-9 or not (atr_ea[j - 1] >= c.min_atr):
            return False
        if c.mode == "B" and side != dirn[j]:
            return False
        if (side == 1 and stp >= bid[i]) or (side == -1 and stp <= ask[i]):
            return False
        px = ask[i] if side == 1 else bid[i]
        if c.max_risk_usd > 0 and abs(px - stp) > c.max_risk_usd:
            return False
        return True

    def open_(j, i, side, why):
        nonlocal pos, entry, ti, why_in, risk0, a_in, best, p_on, ep_used
        ep_used = True
        pos, ti, why_in, a_in = side, i, why, atr_ea[j - 1]
        entry = ask[i] if side == 1 else bid[i]
        risk0, best, p_on = abs(entry - stop), entry, False

    def close_(i, why):
        nonlocal pos
        px = bid[i] if pos == 1 else ask[i]
        lo_i, hi_i = ti, i + 1
        adverse = (entry - bid[lo_i:hi_i].min()) if pos == 1 else (ask[lo_i:hi_i].max() - entry)
        favor = (bid[lo_i:hi_i].max() - entry) if pos == 1 else (entry - ask[lo_i:hi_i].min())
        trades.append({"t_in": t[ti], "t_out": t[i], "side": pos, "entry": entry, "exit": px,
                       "usd": (px - entry) * pos, "why_in": why_in, "why": why, "risk0": risk0,
                       "atr": a_in, "mae": adverse, "mfe": favor})
        pos = 0

    for j in range(start, len(b)):
        i0, i1 = int(i0s[j]), int(i1s[j])
        atr1, c1 = atr_ea[j - 1], close[j - 1]
        if not np.isfinite(atr1) or atr1 <= 0:
            continue
        key = int(dirn[j]) if (en[j] and not fl[j]) else 0
        if key != ep_key:                                        # novo episódio (direção mudou ou desligou)
            ep_key, ep_used = key, False
        # ---- nova barra: zera se fora da janela (OnTimer), arrasta o SAR, entra se permitido
        if pos != 0 and fl[j]:
            close_(i0, "FLATTEN")
        if sar == 0:
            sar = 1 if c1 >= close[j - 21] else -1
            ext, stop = c1, c1 - sar * k * atr1
        elif sar == 1:
            ext = max(ext, c1)
            stop = max(stop, ext - k * atr1)
        else:
            ext = min(ext, c1)
            stop = min(stop, ext + k * atr1)
        if pos == 0 and can_open(j, i0, sar, stop):
            open_(j, i0, sar, "ENTRY")
        # ---- dentro da barra: toques no stop (SAR e proteção)
        i = i0
        while i < i1:
            need_scan = (lows[j] <= stop) if sar == 1 else (ahigh[j] >= stop)
            if c.protect_at > 0 and pos != 0:
                need_scan = True
            if not need_scan:
                break
            seg_b, seg_a = bid[i:i1], ask[i:i1]
            eff = np.full(i1 - i, stop)
            prot = c.protect_at > 0 and pos != 0                 # pos != 0 implica pos == sar
            if prot:
                s = pos
                fav = seg_b if s == 1 else -seg_a                # preço favorável "para cima"
                bst = np.maximum.accumulate(np.maximum(fav, best * s))
                act = p_on | (bst - entry * s >= c.protect_at * a_in)
                lock = (entry + (seg_a - seg_b)) * s             # entrada + spread do momento
                ps = np.where(act, np.maximum(lock, bst - c.protect_trail * a_in), -np.inf)
                if p_on:
                    ps = np.maximum(ps, p_stop * s)
                ps = np.maximum.accumulate(ps)
                # stop modificado num tick só vale a partir do tick seguinte
                in_force = np.r_[p_stop * s if p_on else -np.inf, ps[:-1]]
                eff = s * np.maximum(stop * s, in_force)
            hit = (seg_b <= eff) if sar == 1 else (seg_a >= eff)
            hits = np.flatnonzero(hit)
            if len(hits) == 0:
                if prot:
                    best = bst[-1] * pos
                    if act[-1]:
                        p_on, p_stop = True, ps[-1] * pos
                break
            h = i + int(hits[0])
            sar_hit = (bid[h] <= stop) if sar == 1 else (ask[h] >= stop)
            if not sar_hit:                                      # saiu pela proteção de lucro
                close_(h, "LOCK")
                blocked = True                                   # espera a virada do SAR
                i = h + 1
                continue
            if pos == sar:
                close_(h, "STOP")
            sar = -sar
            ext = ask[h] if sar == 1 else bid[h]
            stop = ext - sar * k * atr1
            blocked = False
            if c.reentry == "flip" and can_open(j, h, sar, stop):
                open_(j, h, sar, "FLIP")
            i = h + 1
    df = pd.DataFrame(trades)
    if not df.empty:
        df["t_in"] = pd.to_datetime(df.t_in, unit="ms", utc=True)
        df["t_out"] = pd.to_datetime(df.t_out, unit="ms", utc=True)
    return df


def stats(tr: pd.DataFrame) -> str:
    if tr.empty:
        return "sem trades"
    u = tr.usd
    eq = u.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    pf = u[u > 0].sum() / max(-u[u < 0].sum(), 1e-9)
    top = u.sum() - u.max()
    return (f"n={len(u):4d} win={100 * (u > 0).mean():4.1f}% net=${u.sum():+7.1f} PF={pf:4.2f} "
            f"med=${u.mean():+5.2f} sem_maior=${top:+7.1f} maxDD=${dd:5.1f} risco0 med=${tr.risk0.median():4.1f}")


def by_month(tr: pd.DataFrame) -> str:
    m = tr.groupby(tr.t_out.dt.strftime("%m")).usd.sum()
    return " ".join(f"{k}:{v:+.0f}" for k, v in m.items())


GOLDNIGHT = Cfg()
GOLDFLIP = Cfg(name="goldflip", window="day", trail=1.5)


def main() -> None:
    import sys
    P = prepare(T.load("GOLD"))
    b = P["b5"]
    print(f"GOLD ticks: {b.time.iloc[0]:%Y-%m-%d} -> {b.time.iloc[-1]:%Y-%m-%d %H:%M} UTC | {b.n.sum():,} ticks | "
          f"spread médio noite={b.spread[P['night']].mean():.3f} dia={b.spread[P['day']].mean():.3f}")
    if "--validate" in sys.argv:
        t0 = pd.Timestamp("2026-11-08", tz="UTC")
        for c in (GOLDNIGHT, GOLDFLIP):
            tr = simulate(P, c)
            print(f"\n{c.name} (simulado, a partir de {t0:%Y-%m-%d}):")
            print(tr[tr.t_in >= t0][["t_in", "t_out", "side", "entry", "exit", "usd", "why_in", "why", "risk0", "atr"]]
                  .round(2).to_string())
        return
    cut = pd.Timestamp("2026-06-01", tz="UTC")
    for base in (GOLDNIGHT, GOLDFLIP):
        tr = simulate(P, base)
        print(f"\n===== {base.name} (config ao vivo) {stats(tr)}")
        print(f"  IS  <{cut:%Y-%m-%d}: {stats(tr[tr.t_out < cut])}")
        print(f"  OOS >={cut:%Y-%m-%d}: {stats(tr[tr.t_out >= cut])}")
        print(f"  por mês: {by_month(tr)}")


if __name__ == "__main__":
    main()
