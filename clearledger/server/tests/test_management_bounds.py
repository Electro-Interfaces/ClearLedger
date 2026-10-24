"""Границы календаря: представимость UTC, включительный период и DST."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services.management_overview import calendar_bounds


@pytest.mark.parametrize("day,zone,expected_start", [
    (date.min, "UTC", "0001-01-01T00:00:00+00:00"),
    (date.min, "Etc/GMT+12", "0001-01-01T12:00:00+00:00"),
    (date(1, 1, 2), "Etc/GMT-14", "0001-01-01T10:00:00+00:00"),
    (date(2026, 10, 24), "Europe/Moscow", "2026-10-23T21:00:00+00:00"),
    (date(9999, 12, 30), "Etc/GMT+12", "9999-12-30T12:00:00+00:00"),
    (date(9999, 12, 30), "Etc/GMT-14", "9999-12-29T10:00:00+00:00"),
])
def test_representable_extreme_days(day, zone, expected_start):
    start, end = calendar_bounds("calendar", day, day, zone)
    assert start == datetime.fromisoformat(expected_start)
    assert end - start == timedelta(days=1)
    assert start.tzinfo == end.tzinfo == timezone.utc


@pytest.mark.parametrize("start,end,zone", [
    (date.min, date.min, "Europe/Moscow"),
    (date.min, date.min, "Etc/GMT-14"),
    (date.max, date.max, "UTC"),
    (date.max, date.max, "Europe/Moscow"),
    (date.max, date.max, "Etc/GMT+12"),
    (date.max, date.max, "Etc/GMT-14"),
    (date(9999, 12, 30), date.max, "UTC"),
])
def test_unrepresentable_bounds_are_validation_errors(start, end, zone):
    with pytest.raises(HTTPException) as exc:
        calendar_bounds("calendar", start, end, zone)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("year", [1900, 2026, 2100, 9000])
@pytest.mark.parametrize("zone", ["UTC", "Europe/Moscow", "Europe/Berlin"])
def test_inclusive_367_day_limit_without_arbitrary_year_cutoff(year, zone):
    first = date(year, 1, 1)
    start, end = calendar_bounds("calendar", first, first + timedelta(days=366), zone)
    assert start < end
    with pytest.raises(HTTPException) as exc:
        calendar_bounds("calendar", first, first + timedelta(days=367), zone)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_day_length_follows_dst(day, hours):
    start, end = calendar_bounds("calendar", day, day, "Europe/Berlin")
    assert end - start == timedelta(hours=hours)


@pytest.mark.parametrize("first,last,zone", [
    (None, None, "UTC"),
    (date(2026, 1, 2), date(2026, 1, 1), "UTC"),
    (date.min, date.min, "unknown"),
])
def test_bad_period_or_zone_still_rejected(first, last, zone):
    with pytest.raises(HTTPException) as exc:
        calendar_bounds("calendar", first, last, zone)
    assert exc.value.status_code == 422
