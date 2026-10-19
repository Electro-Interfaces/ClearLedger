import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.models import Company, EdgeAgent, EdgeDownlink, EdgePacket
from app.routers import edge_router, store_router
from app.services.edge_transfers import route_transfer_tasks
from app.services.edge_transfer_register import latest_documents, between_stations


def request(station, body=None):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode() if body else b""}
    return Request({"type": "http", "headers": [(b"x-station-id", str(station).encode())]}, receive)


@pytest.mark.asyncio(loop_scope="session")
async def test_transfer_cancel_replay_capability_and_result(db, monkeypatch):
    company = Company(name="Проверка перемещений", slug="stock-flow-" + uuid.uuid4().hex, profile_id="fuel")
    db.add(company)
    await db.flush()
    recipient = EdgeAgent(company_id=company.id, station_id=8, payload={})
    db.add_all([recipient, EdgeAgent(company_id=company.id, station_id=208, payload={})])
    await db.commit()
    outgoing = {"Тип": "transfer", "ИсточникUUID": "source", "ИдентификаторДокумента": "out",
                "Дата": "2026-10-19T10:00:00+03:00", "Направление": "out", "КодАЗСПолучателя": 8,
                "РедакцияДата": "2026-10-19T10:00:00.123456+03:00",
                "Товары": [{"Номенклатура": "item", "ШтрихКод": "111", "КоличествоОтправлено": 3}]}
    payload = {"Документы": [outgoing], "ВремяВыгрузки": outgoing["РедакцияДата"]}
    assert await route_transfer_tasks(db, company.id, 208, payload) == 1
    await db.commit()
    assert await route_transfer_tasks(db, company.id, 208, payload) == 0
    cancelled = {**payload, "Документы": [{**outgoing, "ПометкаУдаления": True}]}
    assert await route_transfer_tasks(db, company.id, 208, cancelled) == 1
    await db.commit()
    assert (await edge_router.downlink(request(8), company, 8, db))["count"] == 0
    recipient.payload = {"capabilities": ["transfer_cancellation_v1"]}
    await db.commit()
    response = await edge_router.downlink(request(8), company, 8, db)
    assert response["count"] == 1
    task = response["tasks"][0]
    assert task["kind"] == "incoming_transfer_cancelled"
    result = {"result": {"document_id": "incoming:208:out", "status": "conflict", "reason": "Уже принято"}}
    await edge_router.downlink_ack(uuid.UUID(task["id"]), request(8, result), company, 8, db)
    saved = await db.get(EdgeDownlink, uuid.UUID(task["id"]))
    assert saved.payload["_delivery_result"]["status"] == "conflict"
    # Поздний исходный пакет не возрождает задание при равной legacy-метке.
    assert await route_transfer_tasks(db, company.id, 208, payload) == 0
    await db.commit()
    assert (await edge_router.downlink(request(8), company, 8, db))["count"] == 0
    db.add_all([
        EdgePacket(company_id=company.id, station_id=208, packet_uuid="original", kind="transfer", payload=payload),
        EdgePacket(company_id=company.id, station_id=208, packet_uuid="cancel", kind="transfer", payload=cancelled),
    ])
    await db.commit()
    documents = await latest_documents(db, company.id)
    assert len(documents) == 1 and documents[0]["doc"]["ПометкаУдаления"]
    register = await between_stations(db, company.id)
    assert register["total"] == 0 and len(register["cancellation_conflicts"]) == 1
    assert (await between_stations(db, company.id, station_scope=()))["cancellation_conflicts"] == []


@pytest.mark.asyncio(loop_scope="session")
async def test_stock_register_latest_tombstone_company_station_and_date(db, monkeypatch):
    company = Company(name="Проверка списаний", slug="writeoff-flow-" + uuid.uuid4().hex, profile_id="fuel")
    other = Company(name="Другая компания", slug="other-flow-" + uuid.uuid4().hex, profile_id="fuel")
    db.add_all([company, other])
    await db.commit()
    document = {"Тип": "writeoff", "ИсточникUUID": "writeoff", "Номер": "СП-1", "Автор": "оператор",
                "Дата": "2026-10-18T23:30:00Z", "МестоХранения": "20800002",
                "Товары": [{"Номенклатура": "item", "Наименование": "Товар", "Количество": 2,
                            "Сумма": 20, "КачествоСебестоимости": "unknown"}]}
    for station, cid, packet, doc in [(208, company.id, "one", document),
            (242, company.id, "two", {**document, "ИсточникUUID": "station242"}),
            (208, other.id, "foreign", {**document, "ИсточникUUID": "foreign"})]:
        db.add(EdgePacket(company_id=cid, station_id=station, packet_uuid=packet, kind="writeoff",
                          payload={"Документы": [doc], "ВремяВыгрузки": "2026-10-19T08:00:00Z"}))
    await db.commit()
    async def cid(*_args): return company.id
    async def access(*_args): return SimpleNamespace(network=False, station_ids=(208,))
    monkeypatch.setattr(store_router, "scope_company_id", cid)
    monkeypatch.setattr(store_router, "resolve_document_access", access)
    from datetime import date
    response = await store_router.store_stock_documents("writeoff", date(2026, 10, 19), date(2026, 10, 19), None, None, db)
    assert response["total"] == 1
    assert response["docs"][0]["author"] == "оператор"
    assert response["docs"][0]["place_from"] == "20800002"
    assert response["amount"] == 0 and response["unvalued_positions"] == 1
    assert (await store_router.store_stock_documents("writeoff", None, None, "242", None, db))["total"] == 0
    db.add(EdgePacket(company_id=company.id, station_id=208, packet_uuid="deleted", kind="writeoff",
        payload={"Документы": [{**document, "ПометкаУдаления": True}], "ВремяВыгрузки": "2026-10-19T09:00:00Z"}))
    await db.commit()
    assert (await store_router.store_stock_documents("writeoff", None, None, None, None, db))["total"] == 0
