"""Backtest comparativo.

Uso:
  python -m backtest.run_backtest --fetch          # baixa histórico do MT5 (read-only) para data/
  python -m backtest.run_backtest                  # roda as variantes e grava reports/backtest_<data>.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest import data as bdata
from backtest.simulate import breakdown, run_portfolio
from engine.config import ROOT, load_config
from engine.regime import NewsCalendar

VARIANTS = {
    "BASE (A4 trend_filter=ON)": {},
    "A4 trend_filter=OFF": {"agents": {"A4_RSI_REVERSAL": {"trend_filter": False}}},
    "INFO: BTC com A2/A3 (scalpers)": {"symbols": {"BTCUSD": {"agents": ["A2_PULLBACK", "A3_BOS_RETEST", "A4_RSI_REVERSAL"]}}},
    "INFO: alvo Fib 1.618": {"agents": {"A2_PULLBACK": {"tp_extension": 1.618}, "A3_BOS_RETEST": {"tp_extension": 1.618}}},
}


def fmt(df: pd.DataFrame) -> str:
    cols = ["agent", "symbol", "trades", "win_rate", "payoff", "expectancy_r", "total_r", "profit_factor",
            "max_dd_r", "net_usd", "max_dd_usd"]
    d = df[cols].copy()
    d["win_rate"] = (d["win_rate"] * 100).map("{:.1f}%".format)
    for c in ("payoff", "expectancy_r", "total_r", "profit_factor", "max_dd_r", "net_usd", "max_dd_usd"):
        d[c] = d[c].map(lambda v: f"{v:.2f}")
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(str(x) for x in row) + " |" for row in d.itertuples(index=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="baixar histórico do MT5 antes")
    ap.add_argument("--only", default=None, help="rodar só a variante cujo nome contém este texto")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    cfg0 = load_config()
    symbols = list(cfg0["symbols"].keys())
    if args.fetch or not (bdata.DATA_DIR / "specs.json").exists():
        print("Baixando histórico do MT5 (somente leitura)...")
        bdata.fetch_from_mt5(symbols, bars=int(cfg0["backtest"]["bars"]), server_time=cfg0["account"]["server_time"])

    data, specs = {}, {}
    for s in symbols:
        data[s], specs[s] = bdata.load(s)
    start = max(data[s]["M5"]["time"].iloc[0] for s in symbols)
    end = min(data[s]["M5"]["time"].iloc[-1] for s in symbols)
    news_csv = ROOT / "config" / "news_events.csv"
    spread_mult = float(cfg0["backtest"].get("spread_mult", 1.0))

    out = [f"# Backtest comparativo — {datetime.now():%Y-%m-%d %H:%M}",
           f"Período M5: {start:%Y-%m-%d} → {end:%Y-%m-%d} | spread das barras x{spread_mult} | "
           f"lotes: " + ", ".join(f"{s} {cfg0['symbols'][s]['lot']}" for s in symbols),
           f"Filtro de notícias: {'config/news_events.csv' if news_csv.exists() else 'SEM dados históricos (não aplicado)'}",
           "R = resultado / risco inicial. Execução conservadora (SL antes de TP na mesma barra; MARKET na abertura seguinte).", ""]
    for name, ov in VARIANTS.items():
        if args.only and args.only.lower() not in name.lower():
            continue
        cfg = load_config(overrides=ov)
        cal = NewsCalendar(cfg["regime"]["news_keywords"], cfg["regime"]["news_window_minutes"],
                           str(news_csv) if news_csv.exists() else None)
        trades = run_portfolio(cfg, data, specs, calendar=cal, spread_mult=spread_mult)
        table = fmt(breakdown(trades))
        out += [f"## {name}", "", table, ""]
        print(f"\n## {name}\n{table}", flush=True)
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    path = rep / f"backtest_{datetime.now():%Y%m%d_%H%M}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\nRelatório: {path}")


if __name__ == "__main__":
    sys.exit(main())
