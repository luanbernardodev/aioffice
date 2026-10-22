"""Sentinela: motor matemático de custo zero (pandas/numpy). Só emite dados quando há gatilho real."""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import settings
from core.mt5_bridge import MT5Bridge
from core import derivatives_collector
from strategies.smc_logic import map_liquidity_zones, detect_liquidity_sweep, SMCAnalysisResult

log = logging.getLogger("sentinel")


# ----------------------------------------------------------------- indicadores
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                      (df["low"] - prev_close).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    dev = close.rolling(period).std(ddof=0)
    return mid + std * dev, mid, mid - std * dev


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_ = atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP ancorado no início de cada dia UTC (sessão)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].clip(lower=1e-9)
    day = df["time"].dt.date
    return (typical * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "volume" not in out:
        out["volume"] = out["tick_volume"] if "tick_volume" in out else 1.0
    out["rsi"] = rsi(out["close"], 14)
    out["ema9"], out["ema21"] = ema(out["close"], 9), ema(out["close"], 21)
    out["ema20"], out["ema50"], out["ema200"] = (ema(out["close"], p) for p in (20, 50, 200))
    out["atr"] = atr(out, 14)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger(out["close"], 20, 2.0)
    out["bandwidth"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"]
    out["adx"] = adx(out, 14)
    out["vwap"] = vwap(out)
    out["vol_ma20"] = out["volume"].rolling(20, min_periods=5).mean()
    out["vol_ratio"] = out["volume"] / out["vol_ma20"].shift(1).clip(lower=1e-9)

    # 1. MAPEAMENTO DE CONTEXTO (Regiões Respeitadas): Suporte (SSL) e Resistência (BSL)
    # Janela de 50 barras ignorando os últimos 2 candles
    out = map_liquidity_zones(out, window=50)
    return out


# -------------------------------------------------------- ANÁLISE TÉCNICA E AUTONOMIA MATEMÁTICA
def check_indecision_filters(df: pd.DataFrame, direction: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validação técnica autônoma e direta para agentes do Setor 1:
    - Triple Check (ADX > 25 e Volume Spike) REMOVIDO: autonomia matemática direta.
    - Nova Regra de Compra Absoluta: Se RSI <= 30, gera sinal de COMPRA.
    - Nova Regra de Venda Absoluta: Se RSI >= 70, gera sinal de VENDA.
    Retorna: (aprovado: bool, motivo_aborto: Optional[str], detalhes_aprovacao: Optional[str])
    """
    if len(df) < 20:
        return False, "Abortado: Histórico insuficiente de velas", None

    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0

    if direction == "BUY":
        if rsi_val <= 30.0:
            return True, None, f"RSI {rsi_val:.1f} <= 30 (Sinal de Compra Absoluto)"
        return False, f"Abortado: Mercado em zona de indecisão (RSI Neutro: {rsi_val:.1f} > 30)", None
    elif direction == "SELL":
        if rsi_val >= 70.0:
            return True, None, f"RSI {rsi_val:.1f} >= 70 (Sinal de Venda Absoluto)"
        return False, f"Abortado: Mercado em zona de indecisão (RSI Neutro: {rsi_val:.1f} < 70)", None
    else:
        return False, f"Abortado: Direção inválida '{direction}'", None


# --------------------------------------------------------------------- gatilhos
class SignalResult(str):
    """Representação de sinal com flag de autorização especial (Autonomia / force_execute) e detalhes SMC."""
    force_execute: bool = False
    details: Dict[str, Any] = {}

    def __new__(cls, val: str, force_execute: bool = True, details: Optional[Dict[str, Any]] = None):
        obj = str.__new__(cls, val)
        obj.force_execute = force_execute
        obj.details = details or {}
        return obj


def analyze_market(df: pd.DataFrame, strategy: str = "ops_beta") -> SMCAnalysisResult:
    """Análise quantitativa institucional para agentes operacionais (Setor 1).
    Compatível com SMCAnalysisResult(bias, force_execute, details):
    1. Modelo Principal SMC: Falso Rompimento Institucional (Liquidity Sweep)
       avaliando Contexto (BSL/SSL), Direção (Spring/Upthrust) e Força (Volume >= 1.3x).
       Se RSI < 35 ou > 65, concede Golden Ticket (force_execute = True).
    2. Golden Ticket de Reversão Extrema de RSI (<= 30 BUY, >= 70 SELL):
       Prioridade matemática máxima com autonomia imediata (force_execute = True).
    """
    if df is None or len(df) == 0:
        return SMCAnalysisResult(None, False, {})

    # 1. Modelo Principal SMC: Falso Rompimento Institucional (Liquidity Sweep)
    bias_smc, force_smc, details_smc = detect_liquidity_sweep(df, window=50, min_vol_ratio=1.3)
    if bias_smc:
        return SMCAnalysisResult(bias_smc, force_smc, details_smc)

    # 2. GOLDEN TICKET ABSOLUTO: Extremos de RSI (Sobrevenda <= 30 / Sobrecompra >= 70)
    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0
    vol_ratio = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0

    if rsi_val <= 30.0:
        rat = f"Sniper RSI Reversal (RSI: {rsi_val:.1f} <= 30 | Sobrevenda Extrema) [GOLDEN TICKET]"
        details = {
            "bias": "BUY",
            "pattern": "SNIPER_RSI_OVERSOLD",
            "rationale": rat,
            "vol_ratio": vol_ratio,
            "rsi": rsi_val,
            "force_execute": True,
            "golden_ticket": True,
            "strategy": "ops_beta",
        }
        return SMCAnalysisResult("BUY", True, details)

    if rsi_val >= 70.0:
        rat = f"Sniper RSI Reversal (RSI: {rsi_val:.1f} >= 70 | Sobrecompra Extrema) [GOLDEN TICKET]"
        details = {
            "bias": "SELL",
            "pattern": "SNIPER_RSI_OVERBOUGHT",
            "rationale": rat,
            "vol_ratio": vol_ratio,
            "rsi": rsi_val,
            "force_execute": True,
            "golden_ticket": True,
            "strategy": "ops_beta",
        }
        return SMCAnalysisResult("SELL", True, details)

    return SMCAnalysisResult(None, False, {})


def _check_alpha(df: pd.DataFrame) -> Optional[SignalResult]:
    """Agente ALPHA (Trend Following - M15):
    Opera a favor da tendência com pullback na EMA20 e confirmação de ADX >= 20."""
    if df is None or len(df) < 50:
        return None
    c = df.iloc[-1]
    price = float(c["close"])
    open_p = float(c["open"])
    ema20 = float(c["ema20"])
    ema50 = float(c["ema50"])
    adx_val = float(c["adx"]) if "adx" in c and not pd.isna(c["adx"]) else 25.0
    vol_ratio = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0

    if ema20 > ema50 and adx_val >= 20.0 and float(c["low"]) <= ema20 * 1.003 and price >= ema20 and price > open_p:
        rat = f"Trend Following Pullback EMA20 (ADX: {adx_val:.1f} | Tendência de Alta | Vol: {vol_ratio:.1f}x)"
        details = {"bias": "BUY", "pattern": "TREND_PULLBACK_BUY", "rationale": rat, "vol_ratio": vol_ratio, "strategy": "ops_alpha", "specialty": "Trend Following"}
        return SignalResult("BUY", force_execute=False, details=details)

    if ema20 < ema50 and adx_val >= 20.0 and float(c["high"]) >= ema20 * 0.997 and price <= ema20 and price < open_p:
        rat = f"Trend Following Pullback EMA20 (ADX: {adx_val:.1f} | Tendência de Baixa | Vol: {vol_ratio:.1f}x)"
        details = {"bias": "SELL", "pattern": "TREND_PULLBACK_SELL", "rationale": rat, "vol_ratio": vol_ratio, "strategy": "ops_alpha", "specialty": "Trend Following"}
        return SignalResult("SELL", force_execute=False, details=details)

    return None


def _check_beta(df: pd.DataFrame) -> Optional[SignalResult]:
    """Agente BETA (Sniper RSI - M15):
    Responsável exclusivo por operar as reversões extremas de RSI (30/70) no M15.
    Possui autonomia total (Golden Ticket: force_execute = True) e bypass absoluto de qualquer regra de IA."""
    if df is None or len(df) == 0:
        return None
    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0
    vol_ratio = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0

    # Sobrevenda Extrema (RSI <= 30) -> COMPRA IMEDIATA (Golden Ticket)
    if rsi_val <= 30.0:
        rat = f"Sniper RSI Reversal (RSI {rsi_val:.1f} <= 30 | Sobrevenda Extrema) [GOLDEN TICKET]"
        details = {
            "bias": "BUY",
            "pattern": "SNIPER_RSI_OVERSOLD",
            "rationale": rat,
            "rsi": rsi_val,
            "vol_ratio": vol_ratio,
            "force_execute": True,
            "golden_ticket": True,
            "strategy": "ops_beta",
            "specialty": "Sniper RSI Reversal",
        }
        return SignalResult("BUY", force_execute=True, details=details)

    # Sobrecompra Extrema (RSI >= 70) -> VENDA IMEDIATA (Golden Ticket)
    if rsi_val >= 70.0:
        rat = f"Sniper RSI Reversal (RSI {rsi_val:.1f} >= 70 | Sobrecompra Extrema) [GOLDEN TICKET]"
        details = {
            "bias": "SELL",
            "pattern": "SNIPER_RSI_OVERBOUGHT",
            "rationale": rat,
            "rsi": rsi_val,
            "vol_ratio": vol_ratio,
            "force_execute": True,
            "golden_ticket": True,
            "strategy": "ops_beta",
            "specialty": "Sniper RSI Reversal",
        }
        return SignalResult("SELL", force_execute=True, details=details)

    return None


def _check_gamma(df: pd.DataFrame) -> Optional[SignalResult]:
    """Agente GAMMA (Volatility Breakout - M15):
    Opera rompimento das Bandas de Bollinger com expansão de volume institucional."""
    if df is None or len(df) < 30:
        return None
    c = df.iloc[-1]
    price = float(c["close"])
    bb_upper = float(c["bb_upper"])
    bb_lower = float(c["bb_lower"])
    vol_ratio = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0

    if price > bb_upper and vol_ratio >= 1.2:
        rat = f"Volatility Breakout Bandas Bollinger (Preço {price:.2f} > Upper {bb_upper:.2f} | Vol: {vol_ratio:.1f}x)"
        details = {"bias": "BUY", "pattern": "VOLATILITY_BREAKOUT_BUY", "rationale": rat, "vol_ratio": vol_ratio, "strategy": "ops_gamma", "specialty": "Volatility Breakout"}
        return SignalResult("BUY", force_execute=False, details=details)

    if price < bb_lower and vol_ratio >= 1.2:
        rat = f"Volatility Breakout Bandas Bollinger (Preço {price:.2f} < Lower {bb_lower:.2f} | Vol: {vol_ratio:.1f}x)"
        details = {"bias": "SELL", "pattern": "VOLATILITY_BREAKOUT_SELL", "rationale": rat, "vol_ratio": vol_ratio, "strategy": "ops_gamma", "specialty": "Volatility Breakout"}
        return SignalResult("SELL", force_execute=False, details=details)

    return None


def check_delta_strategy(df: pd.DataFrame, symbol: str = "BTCUSD") -> Tuple[bool, Optional[str]]:
    """Avaliação quantitativa autônoma do Agente Delta (SMC Liquidity Sweep)."""
    res = _check_delta(df, symbol=symbol)
    if res:
        rat = res.details.get("rationale") or f"Gatilho Autônomo Delta ({res})"
        return True, rat
    return False, None


def _check_delta(df: pd.DataFrame, symbol: str = "BTCUSD") -> Optional[SignalResult]:
    """Agente DELTA (SMC Scalper - M1/M5):
    Focado em operar Liquidity Sweeps e Falsos Rompimentos rápidos em M1/M5,
    utilizando mapeamento de contexto (SSL/BSL) e validações de volume institucional."""
    if df is None or len(df) == 0:
        return None
    bias, force_execute, details = detect_liquidity_sweep(df, window=50, min_vol_ratio=1.3)
    if bias:
        details["strategy"] = "ops_delta"
        details["specialty"] = "SMC Scalper (Liquidity Sweep & False Breakout)"
        return SignalResult(bias, force_execute=force_execute, details=details)
    return None


def _check_epsilon(df: pd.DataFrame) -> Optional[SignalResult]:
    """Agente EPSILON (VWAP/Momentum Scalper - M1/M5):
    Scalper de fluxo institucional em M1/M5. Opera a favor da tendência quando o preço faz
    pullback rápido na EMA ou VWAP com volume e momentum favoráveis."""
    if df is None or len(df) < 25:
        return None
    c = df.iloc[-1]
    price = float(c["close"])
    open_p = float(c["open"])
    vwap_val = float(c.get("vwap")) if c.get("vwap") is not None and not pd.isna(c.get("vwap")) else price
    ema9 = float(c.get("ema9")) if c.get("ema9") is not None and not pd.isna(c.get("ema9")) else price
    ema21 = float(c.get("ema21")) if c.get("ema21") is not None and not pd.isna(c.get("ema21")) else price
    vol_ratio = float(c.get("vol_ratio")) if c.get("vol_ratio") is not None and not pd.isna(c.get("vol_ratio")) else 1.0
    rsi_val = float(c.get("rsi")) if c.get("rsi") is not None and not pd.isna(c.get("rsi")) else 50.0

    # Fluxo Comprador: Tendência de alta (Preço >= VWAP ou EMA9 >= EMA21)
    # Pullback rápido: mínima testou a região de suporte dinâmico (VWAP ou EMA9/21) e fechou recuperando
    bullish_trend = (ema9 >= ema21) or (price >= vwap_val)
    tested_support = float(c["low"]) <= max(ema9, ema21, vwap_val) * 1.002
    closed_bullish = (price > open_p) and (price >= min(ema9, vwap_val))

    if bullish_trend and tested_support and closed_bullish and vol_ratio >= 1.0 and rsi_val < 68.0:
        rat = f"VWAP Flow Momentum Scalp (Pullback VWAP/EMA | Vol: {vol_ratio:.1f}x | RSI: {rsi_val:.1f})"
        details = {
            "bias": "BUY",
            "pattern": "VWAP_MOMENTUM_PULLBACK_BUY",
            "rationale": rat,
            "vol_ratio": vol_ratio,
            "vwap": vwap_val,
            "rsi": rsi_val,
            "strategy": "ops_epsilon",
            "specialty": "VWAP/Momentum Flow Scalper",
            "force_execute": False,
        }
        return SignalResult("BUY", force_execute=False, details=details)

    # Fluxo Vendedor: Tendência de baixa (Preço <= VWAP ou EMA9 <= EMA21)
    # Pullback rápido: máxima testou a região de resistência dinâmica (VWAP ou EMA9/21) e fechou rejeitando
    bearish_trend = (ema9 <= ema21) or (price <= vwap_val)
    tested_resistance = float(c["high"]) >= min(ema9, ema21, vwap_val) * 0.998
    closed_bearish = (price < open_p) and (price <= max(ema9, vwap_val))

    if bearish_trend and tested_resistance and closed_bearish and vol_ratio >= 1.0 and rsi_val > 32.0:
        rat = f"VWAP Flow Momentum Scalp (Pullback VWAP/EMA | Vol: {vol_ratio:.1f}x | RSI: {rsi_val:.1f})"
        details = {
            "bias": "SELL",
            "pattern": "VWAP_MOMENTUM_PULLBACK_SELL",
            "rationale": rat,
            "vol_ratio": vol_ratio,
            "vwap": vwap_val,
            "rsi": rsi_val,
            "strategy": "ops_epsilon",
            "specialty": "VWAP/Momentum Flow Scalper",
            "force_execute": False,
        }
        return SignalResult("SELL", force_execute=False, details=details)

    return None


# Chaves = estratégia-base vinculadas a cada especialidade
CHECKS = {
    "ops_alpha": _check_alpha,
    "ops_beta": _check_beta,
    "ops_gamma": _check_gamma,
    "ops_delta": _check_delta,
    "ops_epsilon": _check_epsilon,
}

TRIGGER_NAMES = {
    "ops_alpha": "TREND_PULLBACK",
    "ops_beta": "SNIPER_RSI_REVERSAL",
    "ops_gamma": "VOLATILITY_BREAKOUT",
    "ops_delta": "LIQUIDITY_SWEEP_SMC",
    "ops_epsilon": "VWAP_MOMENTUM_PULLBACK",
}


def _num(row: pd.Series, key: str, digits: int = 5) -> Optional[float]:
    v = row.get(key)
    return None if v is None or pd.isna(v) else round(float(v), digits)


def check_vaccines(agent_id: str, bias: str, df: pd.DataFrame,
                   vaccines: List[Dict[str, Any]]) -> Optional[str]:
    """Avalia se uma entrada em MEIO DE GRÁFICO (30 < RSI < 70) infringe algum filtro do Setor 3.
    
    LIMITAÇÕES ESTRITAS DO SETOR 3 (FIM DO OVERFITTING):
    1. Golden Ticket (Bypass Absoluto): Se RSI <= 30 ou RSI >= 70, as vacinas são 100% IGNORADAS.
    2. Agente Beta (Sniper RSI): Possui autonomia total e NUNCA é vetado por regras de IA.
    3. As vacinas atuam unicamente como filtros de meio de gráfico para ruídos normais.
    """
    if not vaccines or df is None or len(df) == 0:
        return None

    c = df.iloc[-1]
    rsi_val = float(c.get("rsi") if c.get("rsi") is not None and not pd.isna(c.get("rsi")) else 50.0)

    # 1. RESTAURAÇÃO DO "GOLDEN TICKET" (Bypass Absoluto):
    # Se RSI <= 30 (Sobrevenda) ou RSI >= 70 (Sobrecompra): A ordem DEVE ser executada imediatamente.
    if rsi_val <= 30.0 or rsi_val >= 70.0:
        log.info("[GOLDEN TICKET - BYPASS TOTAL] RSI extremo (%.1f). Todas as vacinas e bloqueios de IA do Setor 3 são ignorados!", rsi_val)
        return None

    # Agente Beta tem autonomia total de reversão extrema
    if agent_id == "ops_beta":
        return None

    # 2. FILTRO DE MEIO DE GRÁFICO:
    indicators = {
        "RSI": rsi_val,
        "ADX": float(c.get("adx") if c.get("adx") is not None and not pd.isna(c.get("adx")) else 0.0),
        "ATR": float(c.get("atr") if c.get("atr") is not None and not pd.isna(c.get("atr")) else 0.0),
        "VOL_RATIO": float(c.get("vol_ratio") if c.get("vol_ratio") is not None and not pd.isna(c.get("vol_ratio")) else 1.0),
        "BANDWIDTH": float(c.get("bandwidth") if c.get("bandwidth") is not None and not pd.isna(c.get("bandwidth")) else 0.0),
    }

    for vac in vaccines:
        if not isinstance(vac, dict):
            continue
        ind_name = str(vac.get("indicator") or "").strip().upper()
        if ind_name not in indicators:
            continue

        curr_val = indicators[ind_name]
        op = str(vac.get("operator") or "").strip()
        try:
            threshold = float(vac.get("value") or 0.0)
        except (ValueError, TypeError):
            continue
        cond = str(vac.get("condition") or "").lower()

        # Checa se a vacina restringe a direção pretendida (ex: avoid_buy ou avoid_sell)
        should_check = False
        if bias == "BUY" and ("buy" in cond):
            should_check = True
        elif bias == "SELL" and ("sell" in cond):
            should_check = True

        if not should_check:
            continue

        violated = False
        if op == "<" and curr_val < threshold:
            violated = True
        elif op == "<=" and curr_val <= threshold:
            violated = True
        elif op == ">" and curr_val > threshold:
            violated = True
        elif op == ">=" and curr_val >= threshold:
            violated = True
        elif op in ("==", "=") and abs(curr_val - threshold) < 1e-4:
            violated = True

        if violated:
            source = str(vac.get("source_agent") or "Setor3").replace("ops_", "").title()
            desc = vac.get("description") or f"{ind_name} {op} {threshold}"
            return f"Filtro de Meio de Gráfico ({source}: {desc})"

    return None


class Sentinel:
    def __init__(self, bridge: MT5Bridge, db: Optional[Any] = None) -> None:
        self.bridge = bridge
        self.db = db
        # Anti-spam tick a tick: restrito a 1 tiro por formação de vela
        self.last_bar_time: Dict[Tuple[str, str], str] = {}
        self._last_signal = self.last_bar_time

    def _snapshot(self, symbol: str, agent_id: str, strategy: str, trigger: str, bias: str,
                  df: pd.DataFrame, force_execute: bool = False,
                  rationale: Optional[str] = None, details: Optional[dict] = None) -> dict:
        c = df.iloc[-1]
        vol_ratio_val = _num(c, "vol_ratio", 2) or 1.0
        rat = rationale or (details.get("rationale") if details else None) or f"False Breakout - Liquidity Sweep (Volume: {vol_ratio_val:.1f}x)"
        return {
            "symbol": symbol, "agent_id": agent_id, "strategy": strategy, "trigger": trigger, "bias": bias,
            "force_execute": force_execute,
            "rationale": rat,
            "timeframe": settings.STRATEGY_TIMEFRAMES.get(strategy, settings.TIMEFRAME),
            "candle_time": str(c["time"]),
            "price": round(float(c["close"]), 5), "atr": round(float(c["atr"]), 5),
            "rsi": round(float(c["rsi"]), 2), "adx": round(float(c["adx"]), 2),
            "support": _num(c, "ssl") or _num(c, "support"),
            "resistance": _num(c, "bsl") or _num(c, "resistance"),
            "vol_ratio": vol_ratio_val,
            "ema9": _num(c, "ema9"), "ema21": _num(c, "ema21"),
            "ema20": round(float(c["ema20"]), 5), "ema50": round(float(c["ema50"]), 5),
            "ema200": round(float(c["ema200"]), 5), "bb_upper": round(float(c["bb_upper"]), 5),
            "bb_lower": round(float(c["bb_lower"]), 5), "bandwidth": round(float(c["bandwidth"]), 5),
            "vwap": _num(c, "vwap"),
            "candle": {k: round(float(c[k]), 5) for k in ("open", "high", "low", "close")},
            "smc_details": details or {},
        }

    def _prepare(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        df = self.bridge.get_rates(symbol, timeframe, 400)
        df = df.iloc[:-1].reset_index(drop=True)  # descarta candle em formação
        if len(df) < 210:
            log.warning("Histórico insuficiente para %s %s", symbol, timeframe)
            return None
        return compute_indicators(df)

    def scan_symbol(self, symbol: str, active_agents: Optional[Dict[str, str]] = None,
                    agent_params: Optional[Dict[str, dict]] = None) -> List[dict]:
        """`active_agents`: {agent_id: estratégia-base}. Retorna gatilhos matemáticos validados."""
        if active_agents is None:
            active_agents = {a: a for a in CHECKS}
        frames: Dict[str, Optional[pd.DataFrame]] = {}  # um cálculo por timeframe
        triggers = []
        for agent_id, strategy in active_agents.items():
            check = CHECKS.get(strategy)
            if check is None:
                continue
            tf = settings.STRATEGY_TIMEFRAMES.get(strategy, settings.TIMEFRAME)
            if tf not in frames:
                frames[tf] = self._prepare(symbol, tf)
            df = frames[tf]
            if df is None:
                continue
            candle_time = str(df.iloc[-1]["time"])

            # 4. ANTI-SPAM TICK A TICK: Restrito a 1 tiro por formação de vela
            if self.last_bar_time.get((symbol, agent_id)) == candle_time:
                continue

            try:
                check_res = check(df, symbol=symbol)
            except TypeError:
                check_res = check(df)

            force_execute = True
            details_dict: Dict[str, Any] = {}
            if isinstance(check_res, tuple):
                bias = check_res[0]
                force_execute = check_res[1]
                details_dict = getattr(check_res, "details", {})
                if len(check_res) > 2 and isinstance(check_res[2], dict):
                    details_dict = check_res[2]
            elif hasattr(check_res, "force_execute"):
                bias = str(check_res)
                force_execute = bool(check_res.force_execute)
                details_dict = getattr(check_res, "details", {})
            else:
                bias = check_res

            # Heartbeat Verbose Logging: Imprime distância do preço para o gatilho se VERBOSE_LOGS=True
            if getattr(settings, "VERBOSE_LOGS", True):
                self._log_strategy_proximity(agent_id, strategy, symbol, df, bias)

            if bias:
                label = agent_id.replace("ops_", "Ops ").title()
                rsi_curr = float(df.iloc[-1].get("rsi", 50))
                vol_curr = float(df.iloc[-1].get("vol_ratio", 1.0))

                # 1. RESTAURAÇÃO DO "GOLDEN TICKET" (Bypass Absoluto):
                # Se RSI <= 30 (Sobrevenda) ou RSI >= 70 (Sobrecompra): A ordem DEVE ser executada imediatamente.
                # O código ignora temporariamente QUALQUER "vacina", filtro de tendência ou bloqueio gerado pelo Setor 3.
                is_golden_ticket = (
                    (rsi_curr <= 30.0 or rsi_curr >= 70.0)
                    or force_execute
                    or details_dict.get("golden_ticket", False)
                    or (strategy == "ops_beta" and (rsi_curr <= 30.0 or rsi_curr >= 70.0))
                )

                if is_golden_ticket:
                    force_execute = True
                    log.info("[%s] GOLDEN TICKET ATIVADO (RSI Extremo: %.1f)! Bypass Absoluto de qualquer vacina ou veto de IA.",
                             label, rsi_curr)
                else:
                    # Checa vacinas ativas do Setor 3 unicamente para entradas normais de meio de gráfico (30 < RSI < 70)
                    vaccines = []
                    if agent_params and agent_id in agent_params:
                        vaccines = agent_params[agent_id].get("vaccines") or []
                    elif self.db:
                        try:
                            p = self.db.get_strategy_params(agent_id)
                            vaccines = p.get("vaccines") or []
                        except Exception:
                            pass

                    vaccine_veto = check_vaccines(agent_id, bias, df, vaccines)
                    if vaccine_veto:
                        log.warning("[%s] GATILHO VETADO EM MEIO DE GRÁFICO PELO SETOR 3: %s no ativo %s (%s)",
                                    label, vaccine_veto, symbol, bias)
                        continue

                # 2. Definição do trigger nominal de acordo com a especialidade do agente
                trigger_name = TRIGGER_NAMES.get(strategy, "QUANT_AUTONOMOUS_TRIGGER")
                rat = details_dict.get("rationale") or f"Gatilho Autônomo ({trigger_name} | Vol: {vol_curr:.1f}x | RSI: {rsi_curr:.1f})"

                # 3. Registrar trava anti-spam para evitar múltiplos tiros no mesmo candle
                self.last_bar_time[(symbol, agent_id)] = candle_time
                self._last_signal[(symbol, agent_id)] = candle_time

                # 4. Log Limpo e Especializado do Agente
                order_desc = "Compra" if bias == "BUY" else "Venda"
                log.info("[%s] GATILHO APROVADO (%s): %s -> %s | Rationale: %s",
                         label, trigger_name, order_desc, symbol, rat)

                triggers.append(self._snapshot(symbol, agent_id, strategy,
                                               trigger_name,
                                               bias, df, force_execute=force_execute,
                                               rationale=rat, details=details_dict))
        return triggers

    def _log_strategy_proximity(self, agent_id: str, strategy: str, symbol: str,
                                df: pd.DataFrame, bias: Optional[str]) -> None:
        """Imprime a telemetria quantitativa e distância para os gatilhos matemáticos de cada mesa."""
        c = df.iloc[-1]
        price = float(c["close"])

        if strategy == "ops_beta":
            rsi_val = float(c["rsi"])
            if bias:
                log.info("[Ops Beta] %s REVERSÃO SNIPER DETECTADA (RSI: %.1f) -> GOLDEN TICKET DISPARADO (%s)",
                         symbol, rsi_val, bias)
            else:
                dist_extremo = min(abs(rsi_val - 30.0), abs(70.0 - rsi_val))
                log.info("[Ops Beta] %s Sniper RSI Reversal (RSI: %.1f | Distância do Extremo: %.1f pts) -> Aguardando Extremo <=30 ou >=70",
                         symbol, rsi_val, dist_extremo)

        elif strategy == "ops_delta":
            swing = df.iloc[-23:-3]
            swing_low = float(swing["low"].min())
            swing_high = float(swing["high"].max())
            dist_low = ((price - swing_low) / price) * 100
            dist_high = ((swing_high - price) / price) * 100
            min_dist = min(abs(dist_low), abs(dist_high))
            if bias:
                log.info("[Ops Delta] %s SMC LIQUIDITY SWEEP DETECTADO! Bias=%s (Preço: %.2f) -> Disparando", symbol, bias, price)
            else:
                log.info("[Ops Delta] %s SMC Scalper (Falta %.2f%% para SSL/BSL | Vol Ratio: %.2fx) -> Aguardando Sweep",
                         symbol, min_dist, float(c.get("vol_ratio") or 1.0))

        elif strategy == "ops_epsilon":
            vwap_val = float(c["vwap"]) if c["vwap"] is not None and not pd.isna(c["vwap"]) else price
            dist_vwap = ((price - vwap_val) / price) * 100
            vol_ratio = float(c["vol_ratio"]) if c["vol_ratio"] is not None and not pd.isna(c["vol_ratio"]) else 1.0
            if bias:
                log.info("[Ops Epsilon] %s VWAP MOMENTUM DETECTADO! Bias=%s -> Disparando Scalp de Fluxo", symbol, bias)
            else:
                log.info("[Ops Epsilon] %s VWAP Flow Scalper (Distância VWAP: %+.2f%% | Vol: %.2fx) -> Aguardando Pullback",
                         symbol, dist_vwap, vol_ratio)

        elif strategy == "ops_alpha":
            ema20 = float(c["ema20"])
            dist_ema = ((price - ema20) / price) * 100
            adx_val = float(c["adx"])
            if bias:
                log.info("[Ops Alpha] %s TREND PULLBACK DETECTADO! Bias=%s -> Disparando", symbol, bias)
            else:
                log.info("[Ops Alpha] %s Trend Following (Distância EMA20: %+.2f%% | ADX: %.1f) -> Aguardando Pullback",
                         symbol, dist_ema, adx_val)

        elif strategy == "ops_gamma":
            bw = float(c["bandwidth"])
            atr_val = float(c["atr"])
            if bias:
                log.info("[Ops Gamma] %s BREAKOUT DETECTADO! Bias=%s -> Disparando", symbol, bias)
            else:
                log.info("[Ops Gamma] %s Volatility Breakout (Bandwidth: %.4f | ATR: %.2f) -> Aguardando Rompimento",
                         symbol, bw, atr_val)

    def scan_all(self, active_agents: Optional[Dict[str, str]] = None,
                 agent_params: Optional[Dict[str, dict]] = None,
                 active_assets: Optional[List[str]] = None) -> List[dict]:
        """Varre exclusivamente os ativos selecionados dinamicamente no system_config da UI."""
        if active_assets is None:
            if self.db:
                try:
                    cfg = self.db.get_system_config()
                    active_assets = cfg.get("active_assets")
                except Exception as exc:
                    log.warning("Falha ao obter active_assets em scan_all: %s", exc)
            if not active_assets:
                active_assets = settings.SYMBOLS

        found: List[dict] = []
        for symbol in active_assets:
            try:
                found.extend(self.scan_symbol(symbol, active_agents, agent_params=agent_params))
            except Exception as exc:  # noqa: BLE001
                log.error("Sentinela falhou em %s: %s", symbol, exc)
        return found

    def force_trigger(self, symbol: str, agent_id: str, strategy: Optional[str] = None) -> Optional[dict]:
        """Gatilho sintético para testes (--test-flow): usa o viés da EMA20 vs EMA50."""
        strategy = strategy or agent_id
        df = self._prepare(symbol, settings.STRATEGY_TIMEFRAMES.get(strategy, settings.TIMEFRAME))
        if df is None:
            return None
        c = df.iloc[-1]
        bias = "BUY" if c["ema20"] >= c["ema50"] else "SELL"
        return self._snapshot(symbol, agent_id, strategy, TRIGGER_NAMES[strategy] + "_FORCED_TEST", bias, df)
