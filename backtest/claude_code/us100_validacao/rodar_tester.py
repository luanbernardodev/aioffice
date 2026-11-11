"""Roda o EA US100_RSI2_Connors_H1 no Strategy Tester (ticks reais) numa CÓPIA PORTÁTIL do MT5.

O terminal aberto (usado pelos agentes/MCP) não é tocado: a instalação é copiada para uma pasta própria,
iniciada com /portable e fechada pelo próprio tester (ShutdownTerminal=1). Credenciais DEMO vêm do .env.

  python backtest/claude_code/us100_validacao/rodar_tester.py 2025.09.01 2026.11.10 [pasta_portatil]
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EA = ROOT / "mql5" / "Experts" / "US100_RSI2_Connors_H1.mq5"
INSTALL = Path(r"C:\Program Files\XM Global MT5")


def env() -> dict:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def prepare(dst: Path) -> Path:
    if not (dst / "terminal64.exe").exists():
        shutil.copytree(INSTALL, dst, dirs_exist_ok=True)
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 não respondeu: {mt5.last_error()}")
    data, server = Path(mt5.terminal_info().data_path), mt5.account_info().server
    mt5.shutdown()
    include = dst / "MQL5" / "Include"
    if not (include / "Trade" / "Trade.mqh").exists():     # bibliotecas padrão: cópia (só leitura) do terminal
        shutil.copytree(data / "MQL5" / "Include", include, dirs_exist_ok=True)
    # histórico e ticks reais já baixados pelo terminal aberto (cópia só leitura): a instância portátil, com a
    # mesma conta logada em paralelo, não consegue baixar ticks sozinha ("history check timeout")
    for kind in ("history", "ticks"):
        src = data / "bases" / server / kind / "US100Cash"
        out = dst / "bases" / server / kind / "US100Cash"
        out.mkdir(parents=True, exist_ok=True)
        for f in (src.iterdir() if src.exists() else []):
            try:
                shutil.copy2(f, out / f.name)
            except OSError:                                 # arquivo em uso pelo terminal aberto: pula
                print(f"em uso, não copiado: {kind}/{f.name}", flush=True)
    experts = dst / "MQL5" / "Experts"
    experts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EA, experts / EA.name)
    log = dst / "compile.log"
    editor = dst / "MetaEditor64.exe"
    subprocess.run([str(editor), "/portable", f"/compile:{experts / EA.name}", f"/log:{log}"], check=False)
    text = log.read_bytes().decode("utf-16", errors="ignore") if log.exists() else ""
    m = re.search(r"Result:\s*(\d+)\s*errors?,\s*(\d+)\s*warnings?", text)
    if not m or int(m.group(1)) > 0 or not (experts / EA.with_suffix(".ex5").name).exists():
        raise RuntimeError("compilação falhou:\n" + "\n".join(l for l in text.splitlines() if "error" in l.lower()))
    print(f"compilado: {m.group(1)} erros, {m.group(2)} warnings", flush=True)
    return experts


def run(date_from: str, date_to: str, dst: Path, timeout_min: int = 240) -> Path:
    e = env()
    prepare(dst)
    name = f"us100_rsi2_{date_from.replace('.', '')}_{date_to.replace('.', '')}"
    ini = dst / "tester_us100_rsi2.ini"
    ini.write_text("\n".join([
        "[Common]", f"Login={e['MT5_LOGIN_DEMO']}", f"Password={e['MT5_PASSWORD_DEMO']}", f"Server={e['MT5_SERVER_DEMO']}",
        "[Tester]", "Expert=US100_RSI2_Connors_H1.ex5", "Symbol=US100Cash", "Period=H1", "Model=4",
        "Optimization=0", "ExecutionMode=0", f"FromDate={date_from}", f"ToDate={date_to}", "Deposit=10000",
        "Currency=USD", "Leverage=100", "Visual=0", f"Report={name}", "ReplaceReport=1", "ShutdownTerminal=1", ""]),
        encoding="utf-16")
    t0 = time.time()
    try:
        subprocess.run([str(dst / "terminal64.exe"), "/portable", f"/config:{ini}"], timeout=timeout_min * 60, check=False)
    finally:
        ini.unlink(missing_ok=True)                     # não deixa a senha em disco
    rep = next((p for p in (dst / f"{name}.htm", dst / f"{name}.html") if p.exists()), None)
    if rep is None:
        raise RuntimeError(f"relatório não gerado (veja {dst / 'Tester' / 'logs'})")
    out = HERE / "tester" / rep.name
    out.parent.mkdir(exist_ok=True)
    shutil.copy2(rep, out)
    for png in dst.glob(f"{name}*.png"):
        shutil.copy2(png, out.parent / png.name)
    print(f"tester {date_from}..{date_to}: {time.time() - t0:.0f}s -> {out}", flush=True)
    return out


def parse(report: Path) -> dict:
    raw = report.read_bytes()
    text = raw.decode("utf-16", errors="ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
    cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", text, re.S)]
    want = {"Total Net Profit:": "net", "Profit Factor:": "pf", "Total Trades:": "trades",
            "Profit Trades (% of total):": "wins", "Balance Drawdown Maximal:": "dd", "History Quality:": "quality",
            "Lucro Líquido Total:": "net", "Fator de Lucro:": "pf", "Total de Negociações:": "trades",
            "Negociações com Lucro (% do total):": "wins", "Rebaixamento Máximo do Saldo:": "dd",
            "Qualidade do histórico:": "quality"}
    out = {}
    for i, c in enumerate(cells[:-1]):
        if c in want and want[c] not in out:
            out[want[c]] = cells[i + 1]
    # negociações: cada saída (out) com lucro, para o acerto real
    deals = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)
    profits = []
    for d in deals:
        cs = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", d, re.S)]
        if len(cs) >= 13 and cs[4] == "out" and cs[3] in ("buy", "sell"):
            try:
                profits.append((cs[0], float(cs[10].replace(" ", "")), float(cs[11].replace(" ", ""))))
            except ValueError:
                pass
    out["deals_out"] = profits
    return out


if __name__ == "__main__":
    a, b = sys.argv[1], sys.argv[2]
    dst = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(tempfile.gettempdir()) / "mt5_tester_portable"
    r = run(a, b, dst)
    p = parse(r)
    print({k: v for k, v in p.items() if k != "deals_out"}, "| saídas:", len(p["deals_out"]))
