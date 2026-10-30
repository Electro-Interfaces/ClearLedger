"""Синтетические SQL-контракты corporate producer; без внешних источников.

Тот же файл проверяет исходник и кандидат. Явный opt-in проверяется до ORM;
разрушительные conftest fixtures допустимы только в выделенной тестовой БД.
"""
import os
from copy import deepcopy
from types import SimpleNamespace
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS") != "1":
    pytest.skip("Требуется RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS"):
    raise RuntimeError(error)

import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import Company, Contract, CorporateClient, Counterparty, Organization
from app.services.charge_sessions_normalize import CORP_CONTRACT_TYPE, _sync_corporate_contracts
from app.services.counterparty_commands import create_imported_counterparty
from app.services.reference_identity import CounterpartyIndex, IdentityConflict
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    token = uuid.uuid4().hex[:12]
    companies = [Company(name="Синтетическая компания", slug=f"corp-command-{token}-{i}",
                         profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    own, foreign = companies
    organizations = [Organization(company_id=c.id, name="Синтетическая организация",
                                  inn="", prefix="Т") for c in companies]
    db.add_all(organizations)
    await db.flush()
    try:
        yield SimpleNamespace(db=db, cid=own.id, foreign_cid=foreign.id,
                              org_id=organizations[0].id)
    finally:
        await db.rollback()


async def rows(w, model, cid=None):
    return list((await w.db.execute(select(model).where(
        model.company_id == (w.cid if cid is None else cid)))).scalars())


async def clients(w, orgs, cid=None):
    for org in orgs:
        w.db.add(CorporateClient(company_id=w.cid if cid is None else cid,
                                name=org["name"][:500], phone=org["phone"],
                                ext_id="synthetic-" + org["phone"], mode="flat", rate=17.25,
                                discount_pct=12.5, matrix={"Тест": {"CCS2": 19}},
                                status="synthetic", users=2))
    await w.db.flush()


def state(items):
    return {str(row.id): deepcopy(snapshot_reference_fields(row)) | {"raw": deepcopy(row.raw)}
            for row in items}


@pytest.mark.parametrize("inn_input", [{}, {"inn": None}, {"inn": ""}, {"inn": 0}],
                         ids=["omitted", "null", "empty", "numeric-zero"])
async def test_two_unknown_inn_parties_contracts_phone_links_and_replay(world, inn_input):
    w = world
    # Проверяем сам существующий индекс, а не только декларацию модели.
    definition = (await w.db.execute(text("SELECT indexdef FROM pg_indexes "
        "WHERE schemaname='public' AND indexname='uq_counterparties_inn_kpp'"))).scalar_one()
    assert "UNIQUE INDEX" in definition and "WHERE (inn IS NOT NULL)" in definition
    orgs = [{"name": name, "phone": phone, "contract_start": "28.11.2023", **inn_input}
            for name, phone in [("ООО Синтетический Альфа", "70000000001"),
                                ("АО Синтетический Бета", "70000000002")]]
    await clients(w, orgs)
    client_before = {c.phone: snapshot_reference_fields(c) for c in await rows(w, CorporateClient)}
    assert await _sync_corporate_contracts(w.db, w.cid, orgs) is None
    parties, contracts = await rows(w, Counterparty), await rows(w, Contract)
    assert len(parties) == len(contracts) == 2
    by_name = {cp.name: cp for cp in parties}
    for org in orgs:
        cp = by_name[org["name"]]
        assert cp.inn is None and cp.kpp is None
        assert cp.aliases == ["corporate"] and cp.kind == "external" and cp.type == "ЮЛ"
        assert cp.raw == {"referenceIdentity": {"name": org["name"], "inn": "", "kpp": None}}
        contract = next(c for c in contracts if str(c.counterparty_id) == str(cp.id))
        assert str(contract.organization_id) == str(w.org_id)
        assert (contract.number, contract.date, contract.type, contract.kind, contract.basis,
                contract.scope_type) == ("б/н", "2023-11-28", CORP_CONTRACT_TYPE,
                                         "СПокупателем", "договор", "company")
        assert contract.raw == {"referenceIdentity": {"counterparty_id": str(cp.id),
            "type": CORP_CONTRACT_TYPE, "number": "б/н", "date": "2023-11-28"}}
    for c in await rows(w, CorporateClient):
        assert c.counterparty_id == by_name[c.name].id
        assert snapshot_reference_fields(c) == client_before[c.phone] | {"counterparty_id": c.counterparty_id}
    before = state(parties), state(contracts)
    await _sync_corporate_contracts(w.db, w.cid, orgs)
    assert (state(await rows(w, Counterparty)), state(await rows(w, Contract))) == before


@pytest.mark.parametrize("inn,kpp", [("7711111111", None), ("7711111111", ""),
    ("7711111111", "771101001"), ("7711111111", " " * 3), ("7711111111", 0),
    ("7711111111", "0"), ("0", "771101001"), ("   ", None),
    (123, "771101001"), ("1" * 25, "2" * 20)])
async def test_source_snapshot_kpp_and_adapter_limits_unchanged(world, inn, kpp):
    w = world
    name = "ИП " + "А" * 520
    org = {"name": "  " + name + " (тестовая заметка)  ", "inn": inn, "kpp": kpp,
           "phone": "70000000003"}
    await _sync_corporate_contracts(w.db, w.cid, [org])
    cp, = await rows(w, Counterparty)
    assert cp.name == name[:500] and cp.type == "ИП"
    assert cp.inn == str(inn or "")[:20] and cp.kpp == (kpp or None)
    assert cp.raw == {"referenceIdentity": {"name": name, "inn": str(inn or ""), "kpp": kpp}}
    assert cp.aliases == ["corporate"] and cp.kind == "external"


@pytest.mark.parametrize("frozen", [False, True])
async def test_known_identity_alias_accumulation_and_manual_replay(world, frozen):
    w = world
    org = {"name": "ООО Синтетический Источник", "inn": "7711111111", "kpp": "771101001",
           "phone": "70000000004", "contract_start": "2026-01-01"}
    await clients(w, [org])
    await _sync_corporate_contracts(w.db, w.cid, [org])
    cp, = await rows(w, Counterparty)
    contract, = await rows(w, Contract)
    raw = deepcopy(cp.raw), deepcopy(contract.raw)
    before = snapshot_reference_fields(cp)
    cp.name, cp.inn, cp.kpp = "Ручное имя", "7722222222", "772201001"
    cp.aliases = ["manual"] if frozen else ["rent"]
    mark_reference_changes(cp, before)
    if not frozen:
        cp.manual_overrides = [f for f in cp.manual_overrides if f != "aliases"]
    before = snapshot_reference_fields(contract)
    contract.number, contract.type, contract.date = "Ручной номер", "Ручной вид", "2026-02-02"
    mark_reference_changes(contract, before)
    await w.db.flush()
    expected_contract = state([contract])
    ids = cp.id, contract.id
    for _ in range(2):
        await _sync_corporate_contracts(w.db, w.cid, [org])
    cp, = await rows(w, Counterparty)
    contract, = await rows(w, Contract)
    assert (cp.id, contract.id) == ids and state([contract]) == expected_contract
    assert (cp.name, cp.inn, cp.kpp) == ("Ручное имя", "7722222222", "772201001")
    assert cp.aliases == (["manual"] if frozen else ["corporate", "rent"])
    assert (cp.raw, contract.raw) == raw
    client, = await rows(w, CorporateClient)
    assert client.counterparty_id == cp.id


async def test_known_inn_kpp_branches_and_foreign_company_untouched(world):
    w = world
    orgs = [{"name": "ООО Синтетический Филиал", "inn": "7711111111", "kpp": kpp,
             "phone": phone} for kpp, phone in [("771101001", "70000000005"),
                                                ("771102002", "70000000006")]]
    await clients(w, orgs, w.foreign_cid)
    await _sync_corporate_contracts(w.db, w.foreign_cid, orgs)
    foreign_before = (state(await rows(w, Counterparty, w.foreign_cid)),
                      state(await rows(w, Contract, w.foreign_cid)))
    foreign_clients = {c.id: snapshot_reference_fields(c)
                       for c in await rows(w, CorporateClient, w.foreign_cid)}
    await clients(w, orgs)
    await _sync_corporate_contracts(w.db, w.cid, orgs)
    parties, contracts = await rows(w, Counterparty), await rows(w, Contract)
    assert len(parties) == len(contracts) == 2
    assert {cp.kpp for cp in parties} == {"771101001", "771102002"}
    assert all(cp.inn == "7711111111" and cp.company_id == w.cid for cp in parties)
    before = state(parties), state(contracts)
    await _sync_corporate_contracts(w.db, w.cid, [dict(o, name="Другое имя источника") for o in orgs])
    assert (state(await rows(w, Counterparty)), state(await rows(w, Contract))) == before
    assert (state(await rows(w, Counterparty, w.foreign_cid)),
            state(await rows(w, Contract, w.foreign_cid))) == foreign_before
    assert {c.id: snapshot_reference_fields(c)
            for c in await rows(w, CorporateClient, w.foreign_cid)} == foreign_clients


@pytest.mark.parametrize("case,message", [("missing-kpp", "КПП"),
    ("missing-inn", "ИНН"), ("ambiguous-name", "Неоднозначное")])
async def test_existing_matcher_conflicts_leave_no_contract_or_link(world, case, message):
    w = world
    name = "ООО Синтетический Конфликт"
    if case == "ambiguous-name":
        for inn in ("7711111111", "7722222222"):
            w.db.add(Counterparty(company_id=w.cid, name=name, inn=inn))
        org = {"name": name, "phone": "70000000007"}
    else:
        w.db.add(Counterparty(company_id=w.cid, name=name,
                              inn="7711111111" if case == "missing-kpp" else None))
        org = {"name": name, "inn": "7711111111", "kpp": "771101001", "phone": "70000000007"}
    await clients(w, [org])
    before = state(await rows(w, Counterparty))
    with pytest.raises(IdentityConflict, match=message):
        await _sync_corporate_contracts(w.db, w.cid, [org])
    assert state(await rows(w, Counterparty)) == before
    assert await rows(w, Contract) == []
    client, = await rows(w, CorporateClient)
    assert client.counterparty_id is None


async def test_success_is_not_committed_and_native_failure_rolls_back_atomically(world):
    w = world
    org = {"name": "ООО Синтетический Откат", "inn": "7711111111", "kpp": "771101001",
           "phone": "70000000008"}
    await clients(w, [org])
    before = {c.id: snapshot_reference_fields(c) for c in await rows(w, CorporateClient)}
    async with w.db.begin_nested() as transaction:
        await _sync_corporate_contracts(w.db, w.cid, [org])
        assert len(await rows(w, Counterparty)) == len(await rows(w, Contract)) == 1
        await transaction.rollback()
    assert await rows(w, Counterparty) == await rows(w, Contract) == []
    assert {c.id: snapshot_reference_fields(c) for c in await rows(w, CorporateClient)} == before
    # Настоящий отказ flush на втором КПП; первый CP/Contract тоже должны уйти с rollback caller.
    async with w.db.begin_nested() as transaction:
        with pytest.raises(DBAPIError):
            await _sync_corporate_contracts(w.db, w.cid, [org, {
                "name": "ООО Синтетический Слишком Длинный КПП", "inn": "7722222222",
                "kpp": "2" * 21, "phone": "70000000009"}])
        await transaction.rollback()
    assert await rows(w, Counterparty) == await rows(w, Contract) == []
    assert {c.id: snapshot_reference_fields(c) for c in await rows(w, CorporateClient)} == before


async def test_helper_omitted_kpp_raw_shape_and_failed_flush_index(world):
    w = world
    index = CounterpartyIndex()
    cp = await create_imported_counterparty(w.db, w.cid, index,
        name="ООО Синтетический Helper", inn="7711111111", cp_type="ЮЛ", alias=None)
    assert cp.raw == {"referenceIdentity": {"name": cp.name, "inn": "7711111111"}}
    assert cp.kpp is None and cp.aliases == []
    assert index.resolve(cp.name, cp.inn) is cp
    async with w.db.begin_nested() as transaction:
        with pytest.raises(IntegrityError, match="uq_counterparties_inn_kpp"):
            await create_imported_counterparty(w.db, w.cid, index,
                name="ООО Синтетический Отказ", inn=cp.inn, cp_type="ЮЛ", alias="corporate")
        await transaction.rollback()
    assert index.resolve("ООО Синтетический Отказ") is None
    assert index.resolve(cp.name, cp.inn) is cp
    assert len(await rows(w, Counterparty)) == 1


async def test_blank_names_and_empty_input_keep_native_skip(world):
    w = world
    assert await _sync_corporate_contracts(w.db, w.cid, []) is None
    await _sync_corporate_contracts(w.db, w.cid, [{"name": value} for value in (None, "", " ", "ООО")])
    assert await rows(w, Counterparty) == await rows(w, Contract) == []
