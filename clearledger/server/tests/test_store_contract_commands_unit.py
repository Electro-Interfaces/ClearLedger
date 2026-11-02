"""Authored NOT RUN. ROOT executor only; no ordinary pytest/conftest invocation."""
import os
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import uuid

import pytest

if os.environ.get("ROOT_APPROVED_STORE_CONTRACT_WRITERS_UNIT") != "1":
    pytest.skip("ROOT-reviewed isolated unit runner required", allow_module_level=True)

from fastapi import HTTPException
from app.services import store_contract_commands as commands
from app.routers import store_router as router

pytestmark = pytest.mark.asyncio


class Result:
    def __init__(self, row=None, scalar=17):
        self.row, self.value = row, scalar

    def scalar_one_or_none(self):
        return self.row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def scalar_one(self):
        return self.value


def payload(cp, org, **changes):
    return {"counterparty_id": str(cp), "organization_id": str(org),
            "number": " Store-1 ", "date": "2026-01-02T12:34:56", **changes}


async def save(db, cid, data):
    prepared = await commands.prepare_store_contract(db, cid, data)
    return await commands.save_store_contract(db, cid, data, prepared=prepared)


@pytest.fixture
def setup(monkeypatch):
    cid, cp, org = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events, captured = [], []
    db = NS(new=set(), dirty=set(), deleted=set(), no_autoflush=nullcontext(), execute=AsyncMock(return_value=Result()), get=AsyncMock(),
            commit=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock(), add=lambda row: events.append("add"))

    async def lock(db, company, entity):
        assert company == cid
        events.append(entity)

    async def parties(db, company, cp_id, org_id):
        events.append("parties")
        return uuid.UUID(str(cp_id)), uuid.UUID(str(org_id))

    async def duplicates(*args):
        events.append("duplicates")
        return []

    async def create(db, values):
        events.append("create")
        captured.append(values)
        return NS(id=uuid.uuid4(), **vars(values))

    # These retained scalar/HTTP regressions isolate the existing pipeline.
    # Fake preparation is NOT evidence for B; real caller/helper schedules live
    # in test_store_contract_scoped_locks_pg.py.
    prepared = commands.PreparedStoreContractWrite(cid, None)

    async def prepare(db, company):
        await commands._lock_store_references(db, company, prepared=prepared)
        return prepared

    monkeypatch.setattr(commands, "_prepare_store_contract_write", prepare)
    monkeypatch.setattr(commands, "require_store_contract_write", lambda *args: None)
    monkeypatch.setattr(router, "require_store_contract_write", lambda *args: None)
    monkeypatch.setattr(commands, "lock_manual_creation", lock)
    monkeypatch.setattr(commands, "_validate_contract_parties", parties)
    monkeypatch.setattr(commands, "find_contract_card_duplicates", duplicates)
    monkeypatch.setattr(commands, "create_contract_card", create)
    return NS(cid=cid, cp=cp, org=org, db=db, events=events, captured=captured)


async def test_create_barriers_validation_matcher_before_mutation_and_defaults(setup):
    w = setup
    row = await save(w.db, w.cid, payload(w.cp, w.org))
    assert w.events == ["counterparty", "contract", "parties", "duplicates", "create"]
    values, = w.captured
    assert (row.number, row.title, row.date) == ("Store-1", "Договор Store-1", "2026-01-02")
    assert row.raw == {"source": "center_manual", "name": "Договор Store-1"}
    assert (values.scope_type, values.is_closed) == ("unassigned", False)
    assert (values.type, values.kind, values.currency, values.comment) == ("поставка", "СПоставщиком", "RUB", None)
    assert all(getattr(values, key) is None for key in (
        "creation_key", "creation_actor_id", "creation_request_hash", "amount_limit", "signed", "basis"))
    w.db.commit.assert_not_awaited()
    w.db.rollback.assert_not_awaited()


@pytest.mark.parametrize("value", [None, "", 0, False])
async def test_legacy_null_empty_falsy_values(setup, value):
    w = setup
    row = await save(w.db, w.cid, payload(w.cp, w.org,
        title=" Паспорт ", number=value, date=value, kind=value, currency=value,
        type=value, comment=value))
    assert (row.number, row.title, row.date) == ("Паспорт", "Паспорт", "")
    assert (row.kind, row.currency, row.type, row.comment) == ("СПоставщиком", "RUB", "поставка", None)
    assert w.events == ["counterparty", "contract", "parties", "create"]


@pytest.mark.parametrize("changes,detail", [
    ({"counterparty_id": None}, "нужны контрагент и организация"),
    ({"organization_id": ""}, "нужны контрагент и организация"),
    ({"number": " ", "title": None}, "нужно наименование договора или его номер"),
])
async def test_required_400_before_barriers_and_writes(setup, changes, detail):
    w = setup
    with pytest.raises(HTTPException) as error:
        await save(w.db, w.cid, payload(w.cp, w.org, **changes))
    assert (error.value.status_code, error.value.detail) == (400, detail)
    assert not w.events and not w.captured


async def test_update_uses_current_parties_type_excludes_self_preserves_raw_overrides(setup, monkeypatch):
    w = setup
    current = NS(id=uuid.uuid4(), counterparty_id=w.cp, organization_id=w.org,
                 type="Сохранённый тип", raw={"name": "старое"}, manual_overrides=["number"])
    w.db.execute.return_value = Result(current)
    seen = []

    async def matches(db, cid, cp, org, identity):
        seen.append((cid, cp, org, identity))
        return [current]

    monkeypatch.setattr(commands, "find_contract_card_duplicates", matches)
    row = await save(w.db, w.cid, payload(uuid.uuid4(), uuid.uuid4(),
        id=str(current.id), type="Игнорируемый тип", comment="  примечание  "))
    assert row is current and not w.captured
    assert seen == [(w.cid, w.cp, w.org, ("Store-1", "2026-01-02", "Сохранённый тип"))]
    assert (row.counterparty_id, row.organization_id, row.type) == (w.cp, w.org, "Сохранённый тип")
    assert row.raw == {"name": "старое"} and row.manual_overrides == ["number"]
    assert row.comment == "примечание"


async def test_missing_update_404_and_duplicate_409_have_no_mutation(setup, monkeypatch):
    w = setup
    with pytest.raises(HTTPException) as missing:
        await save(w.db, w.cid, payload(w.cp, w.org, id=str(uuid.uuid4())))
    assert missing.value.status_code == 404 and not w.captured
    monkeypatch.setattr(commands, "find_contract_card_duplicates", AsyncMock(return_value=[NS(id=uuid.uuid4())]))
    with pytest.raises(HTTPException) as duplicate:
        await save(w.db, w.cid, payload(w.cp, w.org))
    assert duplicate.value.status_code == 409 and not w.captured


async def test_mixed_plan_locks_and_org_validation_before_first_mutation(setup):
    w = setup

    async def org(model, uid, **kwargs):
        w.events.append("org")
        return NS(company_id=w.cid)

    w.db.get.side_effect = org
    plan = await commands.prepare_store_partner_contract(w.db, w.cid, {
        "organization_id": str(w.org), "signed_on": "2026-02-03T04:05", "date": "ignored",
        "name": " Синтетическое имя ", "number": " ", "type": "ignored", "currency": "ignored"})
    assert w.events == ["counterparty", "contract", "org"]
    assert (plan.fields.title, plan.fields.number, plan.fields.date) == (
        "Синтетическое имя", "Синтетическое имя", "2026-02-03")
    assert (plan.fields.type, plan.fields.kind, plan.fields.currency) == ("поставка", "СПоставщиком", "RUB")
    assert not w.captured


@pytest.mark.parametrize("org", [None, "foreign", "missing"])
async def test_mixed_invalid_organization_rejected_before_add(setup, org):
    w = setup
    w.db.get.return_value = None if org == "missing" else NS(company_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        await commands.prepare_store_partner_contract(w.db, w.cid,
            {"name": "Синтетика", "organization_id": str(w.org) if org else None})
    assert error.value.status_code == 400
    assert "add" not in w.events and not w.captured


@pytest.mark.parametrize("network", [False, True])
async def test_router_contract_keeps_acl_commit_and_response(setup, monkeypatch, network):
    w = setup
    monkeypatch.setattr(router, "_receipt_access", AsyncMock(return_value=NS(network=network, company_id=w.cid)))
    save = AsyncMock(return_value=NS(id=w.cp, title="Паспорт", number="1"))
    monkeypatch.setattr(router, "save_store_contract", save)
    monkeypatch.setattr(router, "prepare_store_contract", AsyncMock(return_value=object()))
    if not network:
        with pytest.raises(HTTPException) as error:
            await router.store_contract_save({}, NS(), w.db)
        assert error.value.status_code == 403
        save.assert_not_awaited()
        w.db.commit.assert_not_awaited()
    else:
        assert await router.store_contract_save({}, NS(), w.db) == {"id": str(w.cp), "title": "Паспорт", "number": "1"}
        w.db.commit.assert_awaited_once()


async def test_partner_empty_contract_stations_and_early_inn_shape(setup, monkeypatch):
    w = setup
    monkeypatch.setattr(router, "_receipt_access", AsyncMock(return_value=NS(network=True, company_id=w.cid)))
    plan = AsyncMock(return_value=None)
    create = AsyncMock()
    monkeypatch.setattr(router, "prepare_store_partner_contract", plan)
    monkeypatch.setattr(router, "create_store_partner_contract", create)
    data = {"name": " Синтетический поставщик ", "stations": [3, "5"], "contract": {}}
    response = await router.store_partner_create(data, NS(), w.db)
    assert set(response) == {"id", "supplier_id", "name", "created", "contract_id"}
    assert response["name"] == "Синтетический поставщик" and response["created"] is True
    assert response["contract_id"] is None
    assert [call.args[1] for call in w.db.execute.await_args_list] == [
        {"cid": w.cid, "uuid": uuid.UUID(response["supplier_id"]), "name": "Синтетический поставщик",
         "full": "Синтетический поставщик", "inn": "", "kpp": "", "role": "supplier", "comment": ""},
        {"p": 17, "s": 3}, {"p": 17, "s": 5}]
    create.assert_not_awaited()
    plan.reset_mock()
    w.db.commit.reset_mock()
    w.events.clear()
    w.db.execute.return_value = Result({"id": 23, "name": "Ранее созданный"})
    assert await router.store_partner_create(data | {"inn": "0000000000", "contract": {"name": "ignored"}}, NS(), w.db) == {
        "id": 23, "name": "Ранее созданный", "created": False}
    plan.assert_not_awaited()
    w.db.commit.assert_not_awaited()
    assert not w.events


async def test_partner_plan_failure_prevents_cp_edge_and_station_writes(setup, monkeypatch):
    w = setup
    monkeypatch.setattr(router, "_receipt_access", AsyncMock(return_value=NS(network=True, company_id=w.cid)))
    monkeypatch.setattr(router, "prepare_store_partner_contract", AsyncMock(side_effect=HTTPException(400, "org")))
    with pytest.raises(HTTPException):
        await router.store_partner_create({"name": "Синтетика", "contract": {"organization_id": str(w.org)},
                                           "stations": [3]}, NS(), w.db)
    assert not w.events
    w.db.execute.assert_not_awaited()
    w.db.flush.assert_not_awaited()
    w.db.commit.assert_not_awaited()


async def test_partner_mixed_success_has_both_barriers_before_cp_add(setup, monkeypatch):
    w = setup
    monkeypatch.setattr(router, "_receipt_access", AsyncMock(return_value=NS(network=True, company_id=w.cid)))
    w.db.get.return_value = NS(company_id=w.cid)
    response = await router.store_partner_create({"name": "Синтетика", "contract": {
        "organization_id": str(w.org), "number": "P-1", "date": "2026-02-03"}}, NS(), w.db)
    assert w.events == ["counterparty", "contract", "add", "parties", "duplicates", "create"]
    assert response["contract_id"] and response["created"] is True
    assert w.captured[0].counterparty_id == uuid.UUID(response["supplier_id"])
    w.db.commit.assert_awaited_once()
