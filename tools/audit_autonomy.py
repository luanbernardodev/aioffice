"""Auditoria de autonomia. NÃO envia ordem: só leitura e mt5.order_check.

  python -m tools.audit_autonomy

Grava em reports/audit_autonomy_<máquina>_<data>.txt. Não imprime credenciais.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

from agents.capitulation import CapitulationAgent
from agents.sweep48 import Sweep48Agent
from engine import indicators as ind
from engine.config import ROOT, load_config
from engine.mt5_broker import MT5Broker
from engine.types import BUY, SELL, OrderIntent

LINES: List[str] = []
SYMBOLS = ["BTCUSD", "GOLD", "US500Cash"]
TRADE_MODE = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}


def out(s: str = "") -> None:
    print(s, flush=True)
    LINES.append(s)


class CheckOnly:
    """Proxy do MT5: qualquer order_send vira order_check. É o que garante que a auditoria não opera."""

    def __init__(self, mt5: Any, sink: Callable[[Dict[str, Any], Any], None]) -> None:
        self._m, self._sink = mt5, sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self._m, name)

    def order_send(self, req: Dict[str, Any]) -> Any:
        res = self._m.order_check(req)
        self._sink(req, res)
        return res


def show_check(agent: str, path: str, req: Dict[str, Any], res: Any, mt5: Any) -> None:
    keep = {k: req.get(k) for k in ("symbol", "type", "volume", "price", "sl", "tp", "magic", "type_filling")}
    if res is None:
        out(f"  {agent:26s} | retcode=None | last_error={mt5.last_error()} | {path} | {keep}")
    else:
        out(f"  {agent:26s} | retcode={res.retcode} {res.comment!r} margem={res.margin:.2f} | {path} | {keep}")


def atr_m5(mt5: Any, symbol: str) -> float:
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 500)
    return float(ind.atr(pd.DataFrame(r), 14).iloc[-1])


def intent(agent: str, sym: str, side: int, kind: str, price: float, a: float) -> OrderIntent:
    return OrderIntent(f"{agent}|{sym}|audit|{kind}", agent, sym, side, kind, price, price - side * 2 * a,
                       price + side * 4 * a, "AUDIT", "audit", tp1=price + side * 3 * a, atr=a, spread=0.0)


def section_checks(mt5: Any, cfg: Dict[str, Any]) -> None:
    out("\n[d] order_check (sem envio; retcode 0 = aprovada; 10018 = mercado fechado)")
    for s in SYMBOLS:
        mt5.symbol_select(s, True)
    specs = {s: {"digits": mt5.symbol_info(s).digits} for s in SYMBOLS}
    current = {"agent": ""}
    proxy = CheckOnly(mt5, lambda rq, rs: show_check(current["agent"], "MT5Broker._send -> mt5.order_send", rq, rs, mt5))
    broker = MT5Broker(proxy, cfg, specs)
    broker._save_state = lambda: None
    sym = "US500Cash"
    t, a = mt5.symbol_info_tick(sym), atr_m5(mt5, sym)
    lot = float(cfg["symbols"][sym]["lot"])
    for agent, side, kind, price in (("A2_PULLBACK US500 LIMIT", BUY, "LIMIT", t.bid - 2 * a),
                                     ("A2_PULLBACK US500 MARKET", BUY, "MARKET", t.ask),
                                     ("A3_BOS_RETEST US500 LIMIT", SELL, "LIMIT", t.ask + 2 * a)):
        current["agent"] = agent
        broker.place(intent(agent[:2] + "_AUDIT", sym, side, kind, price, a), lot, pd.Timestamp.now(tz="UTC"))
    t, a = mt5.symbol_info_tick("BTCUSD"), atr_m5(mt5, "BTCUSD")
    current["agent"] = "A4_RSI_REVERSAL BTC MARKET"
    broker.place(intent("A4_AUDIT", "BTCUSD", BUY, "MARKET", t.ask, a), float(cfg["symbols"]["BTCUSD"]["lot"]),
                 pd.Timestamp.now(tz="UTC"))

    ag = Sweep48Agent(mt5, cfg)                        # sem start(): não toca em estado nem posição
    si = mt5.symbol_info("BTCUSD")
    ag.point, ag.digits, ag.filling_mode = float(si.point), int(si.digits), int(si.filling_mode)
    req = ag.build_entry(BUY, a, t)
    show_check("SWEEP48 BTC MARKET", "Sweep48Agent.build_entry -> mt5.order_send", req, mt5.order_check(req), mt5)

    cap = CapitulationAgent(mt5, cfg)                  # sem start(): não toca em estado nem posição
    cap.digits, cap.filling_mode = int(si.digits), int(si.filling_mode)
    rq = cap.build_buy(float(t.ask), round(float(t.ask) - 2 * a, int(si.digits)))
    show_check("CAPITULATION BTC MARKET", "CapitulationAgent.build_buy -> mt5.order_send", rq, mt5.order_check(rq), mt5)

    def equivalent(name: str, symbol: str, magic: int, volume: float, path: str) -> None:
        tk, atr = mt5.symbol_info_tick(symbol), atr_m5(mt5, symbol)
        rq = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "type": mt5.ORDER_TYPE_BUY,
              "price": tk.ask, "sl": round(tk.ask - 2 * atr, mt5.symbol_info(symbol).digits), "tp": 0.0, "deviation": 30,
              "magic": magic, "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        show_check(name, path, rq, mt5.order_check(rq), mt5)

    equivalent("GoldFlipTrail GOLD", "GOLD", int(cfg["goldflip"]["magic"]), 0.01, "EQUIVALENTE (no EA: CTrade -> OrderSend)")
    equivalent("BTCTrendFlip BTC", "BTCUSD", int(cfg["btcflip"]["magic"]), 0.01, "EQUIVALENTE (no EA: CTrade -> OrderSend)")
    equivalent("legado ops_* BTC", "BTCUSD", 777777, 0.01, "EQUIVALENTE (MT5Bridge.execute_order; main.py)")


PROCESS_QUERY = r'''
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'run_engine|run_sweep48|run_capitulation|start_engine|start_sweep48|start_capitulation|main\.py|terminal64' } |
  ForEach-Object {
    $c = $_.CommandLine -replace '(?i)(--?pass\w*[= ]+)\S+', '$1***'
    '  ' + $_.ProcessId + ' ' + $c.Substring(0, [Math]::Min(110, $c.Length))
  }
'''


def powershell(cmd: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def section_host() -> None:
    out("\n[e] Processos e reinício")
    out(powershell(PROCESS_QUERY))
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    out(f"  Pasta Inicializar: {sorted(p.name for p in startup.glob('*'))}")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon") as k:
            out(f"  AutoAdminLogon = {winreg.QueryValueEx(k, 'AutoAdminLogon')[0]}")
    except OSError as exc:
        out(f"  AutoAdminLogon = não definido ({type(exc).__name__})")


def section_permissions() -> None:
    out("\n[c] Permissões de agentes e MCP nesta máquina (só nomes)")
    home = Path.home()
    for p in (ROOT / ".claude/settings.json", ROOT / ".claude/settings.local.json", home / ".claude/settings.json"):
        try:
            perms = json.loads(p.read_text(encoding="utf-8")).get("permissions")
            out(f"  {p}: permissions={perms}")
        except (OSError, ValueError) as exc:
            out(f"  {p}: {type(exc).__name__}")
    for p in (ROOT / ".mcp.json", home / ".claude.json", home / ".gemini/antigravity/mcp_config.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            servers = dict(d.get("mcpServers", {}))
            for proj in d.get("projects", {}).values():
                servers.update(proj.get("mcpServers", {}))
            out(f"  {p}: " + str({n: {"url_ou_cmd": (c.get("url") or c.get("command") or "")[:40],
                                      "autoApprove": c.get("autoApprove")} for n, c in servers.items()}))
        except (OSError, ValueError) as exc:
            out(f"  {p}: {type(exc).__name__}")


def main() -> None:
    import MetaTrader5 as mt5
    from dotenv import load_dotenv
    logging.disable(logging.CRITICAL)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    if not mt5.initialize():
        raise SystemExit(f"MT5 não respondeu: {mt5.last_error()}")
    out(f"AUDITORIA {datetime.now():%Y-%m-%d %H:%M} | máquina={socket.gethostname()}")
    ti, ai = mt5.terminal_info(), mt5.account_info()
    out("\n[a] Permissões")
    out(f"  terminal_info.trade_allowed={ti.trade_allowed} | tradeapi_disabled={ti.tradeapi_disabled} | connected={ti.connected}")
    out(f"  account_info.trade_allowed={ai.trade_allowed} | trade_expert={ai.trade_expert} | login={ai.login} | "
        f"conta={'DEMO' if ai.trade_mode == 0 else 'NAO-DEMO'} | saldo={ai.balance}")
    for s in SYMBOLS:
        i = mt5.symbol_info(s)
        out(f"  {s}: trade_mode={i.trade_mode} ({TRADE_MODE.get(i.trade_mode)}) | contract_size={i.trade_contract_size} | "
            f"stops_level={i.trade_stops_level} | freeze_level={i.trade_freeze_level} | volume_min={i.volume_min}")
    magics = {777777: "legado", 20261107: "engine", 20261108: "GoldFlip", 20261109: "BTCTrendFlip", 20261110: "SWEEP48", 20261111: "CAPITULATION"}
    out("\n[f] Posições/ordens abertas")
    for p in mt5.positions_get() or []:
        out(f"  posição #{p.ticket} {p.symbol} {p.volume} magic={p.magic} ({magics.get(p.magic, 'manual/outro')}) sl={p.sl} tp={p.tp}")
    for o in mt5.orders_get() or []:
        out(f"  pendente #{o.ticket} {o.symbol} magic={o.magic} ({magics.get(o.magic, 'manual/outro')})")
    from config import settings
    out(f"\n[b] settings.DRY_RUN do sistema legado (main.py) = {settings.DRY_RUN} | "
        f"allow_real={cfg['account']['allow_real']} | QUANT_ALLOW_REAL definido={bool(os.getenv('QUANT_ALLOW_REAL'))}")
    section_permissions()
    section_checks(mt5, cfg)
    section_host()
    mt5.shutdown()
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    path = rep / f"audit_autonomy_{socket.gethostname()}_{datetime.now():%Y%m%d_%H%M}.txt"
    path.write_text("\n".join(LINES), encoding="utf-8")
    print(f"\nRelatório: {path}")


if __name__ == "__main__":
    main()
