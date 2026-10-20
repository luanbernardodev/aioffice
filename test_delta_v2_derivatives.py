"""Teste unitário da estratégia Agente Delta V2 e Coletor de Derivativos."""
import pandas as pd
import numpy as np
from unittest.mock import patch
from core.sentinel import check_delta_strategy, _check_delta
from core.derivatives_collector import get_crypto_derivatives


def create_candle_df(rsi=15.0, adx=30.0, vol_ratio=2.0):
    """Cria DataFrame sintético com indicadores pré-calculados."""
    n = 35
    df = pd.DataFrame({
        "time": pd.date_range("2026-10-20 12:00", periods=n, freq="5min"),
        "open": np.linspace(100, 90, n),
        "high": np.linspace(101, 91, n),
        "low": np.linspace(99, 89, n),
        "close": np.linspace(100, 89.5, n),
        "volume": [100.0] * (n - 1) + [250.0],
        "rsi": [50.0] * (n - 1) + [rsi],
        "adx": [20.0] * (n - 1) + [adx],
        "vol_ratio": [1.0] * (n - 1) + [vol_ratio],
    })
    return df


def test_crypto_liquidation_sweep():
    df = create_candle_df(rsi=18.0, adx=15.0, vol_ratio=1.8)
    
    # 1. Mock de euforia no retalho (funding rate > 0.0001)
    with patch("core.derivatives_collector.get_crypto_derivatives") as mock_deriv:
        mock_deriv.return_value = {"funding_rate": 0.00025, "is_euphoric": True}
        ok, reason = check_delta_strategy(df, symbol="BTCUSD")
        assert ok is True, "Deveria ter disparado Liquidation Sweep para BTCUSD"
        assert "Liquidation Sweep" in reason, f"Razão incorreta: {reason}"
        print(f"[OK] Cripto Eufórica disparou com sucesso: {reason}")

        # Teste de viés _check_delta
        bias = _check_delta(df, symbol="BTCUSD")
        assert bias == "BUY", f"Deveria ter retornado viés BUY, obtido {bias}"
        print("[OK] _check_delta retornou viés BUY para Cripto em Liquidation Sweep")

    # 2. Mock sem euforia (funding rate normal)
    with patch("core.derivatives_collector.get_crypto_derivatives") as mock_deriv:
        mock_deriv.return_value = {"funding_rate": 0.00005, "is_euphoric": False}
        ok, reason = check_delta_strategy(df, symbol="BTCUSD")
        assert ok is False, "Não deveria ter disparado Liquidation Sweep sem euforia"
        print("[OK] Cripto sem euforia não disparou gatilho de sweep")


def test_gold_smc_classico():
    # 1. Setup SMC Clássico válido (RSI < 20, ADX > 25, Vol > 1.5)
    df_valid = create_candle_df(rsi=18.0, adx=28.0, vol_ratio=2.2)
    ok, reason = check_delta_strategy(df_valid, symbol="XAUUSD")
    assert ok is True, "Deveria ter disparado SMC Clássico para XAUUSD"
    assert reason == "SMC Clássico", f"Razão incorreta: {reason}"
    print(f"[OK] XAUUSD disparou com sucesso: {reason}")

    bias = _check_delta(df_valid, symbol="XAUUSD")
    assert bias == "BUY", f"Deveria ter retornado BUY para XAUUSD, obtido {bias}"
    print("[OK] _check_delta retornou viés BUY para XAUUSD em SMC Clássico")

    # 2. Setup inválido por falta de ADX (< 25)
    df_low_adx = create_candle_df(rsi=18.0, adx=19.0, vol_ratio=2.2)
    ok, reason = check_delta_strategy(df_low_adx, symbol="XAUUSD")
    assert ok is False, "Não deveria disparar SMC Clássico com ADX baixo"
    print("[OK] XAUUSD rejeitado com ADX baixo")


if __name__ == "__main__":
    test_crypto_liquidation_sweep()
    test_gold_smc_classico()
    print("\nTODOS OS TESTES DO AGENTE DELTA V2 PASSARAM COM SUCESSO!")
