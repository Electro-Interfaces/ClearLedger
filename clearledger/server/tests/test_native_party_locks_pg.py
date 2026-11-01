"""AUTHORED / NOTRUN: real native commands, INN checker and two-session PG waits.

ROOT owns the preimport composition and disposable, preprovisioned synthetic DB.
Ordinary repository conftest can import app and DROP schemas before this guard.
No schema DDL, execution script, installation or runtime permission is supplied.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_PARTY_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("NATIVE_PARTY_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("NATIVE_PARTY_APPROVAL") == "ROOT-reviewed-synthetic-native-party-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password and _TARGET.path == "/api_native_party_test_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed native party preimport composition required")

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import (
    Company, Contract, Counterparty, CounterpartyContact, LocationContact,
    OneCConnection, Organization, PartnerSpace, ServiceLocation, User, UserCompany,
)
from app.routers import references_router as router
from app.routers import users_router
from app.schemas import (
    ContractCreate, CounterpartyContactIn, CounterpartyCreate, CounterpartyUpdate,
    OrganizationCreate, OrganizationUpdate,
)
from app.scope import set_request_organization, set_request_scope
from app.services import contract_write_locks as locks
from app.services import native_party_locks as native
from app.services.native_contract_commands import create_native_contract
from app.services.onec.sync_service import OneCSyncService
from app.services.reference_identity import lock_manual_creation

pytestmark = pytest.mark.asyncio(loop_scope="session")
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
ROOTS = ("cp_create", "cp_patch", "cp_delete", "org_create", "org_patch",
         "contact_create", "contact_put", "contact_delete")
CONTACTS = ("contact_create", "contact_put", "contact_delete")


@pytest_asyncio.fixture(loop_scope="session")
async def world():
    engine = create_async_engine(_URL, pool_size=8, max_overflow=0, isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex[:16]
    async with factory() as db:
        company = Company(id=uuid4(), name="Synthetic native parties", slug=f"np-{token}", profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic other company", slug=f"no-{token}", profile_id="energy")
        db.add_all([company, other])
        await db.flush()
        actor = User(id=uuid4(), company_id=company.id, email=f"{token}@party.invalid",
            name="Synthetic ordinary member", password_hash="synthetic-noncredential", is_superadmin=False)
        admin = User(id=uuid4(), company_id=company.id, email=f"a-{token}@party.invalid",
            name="Synthetic administrator", password_hash="synthetic-noncredential", is_superadmin=False)
        outsider = User(id=uuid4(), company_id=other.id, email=f"o-{token}@party.invalid",
            name="Synthetic outsider", password_hash="synthetic-noncredential", is_superadmin=False)
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic CP", inn="7701234567",
            kpp="123456789", aliases=["old"], raw={"referenceIdentity": {"name": "Synthetic CP"}})
        free_cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic unused CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Synthetic Org", inn="", prefix="old")
        foreign_cp = Counterparty(id=uuid4(), company_id=other.id, name="Synthetic other CP", aliases=[])
        foreign_org = Organization(id=uuid4(), company_id=other.id, name="Synthetic other Org", inn="")
        partner = PartnerSpace(id=uuid4(), company_id=company.id, role="vendor", code=f"p-{token}",
            name="Synthetic visit issuer", base_url="https://synthetic.invalid", is_active=True)
        connection = OneCConnection(id=uuid4(), company_id=company.id, name="Synthetic catalogs",
            mode="odata", odata_url="https://synthetic.invalid", username="synthetic", password_encrypted="not-a-secret")
        db.add_all([actor, admin, outsider, cp, free_cp, org, foreign_cp, foreign_org, partner, connection])
        await db.flush()
        db.add_all([UserCompany(user_id=actor.id, company_id=company.id, role="user"),
                    UserCompany(user_id=admin.id, company_id=company.id, role="admin")])
        contact = CounterpartyContact(id=uuid4(), company_id=company.id, counterparty_id=cp.id,
            name="Synthetic contact", role="tech", position="old", phone="old", email="old@synthetic.invalid", notes="old")
        db.add(contact)
        await db.commit()
        w = SimpleNamespace(engine=engine, factory=factory, actor=actor, uid=actor.id,
            admin=admin, outsider=outsider, cid=company.id, slug=company.slug, foreign=other.id,
            cp=cp.id, free_cp=free_cp.id, org=org.id, foreign_cp=foreign_cp.id,
            foreign_org=foreign_org.id, contact=contact.id, partner=partner.id, connection=connection.id)
    set_request_scope(None)
    set_request_organization(None)
    try:
        with native_claims_context(None, None):
            yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        await engine.dispose()


@pytest.fixture
def sql_log(world):
    rows = []
    def record(conn, cursor, statement, parameters, context, executemany):
        rows.append((conn.info.get("native_party_label"), statement, parameters))
    event.listen(world.engine.sync_engine, "before_cursor_execute", record)
    try:
        yield rows
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", record)


async def pid(db, label):
    connection = await db.connection()
    connection.sync_connection.info["native_party_label"] = label
    return await db.scalar(text("SELECT pg_backend_pid()"))


def statements(log, label="waiter"):
    return [sql for owner, sql, params in log if owner == label]


def no_writes(sql):
    assert not any(row.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT")) for row in sql)


async def blocked(observer, waiter, owner, key=None, *, mode=X):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if owner in await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}):
            if key is not None:
                namespace, value = locks.advisory_key(key)
                lock = (await observer.execute(text("SELECT mode,granted FROM pg_locks WHERE pid=:p "
                    "AND locktype='advisory' AND classid=:n AND objid=:k AND objsubid=2"),
                    {"p": waiter, "n": namespace, "k": value & 0xFFFFFFFF})).one_or_none()
                if lock != ("ShareLock" if mode is S else "ExclusiveLock", False):
                    await asyncio.sleep(.01)
                    continue
            return
        await asyncio.sleep(.01)
    raise AssertionError("Actual PostgreSQL blocker/pending lock was not observed")


async def invoke(w, db, root, *, actor=None, body=None, target=None):
    actor = w.actor if actor is None else actor
    if root == "cp_create":
        return await router.create_counterparty(CounterpartyCreate(**(body or {
            "company_id": str(w.cid), "name": "Synthetic new CP"})), db, actor)
    if root == "cp_patch":
        return await router.update_counterparty(str(target or w.cp), CounterpartyUpdate(**(body or {"name": "Synthetic changed CP"})), db, actor)
    if root == "cp_delete":
        return await router.delete_counterparty(str(target or w.free_cp), db, actor)
    if root == "org_create":
        return await router.create_organization(OrganizationCreate(**(body or {
            "company_id": str(w.cid), "name": "Synthetic new Org", "inn": ""})), db, actor)
    if root == "org_patch":
        return await router.update_organization(str(target or w.org), OrganizationUpdate(**(body or {"prefix": "new"})), db, actor)
    if root == "contact_create":
        return await router.create_counterparty_contact(str(target or w.cp), CounterpartyContactIn(**(body or {"name": "Synthetic new contact"})), db, actor)
    if root == "contact_put":
        return await router.update_counterparty_contact(str(target or w.cp), str(w.contact), CounterpartyContactIn(**(body or {"name": "Synthetic replacement"})), db, actor)
    if root == "contact_delete":
        return await router.delete_counterparty_contact(str(target or w.cp), str(w.contact), db, actor)
    raise AssertionError(root)


@asynccontextmanager
async def running(w, call, *, retain=False):
    ready, info = asyncio.Event(), {}
    async def run():
        async with w.factory() as db:
            info["db"], info["pid"] = db, await pid(db, "waiter")
            if retain:
                info["retained"] = (await db.get(User, w.uid), await db.get(UserCompany, (w.uid, w.cid)),
                    await db.get(Counterparty, w.cp), await db.get(Organization, w.org),
                    await db.get(CounterpartyContact, w.contact), await db.get(PartnerSpace, w.partner))
            info["root"] = db.sync_session.get_transaction()
            ready.set()
            return await call(db)
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(ready.wait(), 10)
        yield info, task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("root", ROOTS)
@pytest.mark.parametrize("axis", ["company", "user", "member", "reference"])
async def test_actual_roots_wait_on_full_b_before_rows_and_first_pending_write(world, sql_log, root, axis):
    w = world
    key = {"company": locks.CompanyKey(w.cid), "user": locks.UserKey(w.uid),
           "member": locks.MemberKey(w.cid, w.uid), "reference": locks.RefCompositeKey(w.cid)}[axis]
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running(w, lambda db: invoke(w, db, root)) as (info, task):
            mode = S if axis != "reference" or root in CONTACTS else X
            await blocked(observer, info["pid"], owner_pid, key, mode=mode)
            sql = statements(sql_log)
            no_writes(sql)
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in sql)
            assert not info["db"].new and not info["db"].dirty and not info["db"].deleted
            await owner.rollback()
            await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("root", ["cp_create", "cp_patch", "cp_delete"])
async def test_cp_legacy_wait_is_upfront_and_precedes_authority_and_cp_rows(world, sql_log, root):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await lock_manual_creation(owner, w.cid, "counterparty")
        async with running(w, lambda db: invoke(w, db, root)) as (info, task):
            await blocked(observer, info["pid"], owner_pid)
            sql = statements(sql_log)
            no_writes(sql)
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in sql)
            await owner.rollback()
            await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("root", ROOTS)
async def test_retained_membership_revocation_after_b_wait_repeats_native_403_or_404(world, sql_log, root):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running(w, lambda db: invoke(w, db, root), retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid, key, mode=S if root in CONTACTS else X)
            await owner.delete(await owner.get(UserCompany, (w.uid, w.cid)))
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == (403 if root in ("cp_create", "org_create") else 404)
            no_writes(statements(sql_log))


@pytest.mark.parametrize("axis", ["company", "user", "member", "party", "contact"])
async def test_last_physical_wait_refreshes_retained_visit_before_contact_mutation(world, sql_log, axis):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        model, predicate = {
            "company": (Company, Company.id == w.cid), "user": (User, User.id == w.uid),
            "member": (UserCompany, (UserCompany.user_id == w.uid) & (UserCompany.company_id == w.cid)),
            "party": (Counterparty, Counterparty.id == w.cp),
            "contact": (CounterpartyContact, CounterpartyContact.id == w.contact),
        }[axis]
        await owner.execute(select(model).where(predicate).with_for_update())
        claims = {"sub": str(w.uid), "tv": 0, "scp": "visit", "cid": str(w.cid), "pvs": str(w.partner)}
        async def call(db):
            with native_claims_context(claims, w.cid):
                return await invoke(w, db, "contact_put")
        async with running(w, call, retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid)
            (await owner.get(PartnerSpace, w.partner)).is_active = False
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 401
            no_writes(statements(sql_log))


async def test_native_defaults_null_alias_override_and_org_nonclear_behavior(world):
    w = world
    async with w.factory() as db:
        value = await invoke(w, db, "cp_create", body={"company_id": w.slug, "name": "  Synthetic draft  ", "inn": " ", "kpp": ""})
        assert (value.name, value.inn, value.kpp, value.type, value.aliases, value.lifecycleStatus) == (
            "Synthetic draft", None, None, "ЮЛ", [], "draft")
        await db.rollback()
    async with w.factory() as db:
        await invoke(w, db, "cp_patch", body={"inn": None, "kpp": None, "shortName": None,
            "phone": None, "aliases": ["z", "a", "z"]})
        cp = await db.get(Counterparty, w.cp)
        assert cp.inn == "7701234567" and cp.kpp is None and cp.aliases == ["z", "a", "z"]
        assert {"kpp", "aliases"} <= set(cp.manual_overrides)
        assert cp.raw == {"referenceIdentity": {"name": "Synthetic CP"}}
        await db.rollback()
    async with w.factory() as db:
        await invoke(w, db, "org_patch", body={"prefix": None, "kpp": None})
        assert (await db.get(Organization, w.org)).prefix == "old"
        await db.rollback()
    async with w.factory() as db:
        await invoke(w, db, "contact_put")
        row = await db.get(CounterpartyContact, w.contact)
        assert (row.position, row.phone, row.email, row.notes, row.role) == (None, None, None, None, "other")


@pytest.mark.parametrize("root, expected", [("cp_create", 403), ("cp_patch", 409)])
async def test_verified_and_actual_inn_duplicate_error_precedence(world, root, expected):
    w = world
    async with w.factory() as db:
        body = {"inn": "7701234567", "kpp": "123456789", "lifecycleStatus": "verified"}
        if root == "cp_create":
            body.update(company_id=str(w.cid), name="Synthetic duplicate")
        with pytest.raises(HTTPException) as failure:
            await invoke(w, db, root, body=body, target=w.free_cp)
        assert failure.value.status_code == expected
        if expected == 409:
            assert failure.value.detail == f"Контрагент с такими ИНН/КПП уже существует: {w.cp}"


@pytest.mark.parametrize("root", ["cp_patch", "cp_delete", "org_patch"] + list(CONTACTS))
async def test_actual_foreign_and_missing_objects_remain_404_without_added_admin_policy(world, root):
    w = world
    for target in (w.foreign_org if root == "org_patch" else w.foreign_cp, uuid4()):
        async with w.factory() as db:
            with pytest.raises(HTTPException) as failure:
                await invoke(w, db, root, target=target)
            assert (failure.value.status_code, failure.value.detail) == (404, "Не найдено")


@pytest.mark.parametrize("root", ["cp_patch", "org_patch", "contact_create"])
async def test_actual_get_owned_object_scope_policy_is_preserved(world, root):
    w = world
    async with w.factory() as fixture:
        member = await fixture.get(UserCompany, (w.uid, w.cid))
        member.object_scope = ["opaque:synthetic-location"]
        await fixture.commit()
    async with w.factory() as db:
        with pytest.raises(HTTPException) as failure:
            await invoke(w, db, root)
        assert failure.value.status_code == 404


@pytest.mark.parametrize("second", ["cp_create", "cp_patch"])
@pytest.mark.parametrize("release", ["commit", "rollback"])
async def test_actual_inn_checker_serializes_create_and_patch_with_committed_outcomes(world, second, release):
    w = world
    new_inn = "7712345678"
    body = {"company_id": str(w.cid), "name": "Synthetic winner", "inn": new_inn, "kpp": "123456789"}
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        winner = await invoke(w, owner, "cp_create", body=body)
        other_body = body if second == "cp_create" else {"inn": new_inn, "kpp": "123456789"}
        async with running(w, lambda db: invoke(w, db, second, body=other_body, target=w.free_cp)) as (info, task):
            await blocked(observer, info["pid"], owner_pid, locks.RefCompositeKey(w.cid))
            await (owner.commit() if release == "commit" else owner.rollback())
            if release == "commit":
                with pytest.raises(HTTPException) as failure:
                    await asyncio.wait_for(task, 10)
                assert failure.value.status_code == 409
                assert failure.value.detail == f"Контрагент с такими ИНН/КПП уже существует: {winner.id}"
            else:
                result = await asyncio.wait_for(task, 10)
                assert result.inn == new_inn


async def r1_peer(w, db):
    return await create_native_contract(db, ContractCreate(company_id=str(w.cid), number="Synthetic R1 peer",
        date="2026-01-01", type="Synthetic", counterpartyId=str(w.cp), organizationId=str(w.org)), w.actor)


class EmptySyntheticCatalog:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def describe_entity(self, entity):
        return {}

    async def iter_entity(self, *args, **kwargs):
        for item in ():
            yield item


async def onec_peer(w, db, monkeypatch):
    service = OneCSyncService(db)
    async def synthetic_client(connection):
        return EmptySyntheticCatalog()
    monkeypatch.setattr(service, "_open_client", synthetic_client)
    # Real mixed root/log and all five real catalog loops; only external I/O is substituted.
    return await service.sync_catalogs(await db.get(OneCConnection, w.connection))


@pytest.mark.parametrize("party", ["cp_patch", "org_patch"])
@pytest.mark.parametrize("peer", ["r1", "onec", "contact"])
@pytest.mark.parametrize("first", ["party", "peer"])
@pytest.mark.parametrize("release", ["commit", "rollback"])
async def test_actual_peer_roots_both_orders_wait_at_reference_b_before_rows_or_first_write(
    world, sql_log, monkeypatch, party, peer, first, release,
):
    w = world
    async def peer_call(db):
        if peer == "r1":
            return await r1_peer(w, db)
        if peer == "onec":
            return await onec_peer(w, db, monkeypatch)
        return await invoke(w, db, "contact_create")
    first_call = (lambda db: invoke(w, db, party)) if first == "party" else peer_call
    second_call = peer_call if first == "party" else (lambda db: invoke(w, db, party))
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await first_call(owner)
        async with running(w, second_call) as (info, task):
            mode = S if first == "party" and peer in ("r1", "contact") else X
            await blocked(observer, info["pid"], owner_pid, locks.RefCompositeKey(w.cid), mode=mode)
            no_writes(statements(sql_log))
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in statements(sql_log))
            await (owner.commit() if release == "commit" else owner.rollback())
            await asyncio.wait_for(task, 10)


async def test_contacts_share_reference_b_with_actual_contract_only_root(world):
    w = world
    async with w.factory() as owner, w.factory() as peer:
        await r1_peer(w, owner)
        response = await asyncio.wait_for(invoke(w, peer, "contact_create"), 10)
        assert response["counterpartyId"] == str(w.cp)


async def remove_actor(w, db, monkeypatch):
    async def no_external_notification(*args, **kwargs):
        return None
    monkeypatch.setattr(users_router, "log_audit", no_external_notification)
    with native_claims_context({"sub": str(w.admin.id), "tv": 0}, None):
        await users_router.remove_user(str(w.uid), str(w.cid), db, w.admin)
    await db.flush()


@pytest.mark.parametrize("first", ["party", "user"])
@pytest.mark.parametrize("release", ["commit", "rollback"])
async def test_actual_remove_user_and_native_party_actor_guard_both_orders(world, sql_log, monkeypatch, first, release):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        if first == "party":
            await invoke(w, owner, "cp_patch")
            call = lambda db: remove_actor(w, db, monkeypatch)
        else:
            await remove_actor(w, owner, monkeypatch)
            call = lambda db: invoke(w, db, "cp_patch")
        async with running(w, call) as (info, task):
            await blocked(observer, info["pid"], owner_pid, locks.UserKey(w.uid), mode=X if first == "party" else S)
            no_writes(statements(sql_log))
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in statements(sql_log))
            await (owner.commit() if release == "commit" else owner.rollback())
            if first == "user" and release == "commit":
                with pytest.raises(HTTPException) as failure:
                    await asyncio.wait_for(task, 10)
                assert failure.value.status_code == 401
            else:
                await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("release", ["commit", "rollback"])
async def test_actual_cp_delete_precedes_contact_fk_writer_at_b_and_preserves_missing_result(world, release):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await invoke(w, owner, "cp_delete")
        async with running(w, lambda db: invoke(w, db, "contact_create", target=w.free_cp)) as (info, task):
            await blocked(observer, info["pid"], owner_pid, locks.RefCompositeKey(w.cid), mode=S)
            await (owner.commit() if release == "commit" else owner.rollback())
            if release == "commit":
                with pytest.raises(HTTPException) as failure:
                    await asyncio.wait_for(task, 10)
                assert failure.value.status_code == 404
            else:
                assert (await asyncio.wait_for(task, 10))["counterpartyId"] == str(w.free_cp)


async def test_actual_contact_delete_first_then_cp_delete_after_committed_contact_removal(world):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await invoke(w, owner, "contact_delete")
        async with running(w, lambda db: invoke(w, db, "cp_delete", target=w.cp)) as (info, task):
            await blocked(observer, info["pid"], owner_pid, locks.RefCompositeKey(w.cid))
            await owner.commit()
            assert await asyncio.wait_for(task, 10) is None


async def test_real_cross_company_contract_fk_error_is_exact_409_and_requires_whole_root_rollback(world, monkeypatch):
    w = world
    async with w.factory() as seed:
        legacy = Contract(id=uuid4(), company_id=w.foreign, counterparty_id=w.free_cp,
            organization_id=w.foreign_org, number="Synthetic legacy cross-company FK",
            date="2026-01-01", type="Synthetic")
        seed.add(legacy)
        await seed.commit()
        legacy_id = legacy.id
    prepared = []
    real_prepare = router.prepare_native_party_write
    async def observe_preparation(*args, **kwargs):
        result = await real_prepare(*args, **kwargs)
        prepared.append(result)
        return result
    monkeypatch.setattr(router, "prepare_native_party_write", observe_preparation)
    async with w.factory() as db:
        # Real FK restrict: usage's company predicate misses this legacy foreign row.
        with pytest.raises(HTTPException) as failure:
            await invoke(w, db, "cp_delete")
        assert failure.value.status_code == 409
        assert failure.value.detail == "Нельзя удалить контрагента: есть связанные договоры, контакты или другие записи. Сначала удалите или переназначьте связи."
        assert not db.sync_session.is_active
        with pytest.raises(locks.ScopedLockError):
            native.require_native_party_write(db, prepared[-1])
        with pytest.raises(locks.ScopedLockError):
            await locks.acquire_scoped_locks_async(db, prepared[-1].plan)
        await db.rollback()
        assert await db.get(Counterparty, w.free_cp) is not None
        assert await db.get(Contract, legacy_id) is not None
        await db.rollback()
    async with w.factory() as seed:
        await seed.delete(await seed.get(Contract, legacy_id))
        await seed.commit()
    async with w.factory() as db:
        await invoke(w, db, "cp_delete")
        assert await db.get(Counterparty, w.free_cp) is None
        await db.rollback()
    async with w.factory() as db:
        assert await db.get(Counterparty, w.free_cp) is not None


@pytest.mark.parametrize("root", ROOTS)
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
async def test_pending_real_orm_state_is_retained_and_never_autoflushed_by_actual_roots(world, sql_log, root, pending):
    w = world
    async with w.factory() as db:
        await pid(db, "waiter")
        row = await db.get(Counterparty, w.free_cp)
        if pending == "new":
            row = Counterparty(id=uuid4(), company_id=w.cid, name="Synthetic pending", aliases=[])
            db.add(row)
        elif pending == "dirty":
            row.name = "Synthetic pending change"
        else:
            await db.delete(row)
        sql_log.clear()
        with pytest.raises(locks.ScopedLockError, match="clean entry"):
            await invoke(w, db, root)
        no_writes(statements(sql_log))
        assert row in getattr(db, pending)


@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_preparation_cannot_cross_actual_transaction_or_connection_lifetime(world, ending):
    w = world
    async with w.factory() as db:
        prepared = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        native.require_native_party_write(db, prepared)
        with pytest.raises(locks.ScopedLockError):
            native.require_native_party_write(db, replace(prepared, entity="contact", party_id=w.cp))
        await getattr(db, ending)()
        with pytest.raises(locks.ScopedLockError):
            native.require_native_party_write(db, prepared)
        fresh = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        native.require_native_party_write(db, fresh)
        assert fresh.capability is not prepared.capability


async def test_partial_actual_b_cancellation_poison_never_allows_same_root_retry_and_releases_on_rollback(world, sql_log):
    w = world
    plan = native.native_party_plan(w.uid, w.cid, w.cid)
    # Hold the last physical key, so earlier physical acquisitions are real.
    key = max(plan.requests, key=lambda request: locks.advisory_key(request.key)).key
    async with w.factory() as owner, w.factory() as db, w.factory() as observer:
        owner_pid, waiter_pid = await pid(owner, "owner"), await pid(db, "waiter")
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        task = asyncio.create_task(native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty"))
        try:
            await blocked(observer, waiter_pid, owner_pid, key, mode=next(r.mode for r in plan.requests if r.key == key))
            granted = await observer.scalar(text("SELECT count(*) FROM pg_locks WHERE pid=:p "
                "AND locktype='advisory' AND granted"), {"p": waiter_pid})
            assert granted > 0
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(locks.ScopedLockError):
                await locks.acquire_scoped_locks_async(db, plan)
            await db.rollback()
            count = await observer.scalar(text("SELECT count(*) FROM pg_locks WHERE pid=:p AND locktype='advisory'"), {"p": waiter_pid})
            assert count == 0
            await owner.rollback()
            prepared = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
            native.require_native_party_write(db, prepared)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("root", ["contact_put", "contact_delete"])
async def test_legacy_foreign_company_contact_keeps_actual_native_id_plus_cp_admission(world, root):
    w = world
    async with w.factory() as seed:
        (await seed.get(CounterpartyContact, w.contact)).company_id = w.foreign
        await seed.commit()
    async with w.factory() as db:
        result = await invoke(w, db, root)
        if root == "contact_put":
            assert result["id"] == str(w.contact)
            assert (await db.get(CounterpartyContact, w.contact)).company_id == w.foreign
        else:
            await db.flush()
            assert await db.get(CounterpartyContact, w.contact) is None


@pytest.mark.parametrize("root", ["contact_put", "contact_delete"])
async def test_legacy_contact_actual_company_b_wait_precedes_any_rows_or_dml(world, sql_log, root):
    w = world
    async with w.factory() as seed:
        (await seed.get(CounterpartyContact, w.contact)).company_id = w.foreign
        await seed.commit()
    key = locks.CompanyKey(w.foreign)
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running(w, lambda db: invoke(w, db, root), retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid, key, mode=S)
            no_writes(statements(sql_log))
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in statements(sql_log))
            await owner.rollback()
            await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("root", ["contact_put", "contact_delete"])
@pytest.mark.parametrize("change, expected", [("company", 409), ("parent", 409), ("vanish", 404)])
async def test_contact_original_pointer_is_checked_after_all_b_waits_without_late_keys(world, sql_log, root, change, expected):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running(w, lambda db: invoke(w, db, root), retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid, key, mode=S)
            row = await owner.get(CounterpartyContact, w.contact)
            if change == "company":
                row.company_id = w.foreign
            elif change == "parent":
                row.counterparty_id = w.free_cp
            else:
                await owner.delete(row)
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == expected
            no_writes(statements(sql_log))
            # Changed keys were not appended after discovering the new pointer.
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in statements(sql_log))


@pytest.mark.parametrize("root", ["contact_put", "contact_delete"])
async def test_nonmatching_cp_child_remains_404_before_child_lock_or_extra_company_plan(world, sql_log, root):
    w = world
    async with w.factory() as db:
        await pid(db, "waiter")
        with pytest.raises(HTTPException) as failure:
            await invoke(w, db, root, target=w.free_cp)
        assert (failure.value.status_code, failure.value.detail) == (404, "Контакт не найден")
        no_writes(statements(sql_log))
        assert not any("pg_advisory" in s or "FOR UPDATE" in s for s in statements(sql_log))


async def test_actor_home_pointer_change_during_b_wait_aborts_whole_root_without_foreign_keys(world, sql_log):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running(w, lambda db: invoke(w, db, "cp_patch"), retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid, key)
            (await owner.get(User, w.uid)).company_id = w.foreign
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            no_writes(statements(sql_log))
            assert not any("FOR SHARE" in s or "FOR UPDATE" in s for s in statements(sql_log))


async def test_actual_verified_grants_are_fresh_after_final_membership_row_wait(world, sql_log):
    w = world
    async with w.factory() as seed:
        member = await seed.get(UserCompany, (w.uid, w.cid))
        member.business_grants = [{"role": "network_merchandiser", "scope_type": "network", "scope_id": w.slug}]
        await seed.commit()
    async with w.factory() as owner, w.factory() as observer:
        owner_pid = await pid(owner, "owner")
        member = (await owner.execute(select(UserCompany).where(UserCompany.user_id == w.uid,
            UserCompany.company_id == w.cid).with_for_update())).scalar_one()
        body = {"company_id": str(w.cid), "name": "Synthetic verified", "inn": "7723456789",
                "kpp": "123456789", "lifecycleStatus": "verified"}
        async with running(w, lambda db: invoke(w, db, "cp_create", body=body), retain=True) as (info, task):
            await blocked(observer, info["pid"], owner_pid)
            member.business_grants = []
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 403
            assert failure.value.detail == "Карточку контрагента подтверждает товаровед сети или суперадминистратор"
            no_writes(statements(sql_log))


@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_external_actual_connection_completion_invalidates_native_capability(world, ending):
    w = world
    async with w.factory() as db:
        prepared = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        connection = await db.connection()
        await getattr(connection, ending)()
        with pytest.raises(locks.ScopedLockError):
            native.require_native_party_write(db, prepared)
        await db.rollback()
        fresh = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        native.require_native_party_write(db, fresh)


async def test_actual_savepoint_poison_and_reentry_require_fresh_whole_root(world):
    w = world
    async with w.factory() as db:
        prepared = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        with pytest.raises(locks.ScopedLockError):
            await native.prepare_native_party_write(db, w.actor, w.cid, entity="organization")
        async with db.begin_nested():
            with pytest.raises(locks.ScopedLockError):
                native.require_native_party_write(db, prepared)
        with pytest.raises(locks.ScopedLockError):
            native.require_native_party_write(db, prepared)
        await db.rollback()
        fresh = await native.prepare_native_party_write(db, w.actor, w.cid, entity="counterparty")
        native.require_native_party_write(db, fresh)


async def test_actual_contact_delete_cascades_existing_location_assignment_without_mutating_cp(world):
    w = world
    opaque_id = "opaque:synthetic:" + uuid4().hex
    async with w.factory() as seed:
        seed.add(ServiceLocation(id=opaque_id, company_id=w.cid, code=opaque_id,
            name="Synthetic assigned point", type="other", source_bindings=[]))
        await seed.flush()
        seed.add(LocationContact(company_id=w.cid, location_id=opaque_id, contact_id=w.contact,
            responsibility="Synthetic responsibility"))
        await seed.commit()
    async with w.factory() as db:
        await invoke(w, db, "contact_delete")
        await db.flush()
        assert await db.get(CounterpartyContact, w.contact) is None
        assert await db.get(LocationContact, (opaque_id, w.contact)) is None
        assert (await db.get(Counterparty, w.cp)).name == "Synthetic CP"
