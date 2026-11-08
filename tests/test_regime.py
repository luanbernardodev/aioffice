from datetime import datetime, timezone

from engine.regime import CalendarFeed, NewsCalendar, check_gates, in_session


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


FF_EVENTS = [{"country": "USD", "impact": "High", "title": "CPI m/m", "date": "2026-11-12T08:30:00-05:00"},
             {"country": "USD", "impact": "High", "title": "Core PCE Price Index m/m", "date": "2026-11-13T08:30:00-05:00"},
             {"country": "EUR", "impact": "High", "title": "CPI y/y", "date": "2026-11-12T05:00:00-05:00"}]


def test_feed_downloads_once_for_all_calendars():
    calls = []
    feed = CalendarFeed(fetch=lambda: calls.append(1) or FF_EVENTS)
    a = NewsCalendar(["CPI", "PCE"], 30)
    b = NewsCalendar(["CPI"], 15)
    feed._subs += [a, b]
    assert feed.cycle() == CalendarFeed.OK_SECONDS and len(calls) == 1
    t = utc(2026, 11, 13, 13, 30)
    assert a.blocking_event(t) and not b.blocking_event(t)        # cada um mantém filtro e janela próprios
    assert b.blocking_event(utc(2026, 11, 12, 13, 40))
    assert not b.blocking_event(utc(2026, 11, 12, 13, 50))
    feed.cycle()
    assert len(a._events) == 2                                     # sem duplicar


def test_feed_retries_soon_after_429_and_backs_off():
    answers = [RuntimeError("429"), RuntimeError("429"), FF_EVENTS]

    def fetch():
        r = answers.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    feed = CalendarFeed(fetch=fetch)
    cal = NewsCalendar(["CPI"], 30)
    feed._subs.append(cal)
    assert feed.cycle() == 300 and feed.cycle() == 600 and not cal._events
    assert feed.cycle() == CalendarFeed.OK_SECONDS and cal._events
