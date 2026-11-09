"""Auditor MT5 SOMENTE LEITURA: coleta conta/posições/deals, resume, pede um parecer curto ao Claude e
envia ao Telegram. Nunca abre, fecha nem modifica ordens (o acesso ao MT5 passa por um proxy que bloqueia
order_send).

  python -m agents.auditor_mt5 [--horas 24] [--sem-telegram]

Segredos só por variável de ambiente: ANTHROPIC_API_KEY, TG_TOKEN, TG_CHAT_ID.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from engine.config import ROOT, load_config
from engine.features import server_to_utc

log = logging.getLogger("agents.auditor")

LOG_DIR = ROOT / "logs"
MEMORY_FILE = LOG_DIR / "memoria_auditor.md"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 600
TG_LIMIT = 4000
LEGACY_MAGIC = 777777

SYSTEM_PROMPT = (
    "Você é o auditor de risco de um sistema de trading automatizado (conta DEMO na XM, MT5). "
    "Recebe em JSON o estado da conta, as posições abertas e os trades fechados na janela, já agregados por "
    "símbolo e por agente, além das lições anteriores da sua memória. Responda em português do Brasil, curto "
    "(no máximo 12 linhas), neste formato:\n"
    "STATUS: OK | ATENÇÃO | CRÍTICO\n"
    "PROBLEMAS: itens curtos (posição sem SL, drawdown, agente perdedor, overtrading) ou 'nenhum'\n"
    "AÇÃO: uma recomendação objetiva\n"
    "LIÇÃO: uma linha com algo novo que valha lembrar nas próximas auditorias, ou 'nenhuma'\n"
    "Use só os números recebidos; não invente dados. CRÍTICO = posição sem SL ou perda relevante da conta."
)


class ReadOnlyMT5:
    """Proxy do módulo MetaTrader5: qualquer envio de ordem é recusado."""

    BLOCKED = {"order_send"}

    def __init__(self, mt5: Any) -> None:
        self._m = mt5

    def __getattr__(self, name: str) -> Any:
        if name in self.BLOCKED:
            raise PermissionError(f"auditor é somente leitura: {name} bloqueado")
        return getattr(self._m, name)


# ----------------------------------------------------------------- nomes dos agentes
def agent_names(cfg: Dict[str, Any]) -> Dict[int, str]:
    names = {LEGACY_MAGIC: "legado (Setores 1-6)", 0: "manual"}
    names[int(cfg["account"]["magic"])] = "engine"
    for section, value in cfg.items():
        if isinstance(value, dict) and "magic" in value and section != "account":
            names[int(value["magic"])] = section
    return names


def agent_of(magic: int, entry_comment: str, names: Dict[int, str]) -> str:
    base = names.get(int(magic), f"magic {magic}")
    if base == "engine":                         # A2/A3/A4 dividem o magic; o comentário da entrada diz quem foi
        m = re.match(r"(A\d)\|", entry_comment or "")
        return f"engine {m.group(1)}" if m else "engine"
    return base


# ----------------------------------------------------------------- coleta
def collect(mt5: Any, hours: float, names: Dict[int, str], server_time: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError(f"account_info vazio: {mt5.last_error()}")
    positions = []
    for p in mt5.positions_get() or []:
        positions.append({"ticket": int(p.ticket), "simbolo": p.symbol, "tipo": "BUY" if int(p.type) == 0 else "SELL",
                          "lote": float(p.volume), "entrada": float(p.price_open), "sl": float(p.sl), "tp": float(p.tp),
                          "pnl": round(float(p.profit) + float(getattr(p, "swap", 0.0)), 2), "magic": int(p.magic),
                          "agente": agent_of(int(p.magic), str(getattr(p, "comment", "")), names),
                          "sem_sl": float(p.sl) == 0.0})
    start = now - timedelta(hours=hours)
    # margem de 3 dias para achar a entrada de posições fechadas dentro da janela; a hora do servidor é convertida
    raw = mt5.history_deals_get(start.replace(tzinfo=None) - timedelta(days=3),
                                now.replace(tzinfo=None) + timedelta(days=1)) or []
    trades = closed_trades(raw, start, names, server_time)
    return {"gerado_utc": now.strftime("%Y-%m-%d %H:%M"), "janela_horas": hours,
            "conta": {"login": int(acc.login), "demo": int(acc.trade_mode) == 0, "saldo": float(acc.balance),
                      "equity": float(acc.equity), "margem_livre": float(acc.margin_free),
                      "pnl_flutuante": round(float(acc.equity) - float(acc.balance), 2),
                      "dd_flutuante_pct": round(max(0.0, (float(acc.balance) - float(acc.equity)) / float(acc.balance) * 100), 2)
                      if float(acc.balance) > 0 else 0.0},
            "posicoes": positions, "trades": trades, "resumo": summarize(trades)}


def closed_trades(deals: List[Any], start: datetime, names: Dict[int, str], server_time: str) -> List[Dict[str, Any]]:
    by_pos: Dict[int, List[Any]] = {}
    for d in deals:
        if int(d.type) in (0, 1) and int(d.position_id):
            by_pos.setdefault(int(d.position_id), []).append(d)
    out = []
    for pid, ds in by_pos.items():
        exits = [d for d in ds if int(d.entry) in (1, 2, 3)]       # OUT, INOUT, OUT_BY
        if not exits:
            continue
        closed = server_to_utc([int(max(int(d.time) for d in exits))], server_time).iloc[0].to_pydatetime()
        if closed < start:
            continue
        entry = next((d for d in ds if int(d.entry) == 0), ds[0])
        pnl = sum(float(d.profit) + float(d.swap) + float(d.commission) for d in ds)
        out.append({"posicao": pid, "simbolo": entry.symbol, "agente": agent_of(int(entry.magic), str(entry.comment), names),
                    "magic": int(entry.magic), "lado": "BUY" if int(entry.type) == 0 else "SELL",
                    "fechado_utc": closed.strftime("%Y-%m-%d %H:%M"), "pnl": round(pnl, 2)})
    return sorted(out, key=lambda t: t["fechado_utc"])


def _stats(pnls: List[float]) -> Dict[str, Any]:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gl = -sum(losses)
    return {"trades": len(pnls), "pnl": round(sum(pnls), 2), "win_rate_pct": round(100 * len(wins) / len(pnls), 1) if pnls else 0.0,
            "profit_factor": round(sum(wins) / gl, 2) if gl > 0 else (None if not wins else "inf")}


def summarize(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_sym: Dict[str, List[float]] = {}
    by_agent: Dict[str, List[float]] = {}
    for t in trades:
        by_sym.setdefault(t["simbolo"], []).append(t["pnl"])
        by_agent.setdefault(t["agente"], []).append(t["pnl"])
    return {"total": _stats([t["pnl"] for t in trades]),
            "por_simbolo": {k: _stats(v) for k, v in sorted(by_sym.items())},
            "por_agente": {k: _stats(v) for k, v in sorted(by_agent.items())}}


def needs_ai(data: Dict[str, Any]) -> bool:
    return bool(data["trades"]) or any(p["sem_sl"] for p in data["posicoes"])


# ----------------------------------------------------------------- memória e Claude
def read_memory(path: Optional[Path] = None, last_chars: int = 3000) -> str:
    path = path or MEMORY_FILE
    try:
        return path.read_text(encoding="utf-8")[-last_chars:]
    except FileNotFoundError:
        return ""


def extract_lesson(text: str) -> Optional[str]:
    m = re.search(r"LI[ÇC][ÃA]O\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if not m:
        return None
    lesson = m.group(1).strip().strip("*").strip()
    return None if not lesson or lesson.lower().rstrip(".") in ("nenhuma", "nenhum", "-") else lesson


def save_lesson(lesson: str, now: datetime, path: Optional[Path] = None) -> None:
    path = path or MEMORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# Memória do auditor MT5\n\n")
        fh.write(f"- {now:%Y-%m-%d %H:%M} UTC: {lesson}\n")


def make_client() -> Any:
    """Lê ANTHROPIC_API_KEY do ambiente. Chave não vinculada a um workspace exige o cabeçalho
    anthropic-workspace-id: vem de ANTHROPIC_WORKSPACE_ID, como no restante do projeto (config/settings.py)."""
    import anthropic
    ws = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


def ask_claude(data: Dict[str, Any], memory: str, client: Any = None) -> str:
    import anthropic
    client = client or make_client()
    payload = json.dumps({"dados": data, "memoria_recente": memory}, ensure_ascii=False, default=str)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},                       # resposta curta: os 600 tokens ficam para o texto
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": payload}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("o modelo recusou a análise")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ----------------------------------------------------------------- relatório e Telegram
def local_report(data: Dict[str, Any]) -> str:
    c, tot = data["conta"], data["resumo"]["total"]
    lines = [f"Auditor MT5 | {data['gerado_utc']} UTC | janela {data['janela_horas']:g}h",
             f"Conta #{c['login']} {'DEMO' if c['demo'] else 'REAL'} | saldo {c['saldo']:.2f} | equity {c['equity']:.2f} | "
             f"margem livre {c['margem_livre']:.2f} | DD flutuante {c['dd_flutuante_pct']}%",
             f"Trades: {tot['trades']} | PnL {tot['pnl']:+.2f} | win {tot['win_rate_pct']}% | PF {tot['profit_factor']}"]
    for agent, s in data["resumo"]["por_agente"].items():
        lines.append(f"  {agent}: {s['trades']} trades, {s['pnl']:+.2f}, PF {s['profit_factor']}")
    for p in data["posicoes"]:
        lines.append(f"  aberta #{p['ticket']} {p['simbolo']} {p['tipo']} {p['lote']} {p['agente']} "
                     f"SL={'SEM SL' if p['sem_sl'] else p['sl']} PnL {p['pnl']:+.2f}")
    return "\n".join(lines)


def send_telegram(text: str, post: Callable[..., Any] = None) -> bool:
    token, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT_ID")
    if not token or not chat:
        log.warning("TG_TOKEN/TG_CHAT_ID não definidos: relatório não enviado ao Telegram")
        return False
    if post is None:
        import requests
        post = requests.post
    r = post(f"https://api.telegram.org/bot{token}/sendMessage",
             data={"chat_id": chat, "text": text[:TG_LIMIT]}, timeout=20)
    ok = getattr(r, "status_code", 200) == 200
    if not ok:
        log.error("Telegram recusou: HTTP %s %s", getattr(r, "status_code", "?"), getattr(r, "text", "")[:200])
    return ok


# ----------------------------------------------------------------- execução
def run(hours: float, mt5: Any, cfg: Dict[str, Any], claude_client: Any = None, post: Callable[..., Any] = None,
        telegram: bool = True, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    names = agent_names(cfg)
    try:
        data = collect(ReadOnlyMT5(mt5), hours, names, cfg["account"].get("server_time", "ny_plus_7"), now)
    except Exception as exc:  # noqa: BLE001
        log.exception("falha ao ler o MT5")
        msg = f"Auditor MT5 | STATUS: CRÍTICO\nFalha ao ler o MT5: {exc}\nVerifique se o terminal está aberto e logado na VPS."
        if telegram:
            send_telegram(msg, post)
        return msg
    report = local_report(data)
    if needs_ai(data):
        try:
            analysis = ask_claude(data, read_memory(), claude_client)
            lesson = extract_lesson(analysis)
            if lesson:
                save_lesson(lesson, now)
            report = f"{report}\n\n{analysis}"
        except Exception as exc:  # noqa: BLE001
            log.exception("falha na análise do Claude")
            report += f"\n\nAnálise de IA indisponível ({type(exc).__name__}). Dados acima calculados localmente."
    else:
        report += "\n\nSTATUS: OK (sem trades na janela e nenhuma posição sem SL; IA não acionada)"
    log.info("relatório:\n%s", report)
    if telegram:
        send_telegram(report, post)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=float, default=float(os.getenv("HORAS", "24")))
    ap.add_argument("--sem-telegram", action="store_true")
    args = ap.parse_args()
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "auditor.log", encoding="utf-8")])
    import MetaTrader5 as mt5
    from dotenv import load_dotenv
    from engine.live import _connect                      # mesma conexão do motor (sem caminho fixo do terminal)
    load_dotenv(ROOT / ".env")                            # credenciais MT5 da demo, se existirem; não sobrescreve o ambiente
    cfg = load_config()
    try:
        _connect(mt5)
    except Exception as exc:  # noqa: BLE001
        log.exception("MT5 não conectou")
        msg = f"Auditor MT5 | STATUS: CRÍTICO\nMT5 não conectou: {exc}"
        if not args.sem_telegram:
            send_telegram(msg)
        return 1
    try:
        run(args.horas, mt5, cfg, telegram=not args.sem_telegram)   # o relatório sai no log (tela + logs/auditor.log)
    finally:
        mt5.shutdown()                                    # só desconecta este processo; o terminal segue aberto
    return 0


if __name__ == "__main__":
    sys.exit(main())
