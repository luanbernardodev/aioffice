"""Testes de Validação da Estratégia SMC (Smart Money Concepts) - Liquidity Sweep (Falso Rompimento).
Testa:
1. Contexto: Mapeamento de Zonas de Liquidez (BSL / SSL / Resistência / Suporte ignorando os últimos 2 candles).
2. Direção: Gatilho de Compra (Spring) e Gatilho de Venda (Upthrust) via pavio vs corpo.
3. Força: Volume Spike (>= 1.3x) e Micro-Exaustão RSI (Golden Ticket force_execute = True).
4. Integração do Sentinela e Repasse de Rationale Institucional para trades_history.
"""

import unittest
import numpy as np
import pandas as pd

from strategies.smc_logic import map_liquidity_zones, detect_liquidity_sweep, SMCAnalysisResult
from core.sentinel import compute_indicators, analyze_market, Sentinel
from core.mt5_bridge import MT5Bridge
from core.database import DatabaseManager


def build_synthetic_df(n: int = 120, base_price: float = 100.0) -> pd.DataFrame:
    """Gera dataframe sintético com n candles para testes técnicos."""
    dates = pd.date_range("2026-01-01 00:00:00", periods=n, freq="15min")
    rng = np.random.default_rng(42)

    # Cria canal lateral estável entre 95 e 105
    closes = base_price + np.sin(np.linspace(0, 10, n)) * 4.0
    highs = closes + 1.0
    lows = closes - 1.0
    opens = closes + rng.normal(0, 0.2, n)
    volumes = np.full(n, 100.0)

    df = pd.DataFrame({
        "time": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "tick_volume": volumes,
    })
    return df


class TestSMCStrategy(unittest.TestCase):

    def test_1_context_liquidity_mapping(self):
        """1. Contexto: Verifica cálculo de BSL e SSL das últimas 50 barras ignorando os 2 últimos candles."""
        df = build_synthetic_df(100, base_price=100.0)
        df_mapped = map_liquidity_zones(df, window=50)

        # Colunas devem estar presentes no dataframe
        for col in ["bsl", "ssl", "resistance", "support"]:
            self.assertIn(col, df_mapped.columns)

        # Verifica se ignora os últimos 2 candles
        # Vamos injetar um pico extremo nos 2 últimos candles e checar que a resistência não subiu para esse valor
        last_idx = len(df) - 1
        df.loc[last_idx - 1, "high"] = 999.0  # penúltimo candle (shift 1)
        df.loc[last_idx, "high"] = 999.0      # último candle (shift 0)

        df_mapped2 = map_liquidity_zones(df, window=50)
        res_last = df_mapped2.iloc[-1]["resistance"]

        # O nível de resistência estabelecida deve ser menor que 900.0 porque os últimos 2 candles são ignorados
        self.assertLess(res_last, 900.0, "Resistência não deve ser contaminada pelos últimos 2 candles!")

    def test_2_buy_sweep_spring(self):
        """2. Direção: Gatilho de COMPRA (Spring / Sweep de Fundo).
        Mínima perfura Suporte, Fechamento acima do Suporte, Pavio inferior longo, Volume >= 1.3x."""
        df = build_synthetic_df(80, base_price=100.0)
        df = compute_indicators(df)

        # Suporte estabelecido nas barras anteriores
        support_level = float(df.iloc[-1]["support"])

        # Configura o candle fechado para um Spring perfeito:
        # Perfura suporte (low < support), fecha acima (close > support) com pavio inferior proeminente
        last_idx = len(df) - 1
        df.loc[last_idx, "open"] = support_level + 1.0
        df.loc[last_idx, "high"] = support_level + 1.2
        df.loc[last_idx, "low"] = support_level - 1.5   # Perfura fundo (Sweep de liquidez institucional)
        df.loc[last_idx, "close"] = support_level + 0.8  # Fecha ACIMA do suporte
        df.loc[last_idx, "tick_volume"] = 250.0          # Volume spike (2.5x a média de 100)
        df.loc[last_idx, "vol_ma20"] = 100.0
        df.loc[last_idx, "vol_ratio"] = 2.5
        df.loc[last_idx, "rsi"] = 32.0                   # Micro-exaustão (< 35)

        bias, force_execute, details = detect_liquidity_sweep(df, window=50, min_vol_ratio=1.3)

        self.assertEqual(bias, "BUY")
        self.assertTrue(force_execute, "RSI < 35 deve conceder Golden Ticket (force_execute=True)")
        self.assertEqual(details["pattern"], "SPRING_BUY")
        self.assertIn("False Breakout - Liquidity Sweep (Volume:", details["rationale"])

    def test_3_sell_sweep_upthrust(self):
        """2. Direção: Gatilho de VENDA (Upthrust / Sweep de Topo).
        Máxima perfura Resistência, Fechamento abaixo da Resistência, Pavio superior longo, Volume >= 1.3x."""
        df = build_synthetic_df(80, base_price=100.0)
        df = compute_indicators(df)

        res_level = float(df.iloc[-1]["resistance"])

        last_idx = len(df) - 1
        df.loc[last_idx, "open"] = res_level - 1.0
        df.loc[last_idx, "high"] = res_level + 1.5   # Perfura topo (Sweep de liquidez institucional)
        df.loc[last_idx, "low"] = res_level - 1.2
        df.loc[last_idx, "close"] = res_level - 0.8  # Fecha ABAIXO da resistência
        df.loc[last_idx, "tick_volume"] = 200.0
        df.loc[last_idx, "vol_ma20"] = 100.0
        df.loc[last_idx, "vol_ratio"] = 2.0
        df.loc[last_idx, "rsi"] = 68.0               # Micro-exaustão (> 65)

        bias, force_execute, details = detect_liquidity_sweep(df, window=50, min_vol_ratio=1.3)

        self.assertEqual(bias, "SELL")
        self.assertTrue(force_execute, "RSI > 65 deve conceder Golden Ticket (force_execute=True)")
        self.assertEqual(details["pattern"], "UPTHRUST_SELL")
        self.assertIn("False Breakout - Liquidity Sweep (Volume: 2.0x)", details["rationale"])

    def test_4_volume_strength_validation(self):
        """3. Força: Sem volume >= 1.3x, o falso rompimento não deve ser validado."""
        df = build_synthetic_df(80, base_price=100.0)
        df = compute_indicators(df)

        support_level = float(df.iloc[-1]["support"])
        last_idx = len(df) - 1
        df.loc[last_idx, "open"] = support_level + 1.0
        df.loc[last_idx, "high"] = support_level + 1.2
        df.loc[last_idx, "low"] = support_level - 1.5
        df.loc[last_idx, "close"] = support_level + 0.8
        # Volume FRACO: apenas 1.1x (abaixo do limiar institucional de 1.3x)
        df.loc[last_idx, "tick_volume"] = 110.0
        df.loc[last_idx, "vol_ma20"] = 100.0
        df.loc[last_idx, "vol_ratio"] = 1.1
        df.loc[last_idx, "rsi"] = 40.0

        bias, force_execute, details = detect_liquidity_sweep(df, window=50, min_vol_ratio=1.3)
        self.assertIsNone(bias, "Falso rompimento sem volume institucional >= 1.3x deve ser descartado!")

    def test_5_sentinel_rationale_and_execution_logging(self):
        """4. Sentinel e Repasse: Confirma que analyze_market e o Sentinel formatam e transmitem o rationale."""
        df = build_synthetic_df(80, base_price=100.0)
        df = compute_indicators(df)

        support_level = float(df.iloc[-1]["support"])
        last_idx = len(df) - 1
        df.loc[last_idx, "open"] = support_level + 1.0
        df.loc[last_idx, "high"] = support_level + 1.2
        df.loc[last_idx, "low"] = support_level - 1.5
        df.loc[last_idx, "close"] = support_level + 0.8
        df.loc[last_idx, "tick_volume"] = 260.0
        df.loc[last_idx, "vol_ma20"] = 100.0
        df.loc[last_idx, "vol_ratio"] = 2.6
        df.loc[last_idx, "rsi"] = 30.0

        res = analyze_market(df)
        self.assertEqual(res.bias, "BUY")
        self.assertTrue(res.force_execute)

        # Testa compatibilidade de desempacotamento de 2 valores (legado)
        bias, force = analyze_market(df)
        self.assertEqual(bias, "BUY")
        self.assertTrue(force)

        # Testa registro em trades_history no Database
        bridge = MT5Bridge(mock=True)
        db = DatabaseManager()
        sentinel = Sentinel(bridge, db)
        snap = sentinel._snapshot("BTCUSD", "ops_beta", "ops_beta", "FALSE_BREAKOUT_SWEEP", "BUY", df,
                                  force_execute=True, details=res.details)

        self.assertIn("False Breakout - Liquidity Sweep (Volume:", snap["rationale"])
        self.assertIn("support", snap)
        self.assertIn("resistance", snap)

        trade_logged = db.log_trade(
            "ops_beta", "BTCUSD", "BUY", 0.05, 100.0, 95.0, 110.0, 50.0,
            confidence=95, rationale=snap["rationale"], dry_run=True
        )
        self.assertIn("False Breakout - Liquidity Sweep", trade_logged.get("technical_rationale", ""))
        print(f"\n[OK] Trade Logged Technical Rationale: {trade_logged.get('technical_rationale')}")


if __name__ == "__main__":
    unittest.main()
