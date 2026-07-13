import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from app.services.fuel_costing import FuelCostingService, _Batch, _EffectiveSale


def sale(channel: str, liters: float, amount: float) -> _EffectiveSale:
    return _EffectiveSale(
        shift_id=uuid.uuid4(), payment_channel=channel, fuel_code=2,
        liters=liters, amount=amount,
    )


def allocation_map(allocations):
    result = defaultdict(float)
    for row in allocations:
        result[(row.batch.ttn if row.batch else None, row.sale.payment_channel)] += row.liters
    return dict(result)


def test_shift_channels_split_proportionally_across_fifo_boundary():
    moment = datetime(2026, 1, 2, tzinfo=timezone.utc)
    sales = [sale("retail_card", 60, 6000), sale("retail_cash", 40, 3600)]

    def run(rows):
        queue = deque([
            _Batch("TTN-1", moment - timedelta(days=2), 50, 45),
            _Batch("TTN-2", moment - timedelta(days=1), 50, 47),
        ])
        return allocation_map(FuelCostingService._allocate_group(queue, moment, rows))

    expected = {
        ("TTN-1", "retail_card"): 30,
        ("TTN-1", "retail_cash"): 20,
        ("TTN-2", "retail_card"): 30,
        ("TTN-2", "retail_cash"): 20,
    }
    assert run(sales) == expected
    assert run(list(reversed(sales))) == expected


def test_future_receipt_is_not_used_for_sale():
    moment = datetime(2026, 1, 2, tzinfo=timezone.utc)
    future = _Batch("TTN-FUTURE", moment + timedelta(days=1), 100, 45)
    allocations = FuelCostingService._allocate_group(
        deque([future]), moment, [sale("retail_card", 25, 2500)],
    )
    assert len(allocations) == 1
    assert allocations[0].batch is None
    assert allocations[0].liters == 25
    assert future.remaining == 100
