"""Партийной себестоимости остатка верить можно не всегда.

На складе 208 из 573 позиций с партийной себестоимостью 48 имели её выше розничной цены
(маржа −15%), а 66 — вдвое ниже реальной закупки (маржа 65% вместо 23%). Такие цифры
не должны попадать в сводную «потенц. маржу», иначе плитка живёт своей жизнью.
"""
import inspect

import pytest

from app.services.goods_dashboard import _cost_doubt
from app.services import store_reports


def test_partiya_vyshe_ceny_ne_verim():
    # Kent Nano mix: партия 277,05 при цене 240 — маржа ушла бы в минус
    assert _cost_doubt(277.05, 240.0, 186.84) == "выше розничной цены"


def test_partiya_vdvoe_nizhe_zakupki_ne_verim():
    # Winston XS Silver: партия 93,96 при закупке 206,10 — «маржа 64,9%» фальшивая
    assert _cost_doubt(93.96, 268.0, 206.10) is not None


def test_normalnaya_partiya_prohodit():
    # Camel Compact: партия 196,60 при цене 210 — сигаретная маржа 6%, это правда
    assert _cost_doubt(196.60, 210.0, 161.15) is None


def test_bez_zakupok_sudim_tolko_po_cene():
    assert _cost_doubt(120.0, 200.0, None) is None
    assert _cost_doubt(220.0, 200.0, None) == "выше розничной цены"


def test_bez_partii_nechego_proveryat():
    assert _cost_doubt(None, 200.0, 150.0) is None


def test_report_period_uses_station_business_day():
    start, end = store_reports._период("2026-08-17", "2026-08-17")
    assert start.isoformat() == "2026-08-17T00:00:00+03:00"
    assert end.isoformat().startswith("2026-08-17T23:59:59.999999+03:00")


class _Mappings:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement, _params=None):
        return _Mappings(self.rows)


@pytest.mark.asyncio
async def test_unknown_stock_cost_stays_null(monkeypatch):
    async def no_estimates(_db, _cid, _stations):
        return {}

    monkeypatch.setattr(store_reports.store_costs, "ориентиры", no_estimates)
    result = await store_reports.stock(_DB([{
        "station_id": 208, "place_name": "Зал", "place": "1",
        "item_uuid": "coffee", "name": "Кофе", "barcode": "4600",
        "quantity": 2, "retail_price": 120, "cost_unit": None,
        "snapshot_at": None,
    }]), "company", None, None)
    row = result["rows"][0]
    assert row["cost"] is None
    assert row["cost_amount"] is None
    assert result["cost_amount"] is None
    assert result["cost_known"] == 0


def test_money_reports_subtract_returns_and_use_canonical_return_kind():
    shifts_source = inspect.getsource(store_reports.shifts)
    pay_source = inspect.getsource(store_reports.pay_mix)
    returns_source = inspect.getsource(store_reports.returns)
    assert "ВозвращенныеТовары" in shifts_source
    assert "CASE WHEN is_return THEN -abs(total) ELSE total END" in pay_source
    assert "return_purchase" in returns_source
    assert "return_supplier" not in returns_source
