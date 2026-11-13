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
# Fora da amostra: Setores 1-6 (legado, código removido em 13/11). Não entram em trades, totais nem agentes.
EXCLUDED_MAGICS = {LEGACY_MAGIC}

SYSTEM_PROMPT = (
    "Você é o auditor de risco de um sistema de trading automatizado (conta DEMO na XM, MT5). "
    "Recebe em JSON o estado da conta, as posições abertas e os trades fechados na janela, já agregados por "
    "símbolo e por agente, além das lições anteriores da sua memória. Responda em português do Brasil, curto "
    "(no máximo 12 linhas), neste formato:\n"
    "STATUS: OK | ATENÇÃO | CRÍTICO\n"
    "PROBLEMAS: itens curtos (posição sem SL, drawdown, agente perdedor, overtrading) ou 'nenhum'\n"
    "AÇÃO: uma recomendação objetiva\n"
    "LIÇÃO: uma linha com algo novo que valha lembrar nas próximas auditorias, ou 'nenhuma'\n"
    "Use só os números recebidos; não invente dados. CRÍTICO = posição sem SL ou perda relevante da conta.\n"
    "Contexto do sistema: goldflip, goldnight_v2, rsi20 e os agentes v3_* (exceto v3_us500_sweep_h1) saem por "
    "stop móvel ou por tempo e operam SEM take profit por design, então TP = 0 neles não é problema; "
    "SL = 0 é sempre problema. O sistema legado (Setores 1-6) foi removido e não entra nos dados. "
    "Há uma competição (bloco 'competicao' do JSON) entre agentes antigos e os 5 novos v3_*: comente o placar "
    "sem declarar vencedor antes do fim e lembrando que uma semana é amostra pequena. "
    "Com menos de 20 trades de um agente, trate o resultado como amostra pequena, não como conclusão."
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
    names = {0: "manual"}
    names[int(cfg["account"]["magic"])] = "engine"
    for section, value in cfg.items():
        if isinstance(value, dict) and "magic" in value and section != "account":
            names[int(value["magic"])] = section
    names.update(standalone_agent_names())
    return names


def standalone_agents(config_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Agentes com YAML próprio (config/agente_*.yaml): magic, nome, ligado e símbolo."""
    import yaml
    out: List[Dict[str, Any]] = []
    for path in sorted((config_dir or ROOT / "config").glob("agente_*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            log.warning("config %s ilegível: %s", path.name, exc)
            continue
        for section, value in data.items():
            if isinstance(value, dict) and "magic" in value:
                out.append({"magic": int(value["magic"]), "nome": str(value.get("name") or section),
                            "ligado": bool(value.get("enabled", True)), "simbolo": value.get("symbol", "")})
    return out


def standalone_agent_names(config_dir: Optional[Path] = None) -> Dict[int, str]:
    """Agentes com YAML próprio (config/agente_*.yaml, ex.: agente_rsi7_h1 magic 20261114)."""
    return {a["magic"]: a["nome"] for a in standalone_agents(config_dir)}


def agent_roster(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Todos os agentes configurados, com ou sem trade na janela: nome -> {ligado, simbolos}.

    O motor (magic único) entra separado por sub-agente (engine A2/A3/A4) conforme symbols.*.agents."""
    roster: Dict[str, Dict[str, Any]] = {}
    for sym, sc in (cfg.get("symbols") or {}).items():
        for a in sc.get("agents") or []:
            r = roster.setdefault(f"engine {str(a).split('_')[0]}", {"ligado": False, "simbolos": []})
            r["ligado"] = r["ligado"] or bool(sc.get("enabled"))
            if sc.get("enabled"):
                r["simbolos"].append(sym)
    for section, value in cfg.items():
        if isinstance(value, dict) and "magic" in value and section != "account":
            roster[section] = {"ligado": bool(value.get("enabled", True)),
                               "simbolos": [value["symbol"]] if value.get("symbol") else []}
    for a in standalone_agents():
        roster[a["nome"]] = {"ligado": a["ligado"], "simbolos": [a["simbolo"]] if a["simbolo"] else []}
    return roster


def agent_of(magic: int, entry_comment: str, names: Dict[int, str]) -> str:
    base = names.get(int(magic), f"magic {magic}")
    if base == "engine":                         # A2/A3/A4 dividem o magic; o comentário da entrada diz quem foi
        m = re.match(r"(A\d)\|", entry_comment or "")
        return f"engine {m.group(1)}" if m else "engine"
    return base


# ----------------------------------------------------------------- coleta
def collect(mt5: Any, hours: float, names: Dict[int, str], server_time: str, now: Optional[datetime] = None,
            roster: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError(f"account_info vazio: {mt5.last_error()}")
    positions = []
    for p in mt5.positions_get() or []:
        if int(p.magic) in EXCLUDED_MAGICS:
            continue
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
    # acumulado desde o início da conta, para o desempenho de cada agente não depender da janela
    raw_all = mt5.history_deals_get(datetime(2020, 1, 1), now.replace(tzinfo=None) + timedelta(days=1)) or []
    history = closed_trades(raw_all, datetime(2000, 1, 1, tzinfo=timezone.utc), names, server_time)
    return {"gerado_utc": now.strftime("%Y-%m-%d %H:%M"), "janela_horas": hours,
            "agentes": agents_table(trades, history, positions, roster or {}),
            "competicao": competition_table(history, comp) if (comp := competition_config()) else None,
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
        if int(entry.magic) in EXCLUDED_MAGICS:
            continue
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


def agents_table(window: List[Dict[str, Any]], history: List[Dict[str, Any]], positions: List[Dict[str, Any]],
                 roster: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Uma linha por agente configurado (mesmo sem trades) + qualquer outro que apareça nos dados (manual etc.)."""
    seen = list(roster) + [x["agente"] for x in history + window + positions if x["agente"] not in roster]
    out: Dict[str, Dict[str, Any]] = {}
    for name in dict.fromkeys(seen):
        r = roster.get(name, {})
        out[name] = {"ligado": r.get("ligado"), "simbolos": r.get("simbolos", []),
                     "janela": _stats([t["pnl"] for t in window if t["agente"] == name]),
                     "acumulado": _stats([t["pnl"] for t in history if t["agente"] == name]),
                     "abertas": sum(1 for p in positions if p["agente"] == name),
                     "pnl_aberto": round(sum(p["pnl"] for p in positions if p["agente"] == name), 2)}
    return out


# ----------------------------------------------------------------- competição (agentes antigos x novos v3)
COMPETITION_FILE = ROOT / "config" / "agente_v3_competicao.yaml"


def competition_config(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    import yaml
    try:
        data = yaml.safe_load((path or COMPETITION_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    c = data.get("competicao")
    return c if isinstance(c, dict) and c.get("inicio_utc") else None


def competition_table(history: List[Dict[str, Any]], comp: Dict[str, Any]) -> Dict[str, Any]:
    """Placar desde inicio_utc (até fim_utc): resultado, trades, acerto, PF e drawdown de cada participante."""
    ini, fim = str(comp["inicio_utc"])[:16], str(comp.get("fim_utc") or "9999")[:16]
    turma = {**{n: "antigo" for n in comp.get("antigos") or []}, **{n: "novo" for n in comp.get("novos") or []}}
    rows = []
    for name, grupo in turma.items():
        pnls = [t["pnl"] for t in history if t["agente"] == name and ini <= t["fechado_utc"] < fim]
        eq, peak, dd = 0.0, 0.0, 0.0
        for v in pnls:
            eq += v
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        rows.append({"agente": name, "grupo": grupo, **_stats(pnls), "max_dd": round(dd, 2)})
    rows.sort(key=lambda r: (r["pnl"], r["trades"]), reverse=True)
    grupos = {g: round(sum(r["pnl"] for r in rows if r["grupo"] == g), 2) for g in ("antigo", "novo")}
    return {"inicio_utc": ini, "fim_utc": comp.get("fim_utc"), "placar": rows, "total_por_grupo": grupos}


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


class MissingApiKey(RuntimeError):
    pass


def _secret(name: str) -> str:
    """Ambiente primeiro; se faltar OU estiver vazio, o .env do projeto (load_dotenv não sobrescreve uma variável
    já definida, mesmo vazia — causa do TypeError "Could not resolve authentication method")."""
    v = os.getenv(name, "").strip()
    if not v:
        try:
            from dotenv import dotenv_values
            v = str(dotenv_values(ROOT / ".env").get(name) or "").strip()
        except Exception:  # noqa: BLE001 — sem python-dotenv ou sem .env: segue vazio
            v = ""
    return v


def make_client() -> Any:
    """ANTHROPIC_API_KEY do ambiente ou do .env. Chave não vinculada a um workspace exige o cabeçalho
    anthropic-workspace-id: vem de ANTHROPIC_WORKSPACE_ID, como no restante do projeto (config/settings.py)."""
    import anthropic
    key = _secret("ANTHROPIC_API_KEY")
    if not key:
        raise MissingApiKey("ANTHROPIC_API_KEY não definida no ambiente nem no .env")
    ws = _secret("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(api_key=key, default_headers={"anthropic-workspace-id": ws} if ws else None)


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
def _pf(v: Any) -> str:
    return "∞" if v == "inf" else ("–" if v is None else f"{v:.2f}")


def _agent_line(name: str, a: Dict[str, Any]) -> List[str]:
    j, t = a["janela"], a["acumulado"]
    status = "" if a.get("ligado") in (None, True) else " (desligado)"
    syms = f" [{', '.join(a['simbolos'])}]" if a.get("simbolos") else ""
    win = (f"   Janela: {j['trades']} trades | {j['pnl']:+.2f} | acerto {j['win_rate_pct']:.0f}% | "
           f"PF {_pf(j['profit_factor'])}" if j["trades"] else "   Janela: sem trades fechados")
    tot = (f"   Acumulado: {t['trades']} trades | {t['pnl']:+.2f} | acerto {t['win_rate_pct']:.0f}% | "
           f"PF {_pf(t['profit_factor'])}" if t.get("trades") else "   Acumulado: sem trades")
    out = [f"• {name}{syms}{status}", win, tot]
    if a.get("abertas"):
        out.append(f"   Aberto agora: {a['abertas']} posição(ões) | {a['pnl_aberto']:+.2f}")
    return out


def local_report(data: Dict[str, Any]) -> str:
    """Texto puro para o Telegram (sem Markdown, que quebra com _ e * nos nomes): blocos separados por linha
    em branco e um bloco por agente configurado, inclusive os que não fecharam trades na janela."""
    c, tot = data["conta"], data["resumo"]["total"]
    lines = [f"📊 AUDITOR MT5 — {data['gerado_utc']} UTC",
             f"Janela: últimas {data['janela_horas']:g}h",
             "",
             f"💰 CONTA #{c['login']} ({'DEMO' if c['demo'] else 'REAL'})",
             f"Saldo: {c['saldo']:.2f} | Equity: {c['equity']:.2f}",
             f"Margem livre: {c['margem_livre']:.2f}",
             f"Flutuante: {c.get('pnl_flutuante', 0.0):+.2f} | DD flutuante: {c['dd_flutuante_pct']}%",
             "",
             "📈 RESULTADO DA JANELA",
             f"{tot['trades']} trades | PnL {tot['pnl']:+.2f}" + (
                 f" | acerto {tot['win_rate_pct']:.0f}% | PF {_pf(tot['profit_factor'])}" if tot["trades"] else ""),
             "",
             "🤖 AGENTES"]
    agents = data.get("agentes") or {k: {"janela": v, "acumulado": {"trades": 0}, "abertas": 0, "ligado": None}
                                      for k, v in data["resumo"]["por_agente"].items()}
    for name, a in agents.items():
        lines += _agent_line(name, a)
    comp = data.get("competicao")
    if comp:
        fim = f" até {str(comp['fim_utc'])[:16]}" if comp.get("fim_utc") else ""
        g = comp["total_por_grupo"]
        lines += ["", f"🏆 COMPETIÇÃO (desde {comp['inicio_utc']} UTC{fim})",
                  f"Antigos {g['antigo']:+.2f} x Novos {g['novo']:+.2f}"]
        for i, r in enumerate(comp["placar"], 1):
            lines.append(f"{i}. {r['agente']} [{r['grupo']}] {r['pnl']:+.2f} | {r['trades']} trades" + (
                f" | acerto {r['win_rate_pct']:.0f}% | PF {_pf(r['profit_factor'])} | DD {r['max_dd']:.2f}"
                if r["trades"] else ""))
    lines += ["", f"📌 POSIÇÕES ABERTAS ({len(data['posicoes'])})"]
    if not data["posicoes"]:
        lines.append("nenhuma")
    for p in data["posicoes"]:
        lines += [f"• #{p['ticket']} {p['simbolo']} {p['tipo']} {p['lote']:g} — {p['agente']}",
                  f"   SL: {'⚠️ SEM SL' if p['sem_sl'] else p['sl']} | TP: {p['tp'] or '–'} | PnL {p['pnl']:+.2f}"]
    return "\n".join(lines)


def split_message(text: str, limit: int = TG_LIMIT) -> List[str]:
    """Partes de até `limit` caracteres sem cortar linhas (o Telegram aceita 4096 por mensagem)."""
    parts: List[str] = []
    cur = ""
    for line in text.split("\n"):
        while len(line) > limit:                         # linha gigante (raro): corta no limite
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts


def send_telegram(text: str, post: Callable[..., Any] = None) -> bool:
    token, chat = _secret("TG_TOKEN"), _secret("TG_CHAT_ID")
    if not token or not chat:
        log.warning("TG_TOKEN/TG_CHAT_ID não definidos: relatório não enviado ao Telegram")
        return False
    if post is None:
        import requests
        post = requests.post
    ok = True
    parts = split_message(text, TG_LIMIT - 12)
    for i, part in enumerate(parts, 1):
        body = part if len(parts) == 1 else f"({i}/{len(parts)})\n{part}"
        r = post(f"https://api.telegram.org/bot{token}/sendMessage",
                 data={"chat_id": chat, "text": body, "disable_web_page_preview": "true"}, timeout=20)
        if getattr(r, "status_code", 200) != 200:
            ok = False
            log.error("Telegram recusou: HTTP %s %s", getattr(r, "status_code", "?"), getattr(r, "text", "")[:200])
    return ok


# ----------------------------------------------------------------- execução
def run(hours: float, mt5: Any, cfg: Dict[str, Any], claude_client: Any = None, post: Callable[..., Any] = None,
        telegram: bool = True, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    names = agent_names(cfg)
    try:
        data = collect(ReadOnlyMT5(mt5), hours, names, cfg["account"].get("server_time", "ny_plus_7"), now,
                       roster=agent_roster(cfg))
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
            report = f"{report}\n\n🧠 ANÁLISE DA IA\n{analysis}"
        except Exception as exc:  # noqa: BLE001
            log.exception("falha na análise do Claude")
            why = str(exc) if isinstance(exc, MissingApiKey) else type(exc).__name__
            report += f"\n\n🧠 Análise de IA indisponível ({why}). Dados acima calculados localmente."
    else:
        report += "\n\n✅ STATUS: OK\nSem trades na janela e nenhuma posição sem SL (IA não acionada)."
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
