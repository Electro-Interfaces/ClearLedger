import uuid
from datetime import date
from types import SimpleNamespace

from app.services.goods_dashboard import (
    GoodsDashboardService, _station_of_warehouse, _warehouse_in_stations,
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _statement):
        return _Rows(self.results.pop(0))


def _sale(station, number, revenue):
    return SimpleNamespace(meta={
        "Смена": {
            "Смена": f"shift-{station}",
            "КодАЗС": station,
            "НомерСмены": number,
            "Оператор": f"Оператор {station}",
            "Касса": f"Пост {station}",
            "НомерСменыВнутр": f"В-{number}",
            "Открытие": "2026-08-08T00:01:00",
            "Закрытие": "2026-08-08T23:50:00",
        },
        "Секции": {
            "продажа_сопутка": {"сумма": revenue, "строки": []},
            "продажа_общепит": {"сумма": 0, "строки": []},
        },
    })


async def test_shift_documents_are_grouped_by_station_and_day():
    inventories = [
        SimpleNamespace(doc_date="2026-08-08", warehouse_code="20800002", net_amount=10),
        SimpleNamespace(doc_date="2026-08-08", warehouse_code="20900002", net_amount=20),
    ]
    movements = [
        SimpleNamespace(doc_date="2026-08-08", warehouse_code="208", kind="writeoff", total_amount=30),
        SimpleNamespace(doc_date="2026-08-08", warehouse_code="209", kind="writeoff", total_amount=40),
    ]
    service = GoodsDashboardService(_Session([inventories, movements]), uuid.uuid4())
    sales = [_sale("208", 7070, 1000), _sale("209", 8070, 2000)]
    purchases = [
        {"Смена": {"КодАЗС": "208"}, "Документ": {
            "Дата": "2026-08-08", "Товары": [{"Сумма": 120, "СуммаНДС": 20}]}},
        {"Смена": {"КодАЗС": "209"}, "Документ": {
            "Дата": "2026-08-08", "Товары": [{"Сумма": 240, "СуммаНДС": 40}]}},
    ]

    async def load():
        return sales

    async def load_purchases(_from, _to, _stations):
        return purchases

    service._load = load
    service._load_purchases = load_purchases

    result = await service.shifts_composite(date(2026, 8, 8), date(2026, 8, 8))
    by_station = {row["station"]: row for row in result["shifts"]}

    assert by_station["208"]["receipts_amount"] == 100
    assert by_station["209"]["receipts_amount"] == 200
    assert by_station["208"]["inventory_net"] == 10
    assert by_station["209"]["inventory_net"] == 20
    assert by_station["208"]["writeoff_amount"] == 30
    assert by_station["209"]["writeoff_amount"] == 40
    assert by_station["208"]["operator"] == "Оператор 208"
    assert by_station["208"]["register"] == "Пост 208"
    assert by_station["208"]["internal_no"] == "В-7070"


def test_station_warehouse_scope_accepts_warehouse_but_not_neighbour_station():
    assert _warehouse_in_stations("20800002", ["208"])
    assert not _warehouse_in_stations("20900002", ["208"])


def test_document_shift_is_selected_by_station_and_day():
    shifts = [
        {"station": "208", "day": "2026-08-08", "key": "s208", "number": 7070},
        {"station": "209", "day": "2026-08-08", "key": "s209", "number": 8070},
    ]

    result = GoodsDashboardService._shift_of(shifts, "2026-08-08", "208")

    assert result["key"] == "s208"
    assert result["number"] == "7070"
    assert result["count"] == 1


def test_document_without_station_is_not_attached_to_neighbour_shift():
    shifts = [
        {"station": "208", "day": "2026-08-08", "key": "s208", "number": 7070},
        {"station": "209", "day": "2026-08-08", "key": "s209", "number": 8070},
    ]

    result = GoodsDashboardService._shift_of(shifts, "2026-08-08")

    assert result["key"] is None
    assert result["number"] is None
    assert result["reason"] == "не удалось определить станцию документа"


def test_station_is_inferred_from_warehouse_code():
    assert _station_of_warehouse("20800002", ["208", "209"]) == "208"
    assert _station_of_warehouse("209", ["208", "209"]) == "209"
    assert _station_of_warehouse("99900001", ["208", "209"]) is None
