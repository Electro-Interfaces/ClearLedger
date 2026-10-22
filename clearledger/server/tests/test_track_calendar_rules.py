"""Календарные границы: пояс отложения и день ежемесячного правила."""
from datetime import date, datetime, timezone

import pytest

from app.services.placement import clamp_defer, DeferRefused
from app.services.task_scheduler import next_run


@pytest.mark.parametrize("day", [29, 30, 31])
def test_monthly_short_month_preserves_original_day(day):
    rule = {"mode": "monthly", "day": day, "at": "09:00", "tz": "Europe/Moscow"}
    october = next_run(rule, datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert october == datetime(2026, 10, day, 6, tzinfo=timezone.utc)
    february = next_run(rule, datetime(2027, 2, 1, tzinfo=timezone.utc))
    assert february == datetime(2027, 2, 28, 6, tzinfo=timezone.utc)
    march = next_run(rule, february)
    assert march == datetime(2027, 3, day, 6, tzinfo=timezone.utc)
    assert rule["day"] == day
    leap = next_run(rule, datetime(2028, 2, 1, tzinfo=timezone.utc))
    assert leap == datetime(2028, 2, 29, 6, tzinfo=timezone.utc)
    december = next_run(rule, datetime(2026, 12, 31, 20, tzinfo=timezone.utc))
    assert december == datetime(2027, 1, day, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize("tz,due,expected", [
    ("Europe/Moscow", "2026-10-22T21:30:00Z", date(2026, 10, 23)),
    ("Asia/Vladivostok", "2026-10-22T18:00:00Z", date(2026, 10, 23)),
    ("America/Los_Angeles", "2026-10-24T02:00:00Z", date(2026, 10, 23)),
])
def test_defer_deadline_uses_same_timezone_as_today(tz, due, expected):
    assert clamp_defer(date(2026, 11, 1), due, date(2026, 10, 22), tz) == expected
    with pytest.raises(DeferRefused):
        clamp_defer(date(2026, 11, 1), due, expected, tz)


@pytest.mark.parametrize("rule", [[], "", 0, None, {"mode": "monthly", "day": 32},
                                  {"mode": "weekly", "weekday": -1}, {"at": "09:0"}, {"at": None}])
def test_invalid_legacy_rule_is_never_reinterpreted(rule):
    with pytest.raises(ValueError):
        next_run(rule, datetime(2026, 10, 22, tzinfo=timezone.utc))
