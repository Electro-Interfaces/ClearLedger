import uuid
from datetime import datetime
from types import SimpleNamespace

from app.services.fuel_balance import build_fuel_balance


def shift(station_id, number, day):
    return SimpleNamespace(
        id=uuid.uuid4(),
        station_id=station_id,
        shift_number=number,
        opened_at=datetime(2026, 7, day, 8),
        closed_at=datetime(2026, 7, day, 20),
    )


def tank(shift_id, number, start, receipts, sales, end, fuel_code=92, fuel_type="АИ-92"):
    return SimpleNamespace(
        shift_id=shift_id,
        tank_number=number,
        fuel_code=fuel_code,
        fuel_type=fuel_type,
        volume_start=start,
        volume_received=receipts,
        sales=sales,
        volume_end=end,
    )


def station_map(station_id):
    return {station_id: SimpleNamespace(code=6, name="АЗС №6")}


def test_period_uses_first_and_last_balance_not_sum_of_shift_balances():
    station_id = uuid.uuid4()
    first = shift(station_id, 101, 1)
    second = shift(station_id, 102, 2)
    result = build_fuel_balance(
        [first, second],
        [
            tank(first.id, 1, 1000, 500, 300, 1200),
            tank(second.id, 1, 1200, 0, 400, 790),
        ],
        station_map(station_id),
        "station_fuel",
    )

    totals = result["totals"]
    assert totals["balance_start_liters"] == 1000
    assert totals["receipts_liters"] == 500
    assert totals["sales_liters"] == 700
    assert totals["balance_end_liters"] == 790
    assert totals["variance_liters"] == 10
    assert totals["tanks_count"] == 1
    assert totals["records_count"] == 2
    assert result["shifts_count"] == 2
    assert result["integrity"]["unique_tanks"] == 1
    assert result["integrity"]["continuity_breaks"] == 0


def test_continuity_gap_is_reported_separately_from_period_variance():
    station_id = uuid.uuid4()
    first = shift(station_id, 101, 1)
    second = shift(station_id, 102, 2)
    result = build_fuel_balance(
        [first, second],
        [
            tank(first.id, 1, 1000, 500, 300, 1200),
            tank(second.id, 1, 1210, 0, 400, 800),
        ],
        station_map(station_id),
        "station_fuel",
    )

    tank_row = result["tanks"][0]
    assert tank_row["variance_liters"] == 0
    assert tank_row["shift_variance_liters"] == 10
    assert tank_row["continuity_gap_liters"] == 10
    assert tank_row["continuity_breaks"] == 1
    assert result["integrity"]["continuity_breaks"] == 1
    assert result["issues"][0]["gap_liters"] == 10


def test_tank_count_is_unique_within_station():
    station_id = uuid.uuid4()
    first = shift(station_id, 101, 1)
    second = shift(station_id, 102, 2)
    result = build_fuel_balance(
        [first, second],
        [
            tank(first.id, 1, 1000, 0, 100, 900),
            tank(first.id, 2, 2000, 0, 200, 1800, 95, "АИ-95"),
            tank(second.id, 1, 900, 0, 100, 800),
            tank(second.id, 2, 1800, 0, 200, 1600, 95, "АИ-95"),
        ],
        station_map(station_id),
        "station",
    )

    assert result["totals"]["tanks_count"] == 2
    assert result["totals"]["records_count"] == 4
    assert result["lines"][0]["tanks_count"] == 2
