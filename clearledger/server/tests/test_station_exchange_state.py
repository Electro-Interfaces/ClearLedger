from datetime import date, datetime, timezone

from app.routers.store_router import (
    _clock_skew_seconds, _queue_metrics, _station_state, _tail_outage,
    _uptime_pct,
)


def test_единая_шкала_свежести_станции():
    assert _station_state(180) == "онлайн"
    assert _station_state(181) == "офлайн"
    assert _station_state(3600) == "офлайн"
    assert _station_state(3601) == "молчит"
    assert _station_state(None) == "молчит"


def test_текущий_обрыв_не_теряется_в_центре():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)

    assert _tail_outage(
        datetime(2026, 8, 8, 11, 58, tzinfo=timezone.utc), date(2026, 8, 8), now,
    ) is None

    outage = _tail_outage(
        datetime(2026, 8, 8, 11, 55, tzinfo=timezone.utc), date(2026, 8, 8), now,
    )
    assert outage == {
        "started": datetime(2026, 8, 8, 11, 55, tzinfo=timezone.utc),
        "ended": None,
        "minutes": 5,
        "ongoing": True,
    }


def test_хвост_прошлого_периода_закрывается_его_границей():
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    outage = _tail_outage(
        datetime(2026, 8, 7, 23, 50, tzinfo=timezone.utc), date(2026, 8, 7), now,
    )
    assert outage is not None
    assert outage["ongoing"] is False
    assert outage["ended"] == datetime.combine(
        date(2026, 8, 7), datetime.max.time(), tzinfo=timezone.utc,
    )
    assert outage["minutes"] == 10


def test_диагностика_очереди_берётся_из_heartbeat_мягко():
    assert _queue_metrics({
        "queue_bytes": 12000,
        "queue_wire_bytes": "2400",
        "queue_failing": 2,
        "queue_oldest_at": "2026-08-08T10:00:00+03:00",
    }) == {
        "queue_bytes": 12000,
        "queue_wire_bytes": 2400,
        "queue_oldest_at": "2026-08-08T10:00:00+03:00",
        "queue_failing": 2,
        "queue_sent_24": 0,
        "sent_24_bytes": 0,
        "sent_24_wire_bytes": 0,
        "last_sent_at": None,
        "last_attempt_at": None,
        "last_error": None,
    }
    assert _queue_metrics({"queue_bytes": "не число"})["queue_bytes"] == 0


def test_часы_станции_сверяются_с_моментом_приёма():
    received = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    assert _clock_skew_seconds(
        {"client_time": "2026-08-08T15:02:00+03:00"}, received,
    ) == 120
    assert _clock_skew_seconds({}, received) is None


def test_доступность_считается_по_длительности_обрывов():
    row = {"has_heartbeat": True, "window_seconds": 10 * 3600,
           "outage_seconds": 30 * 60}
    assert _uptime_pct(row, date.min, date.max, datetime.now(timezone.utc)) == 95.0
    assert _uptime_pct({"has_heartbeat": False}, date.min, date.max,
                       datetime.now(timezone.utc)) is None
