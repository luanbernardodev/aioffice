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


def test_workspace_header_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(aud, "ROOT", tmp_path)                  # sem .env: só o ambiente conta
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_teste")
    assert aud.make_client().default_headers.get("anthropic-workspace-id") == "wrkspc_teste"
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID")
    assert "anthropic-workspace-id" not in aud.make_client().default_headers


# ----------------------------------------------------------------- relatório com todos os agentes
def test_roster_lists_every_configured_agent(cfg):
    r = aud.agent_roster(cfg)
    for name in ("engine A2", "engine A3", "engine A4", "goldflip", "btcflip", "sweep48", "capitulation", "rsi20",
                 "goldnight", "agente_rsi7_h1", "us100_rsi2_h1"):
        assert name in r, name
    assert "US500Cash" in r["engine A3"]["simbolos"]


def test_report_shows_agents_without_trades_and_cumulative(cfg):
    data = aud.collect(FakeMT5(deals=DEALS), 20, aud.agent_names(cfg), "ny_plus_7", NOW, roster=aud.agent_roster(cfg))
    ag = data["agentes"]
    assert ag["engine A3"]["janela"]["trades"] == 0                  # sem trade na janela, mas listado
    assert ag["goldnight"]["acumulado"]["trades"] == 2               # o trade fora da janela entra no acumulado
    assert ag["goldnight"]["janela"]["trades"] == 1
    text = aud.local_report(data)
    assert "• engine A3 [US500Cash]\n   Janela: sem trades fechados" in text
    assert "\n\n🤖 AGENTES\n" in text and "\n\n📌 POSIÇÕES ABERTAS (0)\nnenhuma" in text
    assert all(len(line) < 140 for line in text.splitlines())


def test_split_message_keeps_lines_whole():
    text = "\n".join(f"linha {i:03d} " + "x" * 50 for i in range(200))
    parts = aud.split_message(text, 1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text


def test_long_report_goes_in_several_telegram_messages(monkeypatch):
    monkeypatch.setenv("TG_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "c")
    sent = []
    ok = aud.send_telegram("\n".join("y" * 100 for _ in range(100)),
                           post=lambda url, data, timeout: sent.append(data["text"]) or types.SimpleNamespace(status_code=200))
    assert ok and len(sent) == 3 and sent[0].startswith("(1/3)\n") and all(len(s) <= 4000 for s in sent)


def test_api_key_falls_back_to_dotenv_when_env_is_empty(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=da_env_file\n", encoding="utf-8")
    monkeypatch.setattr(aud, "ROOT", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    assert aud.make_client().api_key == "da_env_file"
    (tmp_path / ".env").write_text("", encoding="utf-8")
    with pytest.raises(aud.MissingApiKey):
        aud.make_client()


def test_legacy_magic_is_out_of_the_sample(cfg):
    legacy = [deal(9, 0, 0, 777777, 0.0, SRV(20, 0)), deal(9, 1, 1, 777777, -50.0, SRV(20, 30))]
    pos = [types.SimpleNamespace(ticket=5, symbol="GOLD", type=0, volume=0.01, price_open=1.0, sl=0.0, tp=0.0,
                                 profit=-3.0, swap=0.0, magic=777777, comment="")]
    data = aud.collect(FakeMT5(positions=pos, deals=DEALS + legacy), 20, aud.agent_names(cfg), "ny_plus_7", NOW)
    assert 9 not in [t["posicao"] for t in data["trades"]]
    assert data["resumo"]["total"]["pnl"] == pytest.approx(-3.73) and data["posicoes"] == []
    assert 777777 not in aud.agent_names(cfg)
    assert not any("legado" in k for k in data["agentes"])


def test_competition_leaderboard_counts_only_from_start():
    hist = [{"agente": "goldflip", "pnl": 5.0, "fechado_utc": "2026-11-15 10:00"},      # antes do início
            {"agente": "goldflip", "pnl": -2.0, "fechado_utc": "2026-11-16 10:00"},
            {"agente": "v3_a", "pnl": 3.0, "fechado_utc": "2026-11-16 11:00"},
            {"agente": "v3_a", "pnl": -1.0, "fechado_utc": "2026-11-17 11:00"},
            {"agente": "v3_a", "pnl": 4.0, "fechado_utc": "2026-11-22 11:00"}]          # depois do fim
    comp = aud.competition_table(hist, {"inicio_utc": "2026-11-16 00:00", "fim_utc": "2026-11-21 00:00",
                                        "antigos": ["goldflip"], "novos": ["v3_a", "v3_b"]})
    assert [r["agente"] for r in comp["placar"]] == ["v3_a", "v3_b", "goldflip"]
    assert comp["placar"][0]["pnl"] == pytest.approx(2.0) and comp["placar"][0]["max_dd"] == pytest.approx(1.0)
    assert comp["total_por_grupo"] == {"antigo": -2.0, "novo": 2.0}
    text = aud.local_report({"gerado_utc": "x", "janela_horas": 24, "conta": {"login": 1, "demo": True, "saldo": 1,
                             "equity": 1, "margem_livre": 1, "dd_flutuante_pct": 0}, "resumo": {"total": {"trades": 0,
                             "pnl": 0}, "por_agente": {}}, "agentes": {}, "posicoes": [], "competicao": comp})
    assert "🏆 COMPETIÇÃO" in text and "1. v3_a [novo] +2.00" in text and "Antigos -2.00 x Novos +2.00" in text
