"""Authored synthetic real-PG route/adapter schedules; NOTRUN, even collection.

Guard precedes app/SQLAlchemy imports. Repository conftest runs earlier and can
DROP schemas using TEST_DATABASE_URL: ROOT MUST isolate collection first. These
four synthetic tables retain the relevant parent FKs, not the full app schema;
audit/notifications/response decoration are substituted, never scoped locks.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from time import monotonic
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest

_URL = os.environ.get("NATIVE_USER_ROLE_LOCKS_PG_URL", "")
_APPROVED = os.environ.get("NATIVE_USER_ROLE_LOCKS_PG_ROOT_APPROVED_URL", "")
_TARGET = urlsplit(_URL)
if not (_URL and _URL == _APPROVED
        and os.environ.get("NATIVE_USER_ROLE_LOCKS_PG_APPROVAL") == "ROOT-approved-synthetic-native-user-role-v1"
        and _TARGET.scheme == "postgresql+psycopg" and _TARGET.hostname
        and _TARGET.path.startswith("/native_user_role_synthetic_")
        and len(_TARGET.path) > len("/native_user_role_synthetic_")
        and not _TARGET.query and not _TARGET.fragment):
    pytest.skip("Separate ROOT-approved synthetic native target required", allow_module_level=True)

# No app/driver imports above this guard; it cannot protect parent conftest.
import pytest_asyncio
from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table, UniqueConstraint, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema
from app.auth import native_claims_context
from app.models import Company, CompanyRole, User, UserCompany
from app.routers import roles_router, users_router
from app.services import native_user_role_locks as native
from app.services import contract_write_locks as locks

C, A, U, V, R1, R2 = (UUID(int=i) for i in range(100, 106))
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
CLAIMS = {"sub": str(A), "tv": 0}


@pytest_asyncio.fixture
async def store(monkeypatch):
    schema = "native_role_" + uuid4().hex
    engine = create_async_engine(_URL, pool_size=6, max_overflow=0,
                                 isolation_level="READ COMMITTED")
    scoped = engine.execution_options(schema_translate_map={None: schema})
    # Exact four ORM column sets; unrelated FK targets and production triggers
    # are intentionally absent. Keep FKs that motivate the tested row order.
    metadata = MetaData()
    for model in (Company, User, CompanyRole, UserCompany):
        Table(model.__tablename__, metadata, *[
            Column(c.name, c.type, primary_key=c.primary_key,
                   nullable=False if c.primary_key else True)
            for c in model.__table__.columns
        ])
    metadata.tables["users"].append_constraint(UniqueConstraint("email"))
    for table_name, columns, targets in (
        ("users", ["company_id"], ["companies.id"]),
        ("company_roles", ["company_id"], ["companies.id"]),
        ("user_companies", ["company_id"], ["companies.id"]),
        ("user_companies", ["user_id"], ["users.id"]),
        ("user_companies", ["role_id"], ["company_roles.id"]),
    ):
        metadata.tables[table_name].append_constraint(ForeignKeyConstraint(
            columns, targets, ondelete=("SET NULL" if columns == ["role_id"] else
                                       "CASCADE" if table_name == "user_companies" else None)))
    async with engine.begin() as conn:
        await conn.execute(CreateSchema(schema))
    try:
        async with scoped.begin() as conn:
            await conn.run_sync(metadata.create_all)
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        async with factory() as db:
            db.add(Company(id=C, slug="synthetic", name="Synthetic", profile_id="energy"))
            await db.flush()
            db.add_all([User(id=uid, company_id=C, email=f"{uid.int}@example.invalid",
                             password_hash="synthetic", name=str(uid.int), role="user",
                             token_version=0, is_superadmin=False)
                        for uid in (A, U, V)])
            db.add_all([CompanyRole(id=rid, company_id=C, name=str(rid.int), modules=[], is_system=False)
                        for rid in (R1, R2)])
            await db.flush()
            db.add_all([UserCompany(user_id=A, company_id=C, role="admin"),
                        UserCompany(user_id=U, company_id=C, role="user", role_id=R1),
                        UserCompany(user_id=V, company_id=C, role="user", role_id=R2)])
            await db.commit()
        audits = []
        async def audit(db, **kw):
            audits.append(kw)  # excludes unrelated notification/task machinery
        async def response(user, db, scope_cid=None):
            return user.id
        async def leave(*args):
            pass
        monkeypatch.setattr(users_router, "log_audit", audit)
        monkeypatch.setattr(roles_router, "log_audit", audit)
        monkeypatch.setattr(users_router, "_resp", response)
        monkeypatch.setattr(users_router, "_leave_company_chats", leave)
        yield SimpleNamespace(engine=scoped, factory=factory, audits=audits)
    finally:
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def pid(db):
    return (await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def wait_blocked(observer, waiter_pid, owner_pid, key):
    """Observe both the actual blocker and this exact ungranted advisory key."""
    ns, value = locks.advisory_key(key)
    deadline = monotonic() + 15
    while monotonic() < deadline:
        blockers = (await observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid})).scalar_one()
        ungranted = (await observer.execute(text("""
            SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory'
            AND classid=:ns AND objid=:value AND objsubid=2 AND NOT granted
        """), {"pid": waiter_pid, "ns": ns, "value": value & 0xFFFFFFFF})).scalar_one()
        if owner_pid in blockers and ungranted:
            return
        # Query awaits yield to the contender; time is only a harness deadline.
    raise AssertionError("Expected actual pg_locks/pg_blocking_pids wait absent")


@asynccontextmanager
async def running_route(store, invoke):
    ready, pids = asyncio.Event(), {}
    async def worker():
        async with store.factory() as db:
            pids["waiter"] = await pid(db)
            actor = await db.get(User, A)
            ready.set()
            try:
                with native_claims_context(CLAIMS, None):
                    value = await invoke(db, actor)
                # Same commit owner as get_db for routes without local commit.
                await db.commit()
                return value
            except BaseException:
                await db.rollback()
                raise
    task = asyncio.create_task(worker())
    await asyncio.wait_for(ready.wait(), 10)
    try:
        yield task, pids["waiter"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_actual_role_move_waits_for_old_and_new_parents(store):
    for guarded in (R1, R2):
        # Restore pointer for the second schedule.
        async with store.factory() as setup:
            (await setup.get(UserCompany, (U, C))).role_id = R1
            await setup.commit()
        async with store.factory() as owner, store.factory() as observer:
            owner_pid = await pid(owner)
            locks_plan = locks.LockPlan((locks.LockRequest(locks.RoleKey(C, guarded), X),))
            await locks.acquire_scoped_locks_async(owner, locks_plan)
            payload = SimpleNamespace(company_id=str(C), mode="role", role_id=str(R2), modules=None)
            async with running_route(store, lambda db, actor: users_router.set_member_access(
                    str(U), payload, db, actor)) as (task, waiter_pid):
                try:
                    await wait_blocked(observer, waiter_pid, owner_pid, locks.RoleKey(C, guarded))
                finally:
                    await owner.rollback()
                await asyncio.wait_for(task, 10)
        async with store.factory() as verify:
            assert (await verify.get(UserCompany, (U, C))).role_id == R2


@pytest.mark.asyncio
async def test_absent_grant_uses_same_member_guard(store):
    async with store.factory() as setup:
        await setup.delete(await setup.get(UserCompany, (U, C)))
        await setup.commit()
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.MemberKey(C, U), X),)))
        payload = SimpleNamespace(company_id=str(C), role="user")
        async with running_route(store, lambda db, actor: users_router.grant_company(
                str(U), payload, db, actor)) as (task, waiter_pid):
            try:
                await wait_blocked(observer, waiter_pid, owner_pid, locks.MemberKey(C, U))
            finally:
                await owner.rollback()
            await asyncio.wait_for(task, 10)
    async with store.factory() as verify:
        assert await verify.get(UserCompany, (U, C)) is not None


@pytest.mark.asyncio
async def test_actual_account_reset_takes_user_exclusive(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.UserKey(U), S),)))
        async with running_route(store, lambda db, actor: users_router.reset_sessions(
                str(U), str(C), db, actor)) as (task, waiter_pid):
            try:
                await wait_blocked(observer, waiter_pid, owner_pid, locks.UserKey(U))
            finally:
                await owner.rollback()
            assert await asyncio.wait_for(task, 10) == {"ok": True}
    async with store.factory() as verify:
        assert (await verify.get(User, U)).token_version == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["member_parent", "actor_admin", "actor_session"])
async def test_wait_revalidates_pointer_acl_and_session(store, change):
    # Both sides enter the actual adapter; observe the exact declared conflict.
    key = (locks.UserKey(A) if change == "actor_session" else
           locks.MemberKey(C, U if change == "member_parent" else A))
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        actor = await owner.get(User, A)
        with native_claims_context(CLAIMS, None):
            await native.prepare_native_write(owner, actor, company_id=C,
                target_id=U if change == "member_parent" else A,
                account=change == "actor_session",
                new_role_id=R2 if change == "member_parent" else None)
        payload = SimpleNamespace(company_id=str(C), modules=[])
        async with running_route(store, lambda db, actor: users_router.set_member_modules(
                str(U), payload, db, actor)) as (task, waiter_pid):
            try:
                await wait_blocked(observer, waiter_pid, owner_pid, key)
                if change == "member_parent":
                    (await owner.get(UserCompany, (U, C))).role_id = R2
                elif change == "actor_admin":
                    (await owner.get(UserCompany, (A, C))).role = "user"
                else:
                    (await owner.get(User, A)).token_version = 1
                await owner.commit()
                with pytest.raises(Exception) as exc:
                    await asyncio.wait_for(task, 10)
                assert exc.value.status_code == (401 if change == "actor_session" else 409)
            finally:
                await owner.rollback()
    assert not store.audits
    async with store.factory() as verify:
        assert (await verify.get(UserCompany, (U, C))).modules is None


@pytest.mark.asyncio
async def test_remove_has_user_row_before_member_delete_and_no_late_user_upgrade(store):
    statements = []
    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(store.engine.sync_engine, "before_cursor_execute", trace)
    try:
        async with running_route(store, lambda db, actor: users_router.remove_user(
                str(U), str(C), db, actor)) as (task, unused):
            await asyncio.wait_for(task, 10)
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", trace)
    member_delete = next(i for i, sql in enumerate(statements) if sql.startswith("delete from") and "user_companies" in sql)
    user_delete = next(i for i, sql in enumerate(statements) if sql.startswith("delete from") and '.users' in sql)
    assert any(".users" in sql and "for update" in sql for sql in statements[:member_delete])
    assert not any("pg_advisory" in sql for sql in statements[member_delete:])
    assert member_delete < user_delete
    async with store.factory() as verify:
        assert await verify.get(User, U) is None


@pytest.mark.asyncio
async def test_delete_role_holders_wait_behind_role_exclusive(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.RoleKey(C, R1), S),)))
        async with running_route(store, lambda db, actor: roles_router.delete_role(
                str(R1), str(C), db, actor)) as (task, waiter_pid):
            try:
                await wait_blocked(observer, waiter_pid, owner_pid, locks.RoleKey(C, R1))
                assert (await observer.get(UserCompany, (U, C))).role_id == R1
            finally:
                await owner.rollback()
            await asyncio.wait_for(task, 10)
    async with store.factory() as verify:
        assert (await verify.get(UserCompany, (U, C))).role_id is None
        assert await verify.get(CompanyRole, R1) is None
    assert store.audits[-1]["details"] == {"members_reset": 1}


@pytest.mark.asyncio
async def test_preserved_admin_malformed_role_and_system_role_branches(store):
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            payload = SimpleNamespace(company_id=str(C), mode="role", role_id="malformed", modules=[])
            await users_router.set_member_access(str(A), payload, db, actor)
        assert (await db.get(UserCompany, (A, C))).role_id is None
    async with store.factory() as db:
        (await db.get(CompanyRole, R1)).is_system = True
        await db.commit()
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None), pytest.raises(Exception) as exc:
            await roles_router.delete_role(str(R1), str(C), db, actor)
        assert exc.value.status_code == 403
        await db.rollback()


@pytest.mark.asyncio
async def test_update_global_name_empty_value_and_role_scope_error(store):
    async with store.factory() as db:
        actor = await db.get(User, A)
        payload = SimpleNamespace(company_id=str(C), name="", role=None, position=None,
            party_type=None, organization_id=None, department_id=None, app_roles=None)
        with native_claims_context(CLAIMS, None):
            await users_router.update_user(str(U), payload, db, actor)
        assert (await db.get(User, U)).name == ""
        assert db.in_transaction()  # original route leaves commit to get_db
        await db.rollback()
    async with store.factory() as db:
        actor = await db.get(User, A)
        payload.company_id = None
        with pytest.raises(Exception) as exc:
            await users_router.update_user(str(U), payload, db, actor)
        assert exc.value.status_code == 403  # native admin is not global superadmin


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_create_user_full_plan_precedes_user_or_membership_flush(store, monkeypatch, existing):
    from app.routers import invitations_router
    async def close_invites(*args):
        return 0
    monkeypatch.setattr(invitations_router, "close_invites_for", close_invites)
    # Password hashing and invite storage are outside the four-table harness.
    monkeypatch.setattr(users_router, "hash_password", lambda value: "synthetic-hash")
    if existing:
        async with store.factory() as setup:
            await setup.delete(await setup.get(UserCompany, (U, C)))
            await setup.commit()
    email = f"{U.int}@example.invalid" if existing else "new@example.invalid"
    plans, acquired = [], []
    real_acquire = native.acquire_scoped_locks_async
    async def capture(db, plan):
        assert not db.new and not db.dirty and not db.deleted
        assert db.autoflush is False
        plans.append(plan)
        cap = await real_acquire(db, plan)  # never a fake lock receipt
        acquired.append(cap)
        return cap
    monkeypatch.setattr(native, "acquire_scoped_locks_async", capture)
    async with store.factory() as db:
        def before_flush(session, context, instances):
            assert len(acquired) == 1
        event.listen(db.sync_session, "before_flush", before_flush)
        try:
            actor = await db.get(User, A)
            payload = SimpleNamespace(company_id=str(C), party_type="internal", organization_id=None,
                email=email, password="synthetic", name="Created", role="user", position=None)
            with native_claims_context(CLAIMS, None):
                uid = await users_router.create_user(payload, db, actor)
            assert len(plans) == 1 and db.in_transaction()
            wanted = {(r.key, r.mode) for r in plans[0].requests}
            assert (locks.UserKey(uid), S if existing else X) in wanted
            assert (locks.MemberKey(C, uid), X) in wanted
            assert await db.get(UserCompany, (uid, C)) is not None
            await db.rollback()
        finally:
            event.remove(db.sync_session, "before_flush", before_flush)


@pytest.mark.asyncio
async def test_cross_company_legacy_role_pointer_and_holder_fail_closed(store):
    other = UUID(int=999)
    async with store.factory() as db:
        db.add(Company(id=other, slug="other", name="Other", profile_id="energy"))
        await db.flush()
        db.add(UserCompany(user_id=V, company_id=other, role="user", role_id=R1))
        await db.commit()
    # Physical single FK allows this legacy inconsistency. Role delete must not
    # silently cascade outside the planned company, including visit-filter cases.
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None), pytest.raises(Exception) as exc:
            await roles_router.delete_role(str(R1), str(C), db, actor)
        assert exc.value.status_code == 409
        await db.rollback()
        assert await db.get(CompanyRole, R1) is not None
        assert (await db.get(UserCompany, (V, other))).role_id == R1
    # The same actual-owner mismatch must fail before planning a member write.
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None), pytest.raises(Exception) as exc:
            await native.prepare_native_write(db, actor, company_id=other, target_id=V)
        assert exc.value.status_code == 409
        await db.rollback()
    assert not store.audits


@pytest.mark.asyncio
async def test_role_update_preserves_omitted_chat_scope_and_audit_commit(store):
    async with store.factory() as db:
        (await db.get(CompanyRole, R1)).chat_scope = "support"
        await db.commit()
    async with store.factory() as db:
        actor = await db.get(User, A)
        payload = SimpleNamespace(company_id=str(C), name="Renamed", modules=[], chat_scope=None,
                                  model_fields_set={"company_id", "name", "modules"})
        with native_claims_context(CLAIMS, None):
            result = await roles_router.update_role(str(R1), payload, db, actor)
        assert result.chat_scope == "support"
        assert store.audits[-1]["action"] == "role.update"
    async with store.factory() as verify:
        assert (await verify.get(CompanyRole, R1)).name == "Renamed"


@pytest.mark.asyncio
@pytest.mark.parametrize("member_exists,superadmin,raw_role,code", [
    (False, False, "malformed", 404),
    (True, True, "malformed", 403),
    (True, False, str(UUID(int=99999)), 400),
])
async def test_access_legacy_error_order(store, member_exists, superadmin, raw_role, code):
    async with store.factory() as db:
        if not member_exists:
            await db.delete(await db.get(UserCompany, (U, C)))
        (await db.get(User, U)).is_superadmin = superadmin
        await db.commit()
    async with store.factory() as db:
        actor = await db.get(User, A)
        payload = SimpleNamespace(company_id=str(C), mode="role", role_id=raw_role, modules=[])
        with native_claims_context(CLAIMS, None), pytest.raises(Exception) as exc:
            await users_router.set_member_access(str(U), payload, db, actor)
        assert exc.value.status_code == code
        await db.rollback()
    assert not store.audits



@pytest.mark.asyncio
async def test_access_rechecks_target_superadmin_between_preflight_and_discovery(store, monkeypatch):
    real_prepare = users_router.prepare_native_write
    calls = []
    async def promote_then_prepare(db, actor, **kwargs):
        # Deterministic preflight/discovery gap, without replacing the real
        # adapter or lock acquisition. Before/after discovery both see True.
        async with store.factory() as other:
            (await other.get(User, U)).is_superadmin = True
            await other.commit()
        calls.append("promoted")
        return await real_prepare(db, actor, **kwargs)
    monkeypatch.setattr(users_router, "prepare_native_write", promote_then_prepare)
    async with store.factory() as db:
        actor = await db.get(User, A)
        payload = SimpleNamespace(company_id=str(C), mode="custom", role_id=None, modules=[])
        with native_claims_context(CLAIMS, None), pytest.raises(Exception) as exc:
            await users_router.set_member_access(str(U), payload, db, actor)
        assert exc.value.status_code == 403 and calls == ["promoted"]
        await db.rollback()
    async with store.factory() as verify:
        member = await verify.get(UserCompany, (U, C))
        assert member.role_id == R1 and member.modules is None
    assert not store.audits
