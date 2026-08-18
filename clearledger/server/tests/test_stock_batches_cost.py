"""Партии из 1С как стартовая себестоимость запаса.

По товару, который лежал на полке до перехода, закупок в нашей системе нет и
после отключения станционной 1С уже не появится: на 208 это 271 позиция из 389
с непокрытой себестоимостью. Срез партий — единственный источник цифры, и
снять его надо ДО Дня X.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models import InventoryBatch
from app.routers.store_router import BatchRowIn, store_stock_batches_import


class _Access:
    def __init__(self, company_id):
        self.company_id = company_id
        self.network = True


class _Session:
    def __init__(self, existing=()):
        self.rows = list(existing)
        self.added = []
        self.commits = 0

    async def execute(self, statement, parameters=None):
        return _Result(self.rows)

    def add(self, row):
        self.added.append(row)
        self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def mappings(self):
        return self


@pytest.fixture(autouse=True)
def _подмена(monkeypatch):
    cid = uuid.uuid4()
    monkeypatch.setattr("app.routers.store_router._receipt_access",
                        lambda user, db: _вернуть(_Access(cid)))
    monkeypatch.setattr("app.routers.store_router.log_export",
                        lambda *a, **k: None)
    return cid


async def _вернуть(v):
    return v


def _строка(**kw):
    основа = dict(nomenclature_ref=str(uuid.uuid4()), quantity_remaining=10,
                  amount_remaining=1000, warehouse_ref="208",
                  batch_doc_ref="док-1", batch_doc_date="2026-07-01T00:00:00")
    основа.update(kw)
    return BatchRowIn(**основа)


@pytest.mark.asyncio
async def test_schitaet_cenu_edinicy():
    сессия = _Session()
    ответ = await store_stock_batches_import(
        rows=[_строка(quantity_remaining=4, amount_remaining=100)],
        source="1c_partii", user=None, db=сессия)
    assert ответ["accepted"] == 1
    assert сессия.added[0].unit_price == 25.0
    assert сессия.commits == 1


@pytest.mark.asyncio
async def test_partiya_bez_summy_ne_gruzitsya():
    """Ноль в себестоимости читается как «товар бесплатный» — это хуже пустоты."""
    сессия = _Session()
    ответ = await store_stock_batches_import(
        rows=[_строка(amount_remaining=0), _строка(quantity_remaining=0),
              _строка(nomenclature_ref="")],
        source="1c_partii", user=None, db=сессия)
    assert ответ["accepted"] == 0
    assert ответ["skipped"] == 3
    assert сессия.added == []


@pytest.mark.asyncio
async def test_povtornaya_zalivka_obnovlyaet_a_ne_dvoit():
    товар = str(uuid.uuid4())
    было = InventoryBatch(
        id=uuid.uuid4(), company_id=uuid.uuid4(), batch_doc_ref="док-1",
        nomenclature_ref=товар, warehouse_ref="208",
        quantity_remaining=10, amount_remaining=1000, unit_price=100,
        source="1c_partii", snapshot_at=datetime.now(timezone.utc),
    )
    сессия = _Session([было])
    ответ = await store_stock_batches_import(
        rows=[_строка(nomenclature_ref=товар, quantity_remaining=5,
                      amount_remaining=750)],
        source="1c_partii", user=None, db=сессия)
    assert ответ["accepted"] == 1
    assert сессия.added == [], "строка задвоилась вместо обновления"
    assert было.unit_price == 150.0
    assert было.quantity_remaining == 5
