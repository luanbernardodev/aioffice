"""Instala e compila o EA GoldFlipTrail no terminal MT5 aberto (o mesmo que o motor usa).

  python -m tools.deploy_mql5

1. Pergunta ao MT5 a pasta de dados e a pasta de instalação.
2. Copia mql5/Include/GoldFlipControl.mqh -> <dados>/MQL5/Include
        mql5/Experts/GoldFlipTrail.mq5    -> <dados>/MQL5/Experts
3. Compila com o metaeditor64.exe do próprio terminal e confere 0 erros.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPERTS = ["GoldFlipTrail.mq5", "BTCTrendFlip.mq5", "GoldNightFlip.mq5", "GoldNightV2.mq5"]
FILES = {ROOT / "mql5" / "Include" / "GoldFlipControl.mqh": ("MQL5", "Include"),
         **{ROOT / "mql5" / "Experts" / e: ("MQL5", "Experts") for e in EXPERTS}}


def main() -> int:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"ERRO: MT5 não respondeu ({mt5.last_error()}). Abra o XM MT5 e rode de novo.")
        return 1
    info = mt5.terminal_info()
    data, install = Path(info.data_path), Path(info.path)
    mt5.shutdown()

    for src, sub in FILES.items():
        dst = data.joinpath(*sub)
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / src.name)
        print(f"copiado: {src.name} -> {dst}")

    editor = install / "metaeditor64.exe"
    if not editor.exists():
        editor = install / "MetaEditor64.exe"
    failed = False
    for name in EXPERTS:
        src = data / "MQL5" / "Experts" / name
        log = Path(tempfile.gettempdir()) / f"{src.stem}_compile.log"
        subprocess.run([str(editor), f"/compile:{src}", f"/log:{log}"], check=False)
        text = log.read_bytes().decode("utf-16", errors="ignore") if log.exists() else ""
        m = re.search(r"Result:\s*(\d+)\s*errors?,\s*(\d+)\s*warnings?", text)
        ex5 = src.with_suffix(".ex5")
        if not m or int(m.group(1)) > 0 or not ex5.exists():
            print(f"ERRO na compilação de {name}:\n" +
                  "\n".join(l for l in text.splitlines() if "error" in l.lower())[-3000:])
            failed = True
            continue
        print(f"compilado: {ex5}  ({m.group(1)} erros, {m.group(2)} warnings)")
    if failed:
        return 1
    print("\nUma vez só, no MT5 (o MT5 lembra nos próximos reinícios), marcando 'Permitir Algo Trading':\n"
          "  - gráfico GOLD M5   -> arrastar GoldFlipTrail\n"
          "  - gráfico BTCUSD H4 -> arrastar BTCTrendFlip\n"
          "  - SEGUNDO gráfico GOLD M5 -> arrastar GoldNightFlip (se goldnight.enabled)
"
          "  - TERCEIRO gráfico GOLD M5 -> arrastar GoldNightV2 (agente GOLD aprimorado, magic 20261116)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
