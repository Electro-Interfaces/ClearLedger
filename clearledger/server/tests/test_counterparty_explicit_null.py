"""Native HTTP → actual SQL → offline 1С adapter; без вызовов внешней 1С."""
import os
from types import SimpleNamespace
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_COUNTERPARTY_COMMAND_TESTS") != "1":
    pytest.skip("Требуется RUN_COUNTERPARTY_COMMAND_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_COUNTERPARTY_COMMAND_TESTS"):
    raise RuntimeError(error)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Company, Counterparty
from app.services.onec.sync_service import OneCSyncService
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields

pytestmark = pytest.mark.asyncio(loop_scope="session")


class Source:
    def __init__(self, row):
        self.row = row

    async def iter_entity(self, entity, **kwargs):
        yield self.row


def sync_log():
    return SimpleNamespace(items_processed=0, items_created=0, items_updated=0, items_errors=0)


async def setup_party(db, client, *, empty_full_name=False):
    company = Company(name="Синтетическая компания", slug=f"null-{uuid.uuid4().hex[:12]}", profile_id="energy")
    db.add(company)
    await db.commit()
    cid = company.id
    name = f"ООО Очистка {uuid.uuid4().hex[:8]}"
    response = await client.post("/api/references/counterparties", json={
        "company_id": str(cid), "name": name, "inn": "7712345678", "kpp": "771201001",
        "fullName": None if empty_full_name else "Полное имя", "shortName": "Краткое имя", "phone": "+70000000000",
        "email": "synthetic@example.invalid",
    })
    assert response.status_code == 201, response.text
    identifier = uuid.UUID(response.json()["id"])
    source = {"Ref_Key": str(uuid.uuid4()), "Description": name, "ИНН": "7712345678",
              "КПП": "771201001", "НаименованиеПолное": None if empty_full_name else "Имя источника"}
    connection = SimpleNamespace(id=uuid.uuid4(), company_id=cid)
    service = OneCSyncService(db)
    await service._sync_counterparties(Source(source), connection, sync_log())
    row = await db.get(Counterparty, identifier)
    await db.commit()
    return SimpleNamespace(db=db, client=client, cid=cid, identifier=identifier,
                           source=source, connection=connection, row=row, service=service)


async def persisted(w):
    factory = async_sessionmaker(w.db.bind, expire_on_commit=False)
    async with factory() as fresh:
        row = await fresh.get(Counterparty, w.identifier)
        return {"id": row.id, "kpp": row.kpp, "full_name": row.full_name,
                "manual_overrides": row.manual_overrides, "raw": row.raw,
                "external_ref": row.external_ref, "name": row.name}


async def test_http_null_persisted_markers_override_reused_import_session(db, auth_client):
    w = await setup_party(db, auth_client)
    response = await w.client.patch(f"/api/references/counterparties/{w.identifier}",
                                    json={"kpp": None, "fullName": None})
    assert response.status_code == 200, response.text
    saved = await persisted(w)
    assert saved["kpp"] is None and saved["full_name"] is None, saved
    assert {"kpp", "full_name"} <= set(saved["manual_overrides"]), saved
    # Держим прежний объект между commit и новым SELECT: реальный identity map.
    assert w.row.kpp == "771201001" and w.row.full_name == "Имя источника"
    before_raw = saved["raw"]
    stats = await w.service._sync_counterparties(Source(w.source), w.connection, sync_log())
    assert stats["created"] == 0 and stats["updated"] == 1
    assert w.row.kpp is None and w.row.full_name is None, {
        "cached_kpp": w.row.kpp, "cached_full_name": w.row.full_name,
        "cached_markers": w.row.manual_overrides, "persisted_after_patch": saved,
    }
    await w.db.commit()
    saved = await persisted(w)
    assert saved["kpp"] is None and saved["full_name"] is None, saved
    assert saved["raw"] == before_raw
    assert saved["id"] == w.identifier and saved["external_ref"] == w.source["Ref_Key"]


@pytest.mark.parametrize("intent", ["omitted", "unchanged", "null_to_null", "changed_null", "changed_value"])
async def test_patch_intent_boundaries_keep_only_changed_fields_frozen(db, auth_client, intent):
    w = await setup_party(db, auth_client, empty_full_name=intent == "null_to_null")
    payload = {
        "omitted": {}, "unchanged": {"fullName": "Имя источника"},
        "null_to_null": {"fullName": None}, "changed_null": {"fullName": None},
        "changed_value": {"fullName": "Ручное имя"},
    }[intent]
    before = await persisted(w)
    response = await w.client.patch(f"/api/references/counterparties/{w.identifier}", json=payload)
    assert response.status_code == 200, response.text
    after = await persisted(w)
    assert after["raw"] == before["raw"]
    changed = intent in {"changed_null", "changed_value"}
    assert ("full_name" in after["manual_overrides"]) == changed
    w.source["НаименованиеПолное"] = "Обновление источника"
    for _ in range(2):
        await w.service._sync_counterparties(Source(w.source), w.connection, sync_log())
        await w.db.commit()
    after = await persisted(w)
    expected = None if intent == "changed_null" else "Ручное имя" if intent == "changed_value" else "Обновление источника"
    assert after["full_name"] == expected, after
    assert after["raw"]["НаименованиеПолное"] == "Обновление источника"
    assert after["raw"]["referenceIdentity"] == before["raw"]["referenceIdentity"]
    assert after["id"] == w.identifier and after["external_ref"] == w.source["Ref_Key"]


async def test_pending_manual_edit_survives_import_autoflush_and_caller_rollback(db, auth_client):
    w = await setup_party(db, auth_client)
    before = snapshot_reference_fields(w.row)
    w.row.full_name = None
    mark_reference_changes(w.row, before)
    stats = await w.service._sync_counterparties(Source(w.source), w.connection, sync_log())
    assert stats["created"] == 0 and stats["updated"] == 1
    assert w.row.full_name is None and "full_name" in w.row.manual_overrides
    await w.db.rollback()
    saved = await persisted(w)
    assert saved["full_name"] == "Имя источника" and "full_name" not in saved["manual_overrides"]


async def test_branch_kpp_clear_conflict_does_not_change_either_identity(db, auth_client):
    w = await setup_party(db, auth_client)
    branch = Counterparty(company_id=w.cid, name="Другой филиал", inn="7712345678",
                          kpp="771202002", external_ref=str(uuid.uuid4()))
    db.add(branch)
    await db.commit()
    before = await persisted(w)
    response = await w.client.patch(f"/api/references/counterparties/{w.identifier}", json={"kpp": None})
    assert response.status_code == 409, response.text
    assert await persisted(w) == before
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as fresh:
        saved = await fresh.get(Counterparty, branch.id)
        assert saved.kpp == "771202002" and saved.external_ref == branch.external_ref


async def test_same_external_ref_in_another_company_is_not_promoted(db, auth_client):
    w = await setup_party(db, auth_client)
    company = Company(name="Другая компания", slug=f"foreign-{uuid.uuid4().hex[:10]}", profile_id="energy")
    db.add(company)
    await db.flush()
    foreign = Counterparty(company_id=company.id, name="Чужой контрагент", inn="7712345678",
                           kpp="771201001", external_ref=w.source["Ref_Key"], full_name="Чужое имя",
                           raw={"foreign": True}, manual_overrides=[])
    db.add(foreign)
    await db.commit()
    foreign_id = foreign.id
    response = await w.client.patch(f"/api/references/counterparties/{w.identifier}", json={"fullName": None})
    assert response.status_code == 200
    await w.service._sync_counterparties(Source(w.source), w.connection, sync_log())
    await db.commit()
    saved = await persisted(w)
    assert saved["full_name"] is None
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as fresh:
        row = await fresh.get(Counterparty, foreign_id)
        assert row.full_name == "Чужое имя" and row.raw == {"foreign": True} and row.manual_overrides == []
