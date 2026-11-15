"""Proteção de capital dos agentes v3/v4/of_btc (agents/v3_risk.py)."""
import types
from datetime import datetime, timezone

import pytest

from agents.v3_risk import Portfolio, position_risk

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def pos(symbol="BTCUSD", side=-1, entry=64004.85, sl=66000.0, vol=0.01, ticket=1):
    return types.SimpleNamespace(symbol=symbol, type=0 if side == 1 else 1, price_open=entry, sl=sl, volume=vol,
                                 ticket=ticket)


class FakeMT5:
    def __init__(self, positions=(), equity=100.0, balance=140.0, deals=()):
        self.p, self.equity, self.balance, self.d = list(positions), equity, balance, list(deals)

    def symbol_info(self, s):
        tv = {"BTCUSD": 0.01, "GOLD": 1.0, "US500Cash": 0.01}[s]
        return types.SimpleNamespace(trade_tick_size=0.01, trade_tick_value=tv, trade_tick_value_loss=tv)

    def positions_get(self):
        return self.p

    def account_info(self):
        return types.SimpleNamespace(equity=self.equity, balance=self.balance)

    def history_deals_get(self, *a):
        return self.d


def pf(mt5, cfg=None, own=()):
    return Portfolio(mt5, cfg or {}, agents_positions=lambda: list(own), clock=lambda: NOW)


def test_position_risk_values():
    m = FakeMT5()
    assert position_risk(m, pos()) == pytest.approx(19.95, abs=0.01)           # venda: SL 1995 acima x 0.01
    assert position_risk(m, pos(side=1, entry=100.0, sl=101.0)) == 0.0        # stop já protege lucro
    assert position_risk(m, pos(sl=0.0)) == float("inf")                      # sem SL


def test_trade_risk_cap_blocks_wide_stop():
    m = FakeMT5(equity=100.0, balance=100.0)
    assert "risco do trade" in pf(m).check("BTCUSD", 1, 65000.0, 63000.0, 0.01)   # US$20 > 5% de 100
    assert pf(m).check("BTCUSD", 1, 65000.0, 64700.0, 0.01) == ""                  # US$3 cabe


def test_account_open_risk_cap_counts_all_positions():
    m = FakeMT5(positions=[pos(ticket=k) for k in (1, 2, 3)], equity=97.0)        # 3 x 19.95 já abertos
    why = pf(m).check("GOLD", 1, 3880.0, 3877.0, 0.01)                            # +US$3
    assert "risco aberto da conta" in why


def test_one_position_per_symbol_direction():
    m = FakeMT5(equity=1000.0, balance=1000.0)
    own = [pos(side=-1, sl=64100.0)]
    assert "já há posição vendedora" in pf(m, own=own).check("BTCUSD", -1, 64000.0, 64200.0, 0.01)
    assert pf(m, own=own).check("BTCUSD", 1, 64000.0, 63800.0, 0.01) == ""


def test_daily_loss_blocks_new_entries():
    m = FakeMT5(equity=130.0, balance=140.0)                                        # -10 flutuante
    assert "perda do dia" in pf(m, {"perda_diaria_pct": 6.0}).check("GOLD", 1, 3880.0, 3879.0, 0.01)
    assert pf(m, {"perda_diaria_pct": 10.0}).check("GOLD", 1, 3880.0, 3879.0, 0.01) == ""


def test_config_has_risk_block_and_single_orderflow_slot():
    from agents.v3_agent import load_group_caps, load_risk_config
    r = load_risk_config()
    assert r["max_risco_trade_pct"] <= 5 and r["max_risco_aberto_pct"] <= 10 and r["um_por_direcao"] is True
    assert load_group_caps() == {"orderflow_btc": 1}
