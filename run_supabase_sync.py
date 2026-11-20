"""Sincronização MT5 -> Supabase do painel (agents/supabase_sync.py). MT5 somente leitura.

Código de saída 3 = não reiniciar (já rodando ou SUPABASE_URL/SUPABASE_KEY ausentes no .env).
"""
import logging
import os
import sys
import time

from dotenv import load_dotenv

from agents.auditor_mt5 import ReadOnlyMT5
from engine.config import ROOT, load_config
from engine.live import _connect
from run_us100_rsi2 import single_instance

EXIT_NO_RESTART = 3
NAME = "supabase_sync"
INTERVAL = 20


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / f"{NAME}.log", encoding="utf-8")])
    if single_instance(NAME) is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", NAME)
        return EXIT_NO_RESTART
    load_dotenv(ROOT / ".env")
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        logging.critical("SUPABASE_URL / SUPABASE_KEY ausentes no .env: sincronização não iniciada.")
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    from agents.supabase_sync import SupabaseSync
    _connect(mt5)
    sync = SupabaseSync(ReadOnlyMT5(mt5), load_config(), url, key)
    last_hb = 0.0
    while True:
        try:
            n = sync.step()
            if any(n.values()) or time.time() - last_hb > 600:
                last_hb = time.time()
                logging.info("[SYNC] enviados: %s", n)
        except Exception as exc:  # noqa: BLE001 — falha de rede/MT5 não derruba o processo
            logging.warning("[SYNC] falha no ciclo: %s", exc)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
