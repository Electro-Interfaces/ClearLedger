"""Native PATCH → PostgreSQL → actual 1С import with a retained identity map.

Only the upstream transport and HTTP dependencies are fixtures; matcher,
manual markers, SQL, commit and import implementation stay real.
"""
from copy import deepcopy
import os
from types import SimpleNamespace
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_CONTRACT_MANUAL_FRESHNESS_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Требуется {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError(error)

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import get_current_user
from app.database import get_db
from app.models import (Company, Contract, ContractLink, ContractLocation,
                        Counterparty, Organization, ServiceLocation, User, UserCompany)
from app.routers import references_router
from app.scope import set_request_organization, set_request_scope
from app.services.onec.odata_client import ENTITY_CONTRACTS
from app.services.onec.sync_service import OneCSyncService
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields

pytestmark = pytest.mark.asyncio(loop_scope="session")
UPDATED = {"processed": 1, "created": 0, "updated": 1, "skipped": 0, "errors": 0}


class Source:
    def __init__(self, row):
        self.row = row

    async def describe_entity(self, entity):
        assert entity == ENTITY_CONTRACTS
        return {"properties": list(self.row)}

    async def iter_entity(self, entity, **kwargs):
        assert entity == ENTITY_CONTRACTS
        yield deepcopy(self.row)


def sync_log():
    return SimpleNamespace(items_processed=0, items_created=0, items_updated=0, items_errors=0)


async def imported(w):
    log = sync_log()
    stats = await w.service._sync_contracts(Source(w.source), w.connection, log)
    assert stats == UPDATED
    assert (log.items_processed, log.items_created, log.items_updated, log.items_errors) == (1, 0, 1, 0)


async def persisted(w):
    # This session never shares the importer's identity map or transaction.
    async with w.factory() as fresh:
        row = await fresh.get(Contract, w.identifier)
        values = {c.key: deepcopy(getattr(row, c.key)) for c in Contract.__table__.columns}
        values["locations"] = list((await fresh.execute(select(
            ContractLocation.id, ContractLocation.location_id, ContractLocation.note,
        ).where(ContractLocation.contract_id == w.identifier))).all())
        values["links"] = list((await fresh.execute(select(
            ContractLink.id, ContractLink.app_code, ContractLink.project_ref, ContractLink.created_by,
        ).where(ContractLink.contract_id == w.identifier))).all())
        values["company_ids"] = list((await fresh.scalars(select(Contract.id).where(
            Contract.company_id == w.cid))).all())
        return values


def assert_identity_and_local_layer(before, after):
    for field in ("id", "company_id", "external_ref", "counterparty_id", "organization_id",
                  "number", "date", "type", "kind", "scope_type", "basis", "liability",
                  "creation_key", "creation_actor_id", "creation_request_hash", "created_at",
                  "locations", "links", "company_ids"):
        assert after[field] == before[field], field
    for field in ("referenceIdentity", "referenceSource"):
        assert after["raw"][field] == before["raw"][field]


@pytest_asyncio.fixture(loop_scope="session")
async def contract_world(db):
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    company = Company(name="Синтетическая компания", slug=f"fresh-{uuid.uuid4().hex[:12]}", profile_id="energy")
    user = User(name="Тестовый участник", email=f"{uuid.uuid4().hex}@example.invalid", password_hash="unused")
    db.add_all([company, user])
    await db.flush()
    cid = company.id
    party = Counterparty(company_id=cid, name="Синтетический контрагент", inn="7712345678",
                         external_ref=str(uuid.uuid4()))
    org = Organization(company_id=cid, name="Синтетическое юрлицо", inn="",
                       external_ref=str(uuid.uuid4()))
    location = ServiceLocation(id=uuid.uuid4().hex, company_id=cid, code="1", name="Тестовая точка")
    db.add_all([party, org, location, UserCompany(user_id=user.id, company_id=cid, role="admin")])
    await db.commit()

    app = FastAPI()
    app.include_router(references_router.router, prefix="/api")

    async def actor():
        set_request_scope(None)
        set_request_organization(None)
        return user

    async def session():
        async with factory() as patch_db:
            try:
                yield patch_db
                await patch_db.commit()
            except BaseException:
                await patch_db.rollback()
                raise

    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_db] = session

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def setup(*, empty_valid_until=False):
            source = {"Ref_Key": str(uuid.uuid4()), "Owner_Key": party.external_ref,
                      "Организация_Key": org.external_ref, "Номер": "Т-74", "Дата": "2026-01-01",
                      "ВидДоговора": "СПоставщиком", "СрокДействия": None if empty_valid_until else "2026-12-31",
                      "Сумма": 100, "СуммаВключаетНДС": True, "ДоговорПодписан": True,
                      "УстановленСрокОплаты": True, "СрокОплаты": 10, "ExtraSourceField": "original"}
            response = await client.post("/api/references/contracts", json={
                "company_id": str(cid), "creationKey": str(uuid.uuid4()),
                "number": source["Номер"], "date": source["Дата"], "type": source["ВидДоговора"],
                "counterpartyId": str(party.id), "organizationId": str(org.id),
                "scopeType": "locations", "basis": "Синтетическое основание",
            })
            assert response.status_code == 201, response.text
            identifier = uuid.UUID(response.json()["id"])
            w = SimpleNamespace(db=db, factory=factory, cid=cid, client=client, source=source,
                                identifier=identifier, connection=SimpleNamespace(id=uuid.uuid4(), company_id=cid),
                                service=OneCSyncService(db))
            await imported(w)
            # A strong reference is essential: SQLAlchemy's identity map is weak.
            w.row = await db.get(Contract, identifier)
            w.row.liability = {"synthetic": "local terms"}
            db.add_all([
                ContractLocation(company_id=cid, contract_id=identifier, location_id=location.id, note="Тест"),
                ContractLink(company_id=cid, contract_id=identifier, app_code="test", project_ref="site:test",
                             created_by=user.id),
            ])
            await db.commit()
            assert w.row.manual_overrides == []
            return w

        yield setup
    set_request_scope(None)
    set_request_organization(None)


async def patch(w, payload):
    response = await w.client.patch(f"/api/references/contracts/{w.identifier}", json=payload)
    assert response.status_code == 200, response.text
    return await persisted(w)


async def test_changed_upstream_cannot_overwrite_committed_manual_null(contract_world):
    w = await contract_world()
    before = await persisted(w)
    saved = await patch(w, {"validUntil": None, "amountLimit": None, "amountInclVat": None,
                            "paymentTermDays": None})
    fields = {"valid_until", "amount_limit", "amount_incl_vat", "payment_term_days"}
    assert all(saved[f] is None for f in fields)
    assert fields <= set(saved["manual_overrides"])
    assert saved["raw"] == before["raw"]
    assert w.row.valid_until == "2026-12-31" and w.row.manual_overrides == []
    # CHANGED upstream forces real UPDATEs against stale attribute history.
    w.source.update({"СрокДействия": "2027-12-31", "Сумма": 200, "СуммаВключаетНДС": False,
                     "СрокОплаты": 20, "ДоговорПодписан": False, "ExtraSourceField": "changed"})
    for _ in range(2):
        await imported(w)
        await w.db.commit()
        after = await persisted(w)
        assert all(after[f] is None for f in fields), {
            "persisted_after_patch": {f: saved[f] for f in fields},
            "persisted_after_import": {f: after[f] for f in fields},
            "persisted_markers": after["manual_overrides"],
        }
        assert fields <= set(after["manual_overrides"])
        assert after["signed"] is False  # an unmarked field still follows 1С
        assert after["raw"]["СрокДействия"] == "2027-12-31"
        assert after["raw"]["ExtraSourceField"] == "changed"
        assert_identity_and_local_layer(before, after)


async def test_same_upstream_control_does_not_claim_persisted_overwrite(contract_world):
    w = await contract_world()
    saved = await patch(w, {"validUntil": None})
    await imported(w)
    await w.db.commit()
    after = await persisted(w)
    # Baseline may keep a stale Python attribute without writing this column.
    assert after["valid_until"] is None
    assert after["manual_overrides"] == ["valid_until"]
    assert after["raw"] == saved["raw"]
    assert_identity_and_local_layer(saved, after)


@pytest.mark.parametrize("intent", ["omitted", "unchanged", "null_to_null", "changed_null", "changed_value"])
async def test_patch_intent_boundaries(contract_world, intent):
    w = await contract_world(empty_valid_until=intent == "null_to_null")
    payload = {"omitted": {}, "unchanged": {"validUntil": "2026-12-31"},
               "null_to_null": {"validUntil": None}, "changed_null": {"validUntil": None},
               "changed_value": {"validUntil": "2030-01-01"}}[intent]
    before = await persisted(w)
    saved = await patch(w, payload)
    changed = intent in {"changed_null", "changed_value"}
    assert ("valid_until" in saved["manual_overrides"]) == changed
    assert saved["raw"] == before["raw"]
    w.source["СрокДействия"] = "2027-12-31"
    await imported(w)
    await w.db.commit()
    after = await persisted(w)
    expected = None if intent == "changed_null" else "2030-01-01" if intent == "changed_value" else "2027-12-31"
    assert after["valid_until"] == expected, after
    assert ("valid_until" in after["manual_overrides"]) == changed
    assert after["raw"]["СрокДействия"] == "2027-12-31"
    assert_identity_and_local_layer(before, after)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_pending_manual_edit_autoflush_and_caller_transaction(contract_world, finish):
    w = await contract_world()
    before = await persisted(w)
    snapshot = snapshot_reference_fields(w.row)
    w.row.valid_until = None
    mark_reference_changes(w.row, snapshot)
    w.source["СрокДействия"] = "2027-12-31"
    await imported(w)
    assert w.row.valid_until is None and "valid_until" in w.row.manual_overrides
    if finish == "rollback":
        await w.db.rollback()
        assert await persisted(w) == before  # import must not commit for the caller
    else:
        await w.db.commit()
        after = await persisted(w)
        assert after["valid_until"] is None and "valid_until" in after["manual_overrides"]
        assert after["raw"]["СрокДействия"] == "2027-12-31"
        assert_identity_and_local_layer(before, after)


async def test_same_external_ref_other_company_is_untouched(contract_world):
    w = await contract_world()
    company = Company(name="Другая синтетическая компания", slug=f"foreign-{uuid.uuid4().hex[:12]}", profile_id="energy")
    w.db.add(company)
    await w.db.flush()
    party = Counterparty(company_id=company.id, name="Чужой синтетический контрагент", inn="")
    org = Organization(company_id=company.id, name="Чужое синтетическое юрлицо", inn="")
    w.db.add_all([party, org])
    await w.db.flush()
    foreign = Contract(company_id=company.id, counterparty_id=party.id,
                       organization_id=org.id, number="Чужой", date="2026-01-01", type="Прочее",
                       external_ref=w.source["Ref_Key"], valid_until="2040-01-01", raw={"foreign": True})
    w.db.add(foreign)
    await w.db.commit()
    foreign_id = foreign.id
    # Also detect an accidentally broadened populate_existing SELECT.
    async with w.factory() as writer:
        row = await writer.get(Contract, foreign_id)
        row.valid_until = "2041-01-01"
        await writer.commit()
    await patch(w, {"validUntil": None})
    w.source["СрокДействия"] = "2027-12-31"
    await imported(w)
    await w.db.commit()
    assert (await persisted(w))["valid_until"] is None
    assert foreign.valid_until == "2040-01-01"
    async with w.factory() as fresh:
        saved = await fresh.get(Contract, foreign_id)
        assert saved.valid_until == "2041-01-01" and saved.raw == {"foreign": True}
        assert saved.manual_overrides == []
