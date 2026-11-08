"""Processo dos agentes de RSI extremo (seção do config em --section), com loop de tick próprio."""
import argparse
import logging
import sys

from dotenv import load_dotenv

from agents.capitulation import CapitulationAgent
from engine.config import ROOT, load_config
from engine.live import _connect

EXIT_NO_RESTART = 3


class TagFilter(logging.Filter):
    """As mensagens das classes-base saem com o nome do agente deste processo."""

    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = record.msg.replace("[SWEEP48", f"[{self.tag}").replace("[CAPITULATION", f"[{self.tag}")
        return True


def single_instance(section: str):
    import msvcrt
    (ROOT / "state").mkdir(exist_ok=True)
    fh = open(ROOT / "state" / f"{section}.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", default="capitulation")
    section = ap.parse_args().section
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / f"{section}.log", encoding="utf-8")])
    for handler in logging.getLogger().handlers:
        handler.addFilter(TagFilter(section.upper()))
    lock = single_instance(section)
    if lock is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", section)
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    if not cfg[section].get("enabled"):
        logging.warning("%s.enabled=false: agente não iniciado.", section)
        return EXIT_NO_RESTART
    _connect(mt5)
    agent = CapitulationAgent(mt5, cfg, section=section)
    agent.start()
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
