import json
import types
from datetime import datetime, timezone

from agents.goldflip_supervisor import GoldFlipSupervisor, decide_control, in_night_window
from engine.regime import NewsCalendar
from tests.test_goldflip import FakeMT5, P

WED_NIGHT = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)
WED_LONDON = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
SUN_NIGHT = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)   # domingo 18:30 em NY


def reg():
    return {"regime": "trend", "direction": 1, "atr_m5": 4.0}


def test_night_window(cfg):
    s = cfg["goldnight"]["sessions"]
    assert in_night_window(WED_NIGHT, s)
    assert not in_night_window(WED_LONDON, s)
    assert not in_night_window(SUN_NIGHT, s)


def test_control_night_and_flatten_at_london(cfg):
    g = dict(cfg["goldnight"], name="goldnight")
    c = decide_control(reg(), WED_NIGHT, g, 0.01)
    assert c["enabled"] is True and c["trail_atr"] == 3.0
    d = decide_control(reg(), WED_LONDON, g, 0.01)
    assert d["enabled"] is False and d["flatten"] is True


def deal(profit, magic=20261113):
    return types.SimpleNamespace(type=0, magic=magic, profit=profit, swap=0.0, commission=0.0)


def sup(cfg, tmp_path, monkeypatch, mt5):
    import agents.goldflip_supervisor as gs
    monkeypatch.setattr(gs, "ROOT", tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    return GoldFlipSupervisor(mt5, cfg, calendar=NewsCalendar([], 15), section="goldnight")


def test_ignores_daily_kill_switch(cfg, tmp_path, monkeypatch):
    mt5 = FakeMT5(tmp_path, equity=50.0, balance=100.0)
    mt5.positions_get = lambda: [P(magic=20261108, profit=-50.0)]    # outro agente em DD enorme
    s = sup(cfg, tmp_path, monkeypatch, mt5)
    s.check_risk(WED_NIGHT)
    assert not s.guard.kill_reason and not s.halt_reason


def test_own_loss_limit_flattens_and_persists(cfg, tmp_path, monkeypatch):
    mt5 = FakeMT5(tmp_path, equity=60.0, balance=100.0)
    mt5.positions_get = lambda: [P(magic=20261113, profit=-15.0)]
    mt5.history_deals_get = lambda *a: [deal(-25.0), deal(-99.0, magic=20261108)]
    s = sup(cfg, tmp_path, monkeypatch, mt5)
    s.check_risk(WED_NIGHT)
    assert "limite" in s.halt_reason
    assert json.loads((s.dir / "goldnight_control.json").read_text())["flatten"] is True
    again = sup(cfg, tmp_path, monkeypatch, mt5)
    assert again.halt_reason                                          # reinício não religa
    assert decide_control(reg(), WED_NIGHT, dict(cfg["goldnight"]), 0.01, kill_reason=again.halt_reason)["enabled"] is False


def test_below_limit_keeps_running(cfg, tmp_path, monkeypatch):
    mt5 = FakeMT5(tmp_path, equity=90.0, balance=100.0)
    mt5.positions_get = lambda: [P(magic=20261113, profit=-10.0)]
    mt5.history_deals_get = lambda *a: [deal(-20.0)]
    s = sup(cfg, tmp_path, monkeypatch, mt5)
    s.check_risk(WED_NIGHT)
    assert not s.halt_reason
