"""Backtest de portfólio: mesmo Engine/estratégias/risco do ao vivo, sobre SimBroker por barras M5.

Todos os ativos andam juntos no tempo (limites globais de exposição e stop diário valem entre ativos).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from engine.core import Engine
from engine.features import build_features
from engine.regime import NewsCalendar
from engine.sim_broker import SimBroker
from engine.types import ClosedTrade


def run_portfolio(cfg: Dict[str, Any], data: Dict[str, Dict[str, pd.DataFrame]], specs: Dict[str, Dict[str, float]],
                  calendar: Optional[NewsCalendar] = None, spread_mult: float = 1.0,
                  warmup_bars: int = 300) -> List[ClosedTrade]:
    symbols = [s for s in data if cfg["symbols"].get(s, {}).get("enabled", True)]
    feats, arrays, idx_by_time = {}, {}, {}
    for s in symbols:
        m5 = data[s]["M5"].copy()
        m5["spread"] = m5["spread"] * spread_mult
        f = build_features(m5, data[s]["M15"], data[s]["H1"], cfg)
        feats[s] = f
        d5 = f["m5"]
        arrays[s] = {c: d5[c].to_numpy() for c in ("open", "high", "low", "close", "spread")}
        arrays[s]["time"] = d5["time"].tolist()
        arrays[s]["close_time"] = d5["close_time"].tolist()
        idx_by_time[s] = {t: k for k, t in enumerate(arrays[s]["close_time"]) if k >= warmup_bars}

    broker = SimBroker({s: specs[s] for s in symbols})
    engine = Engine(cfg, broker, calendar=calendar)
    timeline = sorted(set().union(*[set(idx_by_time[s].keys()) for s in symbols]))
    for t in timeline:
        for s in symbols:
            k = idx_by_time[s].get(t)
            if k is None:
                continue
            a = arrays[s]
            broker.process_bar(s, a["time"][k], a["close_time"][k], a["open"][k], a["high"][k], a["low"][k],
                               a["close"][k], a["spread"][k])
            bid = a["close"][k]
            engine.last_atr[s] = float(feats[s]["m5"]["atr"].iat[k])
            engine.manage(s, bid, bid + a["spread"][k])
            engine.on_bar(s, feats[s], k, t, a["spread"][k])
    return engine.closed


def metrics(trades: List[ClosedTrade]) -> Dict[str, float]:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0, "payoff": 0.0,
                "expectancy_r": 0.0, "total_r": 0.0, "profit_factor": 0.0, "max_dd_r": 0.0,
                "net_usd": 0.0, "max_dd_usd": 0.0}
    r = np.array([t.r for t in trades])
    usd = np.array([t.pnl_usd for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    eq_r = np.cumsum(r)
    eq_u = np.cumsum(usd)
    dd_r = (np.maximum.accumulate(np.concatenate([[0], eq_r]))[1:] - eq_r).max()
    dd_u = (np.maximum.accumulate(np.concatenate([[0], eq_u]))[1:] - eq_u).max()
    avg_w = wins.mean() if len(wins) else 0.0
    avg_l = losses.mean() if len(losses) else 0.0
    gross_l = -losses.sum()
    return {
        "trades": int(len(r)), "win_rate": float(len(wins) / len(r)), "avg_win_r": float(avg_w),
        "avg_loss_r": float(avg_l), "payoff": float(avg_w / abs(avg_l)) if avg_l else float("inf"),
        "expectancy_r": float(r.mean()), "total_r": float(r.sum()),
        "profit_factor": float(wins.sum() / gross_l) if gross_l > 0 else float("inf"),
        "max_dd_r": float(dd_r), "net_usd": float(usd.sum()), "max_dd_usd": float(dd_u),
    }


def breakdown(trades: List[ClosedTrade]) -> pd.DataFrame:
    rows = []
    groups: Dict[tuple, List[ClosedTrade]] = {}
    for t in trades:
        groups.setdefault((t.agent, t.symbol), []).append(t)
    for (agent, sym), ts in sorted(groups.items()):
        rows.append({"agent": agent, "symbol": sym, **metrics(ts)})
    rows.append({"agent": "PORTFOLIO", "symbol": "ALL", **metrics(trades)})
    return pd.DataFrame(rows)
