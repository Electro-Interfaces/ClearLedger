"""Actual producer/PG characterization for the bounded M06 CREATE extraction.

ROOT only: approved runner must validate the exact disposable database before
pytest/conftest imports. No remote transport or real source data is used.
"""
import os
from urllib.parse import urlsplit

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_CONTRACT_IMPORT_CREATE_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Requires {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
if (urlsplit(os.environ["TEST_DATABASE_URL"]).path != "/api_contract_create_test_20261030"
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or os.environ.get("ROOT_APPROVED_CONTRACT_CREATE_TESTS") != "1"):
    raise RuntimeError("Requires ROOT approval and the exact disposable contract-create database")

import asyncio
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import (
    Company, Contract, ContractDimension, ContractLink, ContractLocation,
    CorporateClient, Counterparty, DataEntry, Organization, ServiceLocation, User,
)
from app.scope import set_request_organization, set_request_scope
from app.services.charge_sessions_normalize import _sync_corporate_contracts
from app.services.contract_commands import create_imported_contract
from app.services.reference_identity import ContractIndex, IdentityConflict
from app.services.reestr_normalize import ingest_reestr
from app.services.reestr_rushydro import L2Cache

pytestmark = pytest.mark.asyncio(loop_scope="session")
PRODUCERS = ("legacy", "l2", "corporate")
NAME = "ООО Синтетический источник"
OTHER = "АО Синтетический отказ"
CORPORATE_TYPE = "Корпоративная зарядка (постоплата)"


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    set_request_scope(None)
    set_request_organization(None)
    token = uuid.uuid4().hex[:12]
    companies = [Company(name="Синтетическая компания", slug=f"contract-create-{token}-{i}",
                         profile_id="energy") for i in range(2)]
    actor = User(name="Синтетический автор", email=f"{token}@example.invalid", password_hash="unused")
    db.add_all([*companies, actor])
    await db.flush()
    organizations = [Organization(company_id=c.id, name="Синтетическая организация", inn="", prefix="Т")
                     for c in companies]
    locations = [[ServiceLocation(id=f"cc-{token}-{i}-{n}", company_id=c.id, code=str(n),
                                  name="Синтетическая точка", type="ev_charging") for n in (1, 2)]
                 for i, c in enumerate(companies)]
    db.add_all([*organizations, *locations[0], *locations[1]])
    await db.flush()
    w = SimpleNamespace(db=db, factory=async_sessionmaker(db.bind, expire_on_commit=False),
                        cid=companies[0].id, org_id=organizations[0].id,
                        loc_ids=[l.id for l in locations[0]], actor_id=actor.id,
                        foreign_cid=companies[1].id, foreign_org_id=organizations[1].id,
                        foreign_loc_ids=[l.id for l in locations[1]])
    await db.commit()
    try:
        yield w
    finally:
        await db.rollback()
        set_request_scope(None)
        set_request_organization(None)


def record(row):
    # Corporate phone-link UPDATE legitimately advances its onupdate timestamp.
    # Mapper keys preserve aliased columns: DataEntry.meta maps SQL metadata;
    # row.metadata is Base.metadata and is not a persisted column value.
    result = {attr.key: deepcopy(getattr(row, attr.key)) for attr in row.__mapper__.column_attrs
              if not (isinstance(row, CorporateClient) and attr.key == "updated_at")}

    def column_value(value):
        if value is None or isinstance(value, (str, bool, int, float, Decimal, date, datetime, uuid.UUID, bytes)):
            return True
        if isinstance(value, dict):
            return all(isinstance(k, str) and column_value(v) for k, v in value.items())
        if isinstance(value, list):
            return all(column_value(v) for v in value)
        return False

    assert all(column_value(value) for value in result.values()), "Snapshot must contain persisted column values"
    if isinstance(row, DataEntry):
        assert "meta" in result and "metadata" not in result
        assert result["meta"] is None or isinstance(result["meta"], dict)
    return result


async def saved(w):
    """Read persisted state through an independent session, never the writer map."""
    async with w.factory() as fresh:
        return {model.__name__: [record(row) for row in (await fresh.execute(
            select(model).where(model.company_id == w.cid).order_by(model.id))).scalars()]
                for model in (Contract, Counterparty, ContractLocation, ContractLink,
                              ContractDimension, CorporateClient, DataEntry)}


async def run_producer(w, session, producer, *, number="Т-74", cdate="2026-01-01",
                       names=(NAME, NAME), capture=None):
    if producer == "legacy":
        cell = None if number is None else f"{number} от 01.01.2026"
        return await ingest_reestr(session, w.cid, [
            {"bu": str(i + 1), "rent_cp": name, "rent_contract": cell}
            for i, name in enumerate(names)])
    if producer == "l2":
        cache = L2Cache()
        await cache.build(session, w.cid)
        if capture is not None:
            capture["index"] = cache.contracts
        stats = {}
        for i, name in enumerate(names):
            cp = await cache.counterparty(session, w.cid, name, alias="rent", res=stats)
            loc = await session.get(ServiceLocation, w.loc_ids[i % len(w.loc_ids)])
            await cache.contract(session, w.cid, cp, "Аренда", number, cdate, "договор", loc, stats)
        return stats
    return await _sync_corporate_contracts(session, w.cid, [
        {"name": name, "phone": f"7000000000{i}", "contract_start": cdate}
        for i, name in enumerate(names)])


async def client_rows(w):
    for i in range(2):
        w.db.add(CorporateClient(company_id=w.cid, name=NAME, phone=f"7000000000{i}",
                                ext_id=f"synthetic-{i}", mode="flat", rate=17.25,
                                discount_pct=12.5, users=2))
    await w.db.commit()


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_actual_create_same_run_and_committed_replay(world, producer):
    w = world
    if producer == "corporate":
        await client_rows(w)
    result = await run_producer(w, w.db, producer)
    if producer != "corporate":
        assert result["contracts"] == 1 and result["counterparties"] == 1
    else:
        assert result is None
    await w.db.commit()
    state = await saved(w)
    contract, = state["Contract"]
    cp, = state["Counterparty"]
    ctype, kind, scope, num = ((CORPORATE_TYPE, "СПокупателем", "company", "б/н")
                                if producer == "corporate" else ("Аренда", "СПоставщиком", "locations", "Т-74"))
    assert {k: contract[k] for k in ("company_id", "number", "date", "counterparty_id",
                                    "organization_id", "type", "kind", "basis", "scope_type", "raw")} == {
        "company_id": w.cid, "number": num, "date": "2026-01-01", "counterparty_id": cp["id"],
        "organization_id": w.org_id, "type": ctype, "kind": kind, "basis": "договор", "scope_type": scope,
        "raw": {"referenceIdentity": {"counterparty_id": str(cp["id"]), "type": ctype,
                                       "number": num, "date": "2026-01-01"}},
    }
    assert contract["manual_overrides"] == [] and contract["creation_key"] is None
    assert contract["creation_actor_id"] is None and contract["creation_request_hash"] is None
    assert cp["name"] == NAME and cp["inn"] is None and cp["kind"] == "external"
    assert cp["aliases"] == (["corporate"] if producer == "corporate" else ["rent"])
    assert len(state["ContractLocation"]) == (0 if producer == "corporate" else 2)
    if producer == "corporate":
        assert all(c["counterparty_id"] == cp["id"] for c in state["CorporateClient"])
        assert all((c["rate"], c["discount_pct"], c["users"]) == (17.25, 12.5, 2)
                   for c in state["CorporateClient"])
    async with w.factory() as another_writer:
        result = await run_producer(w, another_writer, producer)
        if producer != "corporate":
            assert result.get("contracts", 0) == result.get("counterparties", 0) == 0
        await another_writer.commit()
    after = await saved(w)
    for model in ("Contract", "Counterparty", "ContractLocation", "ContractLink", "ContractDimension", "CorporateClient"):
        assert after[model] == state[model]


@pytest.mark.parametrize("producer,number,cdate,expected_number,expected_date", [
    ("legacy", "Д" * 140, "2026-01-01", "Д" * 100, "2026-01-01"),
    ("legacy", None, "2026-01-01", None, None),
    ("l2", "Д" * 140, "", "Д" * 100, ""),
    ("l2", None, None, "б/н", ""),
    ("corporate", None, "28.11.2023", "б/н", "2023-11-28"),
    ("corporate", None, "", "б/н", ""),
], ids=["legacy-long", "legacy-missing", "l2-long", "l2-missing", "corporate-dot-date", "corporate-missing-date"])
async def test_source_adapter_golden_bounds(world, producer, number, cdate, expected_number, expected_date):
    w = world
    await run_producer(w, w.db, producer, number=number, cdate=cdate, names=(NAME,))
    await w.db.commit()
    state = await saved(w)
    if expected_number is None:
        assert state["Contract"] == [] and state["ContractLocation"] == []
        assert len(state["Counterparty"]) == 1
        return
    contract, = state["Contract"]
    assert (contract["number"], contract["date"]) == (expected_number, expected_date)
    assert contract["raw"]["referenceIdentity"]["number"] == expected_number
    assert contract["raw"]["referenceIdentity"]["date"] == expected_date


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_existing_manual_null_identity_metadata_and_relations_survive(world, producer):
    w = world
    await run_producer(w, w.db, producer)
    await w.db.commit()
    c = (await w.db.execute(select(Contract).where(Contract.company_id == w.cid))).scalar_one()
    cp = (await w.db.execute(select(Counterparty).where(Counterparty.company_id == w.cid))).scalar_one()
    c.number, c.date, c.type = "Ручной номер", "2026-02-02", "Ручной вид"
    c.valid_until = c.amount_limit = c.amount_incl_vat = c.payment_term_days = None
    c.manual_overrides = ["number", "date", "type", "valid_until", "amount_limit", "amount_incl_vat", "payment_term_days"]
    c.creation_key, c.creation_actor_id, c.creation_request_hash = uuid.uuid4(), w.actor_id, "a" * 64
    c.external_ref, c.scope_type, c.basis = str(uuid.uuid4()), "company", "Ручное основание"
    c.liability, c.raw = {"source": "manual", "note": "Синтетика"}, {**c.raw, "opaque": {"keep": True}}
    cp.name, cp.aliases, cp.manual_overrides = "Ручная сторона", ["Ручная роль"], ["name", "aliases"]
    w.db.add_all([ContractLink(company_id=w.cid, contract_id=c.id, app_code="ops", project_ref=""),
                  ContractDimension(company_id=w.cid, contract_id=c.id, dim_type="synthetic", dim_ref="keep")])
    if producer == "corporate":
        w.db.add(ContractLocation(company_id=w.cid, contract_id=c.id, location_id=w.loc_ids[0]))
    await w.db.commit()
    before = await saved(w)
    for _ in range(2):
        async with w.factory() as writer:
            await run_producer(w, writer, producer)
            await writer.commit()
    after = await saved(w)
    for model in ("Contract", "Counterparty", "ContractLocation", "ContractLink", "ContractDimension"):
        assert after[model] == before[model]


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_ambiguous_contract_match_rolls_back_without_new_identity(world, producer):
    w = world
    cp = Counterparty(company_id=w.cid, name=NAME, inn=None, aliases=[])
    w.db.add(cp)
    await w.db.flush()
    ctype = CORPORATE_TYPE if producer == "corporate" else "Аренда"
    for _ in range(2):
        w.db.add(Contract(company_id=w.cid, counterparty_id=cp.id, organization_id=w.org_id,
                          number="Т-74", date="2026-01-01", type=ctype))
    await w.db.commit()
    before = await saved(w)
    with pytest.raises(IdentityConflict, match="Неоднозначное"):
        await run_producer(w, w.db, producer)
    await w.db.rollback()
    assert await saved(w) == before


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_foreign_company_identity_is_neither_reused_nor_modified(world, producer):
    w = world
    foreign = SimpleNamespace(**vars(w))
    foreign.cid, foreign.org_id, foreign.loc_ids = w.foreign_cid, w.foreign_org_id, w.foreign_loc_ids
    await run_producer(foreign, w.db, producer)
    await w.db.commit()
    before = await saved(foreign)
    await run_producer(w, w.db, producer)
    await w.db.commit()
    assert await saved(foreign) == before
    own = await saved(w)
    contract, = own["Contract"]
    cp, = own["Counterparty"]
    assert contract["organization_id"] == w.org_id and contract["counterparty_id"] == cp["id"]
    assert contract["id"] != before["Contract"][0]["id"]
    assert cp["id"] != before["Counterparty"][0]["id"]


@pytest.mark.parametrize("producer", PRODUCERS)
@pytest.mark.parametrize("organization_case", ["missing", "ambiguous"])
async def test_organization_selection_stays_explicit(world, producer, organization_case):
    w = world
    if organization_case == "missing":
        await w.db.execute(delete(Organization).where(Organization.company_id == w.cid))
    else:
        w.db.add(Organization(company_id=w.cid, name="Вторая синтетическая организация", inn="", prefix="Т2"))
    await w.db.commit()
    with pytest.raises(IdentityConflict, match="однозначная организация"):
        await run_producer(w, w.db, producer)
    await w.db.rollback()
    state = await saved(w)
    assert state["Contract"] == state["Counterparty"] == state["ContractLocation"] == state["DataEntry"] == []


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_successful_producer_remains_in_caller_transaction(world, producer):
    w = world
    await run_producer(w, w.db, producer)
    await w.db.rollback()
    state = await saved(w)
    assert state["Contract"] == state["Counterparty"] == state["ContractLocation"] == state["DataEntry"] == []


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_actual_second_contract_constraint_failure_rolls_back_whole_caller(world, producer):
    w = world
    bad = Counterparty(company_id=w.cid, name=OTHER, inn=None, aliases=[])
    w.db.add(bad)
    await w.db.commit()
    bad_id = bad.id
    before = await saved(w)
    # Trusted synthetic UUID, no source text interpolation. Transactional DDL is
    # confined to ROOT's exact disposable database; rollback removes this check.
    await w.db.execute(text("ALTER TABLE contracts ADD CONSTRAINT ck_contract_create_synthetic "
                            f"CHECK (counterparty_id <> '{bad_id}'::uuid)"))
    captured = {}
    with pytest.raises(IntegrityError, match="ck_contract_create_synthetic"):
        await run_producer(w, w.db, producer, names=(NAME, OTHER), capture=captured)
    if producer == "l2":
        index = captured["index"]
        assert sum(map(len, index.by_cp_type.values())) == 1
    await w.db.rollback()
    assert await saved(w) == before


async def test_failed_helper_flush_does_not_publish_and_rollback_keeps_old_python_index(world):
    w = world
    cp = Counterparty(company_id=w.cid, name=NAME, inn=None, aliases=[])
    w.db.add(cp)
    await w.db.flush()
    cp_id, index = cp.id, ContractIndex()
    contract = await create_imported_contract(w.db, w.cid, index, number="Успех", date="", counterparty_id=str(cp_id),
        organization_id=str(w.org_id), type="Аренда", kind="СПоставщиком", basis="договор", scope_type="locations", raw={})
    contract_id = str(contract.id)
    w.db.add(ContractLocation(company_id=w.cid, contract_id=contract.id, location_id=w.loc_ids[0]))
    with pytest.raises(IntegrityError):
        await create_imported_contract(w.db, w.cid, index, number=None, date="", counterparty_id=str(cp_id),
            organization_id=str(w.org_id), type="Отказ", kind="СПоставщиком", basis="договор", scope_type="locations", raw={})
    assert (str(cp_id), "Отказ") not in index.by_cp_type
    assert set(index.by_cp_type[(str(cp_id), "Аренда")]) == {contract_id}
    await w.db.rollback()
    # Do not resolve expired ORM rows after rollback: Python index ownership is
    # caller's responsibility, not an invented database rollback cleanup feature.
    assert set(index.by_cp_type[(str(cp_id), "Аренда")]) == {contract_id}
    state = await saved(w)
    assert state["Contract"] == state["Counterparty"] == state["ContractLocation"] == []


async def test_explicit_adapted_columns_and_untrimmed_raw_are_independent(world):
    w = world
    cp = Counterparty(company_id=w.cid, name=NAME, inn=None, aliases=[])
    w.db.add(cp)
    await w.db.flush()
    cp_id, index = cp.id, ContractIndex()
    raw = {"referenceIdentity": {"counterparty_id": str(cp_id), "type": "Аренда",
                                 "number": "Д" * 140, "date": ""}, "opaque": {"keep": [True, None]}}
    c = await create_imported_contract(w.db, w.cid, index, number="Д" * 100, date="", counterparty_id=str(cp_id),
        organization_id=str(w.org_id), type="Аренда", kind="СПоставщиком", basis="разрешение", scope_type="locations", raw=raw)
    assert c is index.resolve(cp, "Аренда", "Д" * 100)
    await w.db.commit()
    c, = (await saved(w))["Contract"]
    assert c["number"] == "Д" * 100 and c["raw"] == raw
    assert c["basis"] == "разрешение" and c["organization_id"] == w.org_id


@pytest.mark.parametrize("producer", PRODUCERS)
async def test_existing_company_locks_serialize_two_actual_producers(world, producer):
    w = world
    async with w.factory() as first:
        first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
        await run_producer(w, first, producer)
        ready = asyncio.Queue()

        async def second_writer():
            async with w.factory() as second:
                await ready.put(await second.scalar(text("SELECT pg_backend_pid()")))
                result = await run_producer(w, second, producer)
                await second.commit()
                return result

        task = asyncio.create_task(second_writer())
        try:
            async with asyncio.timeout(10):
                second_pid = await ready.get()
                async with w.factory() as observer:
                    while True:
                        waiting = await observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE pid=:pid AND locktype='advisory' AND NOT granted) "
                            "AND :blocker = ANY(pg_blocking_pids(:pid))"), {"pid": second_pid, "blocker": first_pid})
                        if waiting:
                            break
                        if task.done():
                            await task
                            pytest.fail("Second producer completed without the existing advisory wait")
                        await asyncio.sleep(0.02)
                await first.commit()
                second_result = await task
                if producer != "corporate":
                    assert second_result.get("contracts", 0) == second_result.get("counterparties", 0) == 0
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await first.rollback()
    state = await saved(w)
    assert len(state["Contract"]) == len(state["Counterparty"]) == 1
    assert len(state["ContractLocation"]) == (0 if producer == "corporate" else 2)
