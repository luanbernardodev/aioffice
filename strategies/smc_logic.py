"""Módulo de Smart Money Concepts (SMC): Falso Rompimento Institucional (Liquidity Sweep).
Implementa o modelo institucional completo para o Sentinela do Setor 1:
1. Mapeamento de Contexto: Suporte (SSL) e Resistência (BSL) das últimas 50 a 100 barras ignorando os últimos 2 candles.
2. Detecção da Direção: Varredura de liquidez (Spring de Fundo para BUY, Upthrust de Topo para SELL).
3. Validação de Força: Volume >= 1.3x MA20 de volume, com Golden Ticket de Micro-Exaustão RSI (< 35 BUY, > 65 SELL).
4. Rationale e Telemetria: Formatação estrita 'False Breakout - Liquidity Sweep (Volume: X)' para trades_history e Setor 3.
"""
import logging
from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

log = logging.getLogger("smc_logic")


class SMCAnalysisResult(tuple):
    """Tupla estendida para suportar desempacotamento de 2 elementos (bias, force_execute)
    mantendo compatibilidade 100% com o código legado, além de acesso por atributos (.details, .bias).
    """
    bias: Optional[str]
    force_execute: bool
    details: Dict[str, Any]

    def __new__(cls, bias: Optional[str], force_execute: bool = False, details: Optional[Dict[str, Any]] = None):
        d = details or {}
        obj = super().__new__(cls, (bias, force_execute))
        obj.bias = bias
        obj.force_execute = force_execute
        obj.details = d
        return obj


def map_liquidity_zones(df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
    """1. MAPEAMENTO DE CONTEXTO (Regiões Respeitadas):
    - Resistance / Buy-Side Liquidity (BSL): Máxima das últimas 50 a 100 barras, ignorando os últimos 2 candles.
    - Support / Sell-Side Liquidity (SSL): Mínima das últimas 50 a 100 barras, ignorando os últimos 2 candles.
    Armazena esses níveis dinâmicos no dataframe para o Sentinela saber onde estão as zonas de liquidez institucionais.
    """
    out = df.copy()
    # Garante janela entre 50 e 100 barras
    w = max(min(window, 100), 20)
    # shift(2) ignora estritamente os últimos 2 candles para focar no histórico estabelecido
    out["bsl"] = out["high"].shift(2).rolling(window=w, min_periods=min(w, 20)).max()
    out["ssl"] = out["low"].shift(2).rolling(window=w, min_periods=min(w, 20)).min()
    out["resistance"] = out["bsl"]
    out["support"] = out["ssl"]
    out["liquidity_high"] = out["bsl"]
    out["liquidity_low"] = out["ssl"]
    return out


def detect_liquidity_sweep(
    df: pd.DataFrame,
    window: int = 50,
    min_vol_ratio: float = 1.3,
) -> Tuple[Optional[str], bool, Dict[str, Any]]:
    """2. DETECÇÃO DA DIREÇÃO & 3. VALIDAÇÃO DE FORÇA (A Armadilha do Falso Rompimento):
    Cria a lógica de varredura (Sweep) avaliando o comportamento do preço (Wick vs Body) e volume institucional:

    - Gatilho de COMPRA (Spring / Sweep de Fundo):
      A mínima perfura o Suporte estabelecido, mas o fechamento (Close) ocorre ACIMA desse suporte,
      deixando um pavio inferior longo. Indica stop run de vendedores e absorção pelo Smart Money.
    - Gatilho de VENDA (Upthrust / Sweep de Topo):
      A máxima perfura a Resistência estabelecida, mas o fechamento (Close) ocorre ABAIXO dessa resistência,
      deixando um pavio superior longo. Compradores de rompimento presos.

    - Validação de Força (Pico de Volume):
      Volume do candle >= 1.3x da Média Móvel de Volume dos últimos 20 períodos.
    - Micro-Exaustão (Golden Ticket Bypass):
      Se RSI < 35 (BUY) ou RSI > 65 (SELL), ativa force_execute = True garantindo entrada imediata.
    """
    if df is None or len(df) < 25:
        return None, False, {}

    # 1. Garante Mapeamento de Contexto
    if "bsl" not in df.columns or "ssl" not in df.columns or df["bsl"].isna().iloc[-1]:
        df = map_liquidity_zones(df, window=window)

    c = df.iloc[-1]
    open_p = float(c["open"])
    high_p = float(c["high"])
    low_p = float(c["low"])
    close_p = float(c["close"])

    support = float(c.get("ssl") if c.get("ssl") is not None and not pd.isna(c.get("ssl")) else 0.0)
    resistance = float(c.get("bsl") if c.get("bsl") is not None and not pd.isna(c.get("bsl")) else 0.0)

    if support <= 0.0 or resistance <= 0.0:
        return None, False, {}

    candle_range = max(high_p - low_p, 1e-6)
    body = abs(close_p - open_p)
    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)

    # Cálculo da Média Móvel de Volume dos últimos 20 períodos
    vol = float(c.get("volume", 0.0))
    if "vol_ma20" in c and not pd.isna(c["vol_ma20"]):
        vol_ma20 = float(c["vol_ma20"])
    else:
        vol_series = df["volume"]
        vol_ma20 = float(vol_series.rolling(20, min_periods=5).mean().iloc[-1] or 1.0)

    vol_ratio = float(c.get("vol_ratio") if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else (vol / max(vol_ma20, 1e-9)))
    rsi_val = float(c.get("rsi") if "rsi" in c and not pd.isna(c["rsi"]) else 50.0)

    # -------------------------------------------------------------
    # 2. DETECÇÃO DA DIREÇÃO (Wick vs Body)
    # -------------------------------------------------------------
    # COMPRA (Spring / Sweep de Fundo):
    # A mínima perfura o Suporte, mas o Close fecha ACIMA do Suporte, deixando pavio inferior
    is_spring = (low_p < support) and (close_p > support) and (
        (lower_wick >= 0.25 * candle_range) or (lower_wick >= body * 0.8) or ((support - low_p) >= 0.20 * candle_range)
    )

    # VENDA (Upthrust / Sweep de Topo):
    # A máxima perfura a Resistência, mas o Close fecha ABAIXO da Resistência, deixando pavio superior
    is_upthrust = (high_p > resistance) and (close_p < resistance) and (
        (upper_wick >= 0.25 * candle_range) or (upper_wick >= body * 0.8) or ((high_p - resistance) >= 0.20 * candle_range)
    )

    # -------------------------------------------------------------
    # 3. VALIDAÇÃO DE FORÇA (Pico de Volume & Micro-Exaustão)
    # -------------------------------------------------------------
    has_volume_spike = (vol_ratio >= min_vol_ratio)
    buy_exhaustion = (rsi_val < 35.0)
    sell_exhaustion = (rsi_val > 65.0)

    # FORMATO OBRIGATÓRIO: "False Breakout - Liquidity Sweep (Volume: X)"
    vol_formatted = f"{vol_ratio:.1f}x"
    base_rationale = f"False Breakout - Liquidity Sweep (Volume: {vol_formatted})"

    # GATILHO COMPRA
    if is_spring and (has_volume_spike or buy_exhaustion):
        force_execute = buy_exhaustion or (vol_ratio >= 1.5)
        ticket_note = " [GOLDEN TICKET - RSI < 35]" if buy_exhaustion else ""
        rationale = f"{base_rationale}{ticket_note}"
        details = {
            "bias": "BUY",
            "pattern": "SPRING_BUY",
            "support": support,
            "resistance": resistance,
            "low_penetration": round(support - low_p, 5),
            "lower_wick": round(lower_wick, 5),
            "vol_ratio": round(vol_ratio, 2),
            "rsi": round(rsi_val, 2),
            "golden_ticket": buy_exhaustion,
            "force_execute": force_execute,
            "rationale": rationale,
        }
        log.info("[SMC LIQUIDITY SWEEP] Spring detectado! Mínima %.2f < Suporte %.2f | Fechamento %.2f | Vol: %s | RSI: %.1f%s",
                 low_p, support, close_p, vol_formatted, rsi_val, ticket_note)
        return "BUY", force_execute, details

    # GATILHO VENDA
    if is_upthrust and (has_volume_spike or sell_exhaustion):
        force_execute = sell_exhaustion or (vol_ratio >= 1.5)
        ticket_note = " [GOLDEN TICKET - RSI > 65]" if sell_exhaustion else ""
        rationale = f"{base_rationale}{ticket_note}"
        details = {
            "bias": "SELL",
            "pattern": "UPTHRUST_SELL",
            "support": support,
            "resistance": resistance,
            "high_penetration": round(high_p - resistance, 5),
            "upper_wick": round(upper_wick, 5),
            "vol_ratio": round(vol_ratio, 2),
            "rsi": round(rsi_val, 2),
            "golden_ticket": sell_exhaustion,
            "force_execute": force_execute,
            "rationale": rationale,
        }
        log.info("[SMC LIQUIDITY SWEEP] Upthrust detectado! Máxima %.2f > Resistência %.2f | Fechamento %.2f | Vol: %s | RSI: %.1f%s",
                 high_p, resistance, close_p, vol_formatted, rsi_val, ticket_note)
        return "SELL", force_execute, details

    return None, False, {}
