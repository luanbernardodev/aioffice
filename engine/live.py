"""Loop ao vivo do motor determinístico (sem LLM).

DRY_RUN=True  -> dados/ticks reais do MT5, ordens simuladas (SimBroker) — log em logs/trades_paper.csv
DRY_RUN=False -> ordens reais na conta DEMO autorizada (MT5Broker com trava de conta)

Ciclo de ~1s: ticks -> trailing (A5) -> a cada M5 fechada: painel + A1 + agentes + A5 -> ordens.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from engine.config import ROOT
from engine.core import Engine
from engine.features import build_features, server_to_utc
from engine.mt5_broker import MT5Broker, verify_account
from engine.regime import NewsCalendar
from engine.sim_broker import SimBroker
from engine.trade_log import TradeLogger

log = logging.getLogger("engine.live")

FETCH = {"M5": 600, "M15": 400, "H1": 300}


def _connect(mt5: Any) -> None:
    """Anexa ao terminal aberto; se houver credenciais DEMO no ambiente, usa-as (nunca são impressas)."""
    login, pwd, srv = os.getenv("MT5_LOGIN_DEMO"), os.getenv("MT5_PASSWORD_DEMO"), os.getenv("MT5_SERVER_DEMO")
    ok = mt5.initialize(login=int(login), password=pwd, server=srv) if (login and pwd and srv) else mt5.initialize()
    if not ok:
        raise RuntimeError(f"MT5 initialize falhou: {mt5.last_error()}")


def _rates(mt5: Any, symbol: str, tf: str, n: int, server_time: str) -> pd.DataFrame:
    tfc = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}[tf]
    r = mt5.copy_rates_from_pos(symbol, tfc, 1, n)  # pos 1 = só barras fechadas
    if r is None or len(r) == 0:
        raise RuntimeError(f"sem barras {symbol} {tf}")
    df = pd.DataFrame(r)
    df["time"] = server_to_utc(df["time"].to_numpy(), server_time).to_numpy()
    return df


def run(cfg: Dict[str, Any], dry_run: bool) -> None:
    import MetaTrader5 as mt5
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    _connect(mt5)
    info = verify_account(mt5, cfg)  # mesmo em DRY_RUN só roda conectado na DEMO autorizada
    server_time = cfg["account"].get("server_time", "ny_plus_7")
    symbols = [s for s, sc in cfg["symbols"].items() if sc.get("enabled", True)]
    specs = {}
    for s in symbols:
        si = mt5.symbol_info(s)
        if si is None or not mt5.symbol_select(s, True):
            raise RuntimeError(f"símbolo indisponível: {s}")
        lot = float(cfg["symbols"][s]["lot"])
        if lot < si.volume_min:
            raise RuntimeError(f"{s}: lote {lot} < volume_min {si.volume_min}")
        specs[s] = {"value_per_unit": si.trade_tick_value / si.trade_tick_size, "digits": si.digits, "point": si.point}

    broker = SimBroker(specs, immediate_market=True) if dry_run else MT5Broker(mt5, cfg, specs)
    trades_csv = cfg["logging"]["trades_csv"]
    if dry_run:
        trades_csv = str(Path(trades_csv).with_name("trades_paper.csv"))
    tlog = TradeLogger(str(ROOT / trades_csv), supabase_sink=bool(cfg["logging"].get("supabase_sink")),
                       account_label="PAPER" if dry_run else "DEMO")
    calendar = NewsCalendar(cfg["regime"]["news_keywords"], cfg["regime"]["news_window_minutes"],
                            str(ROOT / "config" / "news_events.csv"))
    calendar.start_background_refresh()
    engine = Engine(cfg, broker, calendar=calendar, trade_logger=tlog, verbose=True)

    log.info("=== MOTOR DETERMINÍSTICO | conta #%s DEMO | DRY_RUN=%s | ativos=%s ===", info.login, dry_run, symbols)
    last_bar: Dict[str, int] = {}
    last_hb = 0.0
    try:
        while True:
            loop_t = time.time()
            if not dry_run:
                broker.sync()
            for s in symbols:
                tick = mt5.symbol_info_tick(s)
                if tick is None:
                    continue
                now = pd.Timestamp.now(tz="UTC")
                if dry_run:
                    broker.process_tick(s, now, tick.bid, tick.ask)
                engine.manage(s, tick.bid, tick.ask)
                head = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 1, 1)
                if head is None or len(head) == 0:
                    continue
                bar_t = int(head[0]["time"])
                if last_bar.get(s) == bar_t:
                    continue
                last_bar[s] = bar_t
                try:
                    m5 = _rates(mt5, s, "M5", FETCH["M5"], server_time)
                    m15 = _rates(mt5, s, "M15", FETCH["M15"], server_time)
                    h1 = _rates(mt5, s, "H1", FETCH["H1"], server_time)
                    for df in (m5, m15, h1):
                        df["spread"] = df["spread"] * specs[s]["point"]
                    feats = build_features(m5, m15, h1, cfg)
                    i = len(feats["m5"]) - 1
                    engine.on_bar(s, feats, i, now, spread=max(tick.ask - tick.bid, 0.0), quote=(tick.bid, tick.ask))
                except Exception as exc:  # noqa: BLE001
                    log.exception("[%s] falha no ciclo de barra: %s", s, exc)
            if time.time() - last_hb >= 60:
                last_hb = time.time()
                log.info("[HEARTBEAT] posições=%d pendentes=%d | dia=%.2f USD | streak=%d | %s",
                         len(broker.open_positions()), len(broker.pending_orders()), engine.risk.day_pnl,
                         engine.risk.streak, " | ".join(f"{k}: {v}" for k, v in engine.last_status.items()))
            time.sleep(max(0.0, 1.0 - (time.time() - loop_t)))
    except KeyboardInterrupt:
        log.info("Encerrando motor...")
    finally:
        if not dry_run:
            broker.cancel_all_pending()  # posições ficam protegidas por SL/TP na corretora
        mt5.shutdown()
