"""US100 RSI(2) Connors H1 — núcleo da validação (dados do MT5, sinal, simulação com swap e acerto real).

Reaproveita o bt2 original de backtest/claude_code/us100/grid_wr.py (long-only, saída por sinal no open seguinte,
trailing com ativação em ATR da barra do sinal). `bt3` é a mesma lógica devolvendo também o índice de saída;
tests/test_us100_rsi2.py confere que bt3 == bt2 trade a trade.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
US100 = HERE.parent / "us100"
DATA_CSV = HERE / "US100Cash_H1_mt5.csv"
SYMBOL_JSON = HERE / "us100cash_symbol_info.json"
H1_START = pd.Timestamp("2016-09-01", tz="UTC")      # antes disso o "H1" do MT5 são barras diárias
SLIP = 0.5                                            # pts por lado (mesmo valor do grid_nq.py)
SPREAD_FLOOR_PTS = 250                                # spread zerado no histórico antigo -> 2.5 pts


def _load_reference_modules():
    """Importa grid_wr/grid_nq/engine da pasta us100 (o 'engine' de lá, não o pacote engine/ do projeto)."""
    if "grid_wr" in sys.modules:
        return sys.modules["grid_wr"]
    saved = sys.modules.pop("engine", None)
    sys.path.insert(0, str(US100))
    try:
        import grid_wr  # noqa: F401
    finally:
        sys.path.remove(str(US100))
        sys.modules["us100_engine"] = sys.modules.pop("engine")
        if saved is not None:
            sys.modules["engine"] = saved
    return sys.modules["grid_wr"]


gw = _load_reference_modules()
gn = sys.modules["grid_nq"]
E = sys.modules["us100_engine"]
rsi, sma, atr, bt2_original = E.rsi, E.sma, E.atr, gw.bt2


# ----------------------------------------------------------------------------------------- dados
def server_to_utc(epoch: np.ndarray) -> pd.DatetimeIndex:
    """Relógio do servidor XM = America/New_York + 7h."""
    ny = pd.to_datetime(epoch, unit="s") - pd.Timedelta(hours=7)
    return ny.tz_localize("America/New_York", ambiguous=False, nonexistent="shift_forward").tz_convert("UTC")


def export_mt5(n: int = 99999) -> pd.DataFrame:
    """Exporta o máximo de H1 do terminal (pos 1 = só barras fechadas) e grava o symbol_info."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(mt5.last_error())
    mt5.symbol_select("US100Cash", True)
    r = mt5.copy_rates_from_pos("US100Cash", mt5.TIMEFRAME_H1, 1, n)
    si = mt5.symbol_info("US100Cash")
    info = {k: getattr(si, k) for k in ("point", "digits", "trade_contract_size", "trade_tick_value", "trade_tick_size",
                                         "swap_mode", "swap_long", "swap_short", "swap_rollover3days", "volume_min",
                                         "volume_step", "spread", "currency_profit")}
    info["read_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    mt5.shutdown()
    SYMBOL_JSON.write_text(json.dumps(info, indent=2, default=str))
    d = pd.DataFrame(r)
    d["dt"] = pd.to_datetime(d.time, unit="s")
    d.to_csv(DATA_CSV, index=False)
    return d


def symbol_info() -> dict:
    return json.loads(SYMBOL_JSON.read_text())


def load_h1(start: pd.Timestamp = H1_START, spread_mult: float = 1.0) -> pd.DataFrame:
    d = pd.read_csv(DATA_CSV)
    b = pd.DataFrame({"open": d.open, "high": d.high, "low": d.low, "close": d.close,
                      "spread": d.spread.where(d.spread > 0, SPREAD_FLOOR_PTS), "srv": d.time})
    b.index = server_to_utc(d.time.to_numpy())
    b.index.name = "time"
    b = b[b.index >= start]
    b["sp"] = (b.spread / 100 + 2 * SLIP) * spread_mult            # mesmo custo do grid_nq.load
    return b


# ----------------------------------------------------------------------------------------- estratégia
REF = {"rsi_n": 2, "rsi_th": 5.0, "ma_n": 100, "exit_rsi_n": 5, "exit_rsi": 60.0, "exit_mode": "rsi",
       "sl": 3.0, "tp": 0.0, "be": 0.0, "act": 1.5, "trail": 1.5}


def entry_signal(c: np.ndarray, p: dict, block: np.ndarray | None = None) -> np.ndarray:
    s = ((rsi(c, p["rsi_n"]) < p["rsi_th"]) & (c > sma(c, p["ma_n"]))).astype(np.int64)
    s[:200] = 0
    if block is not None:
        s[block] = 0
    return s


def exit_signal(c: np.ndarray, p: dict) -> np.ndarray:
    if p["exit_mode"] == "sma5":
        return c > sma(c, 5)
    return rsi(c, p["exit_rsi_n"]) > p["exit_rsi"]


def entry_block_utc(idx: pd.DatetimeIndex) -> np.ndarray:
    """Guarda do agente: sem entradas 20:55-21:10 UTC. A entrada é no open da barra seguinte; bloqueia o sinal
    cuja barra seguinte abre às 21:00 UTC."""
    nxt = idx + pd.Timedelta(hours=1)
    return np.asarray((nxt.hour == 21) & (nxt.minute == 0))


@njit(cache=True)
def bt3(o, h, l, c, sp, a, sig, xs, sl_k, tp_k, be_k, act_k, tr_k):
    """= grid_wr.bt2, devolvendo (pnl, entrada, saída)."""
    n = len(c); pnl = np.zeros(n); ent = np.full(n, -1); exi = np.full(n, -1)
    k = 0; pos = 0; ep = 0.; st = 0.; tp = 0.; mx = 0.; a0 = 0.; ib = 0; xnext = False
    for i in range(1, n):
        if pos == 1:
            ex = 0.; done = False
            if xnext: ex = o[i]; done = True
            elif o[i] <= st: ex = o[i]; done = True
            elif l[i] <= st: ex = st; done = True
            elif tp > 0 and h[i] >= tp: ex = tp; done = True
            if done:
                pnl[k] = ex - ep; ent[k] = ib; exi[k] = i; k += 1; pos = 0; xnext = False
            else:
                mx = max(mx, h[i])
                if be_k > 0 and mx - ep >= be_k*a0 and st < ep + sp[i]: st = ep + sp[i]
                if act_k > 0 and mx - ep >= act_k*a0:
                    ns = mx - tr_k*a[i]
                    if ns > st: st = ns
                xnext = xs[i]
        if pos == 0 and i < n-1 and sig[i] == 1 and a[i] > 0:
            pos = 1; ib = i+1; a0 = a[i]; ep = o[i+1] + sp[i+1]
            st = ep - sl_k*a0; tp = ep + tp_k*a0 if tp_k > 0 else 0.; mx = ep; xnext = False
    return pnl[:k], ent[:k], exi[:k]


def rollover_count(b: pd.DataFrame, triple_dow: int) -> np.ndarray:
    """Rollovers acumulados (meia-noite do servidor) no início de cada barra; triplo no dia triple_dow
    (ENUM_DAY_OF_WEEK do MQL5: 0=domingo..6=sábado)."""
    day = pd.to_datetime(b["srv"].to_numpy(), unit="s").normalize()
    full = pd.date_range(day[0], day[-1], freq="D")
    w = np.where(((full - pd.Timedelta(days=1)).dayofweek + 1) % 7 == triple_dow, 3.0, 1.0)
    w[0] = 0.0
    cum = np.cumsum(w)
    return cum[(day - day[0]).days.to_numpy()]


def simulate(b: pd.DataFrame, p: dict, si: dict, block: np.ndarray | None = None) -> pd.DataFrame:
    """Trades em pontos de preço por 1 unidade de contrato, com swap, ATR do sinal e flag de ganho real."""
    o, h, l, c, sp = (b[k].to_numpy(np.float64) for k in ("open", "high", "low", "close", "sp"))
    A = atr(h, l, c, 14)
    pnl, ei, xi = bt3(o, h, l, c, sp, A, entry_signal(c, p, block), exit_signal(c, p),
                      p["sl"], p["tp"], p["be"], p["act"], p["trail"])
    roll = rollover_count(b, int(si["swap_rollover3days"]))
    swap_pts = swap_per_roll_pts(si)
    t = pd.DataFrame({"ent": b.index[ei], "exit": b.index[xi], "pnl_px": pnl, "a0": A[ei - 1],
                      "rolls": roll[xi] - roll[ei]})
    t["swap_px"] = t.rolls * swap_pts
    t["pnl"] = t.pnl_px + t.swap_px
    t["real_win"] = t.pnl > 0.1 * t.a0          # ganho real: > 0.1 x ATR (zerado no BE não conta)
    return t


def swap_per_roll_pts(si: dict) -> float:
    """Swap de compra por rollover em pontos de preço por 1 unidade de contrato."""
    m, s, cs = int(si["swap_mode"]), float(si["swap_long"]), float(si["trade_contract_size"])
    if m == 1:
        return s * float(si["point"])
    if m in (2, 3, 4):                       # dinheiro por lote
        return s / cs
    raise ValueError(f"swap_mode {m} não tratado")


def usd(pts: float | np.ndarray, si: dict, lot: float | None = None):
    lot = float(si["volume_min"]) if lot is None else lot
    return pts * float(si["trade_tick_value"]) / float(si["trade_tick_size"]) * lot


def stats(t: pd.DataFrame) -> dict:
    p = t.pnl.to_numpy()
    if len(p) == 0:
        return {"n": 0, "wr_real": float("nan"), "wr_bruto": float("nan"), "pf": float("nan"), "net": 0.0, "dd": 0.0,
                "pior": 0.0}
    gl = -p[p < 0].sum()
    eq = np.cumsum(p)
    return {"n": len(p), "wr_real": float(t.real_win.mean()), "wr_bruto": float((p > 0).mean()),
            "pf": float(p[p > 0].sum() / gl) if gl > 0 else 99.0, "net": float(p.sum()),
            "dd": float((np.maximum.accumulate(np.maximum(eq, 0)) - eq).max()), "pior": float(p.min())}
