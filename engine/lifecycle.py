"""Ciclo de vida do processo do motor: por que ele parou e quantas vezes reiniciou.

state/engine_lifecycle.json guarda a execução atual (pid, início, último heartbeat) e, ao sair, o motivo.
Na partida seguinte o motivo anterior vai para o log:
  - saída registrada  -> exceção não tratada (com o traceback resumido), Ctrl+C etc.;
  - sem registro      -> o processo foi morto de fora (janela fechada, logoff/reinício da VPS,
                         Agendador encerrando a tarefa, crash nativo do Python/MetaTrader5).
logs/restarts.log recebe uma linha por partida, para contar os reinícios por dia.
"""
from __future__ import annotations

import json
import logging
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from engine.config import ROOT

log = logging.getLogger("engine.lifecycle")

STATE_FILE = ROOT / "state" / "engine_lifecycle.json"
RESTARTS_LOG = ROOT / "logs" / "restarts.log"


def _iso(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") if ts else "-"


def _read() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write(obj: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception as exc:  # noqa: BLE001
        log.warning("[VIDA] estado não gravado: %s", exc)


def describe_previous(prev: Dict[str, Any], now: float) -> str:
    """Texto do motivo da parada anterior (função pura, testável)."""
    if not prev:
        return "primeira execução registrada"
    started, beat = prev.get("started_at"), prev.get("last_beat")
    head = f"execução anterior pid={prev.get('pid')} iniciada {_iso(started)}, último sinal de vida {_iso(beat)}"
    ex = prev.get("exit")
    if ex:
        return f"{head}; saiu em {_iso(ex.get('at'))}: {ex.get('reason')}"
    gap = int(now - beat) if beat else None
    return (f"{head}; SEM registro de saída -> processo encerrado de fora (janela fechada, logoff/reinício da VPS, "
            f"Agendador ou crash nativo do Python/MT5)" + (f"; parado há {gap}s" if gap is not None else ""))


def on_start() -> str:
    now = time.time()
    why = describe_previous(_read(), now)
    _write({"pid": os.getpid(), "started_at": now, "last_beat": now, "exit": None})
    log.warning("[REINÍCIO] %s", why)
    try:
        RESTARTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RESTARTS_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{_iso(now)} | start pid={os.getpid()} | anterior: {why}\n")
    except Exception:  # noqa: BLE001
        pass
    return why


def beat() -> None:
    st = _read()
    if st.get("pid") == os.getpid():
        st["last_beat"] = time.time()
        _write(st)


def record_exit(reason: str, exc: Optional[BaseException] = None) -> None:
    st = _read()
    if st.get("pid") not in (None, os.getpid()):
        return
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:] if exc else ""
    st.update({"pid": os.getpid(), "exit": {"at": time.time(), "reason": reason, "traceback": tb}})
    _write(st)
    try:
        with open(RESTARTS_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{_iso(time.time())} | exit pid={os.getpid()} | {reason}\n")
    except Exception:  # noqa: BLE001
        pass
