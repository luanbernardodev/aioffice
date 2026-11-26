"""Atualização incremental dos dados de backtest (somente leitura no MT5 e na Binance).

  ticks GOLD / BTCUSD   data/ticks/<SYM>.npz  += mt5.copy_ticks_range desde o último tick (servidor -> UTC)
  barras M5/M15/H1      data/<SYM>_<TF>.csv   += mt5.copy_rates_range (junta e remove duplicatas; nunca encolhe)
  orderflow BTCUSDT     data/orderflow/*.pkl  += aggTrades diários da Binance a partir do dia seguinte ao último
  caches                data/v3/*.pkl e backtest/orderflow/features_BTCUSDT_H1.pkl apagados (recalculados no uso)

Nada aqui envia ordens: só copy_* e symbol_info do MT5.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest import data as bdata
from engine.features import server_to_utc

log = logging.getLogger("semanal.dados")
TICK_DIR = bdata.DATA_DIR / "ticks"
TICK_SYMBOLS = ("GOLD", "BTCUSD")
BAR_SYMBOLS = ("GOLD", "BTCUSD", "US500Cash")


# ------------------------------------------------------------------ utilidades puras (testadas)
def srv_ms_to_utc(srv_ms: np.ndarray) -> np.ndarray:
    """Epoch em ms no relógio do servidor XM -> epoch em ms UTC (mesma regra de backtest.ticks.convert)."""
    srv_ms = np.asarray(srv_ms, dtype=np.int64)
    if len(srv_ms) == 0:
        return srv_ms
    hrs = srv_ms // 3_600_000
    uh = np.unique(hrs)
    utc_h = server_to_utc(uh * 3600).dt.tz_convert(None).to_numpy().astype("datetime64[s]").astype(np.int64) // 3600
    off = dict(zip(uh.tolist(), ((utc_h - uh) * 3_600_000).tolist()))
    return srv_ms + pd.Series(hrs).map(off).to_numpy(np.int64)


def append_ticks(old: Dict[str, np.ndarray], t: np.ndarray, bid: np.ndarray, ask: np.ndarray) -> Dict[str, np.ndarray]:
    """Junta ticks novos (UTC ms, preço em float) aos antigos (centavos), só os posteriores ao último tick antigo."""
    last = int(old["t"][-1]) if len(old["t"]) else -1
    keep = t > last
    if not keep.any():
        return old
    bid_c = np.round(np.asarray(bid)[keep] * 100).astype(np.int32)
    ask_c = np.round(np.asarray(ask)[keep] * 100).astype(np.int32)
    return {"t": np.concatenate([old["t"], np.asarray(t, dtype=np.int64)[keep]]),
            "bid": np.concatenate([old["bid"], bid_c]), "ask": np.concatenate([old["ask"], ask_c])}


def merge_bars(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Barras antigas + novas por 'time' (a nova vence na sobreposição); nunca perde histórico."""
    out = pd.concat([old, new], ignore_index=True)
    out["time"] = pd.to_datetime(out["time"], utc=True)
    return out.drop_duplicates("time", keep="last").sort_values("time", ignore_index=True)


def merge_footprint(old_bars: pd.DataFrame, old_fp: pd.DataFrame, new_bars: pd.DataFrame,
                    new_fp: pd.DataFrame) -> tuple:
    bars = pd.concat([old_bars, new_bars], ignore_index=True).drop_duplicates("hour", keep="last")
    fp = pd.concat([old_fp, new_fp], ignore_index=True)
    fp = fp.groupby(["hour", "lvl"], as_index=False)[["buy", "sell"]].sum()       # mesma hora em 2 arquivos: soma
    return bars.sort_values("hour", ignore_index=True), fp.sort_values(["hour", "lvl"], ignore_index=True)


def days_to_fetch(last_hour_ms: int, today: date) -> List[date]:
    """Dias completos (UTC) depois do último dia já processado, até ontem (a Binance publica com ~1 dia de atraso)."""
    d = (datetime.fromtimestamp(last_hour_ms / 1000, tz=timezone.utc) + timedelta(hours=1)).date()
    out = []
    while d < today:
        out.append(d)
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ MT5
def update_ticks(mt5: Any, sym: str, now: datetime) -> Dict[str, Any]:
    path = TICK_DIR / f"{sym}.npz"
    if not path.exists():
        return {"simbolo": sym, "erro": f"{path} não existe (copie data/ticks do PC uma vez)"}
    z = np.load(path)
    tk = {"t": z["t"], "bid": z["bid"], "ask": z["ask"]}
    z.close()
    before = len(tk["t"])
    start_utc = datetime.fromtimestamp(int(tk["t"][-1]) / 1000, tz=timezone.utc)
    cur = start_utc - timedelta(hours=4)                   # folga para o fuso do servidor; duplicatas são cortadas
    while cur < now:
        nxt = min(cur + timedelta(days=1), now)
        r = mt5.copy_ticks_range(sym, cur, nxt, mt5.COPY_TICKS_ALL)
        if r is not None and len(r):
            df = pd.DataFrame(r)[["time_msc", "bid", "ask"]]
            df[["bid", "ask"]] = df[["bid", "ask"]].replace(0.0, np.nan).ffill()
            df = df.dropna()
            tk = append_ticks(tk, srv_ms_to_utc(df["time_msc"].to_numpy()), df["bid"].to_numpy(), df["ask"].to_numpy())
        cur = nxt
    added = len(tk["t"]) - before
    if added:
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez(tmp, **tk)
        os.replace(tmp, path)
    return {"simbolo": sym, "ticks_novos": added,
            "ate_utc": pd.to_datetime(int(tk["t"][-1]), unit="ms", utc=True).strftime("%Y-%m-%d %H:%M")}


def update_bars(mt5: Any, sym: str, now: datetime) -> Dict[str, Any]:
    info = mt5.symbol_info(sym)
    if info is None:
        return {"simbolo": sym, "erro": "símbolo não encontrado no MT5"}
    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    out = {"simbolo": sym}
    for tf in bdata.TFS:
        path = bdata.DATA_DIR / f"{sym}_{tf}.csv"
        if not path.exists():
            out[tf] = "sem CSV base"
            continue
        old = pd.read_csv(path)
        last = pd.to_datetime(old["time"].iloc[-1], utc=True).to_pydatetime()
        r = mt5.copy_rates_range(sym, tf_map[tf], last - timedelta(days=2), now)
        if r is None or len(r) == 0:
            out[tf] = 0
            continue
        df = pd.DataFrame(r)
        df["time"] = server_to_utc(df["time"].to_numpy()).to_numpy()
        df["spread"] = df["spread"] * info.point
        df = df[["time", "open", "high", "low", "close", "spread"]].iloc[:-1]       # sem a barra em formação
        merged = merge_bars(old, df)
        merged.to_csv(path, index=False)
        out[tf] = len(merged) - len(old)
    return out


# ------------------------------------------------------------------ Binance
def update_orderflow(today: date) -> Dict[str, Any]:
    from orderflow import footprint as FP
    from orderflow.binance_data import daily_url, download
    bars_p, fp_p = FP.OUT_DIR / "BTCUSDT_bars_H1.pkl", FP.OUT_DIR / "BTCUSDT_fp_H1_b10.pkl"
    if not bars_p.exists() or not fp_p.exists():
        return {"erro": "data/orderflow sem footprint base (copie do PC uma vez)"}
    old_b, old_f = pd.read_pickle(bars_p), pd.read_pickle(fp_p)
    days = days_to_fetch(int(old_b["hour"].iloc[-1]), today)
    if not days:
        return {"dias_novos": 0}
    files, falhas = [], []
    for d in days:
        try:
            files.append(download(daily_url("BTCUSDT", d)))
        except Exception as exc:  # noqa: BLE001
            falhas.append(f"{d}: {exc}")
            break                                            # dias seguintes dependem deste (sem buraco no CVD)
    if files:
        nb, nf = FP.aggregate(files, 10.0)
        b, f = merge_footprint(old_b, old_f, nb, nf)
        b.to_pickle(bars_p)
        f.to_pickle(fp_p)
        for p in files:                                      # o footprint já guarda o necessário
            p.unlink(missing_ok=True)
    return {"dias_novos": len(files), "falhas": falhas,
            "ate": str(days[len(files) - 1]) if files else None}


def clear_caches() -> int:
    from engine.config import ROOT
    n = 0
    for p in list((ROOT / "data" / "v3").glob("*.pkl")) + [ROOT / "backtest" / "orderflow" / "features_BTCUSDT_H1.pkl"]:
        if p.exists():
            p.unlink()
            n += 1
    return n


def atualizar(mt5: Any, now: datetime | None = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    res: Dict[str, Any] = {"ticks": [], "barras": []}
    for sym in TICK_SYMBOLS:
        try:
            res["ticks"].append(update_ticks(mt5, sym, now))
        except Exception as exc:  # noqa: BLE001
            log.exception("ticks %s", sym)
            res["ticks"].append({"simbolo": sym, "erro": str(exc)})
    for sym in BAR_SYMBOLS:
        try:
            res["barras"].append(update_bars(mt5, sym, now))
        except Exception as exc:  # noqa: BLE001
            log.exception("barras %s", sym)
            res["barras"].append({"simbolo": sym, "erro": str(exc)})
    try:
        res["orderflow"] = update_orderflow(now.date())
    except Exception as exc:  # noqa: BLE001
        log.exception("orderflow")
        res["orderflow"] = {"erro": str(exc)}
    res["caches_apagados"] = clear_caches()
    try:                                                     # features de orderflow (lidas pelos of_btc no backtest)
        from backtest.orderflow.bt_rsi7_orderflow import dataset
        d = dataset()
        res["orderflow_features_ate"] = str(pd.to_datetime(int(d.loc[d.has_of, "hour"].max()), unit="ms", utc=True))
    except Exception as exc:  # noqa: BLE001
        log.exception("features de orderflow")
        res["orderflow_features_erro"] = str(exc)
    return res
