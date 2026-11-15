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


def test_one_position_per_symbol_direction_when_enabled():
    m = FakeMT5(equity=1000.0, balance=1000.0)
    own = [pos(side=-1, sl=64100.0)]
    cfg = {"um_por_direcao": True, "sem_duplicata": False}
    assert "já há posição vendedora" in pf(m, cfg, own=own).check("BTCUSD", -1, 64000.0, 64200.0, 0.01)
    assert pf(m, cfg, own=own).check("BTCUSD", 1, 64000.0, 63800.0, 0.01) == ""


def test_daily_loss_blocks_new_entries():
    m = FakeMT5(equity=130.0, balance=140.0)                                        # -10 flutuante
    assert "perda do dia" in pf(m, {"perda_diaria_pct": 6.0}).check("GOLD", 1, 3880.0, 3879.0, 0.01)
    assert pf(m, {"perda_diaria_pct": 10.0}).check("GOLD", 1, 3880.0, 3879.0, 0.01) == ""


def test_config_has_risk_block_and_single_orderflow_slot():
    from agents.v3_agent import load_group_caps, load_risk_config
    r = load_risk_config()
    assert r["max_risco_trade_pct"] <= 8 and r["max_risco_aberto_pct"] <= 10 and r["sem_duplicata"] is True
    assert r["isentos_grupos"] == ["orderflow_btc"]
    assert load_group_caps() == {"orderflow_btc": 3}



def mpos(side, entry, sl, magic, ticket, symbol="BTCUSD"):
    p = pos(symbol=symbol, side=side, entry=entry, sl=sl, ticket=ticket)
    p.magic = magic
    return p


def test_duplicate_same_side_and_price_is_blocked_first_one_stays():
    m = FakeMT5(positions=[mpos(-1, 64004.85, 66000.0, 20261136, 11)], equity=1000.0, balance=1000.0)
    why = pf(m).check("BTCUSD", -1, 64010.0, 66000.0, 0.01, a0=900.0, spread=40.0)     # tolerância 90
    assert why.startswith("duplicata") and "#11" in why
    assert pf(m).check("BTCUSD", -1, 64300.0, 66000.0, 0.01, a0=900.0, spread=40.0) == ""   # outro preço: abre
    assert pf(m).check("BTCUSD", 1, 64004.85, 63000.0, 0.01, a0=900.0, spread=40.0) == ""   # outra direção: abre
    assert pf(m).check("BTCUSD", -1, 64050.0, 66000.0, 0.01, a0=0.0, spread=40.0).startswith("duplicata")  # mín. 2x spread


def test_exempt_group_skips_risk_caps_and_is_out_of_others_open_risk():
    m = FakeMT5(positions=[mpos(-1, 64004.85, 66000.0, 20261136, k) for k in (1, 2, 3)], equity=140.0, balance=140.0)
    cfg = {"isentos_grupos": ["orderflow_btc"]}
    p = Portfolio(m, cfg, agents_positions=lambda: [], clock=lambda: NOW, exempt_magics={20261136})
    assert p.check("BTCUSD", 1, 65000.0, 62600.0, 0.01, group="orderflow_btc", a0=900.0) == ""   # US$24 > 8%: isento
    assert "risco do trade" in p.check("BTCUSD", 1, 65000.0, 62600.0, 0.01, group=None, a0=900.0)
    assert p.open_risk() == 0.0                                                                   # isentos fora da soma
    assert p.check("GOLD", 1, 3880.0, 3877.0, 0.01) == ""                                          # v4 opera normal
