"""Coletor de Derivativos de Criptomoedas (Binance Futures).
Extrai métricas públicas (sem necessidade de API Key) como Funding Rate para aferir
o sentimento e alavancagem do retalho em busca de gatilhos de Liquidation Sweep.
"""
import logging
import time
from typing import Dict, Any, Optional
import requests

log = logging.getLogger("derivatives_collector")

# Endpoint oficial público de dados de mercado da Binance Futures (USDT-M)
BINANCE_PREMIUM_INDEX_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

# Cache em memória simples para evitar spam de requisições a cada tick (TTL de 10 segundos)
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SEC = 10.0


def _normalize_binance_symbol(symbol: str) -> str:
    """Normaliza símbolos internos (ex: 'BTCUSD', 'BTC', 'BTCUSDT') para o formato da Binance Futures ('BTCUSDT')."""
    clean = str(symbol).upper().strip().replace("/", "")
    if clean.endswith("USDT"):
        return clean
    if clean.endswith("USD"):
        clean = clean[:-3]
    return f"{clean}USDT"


def get_crypto_derivatives(symbol: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Extrai métricas de derivativos da Binance Futures para o ativo especificado.
    
    Retorna:
        dict: {
            "funding_rate": float,
            "is_euphoric": bool  # funding_rate > 0.0001 (0.01% por período de 8h = retalho fortemente long)
        }
    """
    binance_symbol = _normalize_binance_symbol(symbol)
    now = time.time()

    # Verifica cache válido
    cached = _CACHE.get(binance_symbol)
    if cached and (now - cached["timestamp"]) < _CACHE_TTL_SEC:
        return cached["data"]

    fallback_result = {"funding_rate": 0.0, "is_euphoric": False}

    try:
        url = f"{BINANCE_PREMIUM_INDEX_URL}?symbol={binance_symbol}"
        response = requests.get(url, timeout=timeout)
        
        if response.status_code == 200:
            data = response.json()
            raw_rate = data.get("lastFundingRate")
            if raw_rate is not None:
                funding_rate = float(raw_rate)
                is_euphoric = funding_rate > 0.0001  # > 0.01% indica euforia alavancada em compras
                result = {
                    "funding_rate": funding_rate,
                    "is_euphoric": is_euphoric,
                }
                # Atualiza cache
                _CACHE[binance_symbol] = {"data": result, "timestamp": now}
                return result
            else:
                log.warning("Campo 'lastFundingRate' não encontrado na resposta da Binance para %s", binance_symbol)
        else:
            log.warning("Binance Futures retornou status %d para %s: %s", response.status_code, binance_symbol, response.text)

    except requests.exceptions.Timeout:
        log.warning("Timeout ao consultar derivativos na Binance Futures para %s", binance_symbol)
    except requests.exceptions.RequestException as req_err:
        log.warning("Erro de rede ao consultar derivativos para %s: %s", binance_symbol, req_err)
    except Exception as exc:
        log.error("Exceção inesperada ao extrair derivativos para %s: %s", binance_symbol, exc)

    return fallback_result
