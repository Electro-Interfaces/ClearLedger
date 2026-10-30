"""Перечень станций в СМР: сохранение, история, область доступа и отсутствие демонтажа."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Company, EzsSite, EzsSiteEvent, ServiceLocation
from app.scope import set_request_scope
from app.services.ezs_site_work import _coerce, update_site
from tests.helpers import seed_company_id


@pytest.mark.parametrize("field,value", [
    ("dismantle_location_ids", "ezs-one"),
    ("dismantle_location_ids", [None]),
    ("dismantle_location_ids", [""]),
    ("dismantle_location_ids", ["x" * 41]),
    ("decommissioned_on", "2026-02-30"),
    ("decommissioned_on", "20260201"),
    ("decommissioned_on", "01.02.2026"),
])
def test_invalid_passport_value_is_rejected(field, value):
    with pytest.raises(ValueError):
        _coerce(field, value)


@pytest.mark.asyncio(loop_scope="session")
async def test_passport_roundtrip_history_clear_and_foreign_station_rejection(auth_client, db):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    company = (await db.execute(select(Company).where(Company.id == cid))).scalar_one()
    foreign = (await db.execute(select(Company).where(Company.id != cid).limit(1))).scalar_one()
    station = ServiceLocation(id=str(uuid4()), company_id=company.id, code="QA-01", name="Тест · ЭЗС", type="ev_charging", status="active", operational_status="working")
    other = ServiceLocation(id=str(uuid4()), company_id=foreign.id, code="QA-02", name="Другая компания", type="ev_charging", status="active")
    warehouse = ServiceLocation(id=str(uuid4()), company_id=company.id, code="QA-03", name="Склад", type="warehouse", status="active")
    db.add_all([station, other, warehouse])
    await db.commit()
    response = await auth_client.post("/api/sites", params={"company_id": cid}, json={"address": "Тест · Паспорт СМР", "kind": "decommission"})
    assert response.status_code in (200, 201), response.text
    site_id = response.json()["id"]
    url = f"/api/sites/{site_id}"
    params = {"company_id": cid}
    response = await auth_client.patch(url, params=params, json={"dismantle_location_ids": [station.id, station.id], "decommissioned_on": "2026-11-12"})
    assert response.status_code == 200, response.text
    detail = (await auth_client.get(url, params=params)).json()
    assert detail["dismantleLocationIds"] == [station.id]
    assert detail["decommissionedOn"] == "2026-11-12"
    assert {"dismantle_location_ids", "decommissioned_on"} <= set(detail["manualFields"])
    await db.refresh(station)
    assert station.status == "active" and station.operational_status == "working"
    assert station.decommissioned_on is None
    events = (await db.execute(select(EzsSiteEvent).where(EzsSiteEvent.site_id == site_id, EzsSiteEvent.kind == "edit"))).scalars().all()
    assert any("dismantle_location_ids" in {item["field"] for item in event.changes or []} for event in events)
    for bad in ([other.id], [warehouse.id], [str(uuid4())]):
        response = await auth_client.patch(url, params=params, json={"address": "Не сохранять", "dismantle_location_ids": bad})
        assert response.status_code == 422, response.text
    response = await auth_client.patch(url, params=params, json={"address": "Не сохранять", "decommissioned_on": "2026-02-30"})
    assert response.status_code == 422
    detail = (await auth_client.get(url, params=params)).json()
    assert detail["address"] == "Тест · Паспорт СМР" and detail["dismantleLocationIds"] == [station.id]
    response = await auth_client.patch(url, params=params, json={"dismantle_location_ids": [], "decommissioned_on": None})
    assert response.status_code == 200
    detail = (await auth_client.get(url, params=params)).json()
    assert detail["dismantleLocationIds"] == [] and detail["decommissionedOn"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_station_outside_object_scope_is_rejected_before_any_change(db):
    company = (await db.execute(select(Company).limit(1))).scalar_one()
    station = ServiceLocation(id=str(uuid4()), company_id=company.id, code="QA-SCOPE", name="Тест · Скоуп", type="ev_charging", status="active")
    site = EzsSite(company_id=company.id, address="Прежний адрес")
    db.add_all([station, site])
    await db.flush()
    set_request_scope(["another-location"])
    try:
        with pytest.raises(ValueError):
            await update_site(db, site, {"address": "Новый адрес", "dismantle_location_ids": [station.id]}, None)
        assert site.address == "Прежний адрес"
    finally:
        set_request_scope(None)
        await db.rollback()
