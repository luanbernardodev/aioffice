"""Validação Quantitativa do Sistema de Gestão de Risco Ativa:
1. Dicionário de Controlo de Posições (Memória de Gestão - managed_positions)
2. Lógica de Break-Even e Realização Parcial (Alvo 1: 1.5x ATR a favor)
3. Fecho Dinâmico pelo RSI (Alvo Final para o restante do lote)
4. Limpeza de Memória (Remoção de tickets fechados para prevenir memory leaks)
"""
import sys
import unittest
from unittest.mock import MagicMock, patch
from config import settings

settings.DRY_RUN = True

from core.mt5_bridge import MT5Bridge, managed_positions
import main


class TestActiveRiskManagement(unittest.TestCase):
    def setUp(self):
        managed_positions.clear()
        self.bridge = MT5Bridge()
        self.bridge.mock = True

    def test_calculate_partial_volume(self):
        """Testa o cálculo e normalização do lote parcial (50%)."""
        # Volume padrão 0.10 -> 0.05
        vol_half = self.bridge.calculate_partial_volume("BTCUSD", 0.10)
        self.assertEqual(vol_half, 0.05)

        # Volume 0.05 -> 0.02 (arredondado para baixo pelo step 0.01)
        vol_half_odd = self.bridge.calculate_partial_volume("BTCUSD", 0.05)
        self.assertEqual(vol_half_odd, 0.02)

        # Volume mínimo 0.01 -> metade é 0.005 < min_lot (0.01) -> retorna 0.0
        vol_min = self.bridge.calculate_partial_volume("BTCUSD", 0.01)
        self.assertEqual(vol_min, 0.0)
        print("[OK] Teste 1: calculate_partial_volume normaliza corretamente o volume.")

    def test_mock_monitoring_break_even_and_partial(self):
        """Testa a execução de Parcial e Break-Even ao atingir Alvo 1 (1.5x ATR)."""
        mock_db = MagicMock()

        # Simula trade aberto no DB: BUY BTCUSD a 60,000 com volume 0.10
        ticket = 999001
        trade_data = {
            "id": ticket,
            "ticket_mt5": ticket,
            "symbol": "BTCUSD",
            "action": "BUY",
            "volume": 0.10,
            "entry_price": 60000.0,
            "sl": 59000.0,
            "tp": 0.0,
            "agent_id": "ops_beta",
        }
        mock_db.get_open_trades.return_value = [trade_data]

        # Simula preço atual subindo a favor: 60,500 (+500 pts)
        # ATR simulado = 100 pts -> 1.5x ATR = 150 pts. Como 500 >= 150, atinge Alvo 1.
        self.bridge.get_price = MagicMock(return_value=60500.0)
        self.bridge.get_current_atr = MagicMock(return_value=100.0)
        self.bridge.get_current_rsi = MagicMock(return_value=50.0)  # RSI neutro (não fecha)

        # 1. Executa monitoramento
        closed = self.bridge.monitor_open_positions_and_close(mock_db)

        # Valida que posição foi adicionada em managed_positions
        self.assertIn(ticket, managed_positions)
        self.assertTrue(managed_positions[ticket]["partial_taken"])
        self.assertTrue(managed_positions[ticket]["breakeven_set"])
        self.assertEqual(len(closed), 0)  # Não fechou tudo, apenas parcial

        # Verifica se atualizou o volume no DB para a metade remanescente (0.05)
        mock_db._update.assert_any_call("trades_history", {"volume": 0.05}, {"ticket_mt5": ticket})

        # Verifica se o SL foi movido para o Break-Even (entry_price + micro_spread)
        # Para BUY BTCUSD: micro_spread = max(60000 * 0.0002, 0.5) = 12.0 -> SL = 60012.0
        calls = [c[0] for c in mock_db._update.call_args_list]
        sl_updates = [c[1] for c in calls if "sl" in c[1]]
        self.assertTrue(len(sl_updates) > 0)
        new_sl = sl_updates[0]["sl"]
        self.assertGreater(new_sl, 60000.0)
        print(f"[OK] Teste 2: Alvo 1 atingido! Parcial executada (50%) e Break-Even setado para {new_sl}.")

    def test_rsi_dynamic_close_final_target_and_memory_cleanup(self):
        """Testa o Alvo Final por RSI dinâmico e a remoção do ticket de managed_positions."""
        mock_db = MagicMock()
        ticket = 999002

        # Posição já teve parcial e break-even ativados
        managed_positions[ticket] = {"partial_taken": True, "breakeven_set": True}

        trade_data = {
            "id": ticket,
            "ticket_mt5": ticket,
            "symbol": "BTCUSD",
            "action": "BUY",
            "volume": 0.05,
            "entry_price": 60000.0,
            "sl": 60012.0,
            "tp": 0.0,
            "agent_id": "ops_beta",
        }
        mock_db.get_open_trades.return_value = [trade_data]

        self.bridge.get_price = MagicMock(return_value=61000.0)
        self.bridge.get_current_atr = MagicMock(return_value=100.0)
        # RSI bate 62.0 (>= 60) -> Gatilho de Fecho Dinâmico Final para BUY
        self.bridge.get_current_rsi = MagicMock(return_value=62.0)

        closed = self.bridge.monitor_open_positions_and_close(mock_db)

        # Valida que posição foi encerrada
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["ticket"], ticket)
        self.assertIn("RSI_DYNAMIC_CLOSE_BUY", closed[0]["reason"])

        # Valida que ticket foi removido da memória managed_positions (sem vazamento de memória)
        self.assertNotIn(ticket, managed_positions)
        print("[OK] Teste 3: Fecho Dinâmico RSI (Alvo Final) acionado e ticket desalocado da memória.")

    def test_inactive_position_garbage_collection(self):
        """Testa a limpeza automática de tickets que foram encerrados externamente (ex: batendo no SL)."""
        mock_db = MagicMock()
        ticket_closed_by_sl = 999003
        managed_positions[ticket_closed_by_sl] = {"partial_taken": True, "breakeven_set": True}

        # get_open_trades agora retorna lista vazia (a corretora já fechou pelo SL)
        mock_db.get_open_trades.return_value = []

        self.bridge.monitor_open_positions_and_close(mock_db)

        # Valida que o ticket inativo foi purgado do dicionário
        self.assertNotIn(ticket_closed_by_sl, managed_positions)
        print("[OK] Teste 4: Limpeza contínua (Garbage Collection) de tickets inativos em managed_positions.")

    def test_trailing_stop_in_profit_buy(self):
        """Testa o avanço contínuo do Stop Loss no lucro (Trailing Stop) para COMPRA conforme o preço sobe."""
        mock_db = MagicMock()
        ticket = 999005
        # Posição já teve parcial e break-even (SL em 60012)
        managed_positions[ticket] = {"partial_taken": True, "breakeven_set": True, "trailing_sl": 60012.0}

        trade_data = {
            "id": ticket,
            "ticket_mt5": ticket,
            "symbol": "BTCUSD",
            "action": "BUY",
            "volume": 0.05,
            "entry_price": 60000.0,
            "sl": 60012.0,
            "tp": 0.0,
            "agent_id": "ops_alpha",
        }
        mock_db.get_open_trades.return_value = [trade_data]

        # Preço sobe para 60,800 (+800 pts a favor)
        # ATR = 100 -> trailing_dist = max(1.2 * 100, 60000 * 0.0025) = 150.0
        # trail_sl = 60800 - 150 = 60650.0 (> 60012.0, travando +650 pts de lucro!)
        self.bridge.get_price = MagicMock(return_value=60800.0)
        self.bridge.get_current_atr = MagicMock(return_value=100.0)
        self.bridge.get_current_rsi = MagicMock(return_value=50.0)  # RSI neutro

        closed = self.bridge.monitor_open_positions_and_close(mock_db)
        self.assertEqual(len(closed), 0)

        calls = [c[0] for c in mock_db._update.call_args_list]
        sl_updates = [c[1] for c in calls if "sl" in c[1]]
        self.assertTrue(len(sl_updates) > 0)
        final_sl = sl_updates[-1]["sl"]
        self.assertGreater(final_sl, 60012.0)
        self.assertGreater(final_sl, 60500.0)
        self.assertGreater(final_sl, trade_data["entry_price"])
        print(f"[OK] Teste 5: Trailing stop de COMPRA moveu SL no lucro para {final_sl} (Entrada: 60000, Preço atual: 60800).")

    def test_trailing_stop_in_profit_sell(self):
        """Testa o avanço contínuo do Stop Loss no lucro (Trailing Stop) para VENDA conforme o preço cai."""
        mock_db = MagicMock()
        ticket = 999006
        # Posição VENDA aberta a 3000.0, break-even setado em 2999.0
        managed_positions[ticket] = {"partial_taken": True, "breakeven_set": True, "trailing_sl": 2999.0}

        trade_data = {
            "id": ticket,
            "ticket_mt5": ticket,
            "symbol": "ETHUSD",
            "action": "SELL",
            "volume": 0.5,
            "entry_price": 3000.0,
            "sl": 2999.0,
            "tp": 0.0,
            "agent_id": "ops_beta",
        }
        mock_db.get_open_trades.return_value = [trade_data]

        # Preço cai para 2900.0 (+100 pts a favor da VENDA)
        # ATR = 10 -> trailing_dist = max(1.2 * 10, 3000 * 0.0025) = 12.0
        # trail_sl = 2900 + 12 = 2912.0 (< 2999.0, travando lucro na ponta vendedora!)
        self.bridge.get_price = MagicMock(return_value=2900.0)
        self.bridge.get_current_atr = MagicMock(return_value=10.0)
        self.bridge.get_current_rsi = MagicMock(return_value=50.0)  # RSI neutro

        closed = self.bridge.monitor_open_positions_and_close(mock_db)
        self.assertEqual(len(closed), 0)

        calls = [c[0] for c in mock_db._update.call_args_list]
        sl_updates = [c[1] for c in calls if "sl" in c[1]]
        self.assertTrue(len(sl_updates) > 0)
        final_sl = sl_updates[-1]["sl"]
        self.assertLess(final_sl, 2999.0)
        self.assertLess(final_sl, trade_data["entry_price"])
        print(f"[OK] Teste 6: Trailing stop de VENDA moveu SL no lucro para {final_sl} (Entrada: 3000, Preço atual: 2900).")


if __name__ == "__main__":
    unittest.main()
