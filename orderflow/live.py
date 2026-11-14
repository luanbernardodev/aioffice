"""Feed ao vivo de orderflow BTCUSDT (Binance, grátis, sem chave) + modo sombra do filtro no RSI7.

Fluxo:
  * partida: REST /api/v3/klines 1h (300 barras) -> histórico de delta pelo volume do tomador comprador
    (taker buy base volume = agressão compradora, a mesma coisa que o delta dos aggTrades). As métricas por nível
    (stacked imbalance, extremos) dessas barras ficam vazias: só barras montadas ao vivo têm footprint.
  * websocket wss://stream.binance.com:9443/ws/btcusdt@aggTrade -> footprint da hora corrente; reconexão com
    recuperação do buraco por REST (/api/v3/aggTrades?fromId=último+1).
  * fechou a hora: confere o volume com a kline oficial (diferença > 2% ou hora iniciada no meio -> incompleta:
    nenhum filtro aprova nela), calcula as métricas e grava state/orderflow_btc_h1.json (últimas 300 barras).
  * modo sombra: em cada H1 fechada da XM, calcula o sinal do RSI(7) 25/75 + SMA100 (agents/rsi7_h1_rules.py) e
    registra em logs/orderflow_shadow.csv se cada filtro deixaria entrar. NÃO envia ordem.
    Uma linha por hora com as features vai para logs/orderflow_features.csv (para comparar com o histórico).
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from engine.config import ROOT
from orderflow import filters as OF
from orderflow.metrics import bar_metrics, series_features

log = logging.getLogger("orderflow.live")

REST = "https://api.binance.com"
WS = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
SYMBOL = "BTCUSDT"
H_MS = 3_600_000
BUCKET = 10.0
STATE_FILE = ROOT / "state" / "orderflow_btc_h1.json"
SHADOW_CSV = ROOT / "logs" / "orderflow_shadow.csv"
FEATURES_CSV = ROOT / "logs" / "orderflow_features.csv"
KEEP = 300
FEAT_COLS = ["hour", "open", "high", "low", "close", "buy", "sell", "delta", "vol", "poc", "vah", "val", "stk_buy",
             "stk_sell", "low_share", "high_share", "complete"]


# ----------------------------------------------------------------- leitura (agentes e sombra)
def load_features(path: Path = STATE_FILE) -> Optional[pd.DataFrame]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = pd.DataFrame(raw.get("bars") or [])
    if rows.empty:
        return None
    m = rows[["hour", "delta", "vol", "poc", "vah", "val", "stk_buy", "stk_sell", "low_share", "high_share"]]
    f = series_features(rows[["hour", "open", "high", "low", "close"]], m)
    f["complete"] = rows["complete"].to_numpy(bool)
    return f


def allow_now(f: Optional[pd.DataFrame], hour_ms: int, side: int, name: str) -> Tuple[Optional[bool], str]:
    """(True/False, motivo) para o sinal da barra `hour_ms`; (None, motivo) se o orderflow dessa barra não está pronto."""
    if name == "none":
        return True, ""
    if f is None:
        return None, "sem arquivo de orderflow"
    hit = np.flatnonzero(f["hour"].to_numpy() == int(hour_ms))
    if not len(hit):
        return None, "barra ainda não fechada no feed"
    i = int(hit[0])
    if not bool(f["complete"].iat[i]):
        return False, "barra incompleta no feed (feed iniciado no meio da hora ou buraco de dados)"
    bull, bear = OF.masks(f, name)
    ok = bool(bull[i] if side == 1 else bear[i])
    return ok, "" if ok else f"filtro {name} contra"


# ----------------------------------------------------------------- feed
class Feed:
    def __init__(self, session: Optional[requests.Session] = None, state_file: Path = STATE_FILE) -> None:
        self.s = session or requests.Session()
        self.state_file = state_file
        self.bars: List[Dict[str, Any]] = []
        self.cur_hour: Optional[int] = None
        self.cur_complete = False
        self.levels: Dict[int, List[float]] = {}
        self.last_id: Optional[int] = None

    # REST ---------------------------------------------------------
    def klines(self, start_ms: Optional[int] = None, limit: int = KEEP) -> List[list]:
        p: Dict[str, Any] = {"symbol": SYMBOL, "interval": "1h", "limit": limit}
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        r = self.s.get(f"{REST}/api/v3/klines", params=p, timeout=15)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def kline_row(k: list) -> Dict[str, Any]:
        vol, tb = float(k[5]), float(k[9])
        return {"hour": int(k[0]), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]),
                "buy": tb, "sell": vol - tb, "delta": 2 * tb - vol, "vol": vol, "poc": np.nan, "vah": np.nan,
                "val": np.nan, "stk_buy": np.nan, "stk_sell": np.nan, "low_share": np.nan, "high_share": np.nan,
                "complete": False}

    def bootstrap(self) -> None:
        now_h = int(time.time() * 1000) // H_MS * H_MS
        ks = [k for k in self.klines() if int(k[0]) < now_h]          # só horas fechadas
        self.bars = [self.kline_row(k) for k in ks]
        log.info("[OF] histórico: %d barras H1 da Binance (até %s)", len(self.bars),
                 pd.to_datetime(self.bars[-1]["hour"], unit="ms") if self.bars else "-")

    def gap_fill(self) -> int:
        """Recupera aggTrades perdidos desde last_id (máx. 50 páginas de 1000)."""
        if self.last_id is None:
            return 0
        got = 0
        for _ in range(50):
            r = self.s.get(f"{REST}/api/v3/aggTrades", params={"symbol": SYMBOL, "fromId": self.last_id + 1,
                                                                "limit": 1000}, timeout=15)
            r.raise_for_status()
            rows = r.json()
            for t in rows:
                self.on_trade(int(t["a"]), int(t["T"]), float(t["p"]), float(t["q"]), bool(t["m"]))
            got += len(rows)
            if len(rows) < 1000:
                break
        if got:
            log.info("[OF] buraco recuperado por REST: %d aggTrades", got)
        return got

    # trades -------------------------------------------------------
    def on_trade(self, agg_id: int, t_ms: int, price: float, qty: float, buyer_maker: bool) -> None:
        if self.last_id is not None and agg_id <= self.last_id:
            return
        self.last_id = agg_id
        hour = t_ms // H_MS * H_MS
        if self.cur_hour is None:
            self.cur_hour, self.cur_complete = hour, False      # começou no meio da hora: incompleta
        elif hour > self.cur_hour:
            self.finalize()
            self.cur_hour, self.cur_complete, self.levels = hour, True, {}
        lv = int(np.floor(price / BUCKET))
        cell = self.levels.setdefault(lv, [0.0, 0.0])
        cell[1 if buyer_maker else 0] += qty

    def finalize(self) -> Dict[str, Any]:
        hour = self.cur_hour
        try:
            k = self.klines(start_ms=hour, limit=1)
            row = self.kline_row(k[0]) if k and int(k[0][0]) == hour else None
        except Exception as exc:  # noqa: BLE001
            log.warning("[OF] kline da hora %s indisponível (%s)", hour, exc)
            row = None
        lv = np.array(sorted(self.levels), dtype=np.int64)
        buy = np.array([self.levels[x][0] for x in lv]) if len(lv) else np.zeros(0)
        sell = np.array([self.levels[x][1] for x in lv]) if len(lv) else np.zeros(0)
        stream_vol = float(buy.sum() + sell.sum())
        if row is None:
            row = {"hour": hour, "open": np.nan, "high": np.nan, "low": np.nan, "close": np.nan, "buy": float(buy.sum()),
                   "sell": float(sell.sum()), "delta": float(buy.sum() - sell.sum()), "vol": stream_vol}
        ok = self.cur_complete and row["vol"] > 0 and abs(stream_vol - row["vol"]) / row["vol"] <= 0.02 and len(lv)
        if len(lv):
            m = bar_metrics(lv, buy, sell, BUCKET)
            row.update({k: m[k] for k in ("poc", "vah", "val", "stk_buy", "stk_sell", "low_share", "high_share")})
        row["complete"] = bool(ok and np.isfinite(row["close"]))
        self.bars = [b for b in self.bars if b["hour"] != hour] + [row]
        self.bars = self.bars[-KEEP:]
        self.write()
        log.info("[OF] H1 %s fechada | delta %+.2f | vol stream %.1f / kline %.1f | completa=%s",
                 pd.to_datetime(hour, unit="ms"), row["delta"], stream_vol, row["vol"], row["complete"])
        return row

    def write(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        clean = [{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in b.items()} for b in self.bars]
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updated_at": int(time.time()), "bucket": BUCKET, "bars": clean}), encoding="utf-8")
        os.replace(tmp, self.state_file)

    # websocket ----------------------------------------------------
    async def run_ws(self) -> None:
        import websockets
        backoff = 1
        while True:
            try:
                async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_queue=10000) as ws:
                    log.info("[OF] websocket conectado")
                    backoff = 1
                    await asyncio.get_running_loop().run_in_executor(None, self.gap_fill)
                    async for msg in ws:
                        t = json.loads(msg)
                        self.on_trade(int(t["a"]), int(t["T"]), float(t["p"]), float(t["q"]), bool(t["m"]))
            except Exception as exc:  # noqa: BLE001
                log.warning("[OF] websocket caiu (%s); reconectando em %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


# ----------------------------------------------------------------- modo sombra
SHADOW_FIELDS = ["hora_utc", "lado", "xm_close", "atr", "orderflow_pronto", "completa"] + \
                [f"f_{n}" for n in OF.FILTERS if n != "none"] + ["delta", "dz", "poc_xm", "vah_xm", "val_xm", "offset"]


class Shadow:
    """Avalia o RSI(7) 25/75 + SMA100 na H1 fechada da XM e registra o que cada filtro decidiria. Somente leitura."""

    P = {"rsi_period": 7, "rsi_level": 25, "ma_type": "sma", "ma_period": 100, "atr_period": 14}

    def __init__(self, mt5: Any, server_time: str = "ny_plus_7", state_file: Path = STATE_FILE,
                 shadow_csv: Path = SHADOW_CSV, features_csv: Path = FEATURES_CSV) -> None:
        self.mt5, self.server_time = mt5, server_time
        self.state_file, self.shadow_csv, self.features_csv = state_file, shadow_csv, features_csv
        self.done_hour = 0

    def _xm(self) -> Optional[pd.DataFrame]:
        from agents import rsi7_h1_rules as R
        from engine.features import server_to_utc
        r = self.mt5.copy_rates_from_pos("BTCUSD", self.mt5.TIMEFRAME_H1, 1, 400)
        if r is None or len(r) < 150:
            return None
        df = pd.DataFrame(r)
        utc = server_to_utc(df["time"].astype("int64").to_numpy(), self.server_time)
        df["hour"] = ((pd.to_datetime(utc, utc=True) - pd.Timestamp("1970-01-01", tz="UTC"))
                      // pd.Timedelta(milliseconds=1)).astype("int64").to_numpy()
        return R.add_indicators(df, self.P)

    @staticmethod
    def _append(path: Path, fields: List[str], row: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    def step(self) -> Optional[Dict[str, Any]]:
        from agents import rsi7_h1_rules as R
        x = self._xm()
        if x is None:
            return None
        hour = int(x["hour"].iat[-1])
        if hour <= self.done_hour:
            return None
        f = load_features(self.state_file)
        ready = f is not None and hour in set(f["hour"].tolist())
        age_s = time.time() - (hour + H_MS) / 1000
        if not ready and age_s < 600:                           # espera o feed fechar a mesma hora (até 10 min)
            return None
        self.done_hour = hour
        if ready:
            i = int(np.flatnonzero(f["hour"].to_numpy() == hour)[0])
            fr = f.iloc[i]
            xm_close = float(x["close"].iat[-1])
            self._append(self.features_csv, ["hora_utc"] + FEAT_COLS + ["dz", "xm_close"],
                         {"hora_utc": str(pd.to_datetime(hour, unit="ms")), **{c: fr.get(c) for c in FEAT_COLS},
                          "dz": fr.get("dz"), "xm_close": xm_close})
        side = R.signal(float(x["rsi"].iat[-2]), float(x["rsi"].iat[-1]), float(x["close"].iat[-1]),
                        float(x["ma"].iat[-1]), self.P["rsi_level"])
        if side == 0:
            return None
        row: Dict[str, Any] = {"hora_utc": str(pd.to_datetime(hour, unit="ms")), "lado": "COMPRA" if side == 1 else "VENDA",
                               "xm_close": float(x["close"].iat[-1]), "atr": float(x["atr"].iat[-1]),
                               "orderflow_pronto": ready}
        if ready:
            offset = row["xm_close"] - float(fr["close"])
            row.update({"completa": bool(fr["complete"]), "delta": fr["delta"], "dz": fr["dz"], "offset": offset,
                        "poc_xm": fr["poc"] + offset, "vah_xm": fr["vah"] + offset, "val_xm": fr["val"] + offset})
            for n in OF.FILTERS:
                if n != "none":
                    ok, _ = allow_now(f, hour, side, n)
                    row[f"f_{n}"] = int(bool(ok))
        self._append(self.shadow_csv, SHADOW_FIELDS, row)
        log.info("[SOMBRA] RSI7 %s em %s | orderflow pronto=%s | conf_w1=%s", row["lado"], row["hora_utc"], ready,
                 row.get("f_conf_w1"))
        return row
