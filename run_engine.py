"""Entrada do motor determinístico.

  python run_engine.py              # DRY_RUN (paper) na DEMO — padrão do config/engine.yaml
  python run_engine.py --live-demo  # ordens reais na conta DEMO 309673774 (DRY_RUN=False)
"""
import argparse
import logging
from pathlib import Path

from engine.config import ROOT, load_config
from engine.live import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-demo", action="store_true", help="DRY_RUN=False: envia ordens à conta DEMO")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    dry_run = bool(cfg["account"].get("dry_run", True)) and not args.live_demo

    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "engine.log", encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    run(cfg, dry_run=dry_run)


if __name__ == "__main__":
    main()
