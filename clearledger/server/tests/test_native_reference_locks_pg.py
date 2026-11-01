"""AUTHORED / NOTRUN: actual nine native roots/use case + frozen helper on PG.

ROOT owns schema provisioning and the isolated preimport composition. Ordinary
pytest is unsafe: repository conftest can import app and DROP schemas before
this guard. No runner, schema DDL, installation, URL fallback or execution GO.
All rows below are synthetic; teardown of the disposable DB belongs to ROOT.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_REFERENCE_R1_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("NATIVE_REFERENCE_R1_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("NATIVE_REFERENCE_R1_APPROVAL") == "ROOT-reviewed-synthetic-native-r1-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password
    and _TARGET.path == "/api_native_reference_r1_test_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed native R1 preimport composition required")

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import (
    App, AuditEvent, Company, CompanyRole, Contract, ContractDimension, ContractLink,
    ContractLocation, Counterparty, Organization, PartnerSpace, ServiceLocation, User, UserCompany,
)
from app.routers import references_router as router
from app.schemas import ContractCreate, ContractDimensionUpdate, ContractScopeUpdate, ContractUpdate
from app.scope import set_request_organization, set_request_scope
from app.services import contract_write_locks as locks
from app.services import native_reference_locks as native
from app.services import location_commands
from app.services.native_contract_commands import create_native_contract
from app.services.reference_identity import lock_manual_creation

pytestmark = pytest.mark.asyncio(loop_scope="session")
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
ROOTS = ("create", "update", "delete", "scope", "link_location", "unlink_location",
         "add_link", "delete_link", "dimension")
OWNED = {"update", "delete", "add_link", "delete_link"}


@pytest_asyncio.fixture(loop_scope="session")
async def world():
    engine = create_async_engine(_URL, pool_size=8, max_overflow=0, isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex[:16]
    async with factory() as db:
        company = Company(id=uuid4(), name="Synthetic native R1", slug=f"nr1-{token}", profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic foreign R1", slug=f"nf1-{token}", profile_id="energy")
        db.add_all([company, other])
        await db.flush()
        actor = User(id=uuid4(), company_id=company.id, email=f"{token}@native-r1.invalid",
                     name="Synthetic ordinary native member", password_hash="synthetic-noncredential",
                     is_superadmin=False)
        outsider = User(id=uuid4(), company_id=other.id, email=f"o-{token}@native-r1.invalid",
                        name="Synthetic outsider", password_hash="synthetic-noncredential", is_superadmin=False)
        role = CompanyRole(id=uuid4(), company_id=company.id, name=f"Synthetic role {token}")
        foreign_role = CompanyRole(id=uuid4(), company_id=other.id, name=f"Synthetic foreign role {token}")
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic retained CP", aliases=[])
        free_cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic unused CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Synthetic retained org", inn="", prefix="S")
        free_org = Organization(id=uuid4(), company_id=company.id, name="Synthetic unused org", inn="", prefix="F")
        loc = ServiceLocation(id=f"opaque:{token}", company_id=company.id, code=token,
                              name="Synthetic point", type="other", source_bindings=[])
        partner = PartnerSpace(id=uuid4(), company_id=company.id, role="vendor", code=f"p-{token}",
                               name="Synthetic visit provider", base_url="https://synthetic.invalid", is_active=True)
        db.add_all([actor, outsider, role, foreign_role, cp, free_cp, org, free_org, loc, partner])
        await db.flush()
        db.add(UserCompany(user_id=actor.id, company_id=company.id, role="user", role_id=role.id))
        contract = Contract(id=uuid4(), company_id=company.id, counterparty_id=cp.id,
                            organization_id=org.id, number="Synthetic retained original", date="2026-01-02",
                            type="Synthetic", scope_type="unassigned")
        linked = Contract(id=uuid4(), company_id=company.id, counterparty_id=cp.id,
                          organization_id=org.id, number="Synthetic linked", date="2026-01-03", type="Synthetic")
        db.add_all([contract, linked])
        await db.flush()
        link = ContractLink(id=uuid4(), company_id=company.id, contract_id=linked.id,
                            app_code=f"nr1-{token}", project_ref="", created_by=actor.id)
        db.add(link)
        active, inactive = f"nr1-active-{token}", f"nr1-inactive-{token}"
        await db.execute(text("INSERT INTO contract_types(code,label,is_active) VALUES "
                              "(:a,'Synthetic active',true),(:i,'Synthetic inactive',false)"),
                         {"a": active, "i": inactive})
        # Existing app/catalog shape; code is a code, not an App UUID.
        app_code = f"nr1-{token}"
        db.add(App(id=uuid4(), code=app_code, name="Synthetic native R1",
                   base_url="https://synthetic.invalid", is_active=True))
        await db.commit()
        w = SimpleNamespace(engine=engine, factory=factory, cid=company.id, foreign=other.id,
            slug=company.slug, actor=actor, uid=actor.id, outsider=outsider, role=role.id,
            foreign_role=foreign_role.id, cp=cp.id, free_cp=free_cp.id, org=org.id, free_org=free_org.id,
            loc=loc.id, partner=partner.id, contract=contract.id, linked=linked.id, link=link.id,
            app_code=app_code, active=active, inactive=inactive)
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
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((conn.info.get("native_r1_label"), statement, parameters))
    event.listen(world.engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", record)


def payload(w, **changes):
    return {"company_id": str(w.cid), "creationKey": str(uuid4()), "number": "Synthetic new",
            "date": "2026-01-04", "type": "Synthetic", "counterpartyId": str(w.free_cp),
            "organizationId": str(w.free_org), **changes}


def target_id(w, root):
    return w.linked if root == "delete_link" else w.contract


async def invoke(w, db, root, *, actor=None, body=None):
    actor = w.actor if actor is None else actor
    uid = str(target_id(w, root))
    if root == "direct":
        return await create_native_contract(db, ContractCreate(**(body or payload(w))), actor)
    if root == "create":
        return await router.create_contract(ContractCreate(**(body or payload(w))), db, actor)
    if root == "update":
        return await router.update_contract(uid, ContractUpdate(**(body or {"comment": "Synthetic changed"})), db, actor)
    if root == "delete":
        return await router.delete_contract(uid, db, actor)
    if root == "scope":
        return await router.set_contract_scope(uid, ContractScopeUpdate(**(body or {
            "scopeType": "locations", "locationIds": [w.loc, w.loc, "synthetic-missing"]})), db, actor)
    if root == "link_location":
        return await router.link_contract_location(uid, w.loc, db, actor)
    if root == "unlink_location":
        return await router.unlink_contract_location(uid, w.loc, db, actor)
    if root == "add_link":
        return await router.add_contract_link(uid, body or {"app": w.app_code}, db, actor)
    if root == "delete_link":
        return await router.delete_contract_link(uid, str(w.link), db, actor)
    if root == "dimension":
        return await router.set_contract_dimension(uid, "synthetic", ContractDimensionUpdate(
            refs=[" A ", "A", "", "B"]), db, actor)
    raise AssertionError(root)


async def pid(db, label=None):
    conn = await db.connection()
    conn.sync_connection.info["native_r1_label"] = label
    return await db.scalar(text("SELECT pg_backend_pid()"))


def caller_sql(log, label="waiter"):
    return [sql for owner, sql, parameters in log if owner == label]


def assert_no_dml(statements):
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)


async def blocked(observer, waiter, owner, key=None):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:p)"), {"p": waiter})
        if owner in blockers:
            if key is not None:
                ns, value = locks.advisory_key(key)
                row = (await observer.execute(text("SELECT mode,granted FROM pg_locks WHERE pid=:p "
                    "AND locktype='advisory' AND classid=:n AND objid=:k AND objsubid=2"),
                    {"p": waiter, "n": ns, "k": value & 0xFFFFFFFF})).one_or_none()
                if row != ("ShareLock", False):
                    await asyncio.sleep(.01)
                    continue
            return
        await asyncio.sleep(.01)
    raise AssertionError("No actual pg_blocking_pids / pending advisory ShareLock evidence")


@asynccontextmanager
async def running(w, call, *, retained=None):
    ready, details = asyncio.Event(), {}
    async def waiter():
        async with w.factory() as db:
            details["db"] = db
            details["pid"] = await pid(db, "waiter")
            if retained is not None:
                details["retained"] = await retained(db)
            details["root"] = db.sync_session.get_transaction()
            ready.set()
            try:
                value = await call(db)
                assert db.sync_session.get_transaction() is details["root"]
                return value
            except BaseException:
                assert db.sync_session.get_transaction() is details["root"]
                raise
    task = asyncio.create_task(waiter())
    try:
        await asyncio.wait_for(ready.wait(), 10)
        yield details, task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("root", ROOTS + ("direct",))
@pytest.mark.parametrize("axis", ["company", "user", "member", "reference"])
async def test_actual_callers_wait_for_complete_shared_b_plan_before_rows_or_dml(world, sql_log, root, axis):
    w = world
    key = {"company": locks.CompanyKey(w.cid), "user": locks.UserKey(w.uid),
           "member": locks.MemberKey(w.cid, w.uid), "reference": locks.RefCompositeKey(w.cid)}[axis]
    async with w.factory() as owner, w.factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root)) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            statements = caller_sql(sql_log)
            assert_no_dml(statements)
            assert not any("FOR SHARE" in sql or "FOR UPDATE" in sql for sql in statements)
            assert not details["db"].new and not details["db"].dirty and not details["db"].deleted
            await owner.rollback()
            await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("root", ROOTS)
@pytest.mark.parametrize("barrier", ["counterparty", "contract"])
async def test_legacy_barriers_precede_all_canonical_rows(world, sql_log, root, barrier):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        await lock_manual_creation(owner, w.cid, barrier)
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root)) as (details, task):
            await blocked(observer, details["pid"], owner_pid)
            statements = caller_sql(sql_log)
            assert_no_dml(statements)
            assert not any("FOR SHARE" in sql or "FOR UPDATE" in sql for sql in statements)
            await owner.rollback()
            await asyncio.wait_for(task, 10)
            statements = caller_sql(sql_log)
            legacy = [i for i, sql in enumerate(statements)
                      if "pg_advisory_xact_lock(" in sql and "CAST(" not in sql]
            rows = [i for i, sql in enumerate(statements) if "FOR SHARE" in sql or "FOR UPDATE" in sql]
            assert len(legacy) == 2 and rows and max(legacy) < min(rows)
            params = [parameters for label, sql, parameters in sql_log
                      if label == "waiter" and "pg_advisory_xact_lock(" in sql and "CAST(" not in sql]
            expected = [int.from_bytes(hashlib.sha256(json.dumps([
                "reference-create-v1", str(w.cid), entity]).encode()).digest()[:8], "big", signed=True)
                for entity in ("counterparty", "contract")]
            assert [p[0] for p in params] == expected


@pytest.mark.parametrize("root", ROOTS + ("direct",))
async def test_membership_removed_during_b_wait_keeps_historical_403_or_404(world, sql_log, root):
    w = world
    async def retain(db):
        return (await db.get(User, w.uid), await db.get(UserCompany, (w.uid, w.cid)),
                await db.get(Contract, target_id(w, root)))
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root), retained=retain) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            await owner.delete(await owner.get(UserCompany, (w.uid, w.cid)))
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == (404 if root in OWNED else 403)
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("axis", ["member-row", "user-row", "company-row"])
async def test_canonical_authority_row_wait_reloads_membership_scope(world, sql_log, axis):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        if axis == "member-row":
            await owner.execute(select(UserCompany).where(UserCompany.user_id == w.uid,
                UserCompany.company_id == w.cid).with_for_update())
        elif axis == "user-row":
            await owner.execute(select(User).where(User.id == w.uid).with_for_update())
        else:
            await owner.execute(select(Company).where(Company.id == w.cid).with_for_update())
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, "update")) as (details, task):
            await blocked(observer, details["pid"], owner_pid)
            member = await owner.get(UserCompany, (w.uid, w.cid))
            member.object_scope = ["synthetic-other-point"]
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 404
            assert_no_dml(caller_sql(sql_log))


async def test_absent_membership_has_logical_guard_even_for_superadmin(world, sql_log):
    w = world
    async with w.factory() as seed:
        user = await seed.get(User, w.uid)
        user.is_superadmin = True
        w.actor = user
        await seed.delete(await seed.get(UserCompany, (w.uid, w.cid)))
        await seed.commit()
    async with w.factory() as owner, w.factory() as observer:
        key = locks.MemberKey(w.cid, w.uid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, "direct")) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            await owner.rollback()
            row = await asyncio.wait_for(task, 10)
            assert row.creation_actor_id == w.uid


async def test_named_role_is_unused_even_with_foreign_pointer_and_exclusive_role_owner(world):
    w = world
    async with w.factory() as seed:
        member = await seed.get(UserCompany, (w.uid, w.cid))
        member.role_id = w.foreign_role
        await seed.commit()
    async with w.factory() as owner, w.factory() as db:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.RoleKey(w.foreign, w.foreign_role), X),)))
        row = await asyncio.wait_for(invoke(w, db, "direct"), 5)
        assert isinstance(row, Contract) and row.creation_actor_id == w.uid
        assert not w.actor.is_superadmin
        await db.rollback()


@pytest.mark.parametrize("pointer", ["user-company", "contract-type"])
async def test_changed_parent_requires_new_root_instead_of_late_plan_extension(world, sql_log, pointer):
    w = world
    call = (lambda db: invoke(w, db, "direct")) if pointer == "user-company" else (
        lambda db: invoke(w, db, "update", body={"typeCode": w.active}))
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, call) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            if pointer == "user-company":
                (await owner.get(User, w.uid)).company_id = w.foreign
            else:
                (await owner.get(Contract, w.contract)).type_code = w.inactive
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("entity", ["counterparty", "organization", "location"])
async def test_clean_strong_retained_references_deleted_during_b_wait_are_not_authority(world, sql_log, entity):
    w = world
    model, uid = {"counterparty": (Counterparty, w.free_cp), "organization": (Organization, w.free_org),
                  "location": (ServiceLocation, w.loc)}[entity]
    async def retained(db):
        row = await db.get(model, uid)
        assert row is not None
        return row
    root = "link_location" if entity == "location" else "direct"
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root), retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            await owner.delete(await owner.get(model, uid))
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == (404 if entity == "location" else 400)
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("root", ["update", "link_location", "delete_link"])
async def test_current_contract_and_child_rows_are_reloaded_after_all_waits(world, sql_log, root):
    w = world
    async def retained(db):
        return (await db.get(Contract, target_id(w, root)), await db.get(ContractLink, w.link))
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root), retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            c = await owner.get(Contract, target_id(w, root))
            c.number = "Synthetic current after wait"
            if root == "link_location":
                c.scope_type = "company"
            elif root == "delete_link":
                (await owner.get(ContractLink, w.link)).contract_id = w.contract
            await owner.commit()
            if root == "update":
                response = await asyncio.wait_for(task, 10)
                assert response.number == "Synthetic current after wait"
                assert response.comment == "Synthetic changed"
            else:
                with pytest.raises(HTTPException) as failure:
                    await asyncio.wait_for(task, 10)
                assert failure.value.status_code == (409 if root == "link_location" else 404)
                assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("root", ["scope", "link_location"])
async def test_readonly_opaque_location_share_precedes_contract_row_without_location_set(world, sql_log, monkeypatch, root):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Readonly contract validation must not enter LocationSet mutation API")
    monkeypatch.setattr(location_commands, "acquire_location_set", forbidden)
    monkeypatch.setattr(location_commands, "locked_visible", forbidden)
    async with world.factory() as db:
        await pid(db, "waiter")
        result = await invoke(world, db, root)
        assert result.scopeType == "locations"
        statements = caller_sql(sql_log)
        loc = next(i for i, sql in enumerate(statements) if "service_locations" in sql and "FOR SHARE" in sql)
        contract = next(i for i, sql in enumerate(statements) if "contracts" in sql and "FOR UPDATE" in sql)
        assert loc < contract
        ids = (await db.execute(select(ContractLocation.location_id).where(
            ContractLocation.contract_id == world.contract))).scalars().all()
        assert ids == [world.loc]


async def test_native_defaults_hash_falsy_values_and_caller_rollback_are_preserved(world):
    w = world
    body = payload(w, amountLimit=0, amountInclVat=False, signed=False,
                   paymentTermDays=0, isStateContract=False, signerOur="")
    model = ContractCreate(**body)
    # Literal external input/default oracle, independent of model_dump.
    golden = {
        "number": "Synthetic new", "date": "2026-01-04", "type": "Synthetic",
        "counterpartyId": str(w.free_cp), "organizationId": str(w.free_org),
        "typeCode": None, "amountLimit": 0.0, "kind": None, "currency": None,
        "validUntil": None, "vatRate": None, "amountInclVat": False,
        "settlementKind": None, "comment": None, "basis": None, "isClosed": False,
        "scopeType": "unassigned", "signed": False, "signedAt": None,
        "paymentTermDays": 0, "isStateContract": False, "igk": None,
        "responsibleId": None, "signerOur": "", "signerOurPosition": None,
        "signerCp": None, "signerCpPosition": None, "signerCpBasis": None,
    }
    expected_hash = hashlib.sha256(json.dumps(
        golden, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    async with w.factory() as db:
        row = await create_native_contract(db, model, w.actor)
        assert isinstance(row, Contract) and row.creation_request_hash == expected_hash
        assert row.creation_actor_id == w.uid and row.scope_type == "unassigned"
        assert (row.amount_limit, row.amount_incl_vat, row.signed, row.payment_term_days,
                row.is_state_contract, row.signer_our, row.manual_overrides) == (0, False, False, 0, False, None, [])
        identity = row.id
        assert db.in_transaction()
        await db.rollback()
    async with w.factory() as observer:
        assert await observer.get(Contract, identity) is None


async def test_inactive_historical_replay_precedes_active_type_check(world):
    w = world
    body = payload(w, typeCode=w.active)
    async with w.factory() as db:
        first = await invoke(w, db, "create", body=body)
        await db.commit()
    async with w.factory() as peer:
        await peer.execute(text("UPDATE contract_types SET is_active=false WHERE code=:c"), {"c": w.active})
        await peer.commit()
    async with w.factory() as db:
        replay = await invoke(w, db, "create", body={**body, "company_id": w.slug})
        assert replay.model_dump() == first.model_dump()
        await db.rollback()


@pytest.mark.parametrize("case,expected", [("unknown-company", 400), ("outsider", 403),
    ("bad-party", 400), ("bad-type-before-responsible", 422), ("bad-responsible", 400)])
async def test_legacy_create_error_order_before_dml(world, sql_log, case, expected):
    w = world
    changes = {"unknown-company": {"company_id": "synthetic-absent"}, "outsider": {},
        "bad-party": {"counterpartyId": str(uuid4()), "typeCode": w.inactive},
        "bad-type-before-responsible": {"typeCode": w.inactive, "responsibleId": "bad"},
        "bad-responsible": {"responsibleId": "bad"}}[case]
    async with w.factory() as db:
        await pid(db, "waiter")
        with pytest.raises(HTTPException) as failure:
            await invoke(w, db, "direct", actor=w.outsider if case == "outsider" else None,
                         body=payload(w, **changes))
        assert failure.value.status_code == expected
        assert_no_dml(caller_sql(sql_log))


async def test_duplicate_and_creation_hash_conflict_keep_precedence_over_type_error(world):
    w = world
    body = payload(w)
    async with w.factory() as db:
        await invoke(w, db, "direct", body=body)
        await db.commit()
    for second in ({**body, "typeCode": w.inactive}, {**body, "creationKey": str(uuid4()), "typeCode": w.inactive}):
        async with w.factory() as db:
            with pytest.raises(HTTPException) as failure:
                await invoke(w, db, "direct", body=second)
            assert failure.value.status_code == 409
            await db.rollback()


@pytest.mark.parametrize("body,detail", [({"app": "synthetic-absent"}, "Неизвестное приложение"),
    ({"projectRef": "site:synthetic-absent"}, "Проект не найден в пространстве")])
async def test_app_and_project_codes_preserve_existing_422(world, sql_log, body, detail):
    async with world.factory() as db:
        await pid(db, "waiter")
        with pytest.raises(HTTPException) as failure:
            await invoke(world, db, "add_link", body={"app": world.app_code, **body})
        assert failure.value.status_code == 422 and detail in failure.value.detail
        assert_no_dml(caller_sql(sql_log))


async def test_claims_present_session_revocation_is_fresh_but_none_claims_need_no_admin(world, sql_log):
    w = world
    claims = {"sub": str(w.uid), "tv": 0}
    async def retained(db):
        return await db.get(User, w.uid)
    async def call(db):
        with native_claims_context(claims, None):
            return await invoke(w, db, "direct")
    async with w.factory() as owner, w.factory() as observer:
        key = locks.UserKey(w.uid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, call, retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            (await owner.get(User, w.uid)).token_version = 1
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 401
            assert_no_dml(caller_sql(sql_log))
    async with w.factory() as db:
        with native_claims_context(None, None):
            assert isinstance(await invoke(w, db, "direct"), Contract)


async def test_visit_revocation_during_wait_uses_current_retained_partner(world, sql_log):
    w = world
    claims = {"sub": str(w.uid), "tv": 0, "scp": "visit", "cid": str(w.cid), "pvs": str(w.partner)}
    async def retained(db):
        return await db.get(PartnerSpace, w.partner)
    async def call(db):
        with native_claims_context(claims, w.cid):
            return await invoke(w, db, "direct")
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, call, retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            (await owner.get(PartnerSpace, w.partner)).is_active = False
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 401
            assert_no_dml(caller_sql(sql_log))


async def test_capabilities_are_root_session_and_company_bound_with_no_reentry(world):
    w = world
    async with w.factory() as db, w.factory() as foreign:
        prepared = await native.prepare_native_reference_write(db, w.actor, w.cid)
        native.require_native_reference_write(db, prepared)
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(foreign, prepared)
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(db, replace(prepared, company_id=w.foreign))
        with pytest.raises(locks.ScopedLockError):
            await native.prepare_native_reference_write(db, w.actor, w.cid)
        await db.rollback()
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(db, prepared)


async def test_partial_actual_acquisition_poison_prevents_same_root_retry(world, sql_log):
    w = world
    acquired = []
    def fail_second(conn, cursor, statement, parameters, context, executemany):
        if conn.info.get("native_r1_label") == "waiter" and "pg_advisory_xact_lock_shared" in statement:
            acquired.append(statement)
            if len(acquired) == 2:
                raise RuntimeError("Synthetic interruption after first actual scoped lock")
    event.listen(w.engine.sync_engine, "before_cursor_execute", fail_second)
    try:
        async with w.factory() as db:
            await pid(db, "waiter")
            root = db.sync_session.get_transaction()
            with pytest.raises(RuntimeError, match="Synthetic interruption"):
                await native.prepare_native_reference_write(db, w.actor, w.cid)
            with pytest.raises(locks.ScopedLockError):
                await native.prepare_native_reference_write(db, w.actor, w.cid)
            assert db.sync_session.get_transaction() is root
            assert len(acquired) == 2
            assert_no_dml(caller_sql(sql_log))
            await db.rollback()
    finally:
        event.remove(w.engine.sync_engine, "before_cursor_execute", fail_second)


async def test_caller_commit_response_dimensions_and_audit_stay_owned_by_caller(world):
    w = world
    commits = []
    def committed(conn):
        commits.append(conn)
    event.listen(w.engine.sync_engine, "commit", committed)
    try:
        async with w.factory() as db:
            before = await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid))
            response = await invoke(w, db, "dimension")
            assert response.dimensions == {"synthetic": ["A", "B"]}
            assert not commits
            after = await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid))
            assert before == after
            await db.commit()
        assert len(commits) == 1
        async with w.factory() as observer:
            values = (await observer.execute(select(ContractDimension.dim_ref).where(
                ContractDimension.contract_id == w.contract).order_by(ContractDimension.dim_ref))).scalars().all()
            assert values == ["A", "B"]
    finally:
        event.remove(w.engine.sync_engine, "commit", committed)


async def test_slug_rebound_during_wait_cannot_admit_an_unplanned_company(world, sql_log):
    w = world
    async with w.factory() as seed:
        actor = await seed.get(User, w.uid)
        actor.is_superadmin = True
        await seed.commit()
        w.actor = actor
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, "direct", body=payload(
                w, company_id=w.slug))) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            (await owner.get(Company, w.cid)).slug = "old-" + w.slug
            await owner.flush()
            (await owner.get(Company, w.foreign)).slug = w.slug
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            assert_no_dml(caller_sql(sql_log))
            row_locks = [parameters for label, sql, parameters in sql_log if label == "waiter"
                         and ("FOR SHARE" in sql or "FOR UPDATE" in sql)]
            assert all(str(w.foreign) not in str(parameters) for parameters in row_locks)


async def test_missing_planned_company_is_not_authority_even_with_retained_instance(world, sql_log):
    w = world
    async with w.factory() as seed:
        empty = Company(id=uuid4(), name="Synthetic disposable parent", slug="empty-" + uuid4().hex[:16],
                        profile_id="energy")
        seed.add(empty)
        await seed.commit()
        cid = empty.id
    async def retained(db):
        return await db.get(Company, cid)
    async with w.factory() as owner, w.factory() as observer:
        key = locks.CompanyKey(cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: native.prepare_native_reference_write(
                db, w.actor, cid), retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            await owner.delete(await owner.get(Company, cid))
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("entity", ["counterparty", "organization"])
async def test_retained_party_reparented_during_wait_keeps_native_400(world, sql_log, entity):
    w = world
    model, identity = (Counterparty, w.free_cp) if entity == "counterparty" else (Organization, w.free_org)
    async def retained(db):
        return await db.get(model, identity)
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, "direct"), retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            (await owner.get(model, identity)).company_id = w.foreign
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 400
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("side", ["old", "new"])
async def test_type_update_discovers_both_exact_catalog_codes_before_any_row_lock(world, sql_log, side):
    w = world
    async with w.factory() as seed:
        (await seed.get(Contract, w.contract)).type_code = w.active
        await seed.commit()
    code = w.active if side == "old" else w.inactive
    async with w.factory() as owner, w.factory() as observer:
        key = locks.TypeCatalogKey(code)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, "update", body={
                "typeCode": w.inactive})) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            statements = caller_sql(sql_log)
            assert_no_dml(statements)
            assert not any("FOR SHARE" in sql or "FOR UPDATE" in sql for sql in statements)
            await owner.rollback()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 422
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("code", [None, ""])
async def test_type_clear_keeps_null_and_empty_historical_meaning(world, code):
    w = world
    async with w.factory() as seed:
        (await seed.get(Contract, w.contract)).type_code = w.active
        await seed.commit()
    async with w.factory() as db:
        response = await invoke(w, db, "update", body={"typeCode": code})
        assert response.typeCode is None
        assert "type_code" in (await db.get(Contract, w.contract)).manual_overrides
        await db.rollback()


@pytest.mark.parametrize("root", ["update", "scope", "link_location"])
async def test_fresh_target_pointer_after_final_row_wait_aborts_without_dml(world, sql_log, root):
    w = world
    async with w.factory() as owner, w.factory() as observer:
        await owner.execute(select(Contract).where(Contract.id == w.contract).with_for_update())
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root)) as (details, task):
            await blocked(observer, details["pid"], owner_pid)
            (await owner.get(Contract, w.contract)).organization_id = w.free_org
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            assert_no_dml(caller_sql(sql_log))


async def test_visit_is_rechecked_after_location_row_wait_without_presence_or_commit(world, sql_log):
    w = world
    claims = {"sub": str(w.uid), "tv": 0, "scp": "visit", "cid": str(w.cid), "pvs": str(w.partner)}
    async def retained(db):
        return (await db.get(User, w.uid), await db.get(UserCompany, (w.uid, w.cid)),
                await db.get(PartnerSpace, w.partner), await db.get(ServiceLocation, w.loc))
    async def call(db):
        with native_claims_context(claims, w.cid):
            return await invoke(w, db, "link_location")
    async with w.factory() as owner, w.factory() as observer:
        await owner.execute(select(ServiceLocation).where(ServiceLocation.id == w.loc).with_for_update())
        owner_pid = await pid(owner, "owner")
        async with running(w, call, retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid)
            assert any("service_locations" in sql and "FOR SHARE" in sql for sql in caller_sql(sql_log))
            (await owner.get(PartnerSpace, w.partner)).is_active = False
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 401
            assert_no_dml(caller_sql(sql_log))


async def test_visit_removed_retained_member_is_401_before_root_membership_admission(world, sql_log):
    w = world
    claims = {"sub": str(w.uid), "tv": 0, "scp": "visit", "cid": str(w.cid), "pvs": str(w.partner)}
    async def retained(db):
        return await db.get(UserCompany, (w.uid, w.cid))
    async def call(db):
        with native_claims_context(claims, w.cid):
            return await invoke(w, db, "direct")
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, call, retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            await owner.delete(await owner.get(UserCompany, (w.uid, w.cid)))
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 401
            assert_no_dml(caller_sql(sql_log))


@pytest.mark.parametrize("root", ROOTS[1:])
async def test_changed_contract_company_never_admits_foreign_company_after_b_wait(world, sql_log, root):
    w = world
    async def retained(db):
        return await db.get(Contract, target_id(w, root))
    async with w.factory() as owner, w.factory() as observer:
        key = locks.RefCompositeKey(w.cid)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner, "owner")
        async with running(w, lambda db: invoke(w, db, root), retained=retained) as (details, task):
            await blocked(observer, details["pid"], owner_pid, key)
            (await owner.get(Contract, target_id(w, root))).company_id = w.foreign
            await owner.commit()
            with pytest.raises(HTTPException) as failure:
                await asyncio.wait_for(task, 10)
            assert failure.value.status_code == 409
            assert_no_dml(caller_sql(sql_log))
            memberships = [parameters for label, sql, parameters in sql_log
                           if label == "waiter" and "FROM user_companies" in sql]
            assert all(str(w.foreign) not in str(parameters) for parameters in memberships)


async def test_require_uses_immutable_actor_identity_without_expired_attribute_io(world, sql_log):
    w = world
    async with w.factory() as db:
        await pid(db, "waiter")
        prepared = await native.prepare_native_reference_write(db, w.actor, w.cid)
        db.expire(prepared.actor)
        before = len(caller_sql(sql_log))
        native.require_native_reference_write(db, prepared)
        assert len(caller_sql(sql_log)) == before
        with pytest.raises(locks.ScopedLockError):
            native.require_native_reference_write(db, replace(prepared, actor_id=w.outsider.id))
        assert len(caller_sql(sql_log)) == before
        await db.rollback()
