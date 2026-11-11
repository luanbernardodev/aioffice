"""Processo do agente US100_RSI2_H1 (US100Cash H1, magic 20261115). Config: config/agente_us100_rsi2_h1.yaml.

Código de saída 3 = não reiniciar (já rodando, desligado no config ou conta não-DEMO).
"""
import logging
import sys

from dotenv import load_dotenv

from agents.us100_rsi2_h1 import Us100Rsi2Agent, load_agent_config
from engine.config import ROOT, load_config
from engine.live import _connect
from engine.mt5_broker import AccountGuardError

EXIT_NO_RESTART = 3
NAME = "us100_rsi2_h1"


def single_instance(name: str):
    import msvcrt
    (ROOT / "state").mkdir(exist_ok=True)
    fh = open(ROOT / "state" / f"{name}.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / f"{NAME}.log", encoding="utf-8")])
    lock = single_instance(NAME)
    if lock is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", NAME)
        return EXIT_NO_RESTART
    g = load_agent_config()
    if not g.get("enabled"):
        logging.warning("%s.enabled=false: agente não iniciado.", NAME)
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    _connect(mt5)
    agent = Us100Rsi2Agent(mt5, load_config(), g)
    try:
        agent.start()
    except AccountGuardError as exc:
        logging.critical("%s recusado: %s", NAME, exc)
        return EXIT_NO_RESTART
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
