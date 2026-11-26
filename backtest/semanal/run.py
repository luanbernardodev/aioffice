"""Backtest semanal (agendado na VPS, sábado): dados -> revalidação -> grade -> análise do Claude -> Telegram.

  python -m backtest.semanal.run                 # tudo
  python -m backtest.semanal.run --sem-grade     # só dados + revalidação (rápido)
  opções: --sem-dados --sem-grade --sem-claude --sem-telegram --max-horas 8 --processos N

Saída em reports/semanal/AAAA-MM-DD/: dados.json, revalidacao.csv, grade.csv, resumo.txt, analise_claude.txt.
SOMENTE RELATA: nenhuma configuração de agente é alterada (o Claude roda só com ferramentas de leitura).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from engine.config import ROOT

log = logging.getLogger("semanal")
REPORTS = ROOT / "reports" / "semanal"
LOCK = ROOT / "logs" / "backtest_semanal.lock"
CLAUDE_TIMEOUT_S = 1200

PROMPT = """Você é o analista quantitativo do projeto quant-office-ai (agentes MT5 numa conta DEMO pequena, ~US$135).
O backtest semanal programado acabou de rodar. Leia os arquivos desta semana em {pasta}:
dados.json (atualização de dados), revalidacao.csv (agentes ligados: histórico x forward x real) e grade.csv
(grade v8 com dados novos; regras fixas no topo de backtest/semanal/grade.py e backtest/semanal/revalidar.py).
{anterior}
Escreva um relatório em português para o Telegram, TEXTO PURO (sem markdown, sem tabelas), no máximo 3.500
caracteres, nesta ordem:
1. Uma linha de status geral (OK / ATENÇÃO / CRÍTICO) e se os dados foram atualizados.
2. Agentes em ALERTA ou DIVERGÊNCIA: nome, números (forward e real) e a leitura em uma frase.
3. Grade: candidatas que passaram nas regras (config e números OOS) ou "nenhuma candidata".
4. Até 3 recomendações objetivas. Elas são SUGESTÕES para o usuário decidir; não diga que algo foi alterado.
Seja honesto com amostras pequenas: menos de 10 trades não sustenta conclusão.
Não altere nenhum arquivo. Responda apenas com o texto do relatório."""


def _claude_exe() -> Optional[str]:
    exe = shutil.which("claude")
    if exe:
        return exe
    for p in (Path.home() / ".local" / "bin" / "claude.exe", Path(os.getenv("APPDATA", "")) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    return None


def ask_claude(pasta: Path, anterior: Optional[Path]) -> Optional[str]:
    """Claude Code em modo não interativo, só com ferramentas de leitura. None se não estiver instalado/logado."""
    exe = _claude_exe()
    if not exe:
        log.warning("Claude Code não encontrado no PATH: relatório sai sem análise")
        return None
    prompt = PROMPT.format(pasta=pasta.relative_to(ROOT).as_posix(),
                           anterior=f"Compare com a semana anterior em {anterior.relative_to(ROOT).as_posix()}."
                           if anterior else "")
    # dontAsk: o que não está liberado é negado sem perguntar (ninguém está olhando a tela às 10h de sábado)
    cmd = [exe, "-p", "--output-format", "text", "--permission-mode", "dontAsk",
           "--allowedTools", "Read", "Glob", "Grep",
           "--disallowedTools", "Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
    try:
        # sem ANTHROPIC_API_KEY: usa a assinatura logada no Claude Code (a chave do .env/ambiente é do auditor)
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        r = subprocess.run(cmd, input=prompt, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           timeout=CLAUDE_TIMEOUT_S, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("Claude Code falhou: %s", exc)
        return None
    if r.returncode != 0 or not r.stdout.strip():
        log.error("Claude Code saiu com código %s: %s", r.returncode, (r.stderr or "")[-500:])
        return None
    return r.stdout.strip()


def resumo_local(dados: Dict[str, Any], rev: Optional[pd.DataFrame], grade: Optional[pd.DataFrame]) -> str:
    """Relatório sem IA (vai junto com a análise do Claude, ou sozinho se ele falhar)."""
    L = [f"Backtest semanal {datetime.now(timezone.utc):%d/%m/%Y}"]
    if dados:
        tk = ", ".join(f"{t['simbolo']} {'+' + format(t['ticks_novos'], ',') if 'ticks_novos' in t else 'ERRO'}"
                       for t in dados.get("ticks", []))
        of = dados.get("orderflow", {})
        L.append(f"Dados: ticks {tk} | orderflow +{of.get('dias_novos', 0)} dia(s)"
                 + (" | ERRO orderflow" if "erro" in of else ""))
    if rev is not None and len(rev):
        alert = rev[rev.situacao.str.contains("ALERTA|DIVERG", na=False)]
        L.append(f"Revalidação: {len(rev)} agentes ligados, {len(alert)} com alerta")
        for _, r in alert.iterrows():
            L.append(f"- {r.agente}: {r.situacao} | fwd {r.fwd_n}t {r.fwd_liquido:+.2f} | real {r.real_comp_n}t "
                     f"{r.real_comp_liquido:+.2f}")
    if grade is not None and len(grade):
        a = grade.attrs
        cand = grade[grade.candidata == True]  # noqa: E712
        L.append(f"Grade: {a.get('total_testado', 0):,} estratégias em {a.get('segundos', 0) // 60} min"
                 + (" (CORTADA POR TEMPO)" if a.get("cortada_por_tempo") else "")
                 + f" | candidatas: {len(cand)}")
        for _, c in cand.iterrows():
            L.append(f"- {c.agente}: {c.config} | OOS {c.OOS_n}t PF {c.OOS_PF} acerto {c.OOS_acerto:.0%} {c['OOS_US$']:+.2f}")
    L.append("Nada foi alterado nos agentes (só relatório).")
    return "\n".join(L)


def _lock() -> bool:
    LOCK.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age_h = (datetime.now().timestamp() - LOCK.stat().st_mtime) / 3600
        if age_h < 20:
            return False
        LOCK.unlink(missing_ok=True)                          # trava velha (execução anterior morreu)
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    for f in ("--sem-dados", "--sem-grade", "--sem-claude", "--sem-telegram"):
        ap.add_argument(f, action="store_true")
    ap.add_argument("--max-horas", type=float, default=8.0)
    ap.add_argument("--processos", type=int, default=None)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")              # janela do cmd da VPS (acentos)
    except Exception:  # noqa: BLE001
        pass
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "backtest_semanal.log", encoding="utf-8")])
    if not _lock():
        log.error("outra execução do backtest semanal está em andamento (%s)", LOCK)
        return 2
    import agents.auditor_mt5 as AUD
    from backtest.semanal import dados as D, grade as G, revalidar as R
    pasta = REPORTS / f"{datetime.now():%Y-%m-%d}"
    pasta.mkdir(parents=True, exist_ok=True)
    anteriores = sorted(p for p in REPORTS.iterdir() if p.is_dir() and p.name < pasta.name)
    dados: Dict[str, Any] = {}
    rev = grade = None
    mt5 = None
    try:
        import MetaTrader5 as _mt5
        from dotenv import load_dotenv
        from engine.live import _connect
        load_dotenv(ROOT / ".env")
        try:
            _connect(_mt5)
            mt5 = _mt5
        except Exception as exc:  # noqa: BLE001
            log.error("MT5 não conectou (%s): segue com os dados que já existem, sem trades reais", exc)
        if not args.sem_dados and mt5 is not None:
            log.info("1/3 atualizando dados")
            dados = D.atualizar(mt5)
            (pasta / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("2/3 revalidando agentes ligados")
        rev = R.revalidar(mt5)
        rev.to_csv(pasta / "revalidacao.csv", index=False)
        if mt5 is not None:
            mt5.shutdown()                                    # só desconecta este processo; o terminal segue aberto
            mt5 = None
        if not args.sem_grade:
            log.info("3/3 grade (até %.1f h)", args.max_horas)
            grade = G.rodar(R.agentes_ligados(), args.max_horas, args.processos)
            grade.to_csv(pasta / "grade.csv", index=False)
            (pasta / "grade_meta.json").write_text(json.dumps(grade.attrs, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.exception("backtest semanal falhou")
        (pasta / "erro.txt").write_text(repr(exc), encoding="utf-8")
    finally:
        if mt5 is not None:
            mt5.shutdown()
    texto = resumo_local(dados, rev, grade)
    if (pasta / "erro.txt").exists():
        texto = "ERRO no backtest semanal: " + (pasta / "erro.txt").read_text(encoding="utf-8")[:300] + "\n" + texto
    (pasta / "resumo.txt").write_text(texto, encoding="utf-8")
    analise = None if args.sem_claude else ask_claude(pasta, anteriores[-1] if anteriores else None)
    if analise:
        (pasta / "analise_claude.txt").write_text(analise, encoding="utf-8")
    msg = (analise + "\n\n---\n" + texto) if analise else texto
    print(msg)
    if not args.sem_telegram:
        AUD.send_telegram("🧪 BACKTEST SEMANAL\n" + msg)
    LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
