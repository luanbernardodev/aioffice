"""Processo único dos agentes v3 da competição (config/agente_v3_competicao.yaml). Um passo por agente a cada ~1 s.

Código de saída 3 = não reiniciar (já rodando, nenhum agente ligado ou conta não-DEMO).
"""
import logging
import sys
import time

from dotenv import load_dotenv

from agents.v3_agent import V3Agent, load_agents_config, load_group_caps
from engine.config import ROOT, load_config
from engine.live import _connect
from engine.mt5_broker import AccountGuardError
from run_us100_rsi2 import single_instance

EXIT_NO_RESTART = 3
NAME = "v3_agents"


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / f"{NAME}.log", encoding="utf-8")])
    lock = single_instance(NAME)
    if lock is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", NAME)
        return EXIT_NO_RESTART
    sections = load_agents_config()             # desligados também entram: zeram posição aberta e não abrem novas
    if not any(v.get("enabled") for v in sections.values()):
        logging.warning("nenhum agente v3 ligado: processo não iniciado.")
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    load_dotenv(ROOT / ".env")
    _connect(mt5)
    cfg = load_config()
    agents = []
    for sec, g in sections.items():
        a = V3Agent(mt5, cfg, sec, g)
        try:
            a.start()
        except AccountGuardError as exc:
            logging.critical("%s recusado: %s", sec, exc)
            return EXIT_NO_RESTART
        agents.append(a)
    caps = load_group_caps()
    for a in agents:                                    # limite de posições simultâneas por grupo (ex.: orderflow BTC)
        grp = a.g.get("grupo")
        if grp and grp in caps:
            members = [x for x in agents if x.g.get("grupo") == grp]
            a.group_full = (lambda ms=members, cap=caps[grp]: sum(len(x._positions()) for x in ms) >= cap)
    last_cfg, last_hb = time.time(), 0.0
    while True:
        for a in agents:
            try:
                a.step()
            except Exception as exc:  # noqa: BLE001 — um agente com erro não derruba os outros
                logging.exception("%s falha no passo: %s", a.tag, exc)
        if time.time() - last_cfg >= 60:                     # kill_switch / enabled relidos a cada minuto
            last_cfg = time.time()
            try:
                fresh = load_agents_config()
                for a in agents:
                    if a.section in fresh:
                        a.g["kill_switch"] = bool(fresh[a.section].get("kill_switch", False))
                        a.g["enabled"] = bool(fresh[a.section].get("enabled", True))
            except Exception as exc:  # noqa: BLE001
                logging.error("config v3 ilegível (%s): mantendo o anterior", exc)
        if time.time() - last_hb >= 300:
            last_hb = time.time()
            logging.info("[V3 HEARTBEAT] %s", " | ".join(
                f"{a.name}: pos={len(a.state['trades'])}{' PARADO' if a.state['halted'] else ''}{' KILL' if a.killed() else ''}"
                for a in agents))
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main())
