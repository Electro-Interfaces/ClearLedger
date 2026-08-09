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
        type="ЮЛ", aliases=[], kind="external",
    )
    organization = Organization(
        company_id=company.id, inn="7800000000", name="ООО ГИГ Тест",
    )
    db.add_all([supplier, organization])
    await db.flush()
    contract = Contract(
        company_id=company.id, number="ПОСТ-1", date="2026-08-01",
        counterparty_id=str(supplier.id), organization_id=str(organization.id),
        type="СПоставщиком", kind="СПоставщиком",
    )
    db.add(contract)
    await db.flush()
    document_id = uuid.uuid4()
    receipt = StoreReceipt(
        id=document_id, company_id=company.id, station_id=208, number="П-208-1",
        doc_date=datetime(2026, 8, 9, tzinfo=timezone.utc),
        supplier_id=supplier.id, supplier=supplier.name,
        contract_id=contract.id, contract=contract.number,
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
        "Организация": str(organization.id), "Склад": str(uuid.uuid4()),
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

    doc["Товары"][0]["Количество"] = 99
    await _ingest_receipts(db, company.id, 208, payload, [doc])
    await db.commit()
    await db.refresh(updated)
    assert updated.lines[0]["qty_fact"] == 2
    assert (await db.execute(select(func.count(StoreReceiptStockMovement.id)).where(
        StoreReceiptStockMovement.receipt_id == document_id,
    ))).scalar_one() == 1
