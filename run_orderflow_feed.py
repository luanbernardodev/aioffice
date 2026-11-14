"""Feed de orderflow BTCUSDT (Binance) + modo sombra do filtro no RSI7. Não envia ordens (MT5 somente leitura).

Código de saída 3 = não reiniciar (já rodando ou falta a biblioteca websockets).
"""
import asyncio
import logging
import sys

from dotenv import load_dotenv

from agents.auditor_mt5 import ReadOnlyMT5
from engine.config import ROOT, load_config
from engine.live import _connect
from run_us100_rsi2 import single_instance

EXIT_NO_RESTART = 3
NAME = "orderflow_feed"


async def shadow_loop(shadow) -> None:
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, shadow.step)
        except Exception as exc:  # noqa: BLE001
            logging.exception("[SOMBRA] falha: %s", exc)
        await asyncio.sleep(10)


async def main_async(feed, shadow) -> None:
    await asyncio.gather(feed.run_ws(), shadow_loop(shadow))


def main() -> int:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / f"{NAME}.log", encoding="utf-8")])
    lock = single_instance(NAME)
    if lock is None:
        logging.error("%s já está rodando nesta máquina; esta cópia não inicia.", NAME)
        return EXIT_NO_RESTART
    try:
        import websockets  # noqa: F401
    except ImportError:
        logging.critical("falta a biblioteca websockets: rode  \"%%PY%%\" -m pip install websockets")
        return EXIT_NO_RESTART
    import MetaTrader5 as mt5
    from orderflow.live import Feed, Shadow
    load_dotenv(ROOT / ".env")
    _connect(mt5)
    cfg = load_config()
    feed = Feed()
    feed.bootstrap()
    shadow = Shadow(ReadOnlyMT5(mt5), cfg["account"].get("server_time", "ny_plus_7"))
    asyncio.run(main_async(feed, shadow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
