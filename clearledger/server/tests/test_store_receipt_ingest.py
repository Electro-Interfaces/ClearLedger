import uuid
import socket
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    Company,
    Contract,
    Counterparty,
    Organization,
    StoreReceipt,
    StoreReceiptStockMovement,
    Warehouse,
)
from app.routers.edge_router import _ingest_receipts


def _postgres_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="локальная clearledger_test PostgreSQL недоступна")


@pytest.mark.asyncio(loop_scope="session")
async def test_edge_ingest_updates_document_id_in_place_and_ledgers_once(db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    supplier = Counterparty(
        company_id=company.id, inn="7812345678", name="ООО Тест Поставка",
        type="ЮЛ", aliases=[], kind="external", external_ref=str(uuid.uuid4()),
    )
    organization = Organization(
        company_id=company.id, inn="7800000000", name="ООО ГИГ Тест",
        external_ref=str(uuid.uuid4()),
    )
    warehouse = Warehouse(
        company_id=company.id, code="208", name="АЗС 208",
        external_ref=str(uuid.uuid4()),
    )
    db.add_all([supplier, organization, warehouse])
    await db.flush()
    contract = Contract(
        company_id=company.id, number="ПОСТ-1", date="2026-08-01",
        counterparty_id=str(supplier.id), organization_id=str(organization.id),
        type="СПоставщиком", kind="СПоставщиком", scope_type="company",
        external_ref=str(uuid.uuid4()),
    )
    db.add(contract)
    await db.flush()
    document_id = uuid.uuid4()
    receipt = StoreReceipt(
        id=document_id, company_id=company.id, station_id=208, number="П-208-1",
        doc_date=datetime(2026, 8, 9, tzinfo=timezone.utc),
        supplier_id=supplier.id, supplier=supplier.name,
        contract_id=contract.id, contract=contract.number,
        organization_id=organization.id, warehouse_id=warehouse.id,
        incoming_number="УПД-1",
        incoming_date=datetime(2026, 8, 8, tzinfo=timezone.utc),
        status="expected", origin="center", delivery_scheme="supplier_to_station",
        signing_mode="office_director", signature_status="pending",
        lines=[{"name": "Вода", "nomenclature_ref": str(uuid.uuid4()),
                "barcode": "4600000000007", "qty_expected": 2, "qty_fact": 0,
                "price": 50, "vat_amount": 0, "upd_codes": [], "mark_codes": [],
                "pack_codes": []}], total_amount=0, vat_amount=0,
    )
    db.add(receipt)
    await db.commit()

    source_uuid = str(uuid.uuid4())
    payload = {
        "ВерсияФормата": "3", "ИдентификаторПакета": str(uuid.uuid4()),
        "ХешПакета": "hash-1",
    }
    doc = {
        "Тип": "purchase", "document_id": str(document_id),
        "ИсточникUUID": source_uuid, "Номер": "П-208-1",
        "Дата": "2026-08-09T10:00:00+03:00", "Контрагент": supplier.name,
        "supplier_id": str(supplier.id), "contract_id": str(contract.id),
        "ДоговорКонтрагента": str(contract.id),
        "НомерВходящегоДокумента": "УПД-1",
        "ДатаВходящегоДокумента": "2026-08-08",
        "organization_id": str(organization.id), "warehouse_id": str(warehouse.id),
        "Организация": str(organization.id), "Склад": str(warehouse.id),
        "СуммаДокумента": 120, "ВалютаДокумента": "RUB",
        "Товары": [{
            "Номенклатура": receipt.lines[0]["nomenclature_ref"],
            "Наименование": "Вода", "ШтрихКод": "4600000000007",
            "КоличествоЗаявлено": 2, "Количество": 2, "Цена": 50,
            "Сумма": 100, "СтавкаНДС": "БезНДС", "СуммаНДС": 0,
            "Единица": "шт", "МестоОприходования": "Магазин",
        }],
        "Услуги": [{"Наименование": "Доставка", "Сумма": 20,
                    "СтавкаНДС": "БезНДС", "СуммаНДС": 0, "ВСебестоимость": True}],
    }
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()

    updated = await db.get(StoreReceipt, document_id)
    assert updated.status == "accepted"
    assert updated.origin == "center"
    assert updated.source_uuid == source_uuid
    assert updated.total_amount == 120
    assert updated.services[0]["name"] == "Доставка"
    assert updated.contract == "ПОСТ-1"
    assert (await db.execute(select(func.count(StoreReceipt.id)).where(
        StoreReceipt.company_id == company.id,
        StoreReceipt.source_uuid == source_uuid,
    ))).scalar_one() == 1
    assert (await db.execute(select(func.count(StoreReceiptStockMovement.id)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 1

    # Администратор исправила количество в уже проведённой накладной: пока
    # документ не уехал в бухгалтерию, центр принимает редакцию, а движение
    # склада догоняет её корректировкой на разницу.
    doc["Товары"][0]["Количество"] = 99
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()
    await db.refresh(updated)
    assert updated.lines[0]["qty_fact"] == 99
    assert updated.accounting_status == "pending"
    assert (await db.execute(select(func.sum(StoreReceiptStockMovement.quantity)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 99
    assert (await db.execute(select(func.count(StoreReceiptStockMovement.id)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 2

    # Повтор того же пакета разницы не даёт и движений не добавляет.
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()
    assert (await db.execute(select(func.count(StoreReceiptStockMovement.id)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 2

    # Забытая позиция дописывается в проведённый документ: прежние строки целы,
    # движение по ним верно, и новая строка получает своё.
    doc["Товары"][0]["Количество"] = 2
    doc["Товары"][0]["Сумма"] = 100
    doc["Товары"].append({
        "Номенклатура": str(uuid.uuid4()), "Наименование": "Изолента",
        "ШтрихКод": "4600000000014", "КоличествоЗаявлено": 3, "Количество": 3,
        "Цена": 20, "Сумма": 60, "СтавкаНДС": "БезНДС", "СуммаНДС": 0,
        "Единица": "шт", "МестоОприходования": "Магазин",
    })
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()
    await db.refresh(updated)
    assert updated.status == "accepted"
    assert len(updated.lines) == 2
    assert updated.lines[1]["name"] == "Изолента"
    assert (await db.execute(select(func.sum(StoreReceiptStockMovement.quantity)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 5

    # Документ уехал в бухгалтерию — редакция со станции больше не применяется:
    # там его уже провёл человек, и правит он же.
    updated.accounting_status = "ready"
    await db.commit()
    doc["Товары"][0]["Количество"] = 7
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()
    await db.refresh(updated)
    assert updated.lines[0]["qty_fact"] == 2
    assert (await db.execute(select(func.sum(StoreReceiptStockMovement.quantity)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 5


def test_редакция_проведённой_приёмки_отличает_дописанное_от_изменённого():
    """Дописанная позиция — не то же самое, что исправленная.

    Администратор провела накладную и вспомнила про забытые позиции: прежние
    строки при этом не меняются, движения по ним верны, и такую редакцию центр
    вправе принять сам. Исправленное количество трогает уже сделанное движение —
    там нужен человек.
    """
    from app.routers.edge_router import _редакция_проведённой_приёмки

    class Док:
        def __init__(self, lines, services=None):
            self.lines = lines
            self.services = services or []

    было = [{"line_id": "l1", "qty_fact": 2, "price": 50, "amount": 100,
             "barcode": "460", "nomenclature_ref": "n1"}]
    дописано = было + [{"line_id": "l2", "qty_fact": 1, "price": 30, "amount": 30,
                        "barcode": "461", "nomenclature_ref": "n2"}]

    assert _редакция_проведённой_приёмки(Док(было), было, []) == "совпадает"
    assert _редакция_проведённой_приёмки(Док(было), дописано, []) == "дописано"

    изменено = [dict(было[0], qty_fact=99)]
    assert _редакция_проведённой_приёмки(Док(было), изменено, []) == "изменено"
    assert _редакция_проведённой_приёмки(Док(было), [], []) == "изменено"

    # Правка шапки при тех же строках (на 208 так меняли договор) — тоже к человеку.
    class Шапка(Док):
        supplier_id = "s1"
        contract_id = "c1"
        incoming_number = "УПД-1"
        number = "П-8-1"

    шапка = {"supplier_id": "s1", "contract_id": "c1",
             "incoming_number": "УПД-1", "number": "П-8-1"}
    assert _редакция_проведённой_приёмки(Шапка(было), было, [], шапка) == "совпадает"
    assert _редакция_проведённой_приёмки(
        Шапка(было), было, [], dict(шапка, contract_id="c2")) == "изменено"
    assert _редакция_проведённой_приёмки(
        Шапка(было), дописано, [], шапка) == "дописано"

    # Строка без line_id несравнима — зовём человека, а не гадаем по позиции.
    безымянная = [{"qty_fact": 2, "price": 50, "amount": 100}]
    assert _редакция_проведённой_приёмки(Док(было), безымянная, []) == "изменено"
    assert _редакция_проведённой_приёмки(Док(безымянная), было, []) == "изменено"
