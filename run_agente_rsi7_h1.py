"""Processo do AGENTE_RSI7_H1 (BTCUSD H1, magic 20261114). Config: config/agente_rsi7_h1.yaml.

Código de saída 3 = não reiniciar (já rodando, desligado no config ou conta não-DEMO).
"""
import logging
import sys

from dotenv import load_dotenv

from agents.rsi7_h1 import SECTION, Rsi7H1Agent, load_agent_config
from engine.config import ROOT, load_config
from engine.live import _connect
from engine.mt5_broker import AccountGuardError

EXIT_NO_RESTART = 3


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
                                  logging.FileHandler(ROOT / "logs" / f"{SECTION}.log", encoding="utf-8")])
    lock = single_instance(SECTION)
    if lock is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", SECTION)
        return EXIT_NO_RESTART
    g = load_agent_config()
    if not g.get("enabled"):
        logging.warning("%s.enabled=false: agente não iniciado.", SECTION)
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    _connect(mt5)
    agent = Rsi7H1Agent(mt5, load_config(), g)
    try:
        agent.start()
    except AccountGuardError as exc:
        logging.critical("%s recusado: %s", SECTION, exc)
        return EXIT_NO_RESTART
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
