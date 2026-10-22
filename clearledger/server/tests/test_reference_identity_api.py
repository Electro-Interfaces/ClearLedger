"""Регрессии НСИ на выделенной TEST_DATABASE_URL, включая конкурирующие POST."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Company, Contract, ContractLocation, CorporateClient, Counterparty, Organization, ServiceLocation
from fastapi import HTTPException
from app.services.charge_sessions_normalize import _sync_corporate_contracts
from app.services.reference_identity import IdentityConflict
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields
from app.services.reestr_normalize import ingest_reestr
from app.services.reestr_rushydro import L2Cache
from app.services.space_registry import list_contracts
from app.services.space_links import link_counterparties

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def post(client, path, body):
    response = await client.post(f"/api/references/{path}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def setup_parties(client, company="gig"):
    tail = uuid.uuid4().hex[:8]
    cp = await post(client, "counterparties", {
        "company_id": company, "name": f"ООО Тест {tail}", "inn": "",
    })
    org = await post(client, "organizations", {
        "company_id": company, "name": f"Организация {tail}", "inn": "", "prefix": "Т",
    })
    return cp, org


def contract_body(cp, org, **kw):
    return {"company_id": "gig", "counterpartyId": cp["id"], "organizationId": org["id"],
            "number": "Тест-74", "date": "2026-01-01", "type": "Аренда", **kw}


async def test_duplicate_counterparty_post_concurrent_scoped_by_company_and_kpp(auth_client):
    body = {"company_id": "gig", "name": "ООО Повтор", "inn": "7799999999", "kpp": "779901001"}
    responses = await asyncio.gather(*[
        auth_client.post("/api/references/counterparties", json=body) for _ in range(2)])
    assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
    first = next(r.json() for r in responses if r.status_code == 201)
    conflict = next(r for r in responses if r.status_code == 409)
    assert first["id"] in conflict.text
    renamed = await auth_client.post("/api/references/counterparties", json={**body, "name": "Другое имя"})
    assert renamed.status_code == 409
    assert first["id"] in renamed.text
    assert (await post(auth_client, "counterparties", {**body, "kpp": "779902002"}))["id"] != first["id"]
    assert (await post(auth_client, "counterparties", {**body, "company_id": "rushydro"}))["id"] != first["id"]
    # У черновиков без реквизитов повтор имени не доказывает тождество.
    for _ in range(2):
        await post(auth_client, "counterparties", {**body, "inn": "", "kpp": None})


async def test_valid_inn_without_kpp_reports_existing_instead_of_duplicate(auth_client):
    body = {"company_id": "gig", "name": "ЮЛ без КПП", "inn": "7788888888"}
    created = await post(auth_client, "counterparties", body)
    for extra in ({}, {"kpp": "778801001"}):
        response = await auth_client.post("/api/references/counterparties", json={**body, **extra})
        assert response.status_code == 409 and created["id"] in response.text
    complete = await post(auth_client, "counterparties", {**body, "inn": "7777777777", "kpp": "777701001"})
    response = await auth_client.post("/api/references/counterparties", json={**body, "inn": "7777777777"})
    assert response.status_code == 409 and complete["id"] in response.text


async def test_duplicate_contract_post_concurrent_and_different_date_or_party(auth_client):
    cp, org = await setup_parties(auth_client)
    body = contract_body(cp, org)
    responses = await asyncio.gather(*[
        auth_client.post("/api/references/contracts", json=body) for _ in range(2)])
    assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
    first = next(r.json() for r in responses if r.status_code == 201)
    assert first["id"] in next(r.text for r in responses if r.status_code == 409)
    response = await auth_client.post("/api/references/contracts", json=body)
    assert response.status_code == 409 and first["id"] in response.text
    await post(auth_client, "contracts", {**body, "date": "2026-02-01"})
    cp2, org2 = await setup_parties(auth_client)
    await post(auth_client, "contracts", contract_body(cp2, org))
    await post(auth_client, "contracts", contract_body(cp, org2))


async def test_contract_checks_both_sides_on_create_and_update(auth_client):
    cp, org = await setup_parties(auth_client)
    foreign_cp, foreign_org = await setup_parties(auth_client, "rushydro")
    body = contract_body(cp, org)
    for field, value in (("counterpartyId", foreign_cp["id"]), ("organizationId", foreign_org["id"]),
                         ("organizationId", str(uuid.uuid4()))):
        response = await auth_client.post("/api/references/contracts", json={**body, field: value})
        assert response.status_code == 400, response.text
    created = await post(auth_client, "contracts", body)
    for field, value in (("counterpartyId", foreign_cp["id"]), ("organizationId", foreign_org["id"])):
        response = await auth_client.patch(f'/api/references/contracts/{created["id"]}', json={field: value})
        assert response.status_code == 400, response.text
    response = await auth_client.get("/api/references/contracts", params={"company_id": "gig"})
    saved = next(c for c in response.json() if c["id"] == created["id"])
    assert saved["counterpartyId"] == cp["id"] and saved["organizationId"] == org["id"]


async def test_patch_marks_only_fields_that_changed(auth_client, db):
    cp, org = await setup_parties(auth_client)
    created = await post(auth_client, "contracts", contract_body(cp, org))
    response = await auth_client.patch(f'/api/references/counterparties/{cp["id"]}',
                                      json={"name": cp["name"], "legalAddress": "Ручной адрес"})
    assert response.status_code == 200, response.text
    party = await db.get(Counterparty, uuid.UUID(cp["id"]))
    assert party.manual_overrides == ["legal_address"]
    response = await auth_client.patch(f'/api/references/contracts/{created["id"]}',
                                      json={"number": created["number"], "amountLimit": 123})
    assert response.status_code == 200, response.text
    doc = await db.get(Contract, uuid.UUID(created["id"]))
    assert doc.manual_overrides == ["amount_limit"]


async def test_registry_and_l2_reuse_real_orm_uuid(auth_client, db):
    cp, org = await setup_parties(auth_client)
    created = await post(auth_client, "contracts", contract_body(cp, org))
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    party = await db.get(Counterparty, uuid.UUID(cp["id"]))
    cache = L2Cache()
    await cache.build(db, company.id)
    stats = {}
    reused = await cache.contract(db, company.id, party, "Аренда", "Тест-74", "2026-01-01", "", None, stats)
    assert str(reused.id) == created["id"] and stats.get("contracts", 0) == 0
    rows = await list_contracts(db, company.id)
    row = next(r for r in rows if r["id"] == created["id"])
    assert row["counterpartyId"] == cp["id"] and row["counterpartyName"] == cp["name"]
    # Существующие дубли не скрываются выбором первой записи.
    db.add(Contract(company_id=company.id, counterparty_id=party.id,
                    organization_id=uuid.UUID(org["id"]), number="Тест-74",
                    date="2026-01-01", type="Аренда"))
    await db.flush()
    await cache.build(db, company.id)
    with pytest.raises(IdentityConflict, match="Неоднозначное"):
        await cache.contract(db, company.id, party, "Аренда", "Тест-74", "2026-01-01", "", None, {})
    await db.rollback()


async def test_legacy_reestr_same_run_and_repeat_reuse_contract(db):
    company = Company(id=uuid.uuid4(), slug=f"identity-{uuid.uuid4().hex[:8]}", name="Тест импорта", profile_id="energy")
    db.add(company)
    await db.flush()
    db.add(Organization(company_id=company.id, name="Своя организация", inn="", prefix="Т"))
    for code in ("1", "2"):
        db.add(ServiceLocation(id=f"identity-{company.id.hex[:20]}-{code}", company_id=company.id,
                               name=f"Точка {code}", code=code, type="ev_charging"))
    await db.flush()
    # Названия полей берём из того же внешнего контракта старого файла.
    from app.services.reestr_normalize import ROLE_COLS
    cp_key, number_key, _ = ROLE_COLS["rent"]
    rows = [{"bu": code, cp_key: "ООО Новый арендодатель", number_key: "№ 74 от 01.01.2026"}
            for code in ("1", "2")]
    result = await ingest_reestr(db, company.id, rows)
    assert result["contracts"] == 1 and result["counterparties"] == 1
    result = await ingest_reestr(db, company.id, rows)
    assert result["contracts"] == 0 and result["counterparties"] == 0
    count = (await db.execute(select(func.count()).select_from(Contract).where(
        Contract.company_id == company.id))).scalar_one()
    assert count == 1
    links = (await db.execute(select(func.count()).select_from(ContractLocation).where(
        ContractLocation.company_id == company.id))).scalar_one()
    assert links == 2
    party = (await db.execute(select(Counterparty).where(Counterparty.company_id == company.id))).scalar_one()
    doc = (await db.execute(select(Contract).where(Contract.company_id == company.id))).scalar_one()
    before = snapshot_reference_fields(party)
    party.name, party.aliases = "Ручное имя", ["Ручная роль"]
    mark_reference_changes(party, before)
    before = snapshot_reference_fields(doc)
    doc.number = "Ручной номер"
    mark_reference_changes(doc, before)
    result = await ingest_reestr(db, company.id, rows)
    assert result["contracts"] == 0 and result["counterparties"] == 0
    assert party.name == "Ручное имя" and party.aliases == ["Ручная роль"]
    assert doc.number == "Ручной номер"
    await db.rollback()


async def test_corporate_missing_organization_is_explicit(db):
    company = Company(id=uuid.uuid4(), slug=f"no-org-{uuid.uuid4().hex[:8]}", name="Без юрлица", profile_id="energy")
    db.add(company)
    await db.flush()
    with pytest.raises(IdentityConflict, match="Organization"):
        await _sync_corporate_contracts(db, company.id, [{"name": "ООО Тест", "inn": "", "phone": ""}])
    await db.rollback()


async def test_corporate_reimport_orm_uuid_and_pinned_source_identity(db):
    company = Company(id=uuid.uuid4(), slug=f"corp-{uuid.uuid4().hex[:8]}",
                      name="Корпоратив", profile_id="energy")
    db.add(company)
    await db.flush()
    db.add(Organization(company_id=company.id, name="Своя организация", inn="", prefix="К"))
    await db.flush()
    rows = [{"name": "ООО Корпоратив", "inn": "7711111111", "kpp": "771101001",
             "contract_start": "01.01.2026", "phone": ""}]
    await _sync_corporate_contracts(db, company.id, rows)
    await _sync_corporate_contracts(db, company.id, rows)
    party = (await db.execute(select(Counterparty).where(Counterparty.company_id == company.id))).scalar_one()
    doc = (await db.execute(select(Contract).where(Contract.company_id == company.id))).scalar_one()
    before = snapshot_reference_fields(party)
    party.name, party.kpp = "Ручное имя", "771102002"
    mark_reference_changes(party, before)
    before = snapshot_reference_fields(doc)
    doc.number, doc.type, doc.date = "Ручной номер", "Ручной вид", "2026-02-01"
    mark_reference_changes(doc, before)
    await _sync_corporate_contracts(db, company.id, rows)
    assert (await db.execute(select(func.count()).select_from(Contract).where(
        Contract.company_id == company.id))).scalar_one() == 1
    assert doc.number == "Ручной номер" and doc.type == "Ручной вид" and doc.date == "2026-02-01"
    assert party.name == "Ручное имя" and party.kpp == "771102002"
    await db.rollback()


async def test_link_counterparties_reports_ambiguous_name_as_409(db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    name = f"ООО Неоднозначное имя {uuid.uuid4().hex[:8]}"
    for inn in ("7722222222", "7733333333"):
        db.add(Counterparty(company_id=company.id, name=name, inn=inn))
    db.add(CorporateClient(company_id=company.id, name=name, phone="", ext_id="test-identity"))
    await db.flush()
    with pytest.raises(HTTPException) as error:
        await link_counterparties(db, company.id, apply=False, only={"corporate_client"})
    assert error.value.status_code == 409
    assert "Неоднозначное" in error.value.detail
    await db.rollback()
