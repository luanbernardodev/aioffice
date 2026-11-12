"""Agente GOLD aprimorado (EA GoldNightV2, seção goldnight_v2) e a seleção de agentes de 12/11."""
import json
import re
import types
from pathlib import Path

from agents.auditor_mt5 import agent_names
from agents.goldflip_supervisor import GoldFlipSupervisor, decide_control
from engine.regime import NewsCalendar
from tests.test_goldflip import FakeMT5, P
from tests.test_goldnight import WED_LONDON, WED_NIGHT, reg

ROOT = Path(__file__).resolve().parent.parent


def test_section_is_separate_from_goldnight(cfg):
    g, old = cfg["goldnight_v2"], cfg["goldnight"]
    assert g["enabled"] is True and g["magic"] == 20261116 and g["symbol"] == "GOLD"
    assert g["magic"] != old["magic"] and g["control_file"] != old.get("control_file")
    assert g["params"]["trend"]["trail_atr"] == 3.0 and g["night_window"] is True


def test_control_only_at_night(cfg):
    g = dict(cfg["goldnight_v2"], name="goldnight_v2")
    assert decide_control(reg(), WED_NIGHT, g, 0.01)["enabled"] is True
    d = decide_control(reg(), WED_LONDON, g, 0.01)
    assert d["enabled"] is False and d["flatten"] is True


def test_supervisor_writes_own_control_file_and_loss_limit(cfg, tmp_path, monkeypatch):
    import agents.goldflip_supervisor as gs
    monkeypatch.setattr(gs, "ROOT", tmp_path)
    (tmp_path / "state").mkdir()
    mt5 = FakeMT5(tmp_path, equity=60.0, balance=100.0)
    mt5.positions_get = lambda: [P(magic=20261116, profit=-15.0)]
    mt5.history_deals_get = lambda *a: [types.SimpleNamespace(type=0, magic=20261116, profit=-30.0, swap=0.0,
                                                              commission=0.0)]
    s = GoldFlipSupervisor(mt5, cfg, calendar=NewsCalendar([], 15), section="goldnight_v2")
    s.check_risk(WED_NIGHT)
    assert "limite" in s.halt_reason
    assert json.loads((s.dir / "goldnight_v2_control.json").read_text())["enabled"] is False


def test_ea_matches_section_and_has_risk_cap(cfg):
    src = (ROOT / "mql5" / "Experts" / "GoldNightV2.mq5").read_text(encoding="utf-8")
    assert '"goldnight_v2_control.json"' in src and '"goldnight_v2_status.json"' in src
    assert re.search(r"InpMagic\s*=\s*20261116;", src)
    assert re.search(r"InpMaxRiskUSD\s*=\s*10\.0;", src)
    assert "RiskUSD(" in src


def test_week_selection_enabled_and_disabled(cfg):
    on = {k for k in ("goldflip", "sweep48", "rsi20", "goldnight_v2") if cfg[k]["enabled"]}
    assert on == {"goldflip", "sweep48", "rsi20", "goldnight_v2"}
    assert not any(cfg[k]["enabled"] for k in ("goldnight", "btcflip", "capitulation"))
    assert cfg["symbols"]["US500Cash"]["enabled"] and not cfg["symbols"]["BTCUSD"]["enabled"]
    assert cfg["symbols"]["US500Cash"]["agents"] == ["A2_PULLBACK", "A3_BOS_RETEST"]


def test_auditor_knows_new_agent(cfg):
    assert agent_names(cfg)[20261116] == "goldnight_v2"
