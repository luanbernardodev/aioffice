"""Histórico do MT5 (somente leitura) com cache em data/. Converte horário do servidor -> UTC."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from engine.config import ROOT
from engine.features import server_to_utc

DATA_DIR = ROOT / "data"
TFS = ("M5", "M15", "H1")


def fetch_from_mt5(symbols, bars: int = 20000, server_time: str = "ny_plus_7") -> None:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize falhou: {mt5.last_error()}")
    try:
        DATA_DIR.mkdir(exist_ok=True)
        tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
        specs = {}
        for s in symbols:
            info = mt5.symbol_info(s)
            if info is None:
                raise RuntimeError(f"símbolo {s} não encontrado")
            mt5.symbol_select(s, True)
            specs[s] = {"point": info.point, "tick_size": info.trade_tick_size, "tick_value": info.trade_tick_value,
                        "value_per_unit": info.trade_tick_value / info.trade_tick_size,
                        "volume_min": info.volume_min, "volume_step": info.volume_step, "digits": info.digits}
            for tf in TFS:
                r = mt5.copy_rates_from_pos(s, tf_map[tf], 1, bars)  # pos 1: sem a barra em formação
                if r is None or len(r) == 0:
                    raise RuntimeError(f"sem dados {s} {tf}: {mt5.last_error()}")
                df = pd.DataFrame(r)
                df["time"] = server_to_utc(df["time"].to_numpy(), server_time).to_numpy()
                df["spread"] = df["spread"] * info.point
                df[["time", "open", "high", "low", "close", "spread"]].to_csv(DATA_DIR / f"{s}_{tf}.csv", index=False)
        (DATA_DIR / "specs.json").write_text(json.dumps(specs, indent=2))
    finally:
        mt5.shutdown()


def load(symbol: str) -> Tuple[Dict[str, pd.DataFrame], Dict[str, float]]:
    out = {}
    for tf in TFS:
        df = pd.read_csv(DATA_DIR / f"{symbol}_{tf}.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True)
        out[tf] = df
    specs = json.loads((DATA_DIR / "specs.json").read_text())
    return out, specs[symbol]
