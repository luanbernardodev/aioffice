"""Sincronização MT5 -> Supabase (sem rede: sessão HTTP falsa; MT5 falso; nada vai ao Supabase real)."""
import json
import types
from datetime import datetime, timezone

import pytest

import agents.auditor_mt5 as aud
from agents.supabase_sync import SupabaseSync, group_of, push_auditor_analysis


class FakeResp:
    def __init__(self, code=201, body=""):
        self.status_code, self.text = code, body

    def json(self):
        return json.loads(self.text) if self.text else None


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append((method, url.split("/rest/v1/")[1], json.loads(data) if data else None, headers.get("Prefer")))
        return FakeResp()

    def post(self, url, headers=None, data=None, timeout=None):
        self.calls.append(("POST", url.split("/rest/v1/")[1], json.loads(data), headers.get("Prefer")))
        return FakeResp()


def srv(h, m=0, d=20):
    import calendar
    return calendar.timegm((2026, 11, d, h + 2, m, 0))     # relógio do servidor (UTC+2 em novembro)


def deal(pos, entry, typ, magic, price, t, profit=0.0, comment="", reason=3, symbol="US500Cash", vol=0.1):
    return types.SimpleNamespace(position_id=pos, entry=entry, type=typ, magic=magic, price=price, time=t, profit=profit,
                                 swap=0.0, commission=0.0, comment=comment, reason=reason, symbol=symbol, volume=vol)


class FakeMT5:
    def __init__(self, deals=(), positions=()):
        self.d, self.p = list(deals), list(positions)

    def account_info(self):
        return types.SimpleNamespace(balance=100.0, equity=98.5, margin_free=90.0, margin_level=900.0, trade_mode=0)

    def history_deals_get(self, *a, **k):
        return self.d

    def positions_get(self, *a, **k):
        return self.p

    def last_error(self):
        return (0, "")


DEALS = [deal(1, 0, 1, 20261107, 7600.0, srv(15), comment="A3|BOS_RETEST"),                       # engine A3 venda
         deal(1, 1, 0, 20261107, 7550.0, srv(16), profit=5.0, reason=5),
         deal(2, 0, 0, 777777, 1.0, srv(15), comment="legado"), deal(2, 1, 1, 777777, 1.0, srv(16), profit=-9.0),
         deal(3, 0, 0, 0, 1.0, srv(15)), deal(3, 1, 1, 0, 1.0, srv(16), profit=-7.0),               # manual
         deal(4, 0, 0, 20261116, 3880.0, srv(1), symbol="GOLD", vol=0.01),
         deal(4, 1, 1, 20261116, 3870.0, srv(2), profit=-10.0, reason=4, symbol="GOLD", vol=0.01)]
OPEN = [types.SimpleNamespace(ticket=9, magic=20261126, comment="V3|v4_btc_rsipb_h1", symbol="BTCUSD", type=0, volume=0.01,
                              price_open=65000.0, sl=63000.0, tp=65500.0, price_current=65200.0, profit=2.0, swap=0.0,
                              time=srv(10))]


@pytest.fixture
def sync(cfg):
    s = SupabaseSync(FakeMT5(DEALS, OPEN), cfg, "https://x.supabase.co", "sb_secret_test", session=FakeSession(),
                     clock=lambda: datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc))
    return s


def test_step_writes_only_active_agents_and_real_trades(sync):
    sync.step()
    calls = sync.s.calls
    deletes = [c for c in calls if c[0] == "DELETE"]
    assert [c[1].split("?")[0] for c in deletes] == ["trades_history", "strategy_parameters", "agent_learning",
                                                      "agents_status"]                       # FK: dependentes antes
    tables = [c[1].split("?")[0] for c in calls if c[0] == "POST"]
    assert tables.index("agents_status") < tables.index("trades_history")                  # agentes antes dos trades
    ag = next(c[2] for c in calls if c[0] == "POST" and c[1].startswith("agents_status"))
    names = {a["agent_id"] for a in ag}
    roster = {n for n, r in aud.agent_roster(sync.cfg).items() if r["ligado"]}
    assert names == roster and "manual" not in names
    a3 = next(a for a in ag if a["agent_id"] == "engine A3")
    assert a3["pnl"] == 5.0 and a3["total_pnl"] == 5.0 and a3["sector"] == 2 and a3["current_state"] == "IDLE"
    btc = next(a for a in ag if a["agent_id"] == "v4_btc_rsipb_h1")
    assert btc["current_state"] == "EXECUTING" and btc["sector"] == 3 and btc["strategy_type"] == "v4"
    tr = [t for c in calls if c[0] == "POST" and c[1].startswith("trades_history") for t in c[2]]
    by = {t["ticket_mt5"]: t for t in tr}
    assert set(by) == {1, 4, 9}                                                             # sem legado e sem manual
    assert by[1]["status"] == "CLOSED" and by[1]["exit_reason"] == "TP_HIT" and by[1]["order_type"] == "SELL"
    assert by[4]["agent_id"] == "goldnight_v2" and by[4]["exit_reason"] == "SL_HIT"
    assert by[9]["status"] == "OPEN" and by[9]["profit_usd"] == 2.0
    cfgrow = next(c[2] for c in calls if c[0] == "POST" and c[1].startswith("system_config"))[0]
    assert cfgrow["trading_mode"] == "DEMO" and "competicao" in cfgrow["agents_pnl"]


def test_second_cycle_sends_nothing_when_unchanged(sync):
    sync.step()
    n = len(sync.s.calls)
    assert sync.step() == {"trades": 0, "agentes": 0}
    assert len(sync.s.calls) == n                                                           # sem DELETE nem POST novos


def test_position_close_is_an_update_of_the_same_ticket(sync):
    sync.step()
    sync.mt5.p = []                                                                         # a posição 9 fechou
    sync.mt5.d += [deal(9, 0, 0, 20261126, 65000.0, srv(10), comment="V3|v4_btc_rsipb_h1", symbol="BTCUSD", vol=0.01),
                   deal(9, 1, 1, 20261126, 65500.0, srv(17), profit=5.0, reason=5, symbol="BTCUSD", vol=0.01)]
    sync.step()
    tr = [c[2] for c in sync.s.calls if c[0] == "POST" and c[1].startswith("trades_history")][-1]
    t9 = next(t for t in tr if t["ticket_mt5"] == 9)
    assert t9["status"] == "CLOSED" and t9["profit_usd"] == 5.0                            # o painel vê OPEN -> CLOSED


def test_every_batch_has_uniform_keys(sync):
    """PGRST102: num mesmo POST todas as linhas precisam das mesmas chaves (aberta tem sl/tp, fechada não)."""
    sync.step()
    posts = [c for c in sync.s.calls if c[0] == "POST" and isinstance(c[2], list)]
    for _, table, rows, _ in posts:
        assert len({tuple(sorted(r)) for r in rows}) == 1, table
    sent = {t["ticket_mt5"] for _, table, rows, _ in posts if table.startswith("trades_history") for t in rows}
    assert sent == {1, 4, 9}                                                                # nada se perdeu


def test_push_auditor_analysis_flags_critical():
    s = FakeSession()
    push_auditor_analysis("https://x.supabase.co", "k", "STATUS: CRÍTICO\nposição sem SL", "STATUS: CRÍTICO", session=s)
    body = s.calls[0][2]
    assert s.calls[0][1] == "market_context" and body["red_flag_pause_trading"] is True and "sem SL" in body["key_driver"]


def test_group_of():
    assert group_of("of_btc_07_st_dz_agree") == "of_btc" and group_of("v4_us500_st_h1") == "v4"
    assert group_of("engine A3") == "antigo" and group_of("goldnight_v2") == "antigo"


def test_auditor_never_pushes_to_supabase_under_pytest(monkeypatch):
    called = []
    monkeypatch.setattr("agents.supabase_sync.push_auditor_analysis", lambda *a, **k: called.append(a))
    aud.push_to_panel("STATUS: OK")
    assert called == []
