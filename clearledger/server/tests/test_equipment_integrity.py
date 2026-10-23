"""Складской цикл на настоящей изолированной PostgreSQL, без моков движений."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (Company, Contract, Counterparty, Organization,
                        ServiceLocation, EzsEquipmentMovement, EzsEquipmentUnit,
                        EzsSparePart)
from app.services import ezs_equipment as E, ezs_equipment_docs as D, ezs_supply as S, ezs_spare_docs as Z


async def graph(db):
    cid = (await db.execute(select(Company.id).where(Company.slug == "rushydro"))).scalar_one()
    tag = uuid.uuid4().hex[:8]
    cp = Counterparty(company_id=cid, inn=tag, name=f"Тест · Поставщик {tag}")
    other = Counterparty(company_id=cid, inn=tag + "1", name=f"Тест · Второй {tag}")
    org = Organization(company_id=cid, inn=tag, name=f"Тест · Организация {tag}")
    a = ServiceLocation(id=f"qa-a-{tag}", company_id=cid, code=f"A-{tag}", name="Тест · Склад А", type="warehouse")
    b = ServiceLocation(id=f"qa-b-{tag}", company_id=cid, code=f"B-{tag}", name="Тест · Склад Б", type="warehouse")
    site = ServiceLocation(id=f"qa-s-{tag}", company_id=cid, code=f"S-{tag}", name="Тест · Объект", type="ev_charging")
    db.add_all([cp, other, org, a, b, site])
    await db.flush()
    c = Contract(company_id=cid, counterparty_id=cp.id, organization_id=org.id,
                 number=tag, date="2026-01-01", valid_until="2027-12-31", type="Поставка")
    db.add(c)
    await db.flush()
    return cid, tag, cp, other, c, a, b, site


async def supply(db, g, **extra):
    cid, tag, cp, other, c, a, b, site = g
    return await S.create_supply(db, cid, None, {
        "number": tag, "doc_date": "2026-10-01", "counterparty_id": cp.id,
        "contract_id": c.id, "warehouse_id": a.id,
        "lines": [{"line_kind": "station", "qty_planned": 2, "unit_price": 1000}], **extra})


async def unit(db, g):
    cid, tag, cp, other, c, a, b, site = g
    u = await E.create_unit(db, cid, None, {"serial_number": tag, "initial_location_id": a.id,
                                         "occurred_on": "2026-10-01"})
    await db.flush()
    m = (await db.execute(select(EzsEquipmentMovement).where(EzsEquipmentMovement.unit_id == u.id))).scalar_one()
    d = await D.document_for(db, cid, None, "receipt", [m], doc_date="2026-10-01")
    await db.flush()
    return u, d


async def test_supplier_change_cannot_keep_unrelated_contract(db):
    g = await graph(db)
    doc = await supply(db, g)
    with pytest.raises(HTTPException, match="другим контрагентом"):
        await S.update_supply(db, g[0], None, doc.id, {"counterparty_id": g[3].id})


@pytest.mark.parametrize("bad", ["2026-02-30", "01.10.2026", "garbage"])
async def test_supply_rejects_invalid_calendar_date(db, bad):
    g = await graph(db)
    with pytest.raises(HTTPException, match="[Дд]ат"):
        await supply(db, g, doc_date=bad)


async def test_supply_head_cannot_rewrite_receipted_primary_document(db):
    g = await graph(db)
    doc = await supply(db, g)
    await S.set_status(db, g[0], None, doc.id, "confirm")
    line = (await S._lines_of(db, g[0], doc.id))[0]
    await S.receive_line(db, g[0], None, doc.id, line.id, {"units": [{"serial": g[1]}]})
    await db.flush()
    with pytest.raises(HTTPException, match="при[её]м|реквизит|провед"):
        await S.update_supply(db, g[0], None, doc.id, {"number": "ДРУГАЯ НАКЛАДНАЯ"})


@pytest.mark.parametrize("qty", [0.5, 1.5])
async def test_serialized_equipment_plan_must_be_whole(db, qty):
    g = await graph(db)
    with pytest.raises(HTTPException, match="цел"):
        await supply(db, g, lines=[{"line_kind": "station", "qty_planned": qty}])


async def test_receipt_does_not_truncate_fractional_equipment(db):
    g = await graph(db)
    doc = await supply(db, g)
    await S.set_status(db, g[0], None, doc.id, "confirm")
    line = (await S._lines_of(db, g[0], doc.id))[0]
    with pytest.raises(HTTPException, match="цел"):
        await S.receive_line(db, g[0], None, doc.id, line.id, {"qty": 1.5})


async def test_cancel_cannot_erase_later_supply_return(db):
    g = await graph(db)
    cid, tag, cp, other, c, a, b, site = g
    u, receipt = await unit(db, g)
    move_doc = await D.post_document(db, cid, None, {
        "op": "transfer", "unit_ids": [str(u.id)], "doc_date": "2026-10-02", "to_location_id": b.id})
    ret = await supply(db, g, doc_type="return", number=tag + "-return")
    await S.set_status(db, cid, None, ret.id, "confirm")
    line = (await S._lines_of(db, cid, ret.id))[0]
    await S.receive_line(db, cid, None, ret.id, line.id, {"unit_ids": [u.id], "occurred_on": "2026-10-03"})
    await db.flush()
    # now() внутри одной транзакции совпадает: имитируем два последовательных HTTP commit.
    moves = list((await db.execute(select(EzsEquipmentMovement).where(
        EzsEquipmentMovement.unit_id == u.id).order_by(EzsEquipmentMovement.occurred_on))).scalars())
    for i, m in enumerate(moves):
        m.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=i)
    await db.flush()
    with pytest.raises(HTTPException, match="сначала отмените"):
        await D.cancel_document(db, cid, None, move_doc["id"], "Тест порядка отмены")
    assert u.state == "returned_to_vendor"


@pytest.mark.parametrize("price", [-1, "NaN", "Infinity"])
async def test_supply_rejects_invalid_unit_price(db, price):
    g = await graph(db)
    with pytest.raises(HTTPException, match="[Цц]ен|числ"):
        await supply(db, g, lines=[{"line_kind": "station", "qty_planned": 1, "unit_price": price}])


async def test_receipt_transfer_cancel_restores_exact_position(db):
    g = await graph(db)
    u, receipt = await unit(db, g)
    d = await D.post_document(db, g[0], None, {
        "op": "transfer", "unit_ids": [str(u.id)], "doc_date": "2026-10-02", "to_location_id": g[6].id,
        "primary_number": "ТЕСТ-М11", "primary_date": "2026-10-02"})
    assert u.current_location_id == g[6].id
    await D.cancel_document(db, g[0], None, d["id"], "Ошибочный склад")
    assert u.current_location_id == g[5].id and u.state == "in_stock_new"


async def test_spare_cancel_cannot_rewrite_average_cost_of_later_expense(db):
    g = await graph(db)
    cid, tag, cp, other, c, a, b, site = g
    part = EzsSparePart(company_id=cid, name="Тест · Кабель", kind="material")
    db.add(part)
    await db.flush()
    docs = []
    for day, qty, price in [("2026-10-01", 2, 100), ("2026-10-02", 8, 1)]:
        docs.append(await Z.post_document(db, cid, None, {
            "op": "receipt", "doc_date": day, "to_location_id": a.id,
            "lines": [{"partId": str(part.id), "qty": qty, "price": price}]}))
    docs.append(await Z.post_document(db, cid, None, {
        "op": "write_off", "doc_date": "2026-10-03", "from_location_id": a.id,
        "lines": [{"partId": str(part.id), "qty": 7}]}))
    from app.models import EzsSparePartMovement
    moves = list((await db.execute(select(EzsSparePartMovement).where(
        EzsSparePartMovement.part_id == part.id).order_by(EzsSparePartMovement.occurred_on))).scalars())
    for i, m in enumerate(moves):
        m.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=i)
    await db.flush()
    with pytest.raises(HTTPException, match="[Сс]начала отмените"):
        await Z.cancel_document(db, cid, None, docs[0]["id"], "Ошибочный приход")


async def test_quantity_documents_reject_serialized_nomenclature(db):
    g = await graph(db)
    part = EzsSparePart(company_id=g[0], name="Тест · Станция по экземплярам", kind="station")
    db.add(part)
    await db.flush()
    with pytest.raises(HTTPException, match="экземпляр"):
        await Z.post_document(db, g[0], None, {"op": "receipt", "doc_date": "2026-10-01",
            "to_location_id": g[5].id, "lines": [{"partId": str(part.id), "qty": 1, "price": 1000}]})


@pytest.mark.parametrize("bad", ["2026-02-30", "01.10.2026"])
async def test_manual_receipt_rejects_invalid_date(db, bad):
    g = await graph(db)
    with pytest.raises(HTTPException, match="[Дд]ат"):
        await E.create_unit(db, g[0], None, {"serial_number": g[1], "initial_location_id": g[5].id, "occurred_on": bad})


async def test_supply_duplicate_cannot_be_created_by_renaming(db):
    g = await graph(db)
    first = await supply(db, g)
    second = await supply(db, g, number=g[1] + "-second")
    with pytest.raises(HTTPException, match="уже введён"):
        await S.update_supply(db, g[0], None, second.id, {"number": first.number})


async def test_lifecycle_install_commission_dismantle_repair(db):
    g = await graph(db)
    u, receipt = await unit(db, g)
    cid, tag, cp, other, contract, a, b, site = g
    steps = [("reserve", "reserved", {}), ("unreserve", "in_stock_new", {}),
             ("to_installation", "in_installation", {"to_location_id": site.id}),
             ("commissioning", "in_operation", {}),
             ("dismantle", "in_stock_used", {"to_location_id": a.id}),
             ("to_repair", "in_repair", {"counterparty_id": cp.id, "contract_id": contract.id}),
             ("from_repair", "in_stock_used", {"to_location_id": b.id, "counterparty_id": cp.id, "contract_id": contract.id}),
             ("write_off", "written_off", {})]
    for i, (op, state, fields) in enumerate(steps, 2):
        await D.post_document(db, cid, None, {"op": op, "unit_ids": [str(u.id)], "doc_date": f"2026-10-{i:02}", **fields})
        assert u.state == state
    assert u.is_used and u.current_location_id is None


@pytest.mark.parametrize("path", [
    "units", "movements", "documents", "documents/meta", "overview", "warehouses/summary",
    "supplies", "suppliers", "spare-parts", "spare-parts/movements/journal", "spare-documents",
    "audit", "settings", "people", "accounting/meta",
    "reports/stock", "reports/turnover", "reports/holders", "reports/repairs", "reports/balance", "reports/osv",
])
async def test_equipment_http_read_contract(auth_client, path):
    r = await auth_client.get(f"/api/equipment/{path}", params={"company_id": "rushydro"})
    assert r.status_code == 200, (path, r.text)
    assert isinstance(r.json(), (dict, list))


async def test_failed_group_document_is_atomic(auth_client, db):
    g = await graph(db)
    u, receipt = await unit(db, g)
    uid, wh = str(u.id), g[6].id
    await db.commit()
    r = await auth_client.post("/api/equipment/documents", params={"company_id": "rushydro"}, json={
        "op": "transfer", "unitIds": [uid, str(uuid.uuid4())], "docDate": "2026-10-02", "toLocationId": wh})
    assert r.status_code == 404, r.text
    r = await auth_client.get(f"/api/equipment/units/{uid}", params={"company_id": "rushydro"})
    assert r.status_code == 200
    assert r.json()["location"]["id"] == g[5].id
    assert len(r.json()["movements"]) == 1


async def test_closed_period_blocks_receipt_and_cancellation(db):
    g = await graph(db)
    u, receipt = await unit(db, g)
    c = await db.get(Company, g[0])
    c.customization = {**(c.customization or {}), "equipment": {"closedUntil": "2026-10-10"}}
    await db.flush()
    with pytest.raises(HTTPException, match="закрытый период"):
        await E.create_unit(db, g[0], None, {"serial_number": g[1] + "-new", "initial_location_id": g[5].id,
                                          "occurred_on": "2026-10-10"})
    with pytest.raises(HTTPException, match="закрытый период"):
        await D.cancel_document(db, g[0], None, receipt.id, "Тест запрета")


async def test_other_company_cannot_move_or_reference_equipment(db):
    g = await graph(db)
    u, receipt = await unit(db, g)
    other = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    with pytest.raises(HTTPException, match="не найдена"):
        await E.apply_movement(db, other, None, u.id, {"op": "transfer", "to_location_id": g[6].id})
    with pytest.raises(HTTPException, match="не найден"):
        await D.check_contract(db, other, g[4].id, g[2].id)


async def test_count_sheet_requires_warehouse(auth_client, db):
    g = await graph(db)
    await db.commit()
    missing = await auth_client.get("/api/equipment/spare-documents/count-sheet", params={"company_id": "rushydro"})
    assert missing.status_code == 422
    r = await auth_client.get("/api/equipment/spare-documents/count-sheet", params={"company_id": "rushydro", "location_id": g[5].id})
    assert r.status_code == 200, r.text


async def test_supply_spares_cannot_backdate_after_newer_stock_document(db):
    g = await graph(db)
    p = EzsSparePart(company_id=g[0], name="Тест · Материал", kind="material")
    db.add(p)
    await db.flush()
    doc = await supply(db, g, lines=[{"line_kind": "spare", "part_id": p.id, "qty_planned": 10, "unit_price": 50}])
    await S.set_status(db, g[0], None, doc.id, "confirm")
    line = (await S._lines_of(db, g[0], doc.id))[0]
    await Z.post_document(db, g[0], None, {"op": "receipt", "doc_date": "2026-10-03", "to_location_id": g[5].id,
        "lines": [{"partId": str(p.id), "qty": 1, "price": 100}]})
    with pytest.raises(HTTPException, match="дата не может быть раньше"):
        await S.receive_line(db, g[0], None, doc.id, line.id, {"qty": 1, "occurred_on": "2026-10-01"})


async def test_supply_note_does_not_revalidate_historical_contract(db):
    g = await graph(db)
    doc = await supply(db, g)
    g[4].is_closed = True
    await db.flush()
    await S.update_supply(db, g[0], None, doc.id, {"note": "Тест · примечание"})
    assert doc.note == "Тест · примечание" and doc.contract_id == g[4].id


async def test_import_rejects_broken_workbook_with_client_error(db):
    g = await graph(db)
    with pytest.raises(HTTPException, match="Excel") as error:
        await E.import_units_xlsx(db, g[0], None, b"broken workbook", "broken.xlsx", True)
    assert error.value.status_code == 400


async def test_import_preview_reads_all_sheets_without_changing_stock(db):
    import io
    import openpyxl
    from sqlalchemy import func
    g = await graph(db)
    wb = openpyxl.Workbook()
    for i, ws in enumerate([wb.active, wb.create_sheet("Медленные")]):
        ws.append(["Серийный номер", "Производитель", "Модель", "Склад"])
        ws.append([g[1] + str(i), "Тест", "Модель", "Тест · Новый склад импорта"])
    content = io.BytesIO()
    wb.save(content)
    before = await db.scalar(select(func.count()).select_from(EzsEquipmentUnit))
    report = await E.import_units_xlsx(db, g[0], None, content.getvalue(), "preview.xlsx", True)
    assert report["dryRun"] and report["created"] == 2 and len(report["sheets"]) == 2
    assert await db.scalar(select(func.count()).select_from(EzsEquipmentUnit)) == before
    assert await db.scalar(select(func.count()).select_from(ServiceLocation).where(
        ServiceLocation.company_id == g[0], ServiceLocation.name == "Тест · Новый склад импорта")) == 0
