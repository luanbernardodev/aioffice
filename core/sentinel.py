"""Sentinela: motor matemático de custo zero (pandas/numpy). Só emite dados quando há gatilho real."""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import settings
from core.mt5_bridge import MT5Bridge
from core import derivatives_collector

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
    out["rsi"] = rsi(out["close"], 14)
    out["ema9"], out["ema21"] = ema(out["close"], 9), ema(out["close"], 21)
    out["ema20"], out["ema50"], out["ema200"] = (ema(out["close"], p) for p in (20, 50, 200))
    out["atr"] = atr(out, 14)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger(out["close"], 20, 2.0)
    out["bandwidth"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"]
    out["adx"] = adx(out, 14)
    out["vwap"] = vwap(out)
    out["vol_ratio"] = out["volume"] / out["volume"].rolling(20).mean().shift(1)
    return out


# -------------------------------------------------------- TRIPLE CHECK OBRIGATÓRIO
def check_indecision_filters(df: pd.DataFrame, direction: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Triple Check Obrigatório contra Zonas de Indecisão (Chop/Ruído Lateral):
    PONTO 1: Exaustão Institucional (BUY se RSI < 20, SELL se RSI > 85).
             Se 20 <= RSI <= 85, aborta: 'Abortado: Mercado em zona de indecisão (RSI Neutro)'.
    PONTO 2: Filtro Anti-Lateralização (ADX > 25).
             Se ADX <= 25, aborta: 'Abortado: Falta de força direcional (ADX Baixo)'.
    PONTO 3: Rejeição ou Fluxo Institucional (Volume Spike >= 1.5x OU Pavio de Rejeição >= 60%).
             Se nenhum dos dois for satisfeito, aborta.
    Retorna: (aprovado: bool, motivo_aborto: Optional[str], detalhes_aprovacao: Optional[str])
    """
    if len(df) < 20:
        return False, "Abortado: Histórico insuficiente de velas", None

    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0
    adx_val = float(c["adx"]) if "adx" in c and not pd.isna(c["adx"]) else 0.0

    # 1. PONTO DE CONFIRMAÇÃO 1: EXAUSTÃO INSTITUCIONAL (REGRA DE OURO)
    if direction == "BUY":
        if rsi_val >= 20.0:
            return False, f"Abortado: Mercado em zona de indecisão (RSI Neutro)", None
    elif direction == "SELL":
        if rsi_val <= 85.0:
            return False, f"Abortado: Mercado em zona de indecisão (RSI Neutro)", None
    else:
        return False, f"Abortado: Direção inválida '{direction}'", None

    # 2. PONTO DE CONFIRMAÇÃO 2: FILTRO ANTI-LATERALIZAÇÃO (ADX > 25)
    if adx_val <= 25.0:
        return False, f"Abortado: Falta de força direcional (ADX Baixo)", None

    # 3. PONTO DE CONFIRMAÇÃO 3: REJEIÇÃO / FLUXO INSTITUCIONAL (Volume + Price Action)
    vol_ratio = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0
    has_vol_spike = vol_ratio >= 1.5

    rng = float(c["high"] - c["low"])
    wick_ratio = 0.0
    if rng > 1e-8:
        if direction == "BUY":
            lower_wick = float(min(c["open"], c["close"]) - c["low"])
            wick_ratio = lower_wick / rng
        else:
            upper_wick = float(c["high"] - max(c["open"], c["close"]))
            wick_ratio = upper_wick / rng

    has_wick_rejection = wick_ratio >= 0.60

    if not (has_vol_spike or has_wick_rejection):
        return False, f"Abortado: Ausência de fluxo institucional ou rejeição por pavio (Vol: {vol_ratio:.1f}x < 1.5x e Pavio: {wick_ratio*100:.0f}% < 60%)", None

    evidences = []
    if has_vol_spike:
        evidences.append(f"Volume Spike {vol_ratio:.1f}x")
    if has_wick_rejection:
        evidences.append(f"Pinbar {wick_ratio*100:.0f}%")
    evidence_str = " | ".join(evidences)

    details = f"RSI {rsi_val:.0f} | ADX {adx_val:.0f} | {evidence_str}"
    return True, None, details


# --------------------------------------------------------------------- gatilhos
def _check_alpha(df: pd.DataFrame) -> Optional[str]:
    """Tendência + Pullback Extremo: EMAs alinhadas a favor da tendência maior,
    com entrada estritamente no esgotamento do pullback validada pelo Triple Check."""
    c = df.iloc[-1]
    if c["ema20"] > c["ema50"] > c["ema200"]:
        ok, _, _ = check_indecision_filters(df, "BUY")
        if ok:
            return "BUY"
    elif c["ema20"] < c["ema50"] < c["ema200"]:
        ok, _, _ = check_indecision_filters(df, "SELL")
        if ok:
            return "SELL"
    return None


class SignalResult(str):
    """Representação de sinal com flag de autorização especial (Golden Ticket / force_execute)."""
    force_execute: bool = False

    def __new__(cls, val: str, force_execute: bool = False):
        obj = str.__new__(cls, val)
        obj.force_execute = force_execute
        return obj


def analyze_market(df: pd.DataFrame, strategy: str = "ops_beta") -> Tuple[Optional[str], bool]:
    """Análise quantitativa de sinal para agentes de reversão (Setor 1):
    - Sinal de Compra: Se RSI <= 30.
    - Sinal de Venda: Se RSI >= 70.
    - Bypass de Veto (Golden Ticket): Se qualquer uma destas duas condições for atingida,
      retorna force_execute = True (autorização suprema para entrar, ignorando vetos dos Setores 2 e 3).
    Retorna: (bias: Optional[str], force_execute: bool)
    """
    if df is None or len(df) == 0:
        return None, False

    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0

    if rsi_val <= 30.0:
        return "BUY", True
    if rsi_val >= 70.0:
        return "SELL", True

    return None, False


def _check_beta(df: pd.DataFrame) -> Optional[SignalResult]:
    """Reversão à Média + Exaustão Institucional por RSI Agressivo (Agente Beta):
    - Gatilho de Compra: RSI <= 30 -> Golden Ticket (force_execute = True)
    - Gatilho de Venda: RSI >= 70 -> Golden Ticket (force_execute = True)
    """
    bias, force = analyze_market(df, strategy="ops_beta")
    if bias:
        return SignalResult(bias, force_execute=force)
    return None


def _check_gamma(df: pd.DataFrame) -> Optional[str]:
    """Rompimento / Breakout: Squeeze prévio de volatilidade rompendo em exaustão/pullback extremo."""
    if len(df) < 60:
        return None
    c = df.iloc[-1]
    window = df["bandwidth"].iloc[-120:].dropna()
    if len(window) < 60:
        return None
    squeezed = df["bandwidth"].iloc[-7:-1].min() <= window.quantile(0.20)
    expanding = c["atr"] > df["atr"].iloc[-4] * 1.03

    if squeezed and expanding:
        if c["close"] > c["bb_mid"]:
            ok, _, _ = check_indecision_filters(df, "BUY")
            if ok:
                return "BUY"
        if c["close"] < c["bb_mid"]:
            ok, _, _ = check_indecision_filters(df, "SELL")
            if ok:
                return "SELL"
    return None


def check_delta_strategy(df: pd.DataFrame, symbol: str = "BTCUSD") -> Tuple[bool, Optional[str]]:
    """Avaliação quantitativa condicional da estratégia Agente Delta V2:
    - Cripto (BTC, ETH, SOL): Coletor de derivativos Binance Futures (Funding Rate) + RSI < 20 + Volume Spike > 1.5.
    - Ouro/Forex (XAUUSD, etc.): SMC Tradicional (RSI < 20 + ADX > 25 + Volume Spike > 1.5).
    """
    if len(df) < 20:
        return False, None
    c = df.iloc[-1]
    rsi_val = float(c["rsi"]) if "rsi" in c and not pd.isna(c["rsi"]) else 50.0
    adx_val = float(c["adx"]) if "adx" in c and not pd.isna(c["adx"]) else 0.0
    volume_spike = float(c["vol_ratio"]) if "vol_ratio" in c and not pd.isna(c["vol_ratio"]) else 1.0

    if symbol in ["BTCUSD", "ETHUSD", "SOLUSD"]:
        # É Cripto! Invoca o coletor de derivativos
        deriv_data = derivatives_collector.get_crypto_derivatives(symbol)
        # Se RSI < 20 (Exaustão) + Volume Spike + Funding Rate muito positivo (Retalho alavancado em Long)
        if rsi_val < 20 and volume_spike > 1.5 and deriv_data.get("is_euphoric"):
            return True, "Gatilho de Liquidation Sweep (Squeeze Institucional)"
    else:
        # É Ouro ou Forex! Mantém a estratégia SMC tradicional (FVG + Order Block + Triple Check)
        if rsi_val < 20 and adx_val > 25 and volume_spike > 1.5:
            return True, "SMC Clássico"

    return False, None


def _check_delta(df: pd.DataFrame, symbol: str = "BTCUSD") -> Optional[str]:
    """SMC Scalper / Liquidation Sweep (Agente Delta V2):
    Varredura de liquidez com desvio condicional Cripto vs Forex/Ouro.
    """
    triggered, reason = check_delta_strategy(df, symbol=symbol)
    if triggered:
        log.info("[Ops Delta] %s disparou: %s", symbol, reason)
        return "BUY"

    # Sweep de Fundo/Topo clássico como confluência de scalper
    if len(df) >= 30:
        swing = df.iloc[-23:-3]
        swing_low, swing_high = swing["low"].min(), swing["high"].max()

        # Sweep de Fundo (Liquidez abaixo de swing_low)
        if (df["low"].iloc[-3:] < swing_low).any():
            ok, _, _ = check_indecision_filters(df, "BUY")
            if ok:
                return "BUY"

        # Sweep de Topo (Liquidez acima de swing_high)
        if (df["high"].iloc[-3:] > swing_high).any():
            ok, _, _ = check_indecision_filters(df, "SELL")
            if ok:
                return "SELL"
    return None


def _check_epsilon(df: pd.DataFrame) -> Optional[str]:
    """Scalper VWAP + Momentum: Alinhamento da VWAP confirmado pelo Triple Check institucional."""
    if len(df) < 30:
        return None
    c = df.iloc[-1]
    price = float(c["close"])
    vwap_val = float(c["vwap"]) if c["vwap"] is not None and not pd.isna(c["vwap"]) else price

    if price >= vwap_val:
        ok, _, _ = check_indecision_filters(df, "BUY")
        if ok:
            return "BUY"
    elif price <= vwap_val:
        ok, _, _ = check_indecision_filters(df, "SELL")
        if ok:
            return "SELL"
    return None


# Chaves = estratégia-base (clones herdam a estratégia via agents_status.strategy_type)
CHECKS = {"ops_alpha": _check_alpha, "ops_beta": _check_beta, "ops_gamma": _check_gamma,
          "ops_delta": _check_delta, "ops_epsilon": _check_epsilon}
TRIGGER_NAMES = {"ops_alpha": "TREND_PULLBACK", "ops_beta": "EXHAUSTION_REVERSAL",
                 "ops_gamma": "VOLATILITY_BREAKOUT", "ops_delta": "LIQUIDITY_SWEEP_FVG",
                 "ops_epsilon": "VWAP_MOMENTUM"}


def _num(row: pd.Series, key: str, digits: int = 5) -> Optional[float]:
    v = row.get(key)
    return None if v is None or pd.isna(v) else round(float(v), digits)


def check_vaccines(agent_id: str, bias: str, df: pd.DataFrame,
                   vaccines: List[Dict[str, Any]]) -> Optional[str]:
    """Avalia se o gatilho matemático infringe alguma vacina pós-morte ativa.
    Retorna o motivo do aborto se violar, ou None se estiver liberado para operar.
    """
    if not vaccines:
        return None

    c = df.iloc[-1]
    indicators = {
        "RSI": float(c.get("rsi") if c.get("rsi") is not None and not pd.isna(c.get("rsi")) else 50.0),
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
            source = str(vac.get("source_agent") or "Gamma").replace("ops_", "").title()
            desc = vac.get("description") or f"{ind_name} {op} {threshold}"
            return f"Vacina Pós-Morte do Agente {source} ({desc})"

    return None


class Sentinel:
    def __init__(self, bridge: MT5Bridge, db: Optional[Any] = None) -> None:
        self.bridge = bridge
        self.db = db
        self._last_signal: Dict[tuple, str] = {}  # evita reacionar ao mesmo candle

    def _snapshot(self, symbol: str, agent_id: str, strategy: str, trigger: str, bias: str,
                  df: pd.DataFrame, force_execute: bool = False) -> dict:
        c = df.iloc[-1]
        return {
            "symbol": symbol, "agent_id": agent_id, "strategy": strategy, "trigger": trigger, "bias": bias,
            "force_execute": force_execute,
            "timeframe": settings.STRATEGY_TIMEFRAMES.get(strategy, settings.TIMEFRAME),
            "candle_time": str(c["time"]),
            "price": round(float(c["close"]), 5), "atr": round(float(c["atr"]), 5),
            "rsi": round(float(c["rsi"]), 2), "adx": round(float(c["adx"]), 2),
            "ema9": _num(c, "ema9"), "ema21": _num(c, "ema21"),
            "ema20": round(float(c["ema20"]), 5), "ema50": round(float(c["ema50"]), 5),
            "ema200": round(float(c["ema200"]), 5), "bb_upper": round(float(c["bb_upper"]), 5),
            "bb_lower": round(float(c["bb_lower"]), 5), "bandwidth": round(float(c["bandwidth"]), 5),
            "vwap": _num(c, "vwap"), "vol_ratio": _num(c, "vol_ratio", 2),
            "candle": {k: round(float(c[k]), 5) for k in ("open", "high", "low", "close")},
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
        """`active_agents`: {agent_id: estratégia-base}. Retorna gatilhos validados e imunizados."""
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
            try:
                check_res = check(df, symbol=symbol)
            except TypeError:
                check_res = check(df)

            force_execute = False
            if isinstance(check_res, tuple):
                bias, force_execute = check_res
            elif hasattr(check_res, "force_execute"):
                bias = str(check_res)
                force_execute = bool(check_res.force_execute)
            else:
                bias = check_res

            # Heartbeat Verbose Logging: Imprime distância do preço para o gatilho se VERBOSE_LOGS=True
            if getattr(settings, "VERBOSE_LOGS", True):
                self._log_strategy_proximity(agent_id, strategy, symbol, df, bias)

            if bias:
                label = agent_id.replace("ops_", "Ops ").title()

                # 1. Validação de Filtros ou Bypass de Veto (Golden Ticket)
                if force_execute:
                    approved = True
                    details = f"RSI {float(df.iloc[-1].get('rsi', 50)):.1f} [GOLDEN TICKET / PASSE LIVRE]"
                    log.info("[%s] %s -> GOLDEN TICKET ATIVADO (%s): Bypass total de indecisão e vetos!",
                             label, symbol, details)
                else:
                    # Blindagem Obrigatória: Validação Final Confluente do Triple Check
                    approved, abort_reason, details = check_indecision_filters(df, bias)
                    if not approved:
                        log.info("[%s] %s -> %s", label, symbol, abort_reason)
                        continue

                # 2. Checagem rigorosa de Vacinas Pós-Morte do Setor 3 (ignorada sob Golden Ticket)
                if not force_execute:
                    vaccines = []
                    if agent_params and agent_id in agent_params:
                        vaccines = agent_params[agent_id].get("vaccines") or []
                    elif self.db:
                        vaccines = self.db.get_strategy_params(agent_id).get("vaccines") or []

                    vaccine_abort = check_vaccines(agent_id, bias, df, vaccines)
                    if vaccine_abort:
                        log.warning("[%s] Gatilho acionado, mas ABORTADO pela %s.", label, vaccine_abort)
                        continue

                # 3. Log Limpo e Vitorioso
                order_desc = "Compra" if bias == "BUY" else "Venda"
                log.info("[%s] GATILHO APROVADO: %s -> Ordem de %s enviada! (force_execute=%s)",
                         label, details, order_desc, force_execute)

                if self._last_signal.get((symbol, agent_id)) != candle_time:
                    self._last_signal[(symbol, agent_id)] = candle_time
                    triggers.append(self._snapshot(symbol, agent_id, strategy,
                                                   TRIGGER_NAMES.get(strategy, "SIGNAL"),
                                                   bias, df, force_execute=force_execute))
        return triggers

    def _log_strategy_proximity(self, agent_id: str, strategy: str, symbol: str,
                                df: pd.DataFrame, bias: Optional[str]) -> None:
        """Imprime a telemetria quantitativa e distância para os gatilhos matemáticos."""
        c = df.iloc[-1]
        price = float(c["close"])

        if strategy == "ops_delta":
            swing = df.iloc[-23:-3]
            swing_low = float(swing["low"].min())
            swing_high = float(swing["high"].max())
            dist_low = ((price - swing_low) / price) * 100
            dist_high = ((swing_high - price) / price) * 100
            min_dist = min(abs(dist_low), abs(dist_high))
            if bias:
                log.info("[Ops Delta] %s GATILHO DETECTADO! Bias=%s (Preço: %.2f) -> Disparando", symbol, bias, price)
            else:
                if symbol in ["BTCUSD", "ETHUSD", "SOLUSD"]:
                    deriv = derivatives_collector.get_crypto_derivatives(symbol)
                    fr = deriv.get("funding_rate", 0.0)
                    log.info("[Ops Delta] %s Cripto Derivativos (Funding: %.6f | Euforia: %s | RSI: %.1f) -> Abortado",
                             symbol, fr, deriv.get("is_euphoric"), float(c.get("rsi") or 50.0))
                else:
                    log.info("[Ops Delta] %s SMC Clássico (Falta %.2f%% para o fundo/topo) -> Abortado", symbol, min_dist)

        elif strategy == "ops_alpha":
            ema20 = float(c["ema20"])
            dist_ema = ((price - ema20) / price) * 100
            adx_val = float(c["adx"])
            if bias:
                log.info("[Ops Alpha] %s PULLBACK DETECTADO! Bias=%s -> Disparando", symbol, bias)
            else:
                log.info("[Ops Alpha] %s monitorando Trend (Distância EMA20: %+.2f%% | ADX: %.1f) -> Abortado",
                         symbol, dist_ema, adx_val)

        elif strategy == "ops_beta":
            rsi_val = float(c["rsi"])
            bb_upper = float(c["bb_upper"])
            bb_lower = float(c["bb_lower"])
            if bias:
                log.info("[Ops Beta] %s Monitorando Reversão + Exaustão (RSI: %.1f) -> GATILHO DISPARADO (%s)",
                         symbol, rsi_val, bias)
            else:
                log.info("[Ops Beta] %s Monitorando Reversão + Exaustão (RSI: %.1f [Bandas: %.2f / %.2f]) -> Aguardando Gatilho",
                         symbol, rsi_val, bb_lower, bb_upper)

        elif strategy == "ops_gamma":
            bw = float(c["bandwidth"])
            atr_val = float(c["atr"])
            if bias:
                log.info("[Ops Gamma] %s BREAKOUT DETECTADO! Bias=%s -> Disparando", symbol, bias)
            else:
                log.info("[Ops Gamma] %s monitorando Breakout (Bandwidth: %.4f | ATR: %.2f) -> Abortado",
                         symbol, bw, atr_val)

        elif strategy == "ops_epsilon":
            vwap_val = float(c["vwap"]) if c["vwap"] is not None and not pd.isna(c["vwap"]) else price
            dist_vwap = ((price - vwap_val) / price) * 100
            vol_ratio = float(c["vol_ratio"]) if c["vol_ratio"] is not None and not pd.isna(c["vol_ratio"]) else 1.0
            if bias:
                log.info("[Ops Epsilon] %s VWAP MOMENTUM DETECTADO! Bias=%s -> Disparando", symbol, bias)
            else:
                log.info("[Ops Epsilon] %s monitorando VWAP (Distância: %+.2f%% | Vol: %.2fx) -> Abortado",
                         symbol, dist_vwap, vol_ratio)

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
