"""Ядро для узла «Телефонии»: телефоны в E.164 (Я-3), опознание и сводка (Я-1, Я-2),
ключ с областью voice.identify.

Ловим:
  * разбор телефона в базе (`phone_to_e164`) и в коде (`to_e164`) разошёлся — узел
    присылает одно, а колонка хранит другое, и звонящий «не находится»;
  * генерируемые колонки не следуют за правкой телефона;
  * общий ключ машинных ручек открывает ПДн звонящего, а ключ узла — общие ручки;
  * «Телефония» выключена компании, а узел всё равно получает ответ;
  * номер звонящего уходит в ответ целиком.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    App, ChargeSession, Company, CorporateClient, Counterparty, CounterpartyContact,
    EzsCustomer, ServiceLocation, SpaceInboundKey, User, UserCompany,
)
from app.services import app_registry
from app.services.phone_e164 import mask, to_e164

pytestmark = pytest.mark.asyncio(loop_scope="session")

SAMPLES = [
    ("+7 (900) 123-45-67", "+79001234567"),
    ("89001234567", "+79001234567"),
    ("8 (495) 123-45-67, доб. 12", "+74951234567"),
    ("+7(999) 999 99-95", "+79999999995"),
    ("9001234567", "+79001234567"),
    ("Главный: 8 495 111-22-33", "+74951112233"),
    ("123-45, 8-912-000-11-22", "+79120001122"),
    ("+7 495 111 22 33 вн. 401", "+74951112233"),
    ("+7 495 111 22 33 ext 5", "+74951112233"),
    ("8 800 / 8 (343) 222-33-44", "+73432223344"),
    ("+49 30 1234567", "+49301234567"),
    ("12-34", None),
    ("", None),
    ("нет", None),
    (None, None),
]


async def _company(db: AsyncSession, slug: str) -> Company:
    return (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()


async def _key(db: AsyncSession, company_id, scopes) -> str:
    raw = secrets.token_urlsafe(24)
    db.add(SpaceInboundKey(company_id=company_id, consumer=f"Узел {uuid.uuid4().hex[:4]}",
                           key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:8],
                           actor_kind="agent", scopes=scopes))
    await db.commit()
    return raw


async def _voice(db: AsyncSession, company_id, enabled: bool) -> None:
    await app_registry.seed_apps(db)
    app_id = (await db.execute(select(App.id).where(App.code == "voice"))).scalar_one()
    await app_registry.set_app(db, company_id, app_id, enabled)


async def test_phone_sql_and_python_agree(db: AsyncSession):
    for raw, want in SAMPLES:
        assert to_e164(raw) == want, raw
        got = (await db.execute(text("SELECT phone_to_e164(:p)"), {"p": raw})).scalar()
        assert got == want, raw
    assert mask("+79001234567") == "+7 900 ***-**-67"
    assert "1234" not in mask("+49301234567")


async def test_generated_columns_follow_phone(db: AsyncSession):
    company = await _company(db, "rushydro")
    cp = Counterparty(company_id=company.id, inn=f"77{uuid.uuid4().int % 10**8:08d}",
                      name="ООО Колонка", phone="8 (495) 765-43-21, доб. 7")
    db.add(cp)
    await db.flush()
    contact = CounterpartyContact(company_id=company.id, counterparty_id=cp.id,
                                  name="Колонкин", phone="+7 912 000 11 22")
    db.add(contact)
    await db.commit()
    await db.refresh(cp)
    await db.refresh(contact)
    assert cp.phone_e164 == "+74957654321"
    assert contact.phone_e164 == "+79120001122"
    await db.execute(update(Counterparty).where(Counterparty.id == cp.id)
                     .values(phone="89120001133"))
    await db.commit()
    await db.refresh(cp)
    assert cp.phone_e164 == "+79120001133"


async def _seed_caller(db: AsyncSession, company: Company, phone: str) -> dict:
    """Клиент ЭЗС с двумя сессиями (одна пустая) на станции + сессия по карте."""
    ext = f"u{uuid.uuid4().hex[:8]}"
    loc_id = f"loc-{uuid.uuid4().hex[:8]}"
    code = f"65.{uuid.uuid4().int % 10**6:06d}"
    db.add(ServiceLocation(id=loc_id, company_id=company.id, code=code, name="ЭЗС Саяногорск",
                           address="ул. Ленина, 1", operational_status="not_working",
                           station_number=code))
    db.add(EzsCustomer(company_id=company.id, customer_ext_id=ext, phone=phone,
                       is_active=True, balance=150.5, registered_at=datetime(2025, 3, 1, 10, 0)))
    await db.flush()
    now = datetime.now() + timedelta(hours=3)
    for i, (kwh, res) in enumerate([(0, "CompleteError"), (31.5, "Complete")]):
        db.add(ChargeSession(company_id=company.id, session_ext_id=f"s-{ext}-{i}",
                             location_id=loc_id, station_code=code,
                             started_at=now - timedelta(days=i + 1), user_id=phone,
                             result=res, energy_kwh=kwh, amount=kwh * 18))
    db.add(ChargeSession(company_id=company.id, session_ext_id=f"s-{ext}-card",
                         location_id=loc_id, started_at=now - timedelta(days=40),
                         user_id=None, card_owner_ext_id=ext, result="Complete",
                         energy_kwh=10, amount=180))
    await db.commit()
    return {"ext": ext, "loc": loc_id, "code": code}


async def test_identify_and_summary(client: AsyncClient, db: AsyncSession):
    company = await _company(db, "rushydro")
    await _voice(db, company.id, True)
    key = await _key(db, company.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    seeded = await _seed_caller(db, company, phone)
    db.add(CorporateClient(company_id=company.id, name="ООО Парк", phone=phone, inn="7700000001",
                           status="Действующая"))
    staff = User(email=f"staff-{uuid.uuid4().hex[:6]}@test.ru", name="Сотрудников Сотрудник",
                 password_hash="x", phone_mobile=phone.replace("+7", "8 ("))
    db.add(staff)
    await db.flush()
    db.add(UserCompany(user_id=staff.id, company_id=company.id))
    await db.commit()

    pretty = f"8 ({phone[2:5]}) {phone[5:8]}-{phone[8:10]}-{phone[10:]}"
    r = await client.post("/api/eco/identify", json={"channel": "phone", "value": pretty},
                          headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert phone not in r.text and phone[2:] not in r.text, "номер целиком в ответе"
    assert body["phoneMasked"].endswith(phone[-2:])
    kinds = [(c["kind"], c["source"]) for c in body["candidates"]]
    assert kinds[0] == ("driver", "ezs_customer"), kinds
    first = body["candidates"][0]
    assert first["ref"] == f"ezs:{seeded['ext']}" and first["name"] is None
    assert first["balance"] == 150.5 and first["active"] is True
    assert first["registeredAt"].startswith("2025-03-01T10:00:00+03:00")
    assert ("organization", "corporate_client") in kinds
    assert ("staff", "user") in kinds
    corp = next(c for c in body["candidates"] if c["source"] == "corporate_client")
    assert corp["orgName"] == "ООО Парк" and corp["active"] is True

    r = await client.post("/api/eco/ezs/customer-summary",
                          json={"phone": phone, "ref": first["ref"], "limit": 5},
                          headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200, r.text
    s = r.json()
    assert [x["result"] for x in s["sessions"]] == ["CompleteError", "Complete", "Complete"]
    assert s["sessions"][0]["failed"] is True and s["sessions"][1]["failed"] is False
    assert s["sessions"][0]["startedAt"].endswith("+03:00")
    assert s["sessions"][2]["ref"].endswith("-card"), "сессия по карте владельца"
    assert s["objects"] == [{"ref": seeded["loc"], "code": seeded["code"], "name": "ЭЗС Саяногорск",
                             "address": "ул. Ленина, 1", "status": "not_working"}]
    assert s["stats"] == {"sessions30d": 2, "failed30d": 1}

    # Без клиента ЭЗС — только по телефону; карта чужого клиента не подтягивается.
    r = await client.post("/api/eco/ezs/customer-summary", json={"phone": phone, "limit": 1},
                          headers={"X-Cloud-API-Key": key})
    assert [x["result"] for x in r.json()["sessions"]] == ["CompleteError"]
    r = await client.post("/api/eco/ezs/customer-summary",
                          json={"phone": "+79990000000", "ref": "ezs:нет-такого"},
                          headers={"X-Cloud-API-Key": key})
    assert r.json()["sessions"] == []

    # Незнакомый и неразборчивый номер — пустой список, не ошибка.
    r = await client.post("/api/eco/identify", json={"value": "+79990000000"},
                          headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200 and r.json()["candidates"] == []
    r = await client.post("/api/eco/identify", json={"value": "123"},
                          headers={"X-Cloud-API-Key": key})
    assert r.json() == {"channel": "phone", "phoneMasked": "—", "candidates": []}


async def test_other_company_data_is_not_seen(client: AsyncClient, db: AsyncSession):
    rh, gig = await _company(db, "rushydro"), await _company(db, "gig")
    await _voice(db, gig.id, True)
    key = await _key(db, gig.id, ["voice.identify"])
    phone = f"+7901{uuid.uuid4().int % 10**7:07d}"
    await _seed_caller(db, rh, phone)
    r = await client.post("/api/eco/identify", json={"value": phone},
                          headers={"X-Cloud-API-Key": key})
    assert r.status_code == 200 and r.json()["candidates"] == []
    r = await client.post("/api/eco/ezs/customer-summary", json={"phone": phone},
                          headers={"X-Cloud-API-Key": key})
    assert r.json()["sessions"] == []


async def test_key_scopes_and_voice_switch(client: AsyncClient, db: AsyncSession):
    company = await _company(db, "rushydro")
    await _voice(db, company.id, True)
    general = await _key(db, company.id, None)
    node = await _key(db, company.id, ["voice.identify"])
    body = {"value": "+79001234567"}

    assert (await client.post("/api/eco/identify", json=body,
                              headers={"X-Cloud-API-Key": general})).status_code == 403
    assert (await client.post("/api/eco/identify", json=body,
                              headers={"X-Cloud-API-Key": "wrong"})).status_code == 401
    # Легаси-ключ компании — общий, ПДн не открывает.
    legacy = (await db.execute(select(Company.cloud_api_key).where(Company.id == company.id))).scalar()
    if legacy:
        assert (await client.post("/api/eco/identify", json=body,
                                  headers={"X-Cloud-API-Key": legacy})).status_code == 401
    # Ключ узла не открывает общие машинные ручки.
    r = await client.post("/api/eco/events", json={"type": "ping"}, headers={"X-Cloud-API-Key": node})
    assert r.status_code == 403, r.text

    ok = await client.post("/api/eco/identify", json=body, headers={"X-Cloud-API-Key": node})
    assert ok.status_code == 200
    used = (await db.execute(select(SpaceInboundKey.last_used_at).where(
        SpaceInboundKey.key_prefix == node[:8]))).scalar()
    assert used is not None

    await _voice(db, company.id, False)
    try:
        r = await client.post("/api/eco/identify", json=body, headers={"X-Cloud-API-Key": node})
        assert r.status_code == 403 and "Телефония" in r.json()["detail"]
    finally:
        await _voice(db, company.id, True)

    # Номер — только в теле: GET-адреса с номером нет.
    assert (await client.get("/api/eco/identify", params=body,
                             headers={"X-Cloud-API-Key": node})).status_code == 405


async def test_admin_issues_scoped_key(auth_client: AsyncClient):
    r = await auth_client.post("/api/inbound-keys", json={
        "company_id": "rushydro", "consumer": "Узел «Телефонии» РусГидро",
        "actor_kind": "agent", "scopes": ["voice.identify"]})
    assert r.status_code in (200, 201), r.text
    assert r.json()["scopes"] == ["voice.identify"]
    listed = (await auth_client.get("/api/inbound-keys", params={"company_id": "rushydro"})).json()
    rows = listed if isinstance(listed, list) else listed.get("items", listed.get("keys", []))
    assert any(k.get("scopes") == ["voice.identify"] for k in rows), listed
    bad = await auth_client.post("/api/inbound-keys", json={
        "company_id": "rushydro", "consumer": "x", "scopes": ["voice.everything"]})
    assert bad.status_code == 422
