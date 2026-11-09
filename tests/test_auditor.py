import calendar
import types
from datetime import datetime, timezone

import pytest

import agents.auditor_mt5 as aud

NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
SRV = lambda h, m=0: calendar.timegm((2026, 11, 9, h, m, 0))   # relógio de parede do servidor (UTC+2 em novembro)


def deal(pos, entry, typ, magic, profit, t, symbol="GOLD", comment=""):
    return types.SimpleNamespace(position_id=pos, entry=entry, type=typ, magic=magic, profit=profit, swap=0.0,
                                 commission=0.0, time=t, symbol=symbol, comment=comment)


class FakeMT5:
    def __init__(self, positions=None, deals=None, fail=False):
        self._p, self._d, self.fail = positions or [], deals or [], fail

    def account_info(self):
        if self.fail:
            return None
        return types.SimpleNamespace(login=309673774, trade_mode=0, balance=100.0, equity=98.0, margin_free=90.0)

    def last_error(self):
        return (-10003, "IPC")

    def positions_get(self):
        return self._p

    def history_deals_get(self, *a):
        return self._d

    def order_send(self, req):
        raise AssertionError("o auditor nunca pode enviar ordem")


class FakeClaude:
    def __init__(self, text):
        self.text, self.calls = text, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=self.text)])


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(aud, "MEMORY_FILE", tmp_path / "memoria_auditor.md")
    monkeypatch.setattr(aud, "read_memory", lambda *a, **k: (tmp_path / "memoria_auditor.md").read_text(encoding="utf-8")
                        if (tmp_path / "memoria_auditor.md").exists() else "")
    monkeypatch.setenv("TG_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "1")


DEALS = [deal(1, 0, 0, 20261107, 0.0, SRV(21, 0), "US500Cash", "A2|FIB_LIMIT_0.5"),
         deal(1, 1, 1, 20261107, 1.62, SRV(21, 38), "US500Cash"),
         deal(2, 0, 0, 20261108, 0.0, SRV(20, 0)), deal(2, 1, 1, 20261108, -0.25, SRV(20, 23)),
         deal(3, 0, 0, 20261113, 0.0, SRV(7, 5)), deal(3, 1, 1, 20261113, -5.10, SRV(7, 41)),
         deal(4, 0, 0, 20261113, 0.0, SRV(1, 0)), deal(4, 1, 1, 20261113, 9.0, SRV(1, 30))]   # fora da janela de 20h


def test_names_from_config(cfg):
    n = aud.agent_names(cfg)
    assert n[20261107] == "engine" and n[20261113] == "goldnight" and n[20261110] == "sweep48" and n[0] == "manual"


def test_collect_window_stats_and_engine_split(cfg):
    data = aud.collect(FakeMT5(deals=DEALS), 20, aud.agent_names(cfg), "ny_plus_7", NOW)
    assert [t["posicao"] for t in data["trades"]] == [3, 2, 1]
    s = data["resumo"]
    assert s["total"]["trades"] == 3 and s["total"]["pnl"] == pytest.approx(-3.73)
    assert s["total"]["profit_factor"] == pytest.approx(round(1.62 / 5.35, 2))
    assert set(s["por_agente"]) == {"engine A2", "goldflip", "goldnight"}
    assert s["por_simbolo"]["GOLD"]["trades"] == 2 and data["conta"]["dd_flutuante_pct"] == 2.0


def test_ai_only_with_trades_or_missing_sl(cfg):
    names = aud.agent_names(cfg)
    quiet = aud.collect(FakeMT5(), 24, names, "ny_plus_7", NOW)
    assert not aud.needs_ai(quiet)
    p = types.SimpleNamespace(ticket=9, symbol="GOLD", type=0, volume=0.01, price_open=4100.0, sl=0.0, tp=0.0,
                              profit=-1.0, swap=0.0, magic=0, comment="")
    assert aud.needs_ai(aud.collect(FakeMT5(positions=[p]), 24, names, "ny_plus_7", NOW))


def test_run_calls_claude_saves_lesson_and_sends(cfg):
    claude = FakeClaude("STATUS: ATENÇÃO\nPROBLEMAS: goldnight perdedor\nAÇÃO: observar\nLIÇÃO: madrugada com spread alto")
    sent = []
    out = aud.run(20, FakeMT5(deals=DEALS), cfg, claude, lambda url, data, timeout: sent.append(data) or
                  types.SimpleNamespace(status_code=200), now=NOW)
    kw = claude.calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 600
    assert "madrugada com spread alto" in aud.MEMORY_FILE.read_text(encoding="utf-8")
    assert len(sent) == 1 and len(sent[0]["text"]) <= 4000 and "STATUS: ATENÇÃO" in out


def test_lesson_nenhuma_is_not_saved(cfg):
    claude = FakeClaude("STATUS: OK\nPROBLEMAS: nenhum\nAÇÃO: nada\nLIÇÃO: nenhuma")
    aud.run(20, FakeMT5(deals=DEALS), cfg, claude, lambda *a, **k: types.SimpleNamespace(status_code=200), now=NOW)
    assert not aud.MEMORY_FILE.exists()


def test_no_trades_skips_claude(cfg):
    claude = FakeClaude("x")
    out = aud.run(24, FakeMT5(), cfg, claude, lambda *a, **k: types.SimpleNamespace(status_code=200), now=NOW)
    assert claude.calls == [] and "IA não acionada" in out


def test_mt5_failure_sends_critical(cfg):
    sent = []
    out = aud.run(24, FakeMT5(fail=True), cfg, FakeClaude("x"),
                  lambda url, data, timeout: sent.append(data) or types.SimpleNamespace(status_code=200), now=NOW)
    assert "CRÍTICO" in out and "CRÍTICO" in sent[0]["text"]


def test_readonly_proxy_blocks_orders():
    with pytest.raises(PermissionError):
        aud.ReadOnlyMT5(FakeMT5()).order_send({})


def test_no_order_calls_in_source():
    src = (aud.ROOT / "agents" / "auditor_mt5.py").read_text(encoding="utf-8")
    assert "order_send(" not in src and "TRADE_ACTION" not in src


def test_extract_lesson():
    assert aud.extract_lesson("LIÇÃO: x y") == "x y"
    assert aud.extract_lesson("**LIÇÃO:** Nenhuma.") is None
    assert aud.extract_lesson("sem formato") is None
