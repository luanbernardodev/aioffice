"""Fase 1 — motor estendido sobre o engine.py original (backtest/claude_code/engine.py).

Reaproveita os indicadores do engine.py e a mesma lógica do `bt` (1 posição, sinal no fechamento da barra i,
entrada no open i+1, preços BID com spread real, stop móvel ATR a partir do extremo, atualizado no fechamento
e só apertando). Acrescenta:
  * breakeven em be_r * R (0 = desligado);
  * slippage (preço) na entrada e nas saídas a mercado/stop (TP é limite: sem slippage);
  * swap por rollover do servidor XM (ler de mt5.symbol_info; ver swap_per_roll);
  * multiplicador de spread (teste de estresse);
  * métricas agregadas dentro do numba (IS/OOS/3 janelas walk-forward), para rodar milhões de combinações.

Com be_r=0, slip=0, swap=0 e spread_mult=1 o resultado é idêntico ao `bt` original (tests/test_fase1_engine2.py).
Unidades: pnl em pontos de preço por 1 unidade de contrato. US$ = pnl * contract_size * lote.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit, prange

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

_spec = importlib.util.spec_from_file_location("cc_engine", HERE.parent / "engine.py")
cc = sys.modules.get("cc_engine")
if cc is None:
    cc = importlib.util.module_from_spec(_spec)
    sys.modules["cc_engine"] = cc     # o cache do numba reimporta o módulo pelo nome
    _spec.loader.exec_module(cc)          # indicadores e bt originais (o load() do engine.py não é usado)

ema, sma, rsi, atr, hh, ll, adx, bt_original = cc.ema, cc.sma, cc.rsi, cc.atr, cc.hh, cc.ll, cc.adx, cc.bt

SPLIT = pd.Timestamp("2026-07-01", tz="UTC")                      # IS: 11/2025-06/2026 | OOS: 07/2026-11/2026
WF = [(pd.Timestamp("2026-03-01", tz="UTC"), pd.Timestamp("2026-06-01", tz="UTC")),   # walk-forward ancorado:
      (pd.Timestamp("2026-06-01", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")),   # treino = início..teste
      (pd.Timestamp("2026-09-01", tz="UTC"), pd.Timestamp("2026-12-01", tz="UTC"))]

# índices das métricas devolvidas por grid()
M_N, M_NET, M_GP, M_GL, M_NIS, M_GPIS, M_GLIS, M_NOOS, M_GPOOS, M_GLOOS, M_MAXW, M_DD = range(12)
M_WF0 = 12            # 12..20: (n, gp, gl) para cada uma das 3 janelas
NM = 21


# ----------------------------------------------------------------------------------------- dados e custos
def load_bars(minutes: int) -> pd.DataFrame:
    """Barras BID (UTC) a partir dos ticks reais do MT5 (data/ticks/BTCUSD.npz) com spread médio da barra."""
    sys.path.insert(0, str(ROOT))
    from backtest import ticks
    tk = ticks.load("BTCUSD")
    return ticks.bars(tk, minutes)[["time", "open", "high", "low", "close", "spread"]].reset_index(drop=True)


def symbol_costs() -> dict:
    """Swap e contract size reais da XM (mt5.symbol_info); cai para o último valor salvo se o MT5 não abrir."""
    cache = HERE / "btcusd_symbol_info.json"
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError(mt5.last_error())
        si = mt5.symbol_info("BTCUSD")
        d = {k: (float(getattr(si, k)) if isinstance(getattr(si, k), float) else int(getattr(si, k)))
             for k in ("point", "digits", "trade_contract_size", "swap_mode", "swap_long", "swap_short",
                       "swap_rollover3days", "volume_min", "trade_tick_value", "trade_tick_size")}
        d["source"] = "mt5.symbol_info"
        d["read_at"] = pd.Timestamp.now(tz="UTC").isoformat()
        mt5.shutdown()
        cache.write_text(json.dumps(d, indent=2))
        return d
    except Exception:      # noqa: BLE001 — sem terminal: usa o cache gravado na última leitura real
        d = json.loads(cache.read_text())
        d["source"] = "cache " + d.get("read_at", "")
        return d


def swap_per_roll(si: dict) -> tuple[float, float, float, float]:
    """(fixo_long, fixo_short, pct_long, pct_short) por rollover, em preço por 1 unidade de contrato.

    swap_mode 1 = pontos; 2/3/4 = dinheiro por lote; 5/6 = juros anuais (% do preço, base 360)."""
    m, sl, ss, cs = int(si["swap_mode"]), float(si["swap_long"]), float(si["swap_short"]), float(si["trade_contract_size"])
    if m == 1:
        return sl * si["point"], ss * si["point"], 0.0, 0.0
    if m in (2, 3, 4):
        return sl / cs, ss / cs, 0.0, 0.0
    if m in (5, 6):
        return 0.0, 0.0, sl / 100 / 360, ss / 100 / 360
    return 0.0, 0.0, 0.0, 0.0


def rollovers(times: pd.Series, triple_dow: int) -> np.ndarray:
    """Contagem acumulada de rollovers (meia-noite do servidor XM = America/New_York + 7h) no início de cada barra.

    triple_dow segue ENUM_DAY_OF_WEEK do MQL5 (0=domingo..6=sábado); 7 = sem dia triplo (valor atual do BTCUSD)."""
    srv = times.dt.tz_convert("America/New_York").dt.tz_localize(None) + pd.Timedelta(hours=7)
    day = srv.dt.normalize()
    days = ((day - day.iloc[0]).dt.days).to_numpy().astype(np.float64)
    if 0 <= triple_dow <= 6:
        # o rollover que ocorre no início do dia D cobra 3x se D-1 for o dia triplo
        full = pd.date_range(day.iloc[0], day.iloc[-1], freq="D")
        w = np.where(((full - pd.Timedelta(days=1)).dayofweek + 1) % 7 == triple_dow, 3.0, 1.0)
        w[0] = 0.0
        cum = np.cumsum(w)
        days = cum[days.astype(np.int64)]
    return days


def window_idx(times: pd.Series) -> tuple[int, np.ndarray]:
    tv = times.values
    split = int(np.searchsorted(tv, SPLIT.to_datetime64()))
    wf = np.array([[np.searchsorted(tv, a.to_datetime64()), np.searchsorted(tv, b.to_datetime64())] for a, b in WF],
                  dtype=np.int64)
    return split, wf


# ----------------------------------------------------------------------------------------- núcleo
@njit(cache=True)
def _run(o, h, l, c, sp, a, sig, sl_k, trail_k, act_k, tp_k, be_r, max_bars, slip, roll, swl, sws, swpl, swps,
         out_pnl, out_ent, out_ex, out_side):
    """Uma simulação. Preenche out_* e devolve o número de trades. Mesma sequência de decisões do bt original."""
    n = len(c)
    k = 0
    pos = 0
    ep = 0.0
    st = 0.0
    tp = 0.0
    ext = 0.0
    risk = 0.0
    ib = 0
    for i in range(1, n):
        if pos != 0:
            s = sp[i]
            exitp = 0.0
            done = False
            if pos == 1:
                if o[i] <= st:
                    exitp = o[i] - slip; done = True
                elif l[i] <= st:
                    exitp = st - slip; done = True
                elif tp > 0 and h[i] >= tp:
                    exitp = tp; done = True
            else:
                if o[i] + s >= st:
                    exitp = o[i] + s + slip; done = True
                elif h[i] + s >= st:
                    exitp = st + slip; done = True
                elif tp > 0 and l[i] + s <= tp:
                    exitp = tp; done = True
            if not done and max_bars > 0 and i - ib >= max_bars:
                exitp = (c[i] - slip) if pos == 1 else (c[i] + s + slip)
                done = True
            if done:
                nroll = roll[i] - roll[ib]
                sw = nroll * ((swl + swpl * ep) if pos == 1 else (sws + swps * ep))
                out_pnl[k] = (exitp - ep) * pos + sw
                out_ent[k] = ib
                out_ex[k] = i
                out_side[k] = pos
                k += 1
                pos = 0
            else:
                if pos == 1:
                    ext = max(ext, h[i])
                    if be_r > 0 and ext - ep >= be_r * risk and ep > st:
                        st = ep
                    if ext - ep >= act_k * risk:
                        ns = ext - trail_k * a[i]
                        if ns > st:
                            st = ns
                else:
                    ext = min(ext, l[i] + s)
                    if be_r > 0 and ep - ext >= be_r * risk and ep < st:
                        st = ep
                    if ep - ext >= act_k * risk:
                        ns = ext + trail_k * a[i]
                        if ns < st:
                            st = ns
        if pos == 0 and i < n - 1 and sig[i] != 0 and a[i] > 0:
            pos = sig[i]
            ib = i + 1
            risk = sl_k * a[i]
            if pos == 1:
                ep = o[i + 1] + sp[i + 1] + slip
                st = ep - risk
                tp = ep + tp_k * a[i] if tp_k > 0 else 0.0
                ext = ep
            else:
                ep = o[i + 1] - slip
                st = ep + risk
                tp = ep - tp_k * a[i] if tp_k > 0 else 0.0
                ext = ep
    return k


def bt2(o, h, l, c, sp, a, sig, sl_k, trail_k, act_k, tp_k, be_r=0.0, max_bars=0, slip=0.0, roll=None,
        swap=(0.0, 0.0, 0.0, 0.0)):
    """Versão de uma simulação com lista de trades (para relatório, testes e agente)."""
    n = len(c)
    roll = np.zeros(n) if roll is None else roll
    P, Ei, Xi, Sd = np.zeros(n), np.zeros(n, np.int64), np.zeros(n, np.int64), np.zeros(n)
    k = _run(o, h, l, c, sp, a, np.asarray(sig, np.int64), float(sl_k), float(trail_k), float(act_k), float(tp_k),
             float(be_r), int(max_bars), float(slip), roll, *map(float, swap), P, Ei, Xi, Sd)
    return P[:k], Ei[:k], Xi[:k], Sd[:k]


@njit(cache=True, parallel=True)
def grid(o, h, l, c, sp, a, sigs, exits, split, wf, slip, roll, swl, sws, swpl, swps):
    """sigs: (S, n) int64; exits: (E, 6) = sl, trail, act, tp, be, max_bars. Devolve (S, E, NM) float32."""
    S = sigs.shape[0]
    E = exits.shape[0]
    n = len(c)
    res = np.zeros((S, E, 21), np.float32)
    for job in prange(S * E):
        si = job // E
        ei = job % E
        P = np.empty(n)
        En = np.empty(n, np.int64)
        Xn = np.empty(n, np.int64)
        Sd = np.empty(n)
        k = _run(o, h, l, c, sp, a, sigs[si], exits[ei, 0], exits[ei, 1], exits[ei, 2], exits[ei, 3], exits[ei, 4],
                 int(exits[ei, 5]), slip, roll, swl, sws, swpl, swps, P, En, Xn, Sd)
        m = np.zeros(21)
        eq = 0.0
        peak = 0.0
        dd = 0.0
        for t in range(k):
            p = P[t]
            e = En[t]
            m[0] += 1
            m[1] += p
            if p > 0:
                m[2] += p
            else:
                m[3] -= p
            if e < split:
                m[4] += 1
                if p > 0:
                    m[5] += p
                else:
                    m[6] -= p
            else:
                m[7] += 1
                if p > 0:
                    m[8] += p
                else:
                    m[9] -= p
            if p > m[10]:
                m[10] = p
            eq += p
            if eq > peak:
                peak = eq
            if peak - eq > dd:
                dd = peak - eq
            for w in range(3):
                if e >= wf[w, 0] and e < wf[w, 1]:
                    m[12 + 3 * w] += 1
                    if p > 0:
                        m[13 + 3 * w] += p
                    else:
                        m[14 + 3 * w] -= p
        m[11] = dd
        for j in range(21):
            res[si, ei, j] = m[j]
    return res


def pf(gp, gl):
    gp, gl = np.asarray(gp, float), np.asarray(gl, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(gl > 0, gp / np.where(gl > 0, gl, 1), np.where(gp > 0, 99.0, 0.0))
