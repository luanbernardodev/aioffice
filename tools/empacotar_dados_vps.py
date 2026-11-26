"""Empacota os dados-base do backtest para copiar para a VPS UMA vez (depois o backtest semanal só acrescenta).

  python -m tools.empacotar_dados_vps        -> data/dados_backtest_vps.zip

Na VPS: extraia o zip NA PASTA DO PROJETO (ele já contém os caminhos data/... e backtest/orderflow/...).
Não leva os 5 GB brutos da Binance: o footprint já agregado basta para continuar de onde parou.
"""
from __future__ import annotations

import zipfile

from engine.config import ROOT

ARQUIVOS = (["data/specs.json", "backtest/orderflow/features_BTCUSDT_H1.pkl"]
            + [f"data/{s}_{tf}.csv" for s in ("GOLD", "BTCUSD", "US500Cash") for tf in ("M5", "M15", "H1")]
            + ["data/ticks/GOLD.npz", "data/ticks/BTCUSD.npz",
               "data/orderflow/BTCUSDT_bars_H1.pkl", "data/orderflow/BTCUSDT_fp_H1_b10.pkl"])


def main() -> None:
    out = ROOT / "data" / "dados_backtest_vps.zip"
    faltando = [a for a in ARQUIVOS if not (ROOT / a).exists()]
    if faltando:
        raise SystemExit(f"faltando no PC: {faltando}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for a in ARQUIVOS:
            z.write(ROOT / a, a)
            print(f"  {a}", flush=True)
    print(f"{out}  ({out.stat().st_size / 1e6:,.0f} MB)")


if __name__ == "__main__":
    main()
