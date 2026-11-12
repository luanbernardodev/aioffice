"""Regras puras do agente US500_RSI2_D1 (Connors RSI(2) diário, somente compra). Mesmo código no backtest
(backtest/agentes_v2/us500_classic.py) e ao vivo.

Dia = data de Nova York da barra H1 (servidor XM = NY + 7h, então a data NY independe do horário de verão).
  Entrada: no fechamento do dia, close > SMA(200) e RSI(2) < 10 -> compra na abertura do dia seguinte.
  Saída:   no fechamento de um dia, close > SMA(5) ou 10 dias desde o dia da entrada -> vende na abertura seguinte.
  Stop:    3% abaixo do preço de entrada, registrado na corretora.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from engine import indicators as ind

NY_OFFSET_S = 7 * 3600      # relógio do servidor XM - relógio de Nova York


def ny_day_from_server(server_epoch: np.ndarray) -> np.ndarray:
    """Data de NY (dias desde 1970) de cada barra, a partir do `time` do MT5 (relógio do servidor)."""
    return (np.asarray(server_epoch, dtype=np.int64) - NY_OFFSET_S) // 86400


def daily_bars(h1: pd.DataFrame, day: np.ndarray) -> pd.DataFrame:
    """Agrega H1 em barras diárias por `day` (rótulo inteiro do dia NY). Mantém a ordem cronológica."""
    d = h1.assign(_day=day).groupby("_day", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        spread=("spread", "median"))
    return d.reset_index().rename(columns={"_day": "day"})


def add_indicators(d: pd.DataFrame, p: dict) -> pd.DataFrame:
    d = d.copy()
    d["rsi"] = ind.rsi(d["close"], int(p.get("rsi_period", 2)))
    d["sma_trend"] = d["close"].rolling(int(p.get("trend_sma", 200))).mean()
    d["sma_exit"] = d["close"].rolling(int(p.get("exit_sma", 5))).mean()
    return d


def entry_signal(row, p: dict) -> bool:
    vals = (row.rsi, row.close, row.sma_trend)
    if any(v is None or np.isnan(v) for v in vals):
        return False
    return row.close > row.sma_trend and row.rsi < float(p.get("rsi_threshold", 10))


def exit_signal(row, days_since_entry: int, p: dict) -> Optional[str]:
    """Motivo de saída no fechamento do dia (ou None). days_since_entry = dias completos após o dia da entrada."""
    if not np.isnan(row.sma_exit) and row.close > row.sma_exit:
        return f"CLOSE>SMA{int(p.get('exit_sma', 5))}"
    if days_since_entry >= int(p.get("max_days", 10)):
        return f"{int(p.get('max_days', 10))}_DIAS"
    return None


def stop_price(entry: float, p: dict) -> float:
    return entry * (1.0 - float(p.get("stop_pct", 3.0)) / 100.0)
