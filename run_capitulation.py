"""Processo do agente CAPITULATION (separado do motor, com loop de tick próprio)."""
import logging
import sys

from dotenv import load_dotenv

from agents.capitulation import CapitulationAgent
from engine.config import ROOT, load_config
from engine.live import _connect

EXIT_NO_RESTART = 3


def single_instance():
    import msvcrt
    (ROOT / "state").mkdir(exist_ok=True)
    fh = open(ROOT / "state" / "capitulation.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "capitulation.log", encoding="utf-8")])
    lock = single_instance()
    if lock is None:
        logging.error("CAPITULATION já está rodando nesta máquina; esta cópia não inicia.")
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    if not cfg["capitulation"].get("enabled"):
        logging.warning("capitulation.enabled=false: agente não iniciado.")
        return EXIT_NO_RESTART
    _connect(mt5)
    agent = CapitulationAgent(mt5, cfg)
    agent.start()
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
