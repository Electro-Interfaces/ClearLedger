"""Контракты native producers: одинаковый файл для baseline и кандидата.

Никаких подмен command/matcher/SQL; HTTP подменяет только текущего пользователя.
Разрушительные conftest fixtures разрешаются только явным opt-in и safety guard.
"""
import os
from types import SimpleNamespace
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_COUNTERPARTY_COMMAND_TESTS") != "1":
    pytest.skip("Требуется RUN_COUNTERPARTY_COMMAND_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_COUNTERPARTY_COMMAND_TESTS"):
    raise RuntimeError(error)

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import get_current_user
from app.database import get_db
from app.models import (Company, Contract, CorporateClient, Counterparty, DataEntry,
                        Organization, ServiceLocation, User, UserCompany)
from app.routers import space_registry_router
from app.scope import set_request_organization, set_request_scope
from app.services.reference_identity import IdentityConflict
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields
from app.services.reestr_normalize import ingest_reestr
from app.services.reestr_rushydro import L2Cache

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    token = uuid.uuid4().hex[:12]
    companies = [Company(name="Синтетическая компания", slug=f"commands-{token}-{i}",
                         profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    cid, foreign_cid = [c.id for c in companies]
    db.add(Organization(company_id=cid, name="Своя организация", inn="", prefix="Т"))
    db.add(ServiceLocation(id=token, company_id=cid, code="1", name="Тестовая точка"))
    await db.flush()
    return SimpleNamespace(db=db, cid=cid, foreign_cid=foreign_cid, location_id=token)


async def imported(w, producer, names, role="rent"):
    if producer == "legacy":
        return await ingest_reestr(w.db, w.cid, [
            {"bu": "1", f"{role}_cp": name, f"{role}_contract": "№ Т-74 от 01.01.2026"}
            for name in names])
    cache = L2Cache()
    await cache.build(w.db, w.cid)
    stats = {}
    for name in names:
        await cache.counterparty(w.db, w.cid, name, alias=role, res=stats)
    return stats


async def parties(w):
    return (await w.db.execute(select(Counterparty).where(
        Counterparty.company_id == w.cid).order_by(Counterparty.name))).scalars().all()


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_import_replay_keeps_manual_fields_and_source(world, producer):
    w = world
    names = ['ООО «Одинаковое имя»']
    result = await imported(w, producer, names)
    assert result["counterparties"] == 1
    rows = await parties(w)
    assert len(rows) == 1
    ids = {row.id for row in rows}
    snapshots = {row.id: row.raw for row in rows}
    for row in rows:
        assert row.kind == "external" and row.aliases == ["rent"] and row.inn == ""
        before = snapshot_reference_fields(row)
        row.name = "Ручное имя " + str(row.id)
        row.aliases = ["Ручная роль"]
        mark_reference_changes(row, before)
    await w.db.flush()
    contracts = (await w.db.execute(select(Contract).where(Contract.company_id == w.cid))).scalars().all()
    contract_values = {c.id: (c.counterparty_id, c.organization_id, c.number, c.date, c.type)
                       for c in contracts}
    result = await imported(w, producer, names)
    assert result.get("counterparties", 0) == 0
    rows = await parties(w)
    assert {row.id for row in rows} == ids
    assert all(row.aliases == ["Ручная роль"] and row.name.startswith("Ручное имя ") for row in rows)
    assert {row.id: row.raw for row in rows} == snapshots
    contracts = (await w.db.execute(select(Contract).where(Contract.company_id == w.cid))).scalars().all()
    assert {c.id: (c.counterparty_id, c.organization_id, c.number, c.date, c.type)
            for c in contracts} == contract_values
    await w.db.rollback()


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_import_preserves_legal_forms_of_existing_tax_identities(world, producer):
    w = world
    names = ['ООО «Одинаковое имя»', 'АО «Одинаковое имя»']
    rows = [Counterparty(company_id=w.cid, name=name, inn=inn, aliases=[])
            for name, inn in zip(names, ("7711111111", "7722222222"))]
    w.db.add_all(rows)
    await w.db.flush()
    identities = {row.id: (row.name, row.inn) for row in rows}
    result = await imported(w, producer, names)
    assert result.get("counterparties", 0) == 0
    saved = await parties(w)
    assert {row.id: (row.name, row.inn) for row in saved} == identities
    assert all(row.aliases == ["rent"] for row in saved)
    await w.db.rollback()


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_second_blank_tax_identity_keeps_existing_sql_refusal_without_merge(world, producer):
    """Прежний DDL запрещает две пустые пары; срез не исправляет этот долг."""
    w = world
    await imported(w, producer, ['ООО «Одинаковое имя»'])
    before = (await parties(w))[0].id
    async with w.db.begin_nested() as transaction:
        with pytest.raises(IntegrityError, match="uq_counterparties_inn_kpp"):
            await imported(w, producer, ['АО «Одинаковое имя»'])
        await transaction.rollback()
    saved = await parties(w)
    assert len(saved) == 1 and saved[0].id == before and saved[0].name == 'ООО «Одинаковое имя»'
    await w.db.rollback()


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_ambiguous_import_rolls_back_without_choosing_a_party(world, producer):
    w = world
    for inn in ("7711111111", "7722222222"):
        w.db.add(Counterparty(company_id=w.cid, name="ООО Неоднозначное", inn=inn))
    await w.db.flush()
    async with w.db.begin_nested() as transaction:
        with pytest.raises(IdentityConflict, match="Неоднозначное"):
            await imported(w, producer, ["ООО Неоднозначное"])
        await transaction.rollback()
    assert len(await parties(w)) == 2
    assert (await w.db.execute(select(func.count()).select_from(Contract).where(
        Contract.company_id == w.cid))).scalar_one() == 0
    assert (await w.db.execute(select(func.count()).select_from(DataEntry).where(
        DataEntry.company_id == w.cid))).scalar_one() == 0
    await w.db.rollback()


@pytest.mark.parametrize("producer", ["legacy", "l2"])
async def test_import_accumulates_roles_and_caller_can_roll_back(world, producer):
    w = world
    async with w.db.begin_nested() as transaction:
        await imported(w, producer, ["ООО Общий участник"])
        before = (await parties(w))[0].id
        for _ in range(2):
            await imported(w, producer, ["ООО Общий участник"], role="energy")
        rows = await parties(w)
        assert len(rows) == 1 and rows[0].id == before and rows[0].aliases == ["energy", "rent"]
        await transaction.rollback()
    assert await parties(w) == []
    assert (await w.db.execute(select(func.count()).select_from(Contract).where(
        Contract.company_id == w.cid))).scalar_one() == 0
    assert (await w.db.execute(select(func.count()).select_from(DataEntry).where(
        DataEntry.company_id == w.cid))).scalar_one() == 0
    await w.db.rollback()


async def test_l2_known_inn_company_scope_and_incomplete_identity(world):
    w = world
    inn = "7733333333"
    foreign = Counterparty(company_id=w.foreign_cid, name="ООО Компания", inn=inn)
    w.db.add(foreign)
    await w.db.flush()
    cache = L2Cache()
    await cache.build(w.db, w.cid)
    created = await cache.counterparty(w.db, w.cid, "ООО Компания", inn=inn)
    assert created.id != foreign.id and created.company_id == w.cid
    assert created.raw == {"referenceIdentity": {"name": "ООО Компания", "inn": inn}}
    assert created.aliases == []
    assert await cache.counterparty(w.db, w.cid, "Другое имя", inn=inn) is created
    unknown = await cache.counterparty(w.db, w.cid, "ООО Без ИНН")
    with pytest.raises(IdentityConflict, match="сверить ИНН"):
        await cache.counterparty(w.db, w.cid, unknown.name, inn="7744444444")
    assert unknown.inn == "" and len(await parties(w)) == 2
    await w.db.rollback()


async def test_l2_preserves_full_source_and_skips_non_parties(world):
    w = world
    cache = L2Cache()
    await cache.build(w.db, w.cid)
    name, inn = "ООО " + "А" * 520, "1" * 25
    row = await cache.counterparty(w.db, w.cid, name, inn=inn)
    assert row.name == name[:500] and row.inn == inn[:20]
    assert row.raw == {"referenceIdentity": {"name": name, "inn": inn}}
    for blank in (None, "", "-", "Информация уточняется"):
        assert await cache.counterparty(w.db, w.cid, blank) is None
    assert len(await parties(w)) == 1
    await w.db.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def http_world(world):
    w = world
    user = User(name="Тестовый участник", email=f"{uuid.uuid4().hex}@example.invalid", password_hash="unused")
    w.db.add(user)
    await w.db.flush()
    membership = UserCompany(user_id=user.id, company_id=w.cid, role="member")
    client_row = CorporateClient(company_id=w.cid, name="ООО Клиент для связи", phone="",
                                 ext_id=uuid.uuid4().hex)
    w.db.add_all([membership, client_row])
    await w.db.commit()
    factory = async_sessionmaker(w.db.bind, expire_on_commit=False)
    app = FastAPI()
    app.include_router(space_registry_router.router, prefix="/api")

    async def actor():
        set_request_scope(None)
        set_request_organization(None)
        return user

    async def session():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(**vars(w), client=client, membership=membership, client_row=client_row)
    set_request_scope(None)
    set_request_organization(None)


async def link(w, **params):
    return await w.client.post("/api/registry/link-counterparties", params={"company_id": str(w.cid), **params})


async def test_native_http_preview_acl_only_and_replay(http_world):
    w = http_world
    response = await link(w)
    assert response.status_code == 200 and response.json()["totals"]["created"] == 1
    assert await parties(w) == []
    assert (await link(w, apply="true")).status_code == 403
    assert (await w.client.post("/api/registry/link-counterparties", params={
        "company_id": str(w.foreign_cid), "apply": "true"})).status_code == 403
    w.membership.role = "admin"
    await w.db.commit()
    response = await link(w, apply="true", only="site_owner")
    assert response.status_code == 200 and response.json()["totals"]["created"] == 0
    assert await parties(w) == []
    response = await link(w, apply="true", only="corporate_client")
    assert response.status_code == 200 and response.json()["totals"] == {"linked": 1, "created": 1}
    rows = await parties(w)
    assert len(rows) == 1 and rows[0].aliases == ["corporate"]
    await w.db.refresh(w.client_row)
    party_id = rows[0].id
    assert w.client_row.counterparty_id == party_id
    response = await link(w, apply="true", only="corporate_client")
    assert response.status_code == 200 and response.json()["totals"] == {"linked": 0, "created": 0}
    assert [p.id for p in await parties(w)] == [party_id]


async def test_native_http_ambiguity_is_409_without_link_or_creation(http_world):
    w = http_world
    w.membership.role = "admin"
    for inn in ("7755555555", "7766666666"):
        w.db.add(Counterparty(company_id=w.cid, name=w.client_row.name, inn=inn))
    await w.db.commit()
    for apply in ("false", "true"):
        response = await link(w, apply=apply, only="corporate_client")
        assert response.status_code == 409 and "Неоднозначное" in response.json()["detail"]
    await w.db.refresh(w.client_row)
    assert w.client_row.counterparty_id is None
    assert len(await parties(w)) == 2


@pytest.mark.parametrize("frozen", [False, True])
async def test_native_http_existing_alias_update_respects_manual_freeze(http_world, frozen):
    w = http_world
    w.membership.role = "admin"
    snapshot = {"referenceIdentity": {"name": w.client_row.name, "inn": ""}}
    row = Counterparty(company_id=w.cid, name=w.client_row.name, inn="", aliases=["rent"],
                       raw=snapshot, manual_overrides=["aliases"] if frozen else [])
    w.db.add(row)
    await w.db.commit()
    identifier = row.id
    response = await link(w, apply="true", only="corporate_client")
    assert response.status_code == 200 and response.json()["totals"] == {"linked": 1, "created": 0}
    await w.db.refresh(row)
    await w.db.refresh(w.client_row)
    assert row.aliases == (["rent"] if frozen else ["corporate", "rent"])
    assert row.raw == snapshot and row.id == identifier
    assert w.client_row.counterparty_id == identifier and len(await parties(w)) == 1
