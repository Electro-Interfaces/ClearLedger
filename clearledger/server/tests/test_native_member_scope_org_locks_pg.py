"""Определения синтетической PG-приёмки P1; NOTRUN, даже collection.

Нужны отдельная одобренная БД, изолированный conftest и согласованное решение
общей UUID-зависимости. Здесь нет локальных casts, driver patches или skips.
RefX-peer проверяет только будущий барьер; отдельные BOTHORDERS определения
вызывают actual legacy delete_organization и Source8 update_organization.
Полные FK/trigger и child-owner проверки будущего удаления остаются NOTRUN.
"""
import asyncio
from contextlib import asynccontextmanager
import os
import json
from time import monotonic
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from pathlib import Path

# До app-imports требуется явно одобренный совместный Source8/P1 состав.
# Проверка не защищает от parent conftest: его изоляция обязательна отдельно.
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if (os.environ.get("NATIVE_MEMBER_SCOPE_SOURCE_COMPOSITION") != "approved-p1-source8"
        or not (_SOURCE_ROOT / "app/services/native_party_locks.py").is_file()):
    raise RuntimeError("NOTRUN: требуется одобренный совместный P1/Source8 source composition до app-imports")

import pytest
import pytest_asyncio
from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table, UniqueConstraint, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.auth import native_claims_context
from app.models import AuditEvent, Company, CompanyRole, Organization, PartnerSpace, ServiceLocation, User, UserCompany
from app.routers import users_router
from app.routers import references_router as refs
from app.schemas import MemberScopeUpdate, OrganizationUpdate
from app.scope import set_request_organization, set_request_scope
from app.services import contract_write_locks as locks
from app.services import native_user_role_locks as native

C, OTHER, HOME, U, A, ROLE, ORG, FOREIGN, VISIT = (UUID(int=i) for i in range(101, 110))
CLAIMS = {"sub": str(A), "tv": 0}
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


@pytest_asyncio.fixture
async def store(monkeypatch):
    url = os.environ.get("NATIVE_MEMBER_SCOPE_PG_URL", "")
    parsed = urlsplit(url)
    approved = os.environ.get("NATIVE_MEMBER_SCOPE_PG_APPROVED_URL", "")
    if not (url and url == approved and parsed.scheme == "postgresql+asyncpg"
            and parsed.hostname and parsed.path.startswith("/native_member_scope_synthetic_")
            and len(parsed.path) > len("/native_member_scope_synthetic_")
            and not parsed.query and not parsed.fragment
            and os.environ.get("NATIVE_MEMBER_SCOPE_PG_APPROVAL") == "approved-isolated-p1"):
        pytest.fail("NOTRUN: требуется отдельная одобренная synthetic БД и изолированный conftest")
    schema = "member_scope_" + uuid4().hex
    engine = create_async_engine(url, pool_size=6, max_overflow=0, isolation_level="READ COMMITTED")
    scoped = engine.execution_options(schema_translate_map={None: schema})
    metadata = MetaData()
    # Полные наборы ORM-колонок, но только относящиеся к P1 физические FK.
    # Это не проверка полной рабочей схемы, триггеров и всех владельцев Org.
    models = (Company, User, CompanyRole, UserCompany, Organization, ServiceLocation, PartnerSpace, AuditEvent)
    for model in models:
        Table(model.__tablename__, metadata, *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=not c.primary_key)
            for c in model.__table__.columns])
    metadata.tables["companies"].append_constraint(UniqueConstraint("slug"))
    metadata.tables["users"].append_constraint(UniqueConstraint("email"))
    for table, column, target, ondelete in (
        ("users", "company_id", "companies.id", None),
        ("company_roles", "company_id", "companies.id", "CASCADE"),
        ("organizations", "company_id", "companies.id", None),
        ("user_companies", "company_id", "companies.id", "CASCADE"),
        ("user_companies", "user_id", "users.id", "CASCADE"),
        ("user_companies", "role_id", "company_roles.id", "SET NULL"),
        ("user_companies", "own_organization_id", "organizations.id", "SET NULL"),
        ("service_locations", "company_id", "companies.id", None),
    ):
        metadata.tables[table].append_constraint(ForeignKeyConstraint([column], [target], ondelete=ondelete))
    async with engine.begin() as conn:
        await conn.execute(CreateSchema(schema))
    statements, notifications = [], []
    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(scoped.sync_engine, "before_cursor_execute", trace)
    try:
        async with scoped.begin() as conn:
            await conn.run_sync(metadata.create_all)
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        async with factory() as db:
            db.add_all([Company(id=cid, slug=slug, name=slug, profile_id="energy")
                        for cid, slug in ((C, "synthetic"), (OTHER, "other"), (HOME, "home"))])
            await db.flush()
            db.add_all([User(id=uid, company_id=HOME, email=f"{uid.int}@example.invalid",
                             password_hash="synthetic", name=str(uid.int), role="user",
                             token_version=0, is_superadmin=False) for uid in (A, U)])
            db.add(CompanyRole(id=ROLE, company_id=C, name="synthetic-role", modules=[], is_system=False))
            db.add_all([Organization(id=oid, company_id=cid, name="Synthetic", inn="0000000000")
                        for oid, cid in ((ORG, C), (FOREIGN, OTHER))])
            db.add_all([ServiceLocation(id=key, company_id=cid, name=key)
                        for key, cid in (("own-object", C), ("foreign-object", OTHER))])
            db.add(PartnerSpace(id=VISIT, company_id=C, role="vendor", is_active=True))
            await db.flush()
            db.add_all([UserCompany(user_id=A, company_id=C, role="admin"),
                        UserCompany(user_id=U, company_id=C, role="user", role_id=ROLE,
                                    own_organization_id=ORG)])
            await db.commit()
        from app.services import notify
        monkeypatch.setattr(notify, "dispatch_async", lambda *args, **kwargs: notifications.append((args, kwargs)))
        statements.clear()
        yield SimpleNamespace(factory=factory, engine=scoped, statements=statements, notifications=notifications)
    finally:
        event.remove(scoped.sync_engine, "before_cursor_execute", trace)
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def pid(db):
    return (await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def blocked(observer, waiter, owner, key=None):
    """Ожидание подтверждается PostgreSQL, таймаут только ограничивает тест."""
    deadline = monotonic() + 15
    while monotonic() < deadline:
        blockers = (await observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})).scalar_one()
        if owner not in blockers:
            continue
        if key is not None:
            ns, value = locks.advisory_key(key)
            count = (await observer.execute(text("""
                SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                AND classid=:ns AND objid=:value AND objsubid=2 AND NOT granted
            """), {"pid": waiter, "ns": ns, "value": value & 0xffffffff})).scalar_one()
            if not count:
                continue
        return
    raise AssertionError("Не наблюдалось ожидаемое блокирование PostgreSQL")


@asynccontextmanager
async def running(store, invoke, claims=CLAIMS):
    ready, state = asyncio.Event(), {}
    async def worker():
        async with store.factory() as db:
            state["pid"] = await pid(db)
            actor = await db.get(User, A)
            # Сохраняем реальные retained instances до ожиданий.
            state["retained_member"] = await db.get(UserCompany, (U, C))
            state["retained_org"] = await db.get(Organization, ORG)
            state["retained_company"] = await db.get(Company, C)
            ready.set()
            try:
                with native_claims_context(claims, None):
                    return await invoke(db, actor)
            finally:
                await db.rollback()
    task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(ready.wait(), 15)
        yield task, state
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def invoke_scope(db, actor, **changes):
    return await users_router.set_member_scope(str(U), MemberScopeUpdate(
        company_id="synthetic", **changes), db, actor)


@pytest.mark.asyncio
@pytest.mark.parametrize("self_target", [False, True])
async def test_actual_helper_complete_B_precedes_all_rows_and_route_dml(store, self_target):
    async with store.factory() as db:
        actor = await db.get(User, A)
        store.statements.clear()
        with native_claims_context(CLAIMS, None):
            prepared = await native.prepare_native_write(db, actor, company_id=C,
                target_id=A if self_target else U, scope_org=True,
                scope_company_ref="synthetic", scope_organization_id=str(ORG))
        assert locks.LockRequest(locks.RefCompositeKey(C), S) in prepared.plan.requests
        assert any(r.key == locks.CompanyKey(HOME) for r in prepared.plan.requests)
        locks.require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        statements = store.statements
        final_advisory = max(i for i, sql in enumerate(statements) if "pg_advisory" in sql)
        rows = [i for i, sql in enumerate(statements) if "for share" in sql or "for update" in sql]
        assert rows and final_advisory < min(rows)
        assert not any(sql.startswith(("insert ", "update ", "delete ")) for sql in statements)
        await db.rollback()


@pytest.mark.asyncio
async def test_future_RefX_first_blocks_actual_producer_before_any_row(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(locks.RefCompositeKey(C), X),)))
        store.statements.clear()
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(ORG))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid, locks.RefCompositeKey(C))
                assert not any("for update" in sql or "for share" in sql for sql in store.statements)
            finally:
                await owner.rollback()
            response = await asyncio.wait_for(task, 15)
            assert response.own_organization_id == str(ORG)


@pytest.mark.asyncio
async def test_actual_producer_RefS_blocks_future_RefX_peer_until_rollback(store):
    async with store.factory() as producer, store.factory() as observer:
        actor = await producer.get(User, A)
        producer_pid = await pid(producer)
        with native_claims_context(CLAIMS, None):
            await native.prepare_native_write(producer, actor, company_id=C, target_id=U,
                scope_org=True, scope_company_ref="synthetic", scope_organization_id=str(ORG))
        async def peer(db, actor):
            return await locks.acquire_scoped_locks_async(db, locks.LockPlan((
                locks.LockRequest(locks.RefCompositeKey(C), X),)))
        async with running(store, peer) as (task, state):
            try:
                await blocked(observer, state["pid"], producer_pid, locks.RefCompositeKey(C))
            finally:
                await producer.rollback()
            await asyncio.wait_for(task, 15)
    # Peer не имеет OrgDELETE body и не доказывает closure удаления.


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ("old_org", 409), ("role", 409), ("admin", 409), ("home", 409),
    ("slug", 409), ("session", 401), ("superadmin", 409),
])
async def test_initial_wait_rejects_discovery_or_authority_drift(store, change, expected):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(locks.RefCompositeKey(C), X),)))
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(ORG))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid, locks.RefCompositeKey(C))
                if change == "old_org":
                    (await owner.get(UserCompany, (U, C))).own_organization_id = FOREIGN
                elif change == "role":
                    (await owner.get(UserCompany, (U, C))).role_id = None
                elif change == "admin":
                    (await owner.get(UserCompany, (A, C))).role = "user"
                elif change == "home":
                    (await owner.get(User, U)).company_id = OTHER
                elif change == "slug":
                    (await owner.get(Company, C)).slug = "renamed"
                elif change == "session":
                    (await owner.get(User, A)).token_version = 1
                else:
                    (await owner.get(User, A)).is_superadmin = True
                await owner.commit()
                with pytest.raises(Exception) as error:
                    await asyncio.wait_for(task, 15)
                assert error.value.status_code == expected
            finally:
                await owner.rollback()
    assert not store.notifications
    async with store.factory() as verify:
        assert (await verify.get(UserCompany, (U, C))).object_scope is None
        assert (await verify.execute(select(AuditEvent))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [("old_org", 409), ("role", 409), ("visit", 401)])
async def test_last_legacy_member_wait_refreshes_retained_instances_and_visit(store, change, expected):
    claims = dict(CLAIMS, scp="visit", cid=str(C), pvs=str(VISIT))
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        member = (await owner.execute(select(UserCompany).where(
            UserCompany.user_id == U, UserCompany.company_id == C).with_for_update())).scalar_one()
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(ORG)), claims) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid)
                if change == "old_org":
                    member.own_organization_id = None
                elif change == "role":
                    member.role_id = None
                else:
                    (await owner.get(PartnerSpace, VISIT)).is_active = False
                await owner.commit()
                with pytest.raises(Exception) as error:
                    await asyncio.wait_for(task, 15)
                assert error.value.status_code == expected
            finally:
                await owner.rollback()
    assert not store.notifications


@pytest.mark.asyncio
@pytest.mark.parametrize("old", [ORG, FOREIGN])
@pytest.mark.parametrize("raw,expected", [(None, "retain"), ("omitted", "retain"),
    ("", None), ("   ", None), ("invalid", None), (str(UUID(int=999)), None),
    (str(FOREIGN), None), (str(ORG), ORG)])
async def test_actual_route_org_null_intent_objects_audit_and_response(store, old, raw, expected):
    async with store.factory() as setup:
        (await setup.get(UserCompany, (U, C))).own_organization_id = old
        await setup.commit()
    changes = {"object_scope": ["own-object", "foreign-object", "opaque-missing"]}
    if raw != "omitted":
        changes["own_organization_id"] = raw
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            response = await invoke_scope(db, actor, **changes)
        effective = old if expected == "retain" else expected
        assert response.object_scope == ["own-object"]
        assert response.own_organization_id == (str(effective) if effective else None)
    async with store.factory() as verify:
        member = await verify.get(UserCompany, (U, C))
        assert member.own_organization_id == effective
        audits = (await verify.execute(select(AuditEvent))).scalars().all()
        assert len(audits) == 1 and audits[0].action == "member.scope"
        assert audits[0].details == (f"{U.int}@example.invalid · "
            + json.dumps({"objects": 1, "организация": str(effective) if effective else "все юрлица"}, ensure_ascii=False))
        assert len(store.notifications) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("objects", [None, []])
async def test_null_and_empty_object_scope_remain_all(store, objects):
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            response = await invoke_scope(db, actor, object_scope=objects)
        assert response.object_scope is None


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [None, dict(CLAIMS, scp="unknown"), dict(CLAIMS, tv=1)])
async def test_actual_native_identity_is_not_programmatic_claims_bypass(store, claims):
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(claims, None), pytest.raises(Exception) as error:
            await invoke_scope(db, actor, own_organization_id="")
        assert error.value.status_code == 401
        await db.rollback()
    assert not store.notifications


@pytest.mark.asyncio
async def test_cancel_during_B_retains_no_capability_and_caller_rolls_back(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(locks.RefCompositeKey(C), X),)))
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id="")) as (task, state):
            await blocked(observer, state["pid"], owner_pid, locks.RefCompositeKey(C))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await owner.rollback()
    async with store.factory() as verify:
        assert (await verify.get(UserCompany, (U, C))).own_organization_id == ORG
        assert (await verify.execute(select(AuditEvent))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [("home", 409), ("session", 401), ("superadmin", 409)])
async def test_legacy_actor_user_wait_rechecks_home_session_and_superadmin(store, change, expected):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        actor = (await owner.execute(select(User).where(User.id == A).with_for_update())).scalar_one()
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(ORG))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid)
                if change == "home":
                    actor.company_id = OTHER
                elif change == "session":
                    actor.token_version = 1
                else:
                    actor.is_superadmin = True
                await owner.commit()
                with pytest.raises(Exception) as error:
                    await asyncio.wait_for(task, 15)
                assert error.value.status_code == expected
            finally:
                await owner.rollback()
    assert not store.notifications


@pytest.mark.asyncio
@pytest.mark.parametrize("missing,expected", [("member", 404), ("claims", 401), ("admin", 403)])
async def test_known_authority_and_absent_member_errors_do_not_enter_org_row_phase(store, missing, expected):
    async with store.factory() as setup:
        if missing == "member":
            await setup.delete(await setup.get(UserCompany, (U, C)))
        elif missing == "admin":
            (await setup.get(UserCompany, (A, C))).role = "user"
        await setup.commit()
    async with store.factory() as db:
        actor = await db.get(User, A)
        store.statements.clear()
        with native_claims_context(None if missing == "claims" else CLAIMS, None), pytest.raises(Exception) as error:
            await invoke_scope(db, actor, own_organization_id=str(ORG))
        assert error.value.status_code == expected
        assert not any("organizations" in sql and "for share" in sql for sql in store.statements)
        await db.rollback()


@pytest.mark.asyncio
async def test_actual_scope_self_actor_preserves_admin_and_response(store):
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            response = await users_router.set_member_scope(str(A), MemberScopeUpdate(
                company_id="synthetic", own_organization_id=str(ORG)), db, actor)
        assert response.id == str(A) and response.role == "admin"
        assert response.own_organization_id == str(ORG)


@pytest.mark.asyncio
async def test_org_row_wait_precedes_every_member_row_and_prevents_legacy_edge_inversion(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await owner.execute(select(Organization).where(Organization.id == ORG).with_for_update())
        store.statements.clear()
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(ORG))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid)
                assert not any("user_companies" in sql and ("for share" in sql or "for update" in sql)
                               for sql in store.statements)
            finally:
                await owner.rollback()
            await asyncio.wait_for(task, 15)
    row_sql = [sql for sql in store.statements if "for share" in sql or "for update" in sql]
    org = next(i for i, sql in enumerate(row_sql) if "organizations" in sql and "for share" in sql)
    member = next(i for i, sql in enumerate(row_sql) if "user_companies" in sql)
    assert org < member


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["absent_to_own", "foreign_to_own"])
async def test_unjoined_candidate_appears_after_org_phase_aborts_without_late_lock_or_dml(store, kind):
    # Это намеренно не участвующий в B synthetic SQL producer; не Source8 composer.
    candidate = UUID(int=999) if kind == "absent_to_own" else FOREIGN
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await owner.execute(select(UserCompany).where(
            UserCompany.user_id == U, UserCompany.company_id == C).with_for_update())
        store.statements.clear()
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(candidate))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid)
                if kind == "absent_to_own":
                    owner.add(Organization(id=candidate, company_id=C, name="Synthetic new", inn="0000000000"))
                else:
                    (await owner.get(Organization, candidate)).company_id = C
                await owner.commit()
                with pytest.raises(Exception) as error:
                    await asyncio.wait_for(task, 15)
                assert error.value.status_code == 409
            finally:
                await owner.rollback()
    first_member_row = next(i for i, sql in enumerate(store.statements)
                            if "user_companies" in sql and ("for update" in sql or "for share" in sql))
    assert not any("organizations" in sql and ("for share" in sql or "for update" in sql)
                   for sql in store.statements[first_member_row + 1:])
    assert not any(sql.startswith("update ") and "user_companies" in sql for sql in store.statements)
    assert not store.notifications
    async with store.factory() as verify:
        assert (await verify.get(UserCompany, (U, C))).own_organization_id == ORG
        assert (await verify.execute(select(AuditEvent))).scalars().all() == []


@pytest.mark.asyncio
async def test_disappearing_proposed_parent_still_clears_when_old_pointer_unchanged(store):
    candidate = UUID(int=111)
    async with store.factory() as setup:
        setup.add(Organization(id=candidate, company_id=C, name="Synthetic proposed", inn="0000000000"))
        await setup.commit()
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(locks.RefCompositeKey(C), X),)))
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id=str(candidate))) as (task, state):
            try:
                await blocked(observer, state["pid"], owner_pid, locks.RefCompositeKey(C))
                # Только synthetic parent DML, не реализация отсутствующего OrgDELETE.
                await owner.delete(await owner.get(Organization, candidate))
                await owner.commit()
                response = await asyncio.wait_for(task, 15)
                assert response.own_organization_id is None
            finally:
                await owner.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["rollback", "commit"])
async def test_completed_root_cannot_reuse_scope_receipt_or_expire_retained_objects(store, completion):
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            prepared = await native.prepare_native_write(db, actor, company_id=C, target_id=U,
                scope_org=True, scope_company_ref="synthetic", scope_organization_id=str(ORG))
        await getattr(db, completion)()
        store.statements.clear()
        with pytest.raises(locks.ScopedLockError):
            await native._refresh_native_scope(db, prepared)
        assert store.statements == []


@pytest.mark.asyncio
async def test_cancelled_partial_B_is_released_for_new_whole_root(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(locks.RefCompositeKey(C), X),)))
        async with running(store, lambda db, actor: invoke_scope(db, actor, own_organization_id="")) as (task, state):
            await blocked(observer, state["pid"], owner_pid, locks.RefCompositeKey(C))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await owner.rollback()
    async with store.factory() as db:
        actor = await db.get(User, A)
        with native_claims_context(CLAIMS, None):
            prepared = await asyncio.wait_for(native.prepare_native_write(
                db, actor, company_id=C, target_id=U, scope_org=True,
                scope_company_ref="synthetic", scope_organization_id=str(ORG)), 15)
        locks.require_scoped_locks(db.sync_session, prepared.capability, prepared.plan.requests)
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_state", ["transient", "detached", "expired"])
async def test_direct_caller_actor_state_preserves_raw_identity_and_uses_fresh_db_actor(store, actor_state):
    async with store.factory() as db:
        if actor_state == "transient":
            actor = User(id=A, company_id=OTHER, email="stale@example.invalid", is_superadmin=True)
        elif actor_state == "detached":
            async with store.factory() as reader:
                actor = await reader.get(User, A)
                reader.expunge(actor)
        else:
            actor = await db.get(User, A)
            db.expire(actor)
        with native_claims_context(CLAIMS, None):
            prepared = await native.prepare_native_write(db, actor, company_id=C, target_id=U,
                scope_org=True, scope_company_ref="synthetic", scope_organization_id=str(ORG))
        assert prepared.actor.id == A
        assert prepared.actor.email == f"{A.int}@example.invalid"
        assert not prepared.actor.is_superadmin
        assert prepared.actor.company_id == HOME
        assert prepared.scope_organization_id == ORG
        await db.rollback()


class CommitGateSession(AsyncSession):
    """Пауза caller перед настоящим commit; SQL и завершение не подменяются."""
    def __init__(self, *args, stage_flush=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit_entered = asyncio.Event()
        self.commit_release = asyncio.Event()
        self.stage_flush = stage_flush

    async def commit(self):
        # Для legacy DELETE останавливаем реальный commit после его flush-фазы.
        # Это только инструмент наблюдения: выполняются actual delete и FK SET NULL.
        if self.stage_flush:
            await self.flush()
        self.commit_entered.set()
        await self.commit_release.wait()
        return await super().commit()


@asynccontextmanager
async def held_actual_call(store, invoke, *, actor_id=A, caller_commit=False, stage_flush=False):
    """Запустить actual route и удержать его живую транзакцию у commit-границы."""
    ready, state = asyncio.Event(), {}
    async def worker():
        async with CommitGateSession(bind=store.engine, expire_on_commit=False, stage_flush=stage_flush) as db:
            state.update(db=db, pid=await pid(db))
            actor = await db.get(User, actor_id)
            ready.set()
            try:
                set_request_organization(None)
                set_request_scope(None)
                with native_claims_context({"sub": str(actor_id), "tv": 0}, None):
                    result = await invoke(db, actor)
                    if caller_commit:
                        await db.commit()
                return result
            finally:
                await db.rollback()
    task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(ready.wait(), 15)
        await asyncio.wait_for(state["db"].commit_entered.wait(), 15)
        assert not task.done(), "Actual caller должен держать незавершённый root"
        yield task, state
    finally:
        if "db" in state:
            state["db"].commit_release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def actual_contender(store, invoke, *, actor_id=A, caller_commit=False):
    """Второй actual caller с собственной SQL-сессией и реальным commit."""
    ready, state = asyncio.Event(), {}
    async def worker():
        async with store.factory() as db:
            state["pid"] = await pid(db)
            actor = await db.get(User, actor_id)
            ready.set()
            try:
                set_request_organization(None)
                set_request_scope(None)
                with native_claims_context({"sub": str(actor_id), "tv": 0}, None):
                    result = await invoke(db, actor)
                    if caller_commit:
                        await db.commit()
                return result
            finally:
                await db.rollback()
    task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(ready.wait(), 15)
        yield task, state
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("old_ref", [True, False])
async def test_actual_legacy_orgdelete_first_scope_waits_before_all_member_rows(store, old_ref):
    if not old_ref:
        async with store.factory() as setup:
            (await setup.get(UserCompany, (U, C))).own_organization_id = None
            await setup.commit()
    # Legacy route не имеет B/RefX. Его caller flush/commit действительно удаляет Org.
    async with held_actual_call(store, lambda db, actor: refs.delete_organization(str(ORG), db, actor),
                                caller_commit=True, stage_flush=True) as (delete_task, deleting):
        store.statements.clear()
        async with store.factory() as observer:
            async with actual_contender(store, lambda db, actor: invoke_scope(
                    db, actor, own_organization_id=str(ORG))) as (scope_task, scoping):
                await blocked(observer, scoping["pid"], deleting["pid"])
                assert not any("user_companies" in sql and ("for update" in sql or "for share" in sql)
                               for sql in store.statements)
                deleting["db"].commit_release.set()
                await asyncio.wait_for(delete_task, 15)
                if old_ref:
                    with pytest.raises(Exception) as error:
                        await asyncio.wait_for(scope_task, 15)
                    assert error.value.status_code == 409
                else:
                    response = await asyncio.wait_for(scope_task, 15)
                    assert response.own_organization_id is None
    async with store.factory() as verify:
        assert await verify.get(Organization, ORG) is None
        assert (await verify.get(UserCompany, (U, C))).own_organization_id is None
        audits = (await verify.execute(select(AuditEvent))).scalars().all()
        assert len(audits) == (0 if old_ref else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_actual_scope_first_legacy_orgdelete_commit_waits_for_org_share(store, completion):
    async with held_actual_call(store, lambda db, actor: invoke_scope(
            db, actor, own_organization_id=str(ORG))) as (scope_task, scoping):
        async with store.factory() as observer:
            async with actual_contender(store, lambda db, actor: refs.delete_organization(str(ORG), db, actor),
                                        caller_commit=True) as (delete_task, deleting):
                await blocked(observer, deleting["pid"], scoping["pid"])
                if completion == "rollback":
                    scope_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await scope_task
                else:
                    scoping["db"].commit_release.set()
                    await asyncio.wait_for(scope_task, 15)
                await asyncio.wait_for(delete_task, 15)
    async with store.factory() as verify:
        assert await verify.get(Organization, ORG) is None
        assert (await verify.get(UserCompany, (U, C))).own_organization_id is None
        audits = (await verify.execute(select(AuditEvent))).scalars().all()
        assert len(audits) == int(completion == "commit")
    # Notify может быть запланирован до rollback: прежняя гарантия audit не усилена.


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["scope", "source8_writer"])
@pytest.mark.parametrize("self_actor", [False, True])
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_actual_source8_orgwriter_and_scope_target_member_both_orders(store, first, self_actor, completion):
    if self_actor:
        async with store.factory() as setup:
            (await setup.get(UserCompany, (U, C))).role = "admin"
            await setup.commit()
    scope_actor = U if self_actor else A
    async def scope_call(db, actor):
        return await users_router.set_member_scope(str(U), MemberScopeUpdate(
            company_id="synthetic", own_organization_id=str(ORG)), db, actor)
    async def writer_call(db, actor):
        return await refs.update_organization(str(ORG), OrganizationUpdate(name="Synthetic changed"), db, actor)
    if first == "scope":
        held, contender = scope_call, writer_call
        held_actor, contender_actor = scope_actor, U
        held_caller_commit, contender_caller_commit = False, True
    else:
        held, contender = writer_call, scope_call
        held_actor, contender_actor = U, scope_actor
        held_caller_commit, contender_caller_commit = True, False
    async with held_actual_call(store, held, actor_id=held_actor,
                                caller_commit=held_caller_commit) as (first_task, holder):
        store.statements.clear()
        async with store.factory() as observer:
            async with actual_contender(store, contender, actor_id=contender_actor,
                                        caller_commit=contender_caller_commit) as (second_task, waiter):
                # Writer actor == scope target: Member S/X конфликтует в полном B,
                # раньше RefX/RefS и любых физических Member/Org строк contender.
                await blocked(observer, waiter["pid"], holder["pid"], locks.MemberKey(C, U))
                assert not any("for update" in sql or "for share" in sql for sql in store.statements)
                if completion == "rollback":
                    first_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first_task
                else:
                    holder["db"].commit_release.set()
                    await asyncio.wait_for(first_task, 15)
                await asyncio.wait_for(second_task, 15)
    async with store.factory() as verify:
        expected_name = "Synthetic" if first == "source8_writer" and completion == "rollback" else "Synthetic changed"
        assert (await verify.get(Organization, ORG)).name == expected_name
        assert (await verify.get(UserCompany, (U, C))).own_organization_id == ORG
        expected_audits = 0 if first == "scope" and completion == "rollback" else 1
        assert len((await verify.execute(select(AuditEvent))).scalars().all()) == expected_audits
