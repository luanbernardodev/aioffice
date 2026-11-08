"""Processo do agente SWEEP48 (separado do motor: loop de tick próprio, sem as pausas de cálculo do motor)."""
import logging
import sys

from dotenv import load_dotenv

from agents.sweep48 import Sweep48Agent
from engine.config import ROOT, load_config
from engine.live import _connect

EXIT_ALREADY_RUNNING = 3


def single_instance():
    """Duas cópias enviariam ordens em duplicidade. O lock do SO é liberado sozinho se o processo morrer."""
    import msvcrt
    (ROOT / "state").mkdir(exist_ok=True)
    fh = open(ROOT / "state" / "sweep48.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "sweep48.log", encoding="utf-8")])
    lock = single_instance()
    if lock is None:
        logging.error("SWEEP48 já está rodando nesta máquina; esta cópia não inicia.")
        return EXIT_ALREADY_RUNNING
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    if not cfg["sweep48"].get("enabled"):
        logging.warning("sweep48.enabled=false: agente não iniciado.")
        return EXIT_ALREADY_RUNNING
    _connect(mt5)
    agent = Sweep48Agent(mt5, cfg)
    agent.start()
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
