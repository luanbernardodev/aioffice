"""Loop ao vivo do motor determinístico (sem LLM).

DRY_RUN=True  -> dados/ticks reais do MT5, ordens simuladas (SimBroker) — log em logs/trades_paper.csv
DRY_RUN=False -> ordens reais na conta DEMO autorizada (MT5Broker com trava de conta)

Ciclo de ~1s: ticks -> trailing (A5) -> a cada M5 fechada: painel + A1 + agentes + A5 -> ordens.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from engine import lifecycle
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


MAX_CYCLE_ERRORS = 300   # ~5 min de falhas seguidas -> encerra (o .bat reinicia e reconecta)


def _cycle_error(where: str, exc: Exception, n: int) -> None:
    """Falha transitória do MT5 não derruba mais o processo; só após MAX_CYCLE_ERRORS seguidas."""
    if n == 1 or n % 30 == 0:
        log.warning("[LOOP] falha em %s (%d seguida(s)): %s: %s", where, n, type(exc).__name__, exc)
    if n >= MAX_CYCLE_ERRORS:
        raise RuntimeError(f"{n} falhas seguidas em {where}: {type(exc).__name__}: {exc}") from exc


def _seed_risk_from_history(mt5: Any, cfg: Dict[str, Any], engine: Engine) -> None:
    """Após restart: recupera P&L realizado do dia (UTC) e sequência de perdas do magic do motor."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    magic = int(cfg["account"]["magic"])
    # history_deals_get usa horário do servidor; margem de 1 dia e filtro posterior em UTC
    deals = mt5.history_deals_get(start - timedelta(days=1), now + timedelta(days=1)) or []
    outs = [d for d in deals if d.magic == magic and d.entry == getattr(mt5, "DEAL_ENTRY_OUT", 1)]
    entry_comment = {int(getattr(d, "position_id", 0)): str(getattr(d, "comment", "")) for d in deals
                     if d.magic == magic and d.entry == getattr(mt5, "DEAL_ENTRY_IN", 0)}
    srv = cfg["account"].get("server_time", "ny_plus_7")
    day_pnl, results = 0.0, []
    for d in sorted(outs, key=lambda x: x.time):
        pnl = float(d.profit) + float(d.swap) + float(d.commission)
        fib = "FIB_LIMIT" in entry_comment.get(int(getattr(d, "position_id", 0)), "")
        results.append((pnl, int(d.time), str(d.symbol), fib))
        if server_to_utc([int(d.time)], srv).iloc[0] >= pd.Timestamp(start):
            day_pnl += pnl
    engine.risk._roll_day(now)
    engine.risk.day_pnl = day_pnl
    engine.risk.streak = loss_streak(results)
    streak = engine.risk.streak
    log.info("[A5] Estado recuperado: P&L do dia %.2f USD | perdas seguidas %d", day_pnl, streak)
    if day_pnl <= -engine.risk.daily_stop:
        nxt = start + timedelta(days=1)
        engine.risk.paused_until, engine.risk.pause_reason = nxt, "daily_stop"
        log.warning("[A5] Stop diário já atingido hoje: pausado até %s", nxt)


def loss_streak(results: list, group_seconds: int = 60) -> int:
    """Perdas seguidas a partir do fim. results: (pnl, epoch, ativo, é_LIMIT_FIB) em ordem cronológica.
    LIMITs FIB do A2 do mesmo ativo fechadas com até `group_seconds` entre si (mesmo SL) contam como uma."""
    streak, prev = 0, None
    for pnl, t, sym, fib in reversed(results):
        if pnl >= 0:
            break
        if not (fib and prev and prev[2] and prev[1] == sym and abs(prev[0] - t) <= group_seconds):
            streak += 1
        prev = (t, sym, fib)
    return streak


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
        specs[s] = {"value_per_unit": si.trade_tick_value / si.trade_tick_size, "digits": si.digits, "point": si.point,
                    "tick_size": si.trade_tick_size, "volume_min": si.volume_min, "volume_step": si.volume_step}

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
    if not dry_run:
        _seed_risk_from_history(mt5, cfg, engine)
        broker.sync()

    # Supervisores dos EAs (GoldFlipTrail, BTCTrendFlip): não operam; controlam os EAs via JSON em MQL5/Files
    supervisors = []
    for section in ("goldflip", "btcflip", "goldnight"):
        if not cfg.get(section, {}).get("enabled"):
            continue
        from agents.goldflip_supervisor import GoldFlipSupervisor
        try:
            sup = GoldFlipSupervisor(mt5, cfg, section=section)
            sup.start()
            supervisors.append(sup)
        except Exception as exc:  # noqa: BLE001
            log.exception("[%s] supervisor não iniciou (motor segue sem ele): %s", section.upper(), exc)

    log.info("=== MOTOR DETERMINÍSTICO | conta #%s DEMO | DRY_RUN=%s | ativos=%s ===", info.login, dry_run, symbols)
    last_bar: Dict[str, int] = {}
    last_hb = 0.0
    errors = 0                                   # ciclos seguidos com falha (MT5 desconectado etc.)
    try:
        while True:
            loop_t = time.time()
            try:
                if not dry_run:
                    broker.sync()
                errors = 0
            except Exception as exc:  # noqa: BLE001
                errors += 1
                _cycle_error("sync", exc, errors)
                time.sleep(min(30.0, float(errors)))
                continue
            for s in symbols:
                tick = mt5.symbol_info_tick(s)
                if tick is None:
                    continue
                now = pd.Timestamp.now(tz="UTC")
                if dry_run:
                    broker.process_tick(s, now, tick.bid, tick.ask)
                try:
                    engine.manage(s, tick.bid, tick.ask)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[%s] falha no trailing (segue no próximo ciclo): %s: %s", s, type(exc).__name__, exc)
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
            for sup in supervisors:
                try:
                    sup.tick(datetime.now(timezone.utc))
                except Exception as exc:  # noqa: BLE001
                    log.exception("[%s] falha no ciclo do supervisor: %s", sup.tag, exc)
            if time.time() - last_hb >= 60:
                last_hb = time.time()
                blocked = engine.spread_block_summary()
                log.info("[HEARTBEAT] posições=%d pendentes=%d | dia=%.2f USD | streak=%d | %s%s",
                         len(broker.open_positions()), len(broker.pending_orders()), engine.risk.day_pnl,
                         engine.risk.streak, " | ".join(f"{k}: {v}" for k, v in engine.last_status.items())
                         + "".join(f" | {sup.summary()}" for sup in supervisors),
                         f" | bloqueadas por spread hoje: {blocked}" if blocked else "")
                lifecycle.beat()
            time.sleep(max(0.0, 1.0 - (time.time() - loop_t)))
    except KeyboardInterrupt:
        log.info("Encerrando motor...")
        lifecycle.record_exit("KeyboardInterrupt (Ctrl+C / janela fechada)")
    finally:
        if not dry_run:
            broker.cancel_all_pending()  # posições ficam protegidas por SL/TP na corretora
        mt5.shutdown()
