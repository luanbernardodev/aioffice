"""Carrega config/engine.yaml (parâmetros por ativo/agente em múltiplos de ATR)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "engine.yaml"


def load_config(path: Optional[str | Path] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with open(path or DEFAULT_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return cfg


def deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
