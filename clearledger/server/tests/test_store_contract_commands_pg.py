"""Authored NOT RUN: real ORM/PG cases for ROOT's separately reviewed executor.

No runner is supplied and ordinary pytest is forbidden: conftest imports before
module guards. ROOT must approve a disposable database BEFORE importing tests,
helpers, app or conftest. Never use working data or the conftest URL fallback.
"""
import os
from urllib.parse import urlsplit

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_STORE_CONTRACT_WRITERS_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("ROOT-approved Store test executor required", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (target.path != "/api_store_contract_writers_test_20261101"
        or target.hostname != "127.0.0.1" or not target.port or not target.password
        or target.query or target.fragment
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or os.environ.get("ROOT_APPROVED_STORE_CONTRACT_WRITERS_TESTS") != "1"):
    raise RuntimeError("Exact ROOT-approved disposable Store database required; no fallback/URL overrides")

from types import SimpleNamespace as NS
import uuid

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Company, Contract, ContractLocation, Counterparty, Organization
from app.services.store_contract_commands import (
    create_store_partner_contract, prepare_store_partner_contract, prepare_store_contract,
    save_store_contract as execute_store_contract,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    token = uuid.uuid4().hex
    companies = [Company(name="Синтетическая компания Store", slug=f"store-contract-{token}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    cid, foreign = (row.id for row in companies)
    cps = [Counterparty(company_id=cid, name="Синтетическая сторона Store") for _ in range(2)]
    foreign_cp = Counterparty(company_id=foreign, name="Чужая синтетическая сторона Store")
    orgs = [Organization(company_id=cid, name="Синтетическая организация Store", inn="", prefix=f"Т{i}") for i in range(2)]
    foreign_org = Organization(company_id=foreign, name="Чужая синтетическая организация Store", inn="", prefix="Ч")
    db.add_all([*cps, foreign_cp, *orgs, foreign_org])
    await db.flush()
    w = NS(cid=cid, foreign=foreign, cp=cps[0].id, cp2=cps[1].id, org=orgs[0].id,
           org2=orgs[1].id, foreign_cp=foreign_cp.id, foreign_org=foreign_org.id,
           factory=async_sessionmaker(db.bind, expire_on_commit=False))
    await db.commit()
    yield w


def body(w, **changes):
    return {"counterparty_id": str(w.cp), "organization_id": str(w.org),
            "title": " Синтетический паспорт ", "number": " Store-PG-1 ",
            "date": "2026-02-03T04:05:06", **changes}


async def save_store_contract(db, cid, data):
    prepared = await prepare_store_contract(db, cid, data)
    return await execute_store_contract(db, cid, data, prepared=prepared)


async def count(w):
    async with w.factory() as db:
        return len((await db.scalars(select(Contract).where(Contract.company_id == w.cid))).all())


async def test_real_typed_binders_defaults_caller_commit_and_rollback(world):
    w = world
    async with w.factory() as db:
        row = await save_store_contract(db, w.cid, body(w, comment="  примечание  "))
        uid = row.id
        assert isinstance(uid, uuid.UUID)
        await db.flush()
        assert await count(w) == 0  # Observer cannot see uncommitted INSERT.
        await db.commit()
    async with w.factory() as fresh:
        row = await fresh.get(Contract, uid)
        assert (row.number, row.title, row.date, row.type) == (
            "Store-PG-1", "Синтетический паспорт", "2026-02-03", "поставка")
        assert (row.kind, row.currency, row.comment, row.scope_type, row.is_closed) == (
            "СПоставщиком", "RUB", "примечание", "unassigned", False)
        assert row.raw == {"source": "center_manual", "name": "Синтетический паспорт"}
        assert row.manual_overrides == []
        assert row.creation_key is row.creation_actor_id is row.creation_request_hash is None
        assert row.amount_limit is row.type_code is row.signed is row.basis is None
        assert (await fresh.scalars(select(ContractLocation).where(ContractLocation.contract_id == uid))).all() == []
    async with w.factory() as db:
        rolled_back = await save_store_contract(db, w.cid, body(w, number="rolled-back"))
        rolled_id = rolled_back.id
        await db.rollback()
    async with w.factory() as fresh:
        assert await fresh.get(Contract, rolled_id) is None


@pytest.mark.parametrize("field", ["counterparty_id", "organization_id"])
@pytest.mark.parametrize("foreign", [False, True])
async def test_cross_company_and_missing_parties_400_before_card(world, field, foreign):
    w = world
    uid = (w.foreign_cp if field == "counterparty_id" else w.foreign_org) if foreign else uuid.uuid4()
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await save_store_contract(db, w.cid, body(w, **{field: str(uid)}))
        assert error.value.status_code == 400
        assert not db.new and not db.dirty
        await db.rollback()
    assert await count(w) == 0


@pytest.mark.parametrize("case", ["same", "cp", "org", "tenant", "date", "type", "incomplete"])
async def test_matcher_exact_tenant_parties_identity_and_incomplete_distinct(world, case):
    w = world
    async with w.factory() as db:
        first = await save_store_contract(db, w.cid, body(w))
        uid = first.id
        await db.commit()
    changes = {"same": {}, "cp": {"counterparty_id": str(w.cp2)},
               "org": {"organization_id": str(w.org2)}, "tenant": {
                   "counterparty_id": str(w.foreign_cp), "organization_id": str(w.foreign_org)},
               "date": {"date": "2026-02-04"}, "type": {"type": "иной тип"},
               "incomplete": {"date": "invalid-date"}}[case]
    async with w.factory() as db:
        if case == "same":
            with pytest.raises(HTTPException) as error:
                await save_store_contract(db, w.cid, body(w))
            assert error.value.status_code == 409 and not db.new
        else:
            tenant = w.foreign if case == "tenant" else w.cid
            prepared = await prepare_store_contract(db, tenant, body(w, **changes))
            row = await execute_store_contract(db, tenant, body(w, **changes), prepared=prepared)
            assert row.id != uid
            if case == "incomplete":
                await db.flush()
                assert not db.new and not db.dirty and not db.deleted
                again = await execute_store_contract(db, w.cid, body(w, **changes), prepared=prepared)
                assert again.id not in {row.id, uid}
        await db.rollback()


async def test_update_real_ownership_404_exclude_self_actual_parties_type(world):
    w = world
    async with w.factory() as db:
        first = await save_store_contract(db, w.cid, body(w, type="original"))
        first.manual_overrides = ["number"]
        first.raw = {"name": "Старый снимок", "synthetic": True}
        uid = first.id
        await db.commit()
    for tenant, target_id in [(w.foreign, uid), (w.cid, uuid.uuid4())]:
        async with w.factory() as db:
            with pytest.raises(HTTPException) as error:
                await save_store_contract(db, tenant, body(w, id=str(target_id)))
            assert error.value.status_code == 404 and not db.dirty and not db.new
            await db.rollback()
    async with w.factory() as db:
        row = await save_store_contract(db, w.cid, body(w, id=str(uid), type="ignored",
            counterparty_id=str(w.cp2), organization_id=str(w.org2), comment=""))
        assert (row.counterparty_id, row.organization_id, row.type) == (w.cp, w.org, "original")
        assert row.manual_overrides == ["number"] and row.raw == {"name": "Старый снимок", "synthetic": True}
        assert row.comment is None
        await db.commit()
    async with w.factory() as db:
        second = await save_store_contract(db, w.cid, body(w, number="other", type="original"))
        second_id = second.id
        await db.commit()
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await save_store_contract(db, w.cid, body(w, id=str(second_id), type="avoid-conflict",
                counterparty_id=str(w.cp2), organization_id=str(w.org2)))
        assert error.value.status_code == 409
        assert not db.dirty and not db.new
        await db.rollback()


async def test_mixed_foreign_org_rejects_before_cp_write_then_real_creator_rollback(world):
    w = world
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await prepare_store_partner_contract(db, w.cid, {"organization_id": str(w.foreign_org)})
        assert error.value.status_code == 400 and not db.new and not db.dirty
        await db.rollback()
    async with w.factory() as db:
        plan = await prepare_store_partner_contract(db, w.cid, {
            "organization_id": str(w.org), "signed_on": "2026-02-03T04:05", "name": "Синтетический mixed"})
        cp = Counterparty(company_id=w.cid, name="Новая синтетическая сторона Store")
        db.add(cp)
        await db.flush()
        cp_id = cp.id
        row = await create_store_partner_contract(db, w.cid, cp.id, plan)
        uid = row.id
        await db.flush()
        assert (row.number, row.title, row.date) == ("Синтетический mixed", "Синтетический mixed", "2026-02-03")
        await db.rollback()
    async with w.factory() as fresh:
        assert await fresh.get(Counterparty, cp_id) is None
        assert await fresh.get(Contract, uid) is None
