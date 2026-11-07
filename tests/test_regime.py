from datetime import datetime, timezone

from engine.regime import NewsCalendar, check_gates, in_session


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_sessions(cfg):
    gold = cfg["symbols"]["GOLD"]["sessions"]
    spx = cfg["symbols"]["US500Cash"]["sessions"]
    assert in_session(utc(2026, 11, 4, 9, 0), gold)          # Londres 09:00
    assert in_session(utc(2026, 11, 4, 20, 0), gold)         # NY 15:00 (EST)
    assert not in_session(utc(2026, 11, 4, 2, 0), gold)      # Ásia
    assert not in_session(utc(2026, 11, 7, 10, 0), gold)     # sábado
    assert not in_session(utc(2026, 11, 4, 14, 0), spx)      # 09:00 NY: antes da abertura
    assert in_session(utc(2026, 11, 4, 15, 0), spx)          # 10:00 NY
    assert not in_session(utc(2026, 11, 4, 21, 30), spx)     # 16:30 NY
    assert in_session(utc(2026, 7, 15, 13, 45), spx)         # 09:45 NY no horário de verão (EDT)
    assert in_session(utc(2026, 11, 7, 3, 0), cfg["symbols"]["BTCUSD"]["sessions"])  # 24/7


def test_spread_gate(cfg):
    g = cfg["symbols"]["GOLD"]
    t = utc(2026, 11, 4, 10, 0)
    assert check_gates(t, g, spread=0.5, atr_m5=4.0).ok              # 0.125 x ATR
    r = check_gates(t, g, spread=0.7, atr_m5=4.0)                     # 0.175 x ATR > 0.15
    assert not r.ok and r.reason.startswith("spread")


def test_news_window(cfg):
    cal = NewsCalendar(cfg["regime"]["news_keywords"], 30)
    cal.add_event(utc(2026, 11, 4, 13, 30), "CPI m/m")
    g = cfg["symbols"]["GOLD"]
    assert not check_gates(utc(2026, 11, 4, 13, 5), g, 0.1, 4.0, cal).ok
    assert not check_gates(utc(2026, 11, 4, 13, 59), g, 0.1, 4.0, cal).ok
    assert check_gates(utc(2026, 11, 4, 14, 1), g, 0.1, 4.0, cal).ok
    assert cal.matches("Non-Farm Employment Change") and cal.matches("Core PCE Price Index m/m")
    assert not cal.matches("Unemployment Claims")
