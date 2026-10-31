"""Authored real-PG actual-route specifications, ALL NOTRUN incl. imports.

actual_target=UNSUPPLIED; execution_approval=NOT_GRANTED. The proposed guard
below is not approval. Parent conftest is earlier/destructive: ROOT must isolate
collection before any future run. No runner is supplied. Synthetic tables test
only account FK/lock seams; production schema acceptance remains UNKNOWN.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
from time import monotonic
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest

_URL = os.environ.get("NATIVE_AUTH_LOCKS_PG_URL", "")
_APPROVED = os.environ.get("NATIVE_AUTH_LOCKS_PG_ROOT_APPROVED_URL", "")
_TARGET = urlsplit(_URL)
if not (_URL and _APPROVED and _URL == _APPROVED
        and os.environ.get("NATIVE_AUTH_LOCKS_PG_APPROVAL", "") == "ROOT-approved-synthetic-native-auth-v1"
        and _TARGET.scheme == "postgresql+psycopg" and _TARGET.hostname
        and _TARGET.path.startswith("/native_auth_synthetic_")
        and len(_TARGET.path) > len("/native_auth_synthetic_")
        and not _TARGET.query and not _TARGET.fragment):
    pytest.skip("UNSUPPLIED ROOT-approved synthetic auth target; no execution approval",
                allow_module_level=True)

# Guard precedes all app/SQLAlchemy/driver imports, not repository conftest.
import pytest_asyncio
from fastapi import HTTPException, Request, Response
from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table, UniqueConstraint, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app import guard, totp
from app.auth import hash_password, native_claims_context, verify_password, decode_token
from app.models import AuditEvent, Company, CompanyRole, Invitation, User, UserCompany
from app.routers import auth_router as routes
from app.routers import invitations_router as invitations
from app.services import contract_write_locks as locks
from app.services import native_auth_locks as native
from app.services import notify

C, D, A, U, I = (UUID(int=i) for i in range(200, 205))
R1, R2, N, E = (UUID(int=i) for i in range(205, 209))
PASSWORD, NEW_PASSWORD = "Synthetic-Q7!Password", "Synthetic-R8!Changed"
RESET = "synthetic-once-reset"
EMAIL = "account@example.invalid"
TOTP_AT = 1_700_000_000
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


@pytest_asyncio.fixture
async def store(monkeypatch):
    schema = "native_auth_" + uuid4().hex
    engine = create_async_engine(_URL, pool_size=7, max_overflow=0,
                                 isolation_level="READ COMMITTED")
    scoped = engine.execution_options(schema_translate_map={None: schema})
    metadata = MetaData()
    # Exact ORM column sets, with only the FK parents relevant to this scope.
    # No production migrations, triggers, seed, or unrelated schema claim.
    for model in (Company, CompanyRole, User, UserCompany, Invitation, AuditEvent):
        Table(model.__tablename__, metadata, *[
            Column(c.name, c.type, primary_key=c.primary_key,
                   nullable=False if c.primary_key else True,
                   server_default=(c.server_default.arg
                                   if c.server_default is not None and c.computed is None else None))
            for c in model.__table__.columns
        ])
    metadata.tables["users"].append_constraint(UniqueConstraint("email"))
    metadata.tables["invitations"].append_constraint(UniqueConstraint("token_hash"))
    for table_name, columns, targets in (
        ("users", ["company_id"], ["companies.id"]),
        ("user_companies", ["company_id"], ["companies.id"]),
        ("user_companies", ["user_id"], ["users.id"]),
        ("user_companies", ["role_id"], ["company_roles.id"]),
        ("company_roles", ["company_id"], ["companies.id"]),
        ("invitations", ["company_id"], ["companies.id"]),
        ("invitations", ["invited_by"], ["users.id"]),
        ("audit_events", ["company_id"], ["companies.id"]),
    ):
        metadata.tables[table_name].append_constraint(ForeignKeyConstraint(columns, targets))
    async with engine.begin() as conn:
        await conn.execute(CreateSchema(schema))
    try:
        async with scoped.begin() as conn:
            await conn.run_sync(metadata.create_all)
        factory = async_sessionmaker(scoped, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            db.add_all([Company(id=cid, slug=f"synthetic-{cid.int}", name="Synthetic", profile_id="energy")
                        for cid in (C, D)])
            await db.flush()
            db.add_all([
                User(id=A, company_id=D, email="admin@example.invalid", password_hash=hash_password(PASSWORD),
                     name="Synthetic admin", role="user", is_superadmin=True, token_version=0),
                User(id=U, company_id=C, email=EMAIL, password_hash=hash_password(PASSWORD),
                     name="Synthetic account", role="user", is_superadmin=False, token_version=0,
                     reset_token_hash=routes._hash_token(RESET),
                     reset_token_expires=datetime.now(timezone.utc) + timedelta(hours=1)),
            ])
            await db.flush()
            db.add(UserCompany(user_id=U, company_id=C))
            await db.commit()
        audits, deliveries, security, failures = [], [], [], []
        real_audit = routes.log_audit
        async def audit(db, **kw):
            audits.append(kw)
            await real_audit(db, **kw)  # real AuditEvent and second failure DB root
        async def reset_mail(*args, **kwargs):
            deliveries.append(("reset", args))
        async def invite_mail(*args, **kwargs):
            deliveries.append(("invite", args))
        async def notice(*args, **kwargs):
            deliveries.append(("notice", args))
        async def record(kind, *args, **kwargs):
            security.append((kind, kwargs))  # original opens its own non-User Session
        def note(email, ip):
            failures.append((email, ip))
            return 0
        async def known_place(*args):
            return False
        real_verify_totp = totp.verify
        def fixed_clock_totp(secret, code, at=None, window=1):
            # Real constant-time TOTP policy, deterministic clock only.
            return real_verify_totp(secret, code, at=TOTP_AT if at is None else at, window=window)
        monkeypatch.setattr(totp, "verify", fixed_clock_totp)
        monkeypatch.setattr(routes, "log_audit", audit)
        monkeypatch.setattr(notify, "dispatch_async", lambda *args, **kwargs: None)
        monkeypatch.setattr(routes, "_is_new_place", known_place)
        monkeypatch.setattr(routes.email_service, "send_password_reset", reset_mail)
        monkeypatch.setattr(routes.email_service, "send_invite", invite_mail)
        monkeypatch.setattr(routes.email_service, "send_notice", notice)
        monkeypatch.setattr(guard, "record", record)
        monkeypatch.setattr(guard, "note_login_failed", note)
        yield SimpleNamespace(engine=scoped, factory=factory, audits=audits,
                              deliveries=deliveries, security=security, failures=failures)
    finally:
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


def request():
    return Request({"type": "http", "method": "POST", "path": "/auth/login",
                    "headers": [(b"user-agent", b"synthetic"), (b"x-forwarded-for", b"192.0.2.20")],
                    "client": ("192.0.2.20", 12345)})


async def pid(db):
    return (await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def wait_blocked(observer, waiter_pid, owner_pid, key):
    ns, value = locks.advisory_key(key)
    deadline = monotonic() + 15
    while monotonic() < deadline:
        blockers = (await observer.execute(text("SELECT pg_blocking_pids(:pid)"),
                                          {"pid": waiter_pid})).scalar_one()
        pending = (await observer.execute(text("""
            SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory'
            AND classid=:ns AND objid=:value AND objsubid=2 AND NOT granted
        """), {"pid": waiter_pid, "ns": ns, "value": value & 0xFFFFFFFF})).scalar_one()
        if owner_pid in blockers and pending:
            return
        # Actual observer queries yield; wall time is a failure deadline, no sleep race.
    raise AssertionError("Expected exact advisory wait in pg_locks/pg_blocking_pids")


@asynccontextmanager
async def running_route(store, invoke, *, actor_id=None, claims=None):
    ready, state = asyncio.Event(), SimpleNamespace(commits=0, rollbacks=0, pid=None)
    async def worker():
        async with store.factory() as db:
            state.pid = await pid(db)
            actor = await db.get(User, actor_id) if actor_id is not None else None
            def committed(session):
                state.commits += 1
            def rolled_back(session):
                state.rollbacks += 1
            event.listen(db.sync_session, "after_commit", committed)
            event.listen(db.sync_session, "after_rollback", rolled_back)
            ready.set()
            try:
                payload = claims if claims is not None else (
                    {"sub": str(actor_id), "tv": 0} if actor_id is not None else None)
                with native_claims_context(payload, None):
                    result = await invoke(db, actor)
                state.handler_commits = state.commits
                # Same owner as get_db for a successful route, even after local commit.
                await db.commit()
                return result
            except BaseException:
                await db.rollback()
                raise
    task = asyncio.create_task(worker())
    await asyncio.wait_for(ready.wait(), 10)
    try:
        yield task, state
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def account_owner(db, uid=U, *, extra_companies=(), member_company=None, roles=()):
    """Real frozen helper, complete Company S + User X plan, then canonical rows."""
    pointer = (await db.execute(select(User.company_id).where(User.id == uid))).scalar_one()
    parents = sorted(set(extra_companies) | ({pointer} if pointer is not None else set()))
    requests = tuple(locks.LockRequest(locks.CompanyKey(cid), S) for cid in parents)
    members = ((locks.LockRequest(locks.MemberKey(member_company, uid), X),)
               if member_company is not None else ())
    role_requests = tuple(locks.LockRequest(locks.RoleKey(cid, rid), S) for cid, rid in roles)
    plan = locks.LockPlan(requests + (locks.LockRequest(locks.UserKey(uid), X),) + role_requests + members)
    cap = await locks.acquire_scoped_locks_async(db, plan)
    for cid in parents:
        await db.execute(select(Company).where(Company.id == cid).with_for_update(read=True))
    user = (await db.execute(select(User).where(User.id == uid).with_for_update()
                             .execution_options(populate_existing=True))).scalar_one()
    for cid, rid in sorted(roles, key=lambda p: p[1]):
        await db.execute(select(CompanyRole).where(CompanyRole.company_id == cid,
            CompanyRole.id == rid).with_for_update(read=True))
    if member_company is not None:
        await db.execute(select(UserCompany).where(UserCompany.company_id == member_company,
            UserCompany.user_id == uid).with_for_update())
    locks.require_scoped_locks(db.sync_session, cap, plan.requests)
    return user, cap, plan


def invoke(name, *, password=PASSWORD, otp=None):
    async def route(db, actor):
        if name == "login":
            return await routes.login(SimpleNamespace(email=EMAIL, password=password, otp=otp), request(), db)
        if name == "forgot_password":
            return await routes.forgot_password(SimpleNamespace(email=EMAIL), db)
        if name == "reset_password":
            return await routes.reset_password(SimpleNamespace(token=RESET, password=NEW_PASSWORD), db)
        if name == "change_password":
            return await routes.change_password(SimpleNamespace(currentPassword=password, newPassword=NEW_PASSWORD), actor, db)
        if name == "logout_all":
            return await routes.logout_all(Response(), actor, db)
        if name == "twofa_setup":
            return await routes.twofa_setup(actor, db)
        if name in ("twofa_enable", "twofa_disable"):
            return await getattr(routes, name)(SimpleNamespace(code=otp or "000000"), actor, db)
        if name == "demo_session":
            return await routes.demo_session(Request({"type": "http", "headers": [
                (b"x-demo-context", b"cabinet")]}), db)
        raise AssertionError(name)
    return route


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["login", "forgot_password", "reset_password", "change_password",
                                 "logout_all", "twofa_setup", "twofa_enable", "twofa_disable", "demo_session"])
async def test_each_existing_account_root_waits_for_actual_user_exclusive(store, monkeypatch, name):
    monkeypatch.setenv("DEMO_SPACE_USER", EMAIL)
    monkeypatch.delenv("DEMO_SPACE_SECRET", raising=False)
    if name in ("twofa_enable", "twofa_disable"):
        async with store.factory() as db:
            user = await db.get(User, U)
            user.totp_secret = totp.seal("JBSWY3DPEHPK3PXP")
            user.totp_enabled = name == "twofa_disable"
            await db.commit()
    code = totp._code("JBSWY3DPEHPK3PXP", int(TOTP_AT // totp.STEP))
    actor_id = U if name in ("change_password", "logout_all", "twofa_setup", "twofa_enable", "twofa_disable") else None
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await account_owner(owner)
        async with running_route(store, invoke(name, otp=code), actor_id=actor_id) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            async with store.factory() as check:
                assert (await check.get(User, U)).token_version == 0
            await owner.rollback()
            result = await asyncio.wait_for(task, 15)
            assert result is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ("password", 401), ("locked", 401), ("totp_missing", 401),
    ("totp_replaced", 401), ("mail_only", 401), ("email", 409), ("company", 409),
])
async def test_login_repeats_actual_policy_after_user_wait(store, change, expected):
    if change == "totp_replaced":
        async with store.factory() as setup:
            user = await setup.get(User, U)
            user.totp_enabled, user.totp_secret = True, totp.seal("JBSWY3DPEHPK3PXP")
            await setup.commit()
    code = totp._code("JBSWY3DPEHPK3PXP", int(TOTP_AT // totp.STEP))
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner, extra_companies=(D,))
        async with running_route(store, invoke("login", otp=code if change == "totp_replaced" else None)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            if change == "password":
                user.password_hash = hash_password(NEW_PASSWORD)
            elif change == "locked":
                user.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
            elif change.startswith("totp"):
                user.totp_enabled, user.totp_secret = True, totp.seal("KRUGS4ZANFZSAYJA")
            elif change == "mail_only":
                user.mail_only = True
            elif change == "email":
                user.email = "moved@example.invalid"
            else:
                user.company_id = D
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == expected
            if change == "totp_missing":
                assert exc.value.detail == routes.OTP_REQUIRED
                assert exc.value.headers == {"X-Need-OTP": "1"}
    assert not any(a["action"] in ("auth.login", "auth.login_new_ip") for a in store.audits)
    if change in ("totp_missing", "mail_only", "email", "company"):
        assert not store.failures


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["consumed", "replaced", "expired"])
async def test_reset_does_not_consume_stale_or_expired_one_time_token(store, change):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke("reset_password")) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            user.reset_token_hash = None if change == "consumed" else (
                routes._hash_token("new-token") if change == "replaced" else user.reset_token_hash)
            if change == "expired":
                user.reset_token_expires = datetime.now(timezone.utc) - timedelta(seconds=1)
            await owner.commit()
            with pytest.raises(HTTPException, match="") as exc:
                await asyncio.wait_for(task, 15)
            assert (exc.value.status_code, exc.value.detail) == (404, "Ссылка недействительна или истекла")
    async with store.factory() as check:
        user = await check.get(User, U)
        assert verify_password(PASSWORD, user.password_hash) and user.token_version == 0
    assert not store.audits


@pytest.mark.asyncio
async def test_two_reset_routes_consume_token_once(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await account_owner(owner)
        async with running_route(store, invoke("reset_password")) as (first, state1):
            async with running_route(store, invoke("reset_password")) as (second, state2):
                await wait_blocked(observer, state1.pid, owner_pid, locks.UserKey(U))
                await wait_blocked(observer, state2.pid, owner_pid, locks.UserKey(U))
                await owner.rollback()
                results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 15)
    assert sum(r == {"ok": True} for r in results) == 1
    errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(errors) == 1 and errors[0].status_code == 404
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.token_version == 1 and user.reset_token_hash is None
        assert verify_password(NEW_PASSWORD, user.password_hash)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["change_password", "logout_all", "twofa_setup", "twofa_enable", "twofa_disable"])
async def test_authenticated_account_routes_reject_concurrent_logout_token_version(store, name):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke(name), actor_id=U) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            user.token_version = 1
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == 401
            assert exc.value.detail == "Сессия завершена — войдите заново"
    assert not store.audits
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.token_version == 1 and not user.totp_enabled
        assert verify_password(PASSWORD, user.password_hash)


@pytest.mark.asyncio
@pytest.mark.parametrize("change,detail", [
    ("password", "Текущий пароль не подходит"),
    ("mail_only", "У этой учётной записи нет пароля"),
    ("empty_hash", "У этой учётной записи нет пароля"),
])
async def test_change_password_current_password_and_mail_policy_are_fresh(store, change, detail):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke("change_password"), actor_id=U) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            if change == "password":
                user.password_hash = hash_password(NEW_PASSWORD)
            elif change == "mail_only":
                user.mail_only = True
            else:
                user.password_hash = ""
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert (exc.value.status_code, exc.value.detail) == (400, detail)
    assert not store.audits


@pytest.mark.asyncio
@pytest.mark.parametrize("name,change,status", [
    ("twofa_setup", "enabled", 409), ("twofa_enable", "secret", 400),
    ("twofa_disable", "secret", 400), ("twofa_disable", "disabled", 400),
])
async def test_twofa_rechecks_enabled_and_sealed_secret_after_wait(store, name, change, status):
    async with store.factory() as setup:
        user = await setup.get(User, U)
        user.totp_secret = totp.seal("JBSWY3DPEHPK3PXP")
        user.totp_enabled = name == "twofa_disable"
        await setup.commit()
    code = totp._code("JBSWY3DPEHPK3PXP", int(TOTP_AT // totp.STEP))
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke(name, otp=code), actor_id=U) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            if change == "enabled":
                user.totp_enabled = True
            elif change == "disabled":
                user.totp_enabled = False
            else:
                user.totp_secret = totp.seal("KRUGS4ZANFZSAYJA")
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == status
    assert not store.audits


@pytest.mark.asyncio
async def test_forgot_password_rechecks_mail_only_and_sends_no_reset(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        original = user.reset_token_hash
        async with running_route(store, invoke("forgot_password")) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            user.mail_only = True
            await owner.commit()
            assert await asyncio.wait_for(task, 15) == {"ok": True}
    async with store.factory() as check:
        assert (await check.get(User, U)).reset_token_hash == original
    assert not store.deliveries


@pytest.mark.asyncio
async def test_failed_login_counts_fresh_value_and_keeps_two_real_commit_roots(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke("login", password="wrong")) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            user.failed_logins = routes.LOCK_AFTER_FAILURES - 1
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == 401 and state.commits == 2
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.failed_logins == 0 and user.locked_until > datetime.now(timezone.utc)
    assert [a["action"] for a in store.audits] == ["auth.login_failed"]
    assert [kind for kind, _ in store.security] == ["account_locked"]
    assert len(store.failures) == 1


@pytest.mark.asyncio
async def test_expired_lock_is_retested_after_wait_without_new_clock_policy(store):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner)
        async with running_route(store, invoke("login")) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await owner.commit()
            response = await asyncio.wait_for(task, 15)
            assert decode_token(response.access_token)["tv"] == 0
    async with store.factory() as check:
        assert (await check.get(User, U)).locked_until is None


@pytest.mark.asyncio
async def test_new_login_notice_writes_reset_under_same_cap_before_success_commit(store, monkeypatch):
    async def new_place(*args):
        return True
    monkeypatch.setattr(routes, "_is_new_place", new_place)
    acquired = []
    real = native.acquire_scoped_locks_async
    async def observe(db, plan):
        cap = await real(db, plan)
        acquired.append((db, cap, plan))
        return cap
    monkeypatch.setattr(native, "acquire_scoped_locks_async", observe)
    async with running_route(store, invoke("login")) as (task, state):
        response = await asyncio.wait_for(task, 15)
    assert response.user.email == EMAIL and state.handler_commits == 1
    assert len(acquired) == 1
    assert any(kind == "notice" for kind, _ in store.deliveries)
    assert [a["action"] for a in store.audits] == ["auth.login_new_ip"]
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.reset_token_hash != routes._hash_token(RESET)
        assert user.reset_token_expires > datetime.now(timezone.utc) + timedelta(hours=23)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["reset_password", "change_password", "logout_all"])
async def test_normal_password_and_logout_payload_token_audit_commit_parity(store, name):
    actor_id = None if name == "reset_password" else U
    async with running_route(store, invoke(name), actor_id=actor_id) as (task, state):
        result = await asyncio.wait_for(task, 15)
    assert result["ok"] is True
    assert state.handler_commits == (0 if name == "reset_password" else 1)
    action = {"reset_password": "auth.password_reset", "change_password": "auth.password_change",
              "logout_all": "auth.logout_all"}[name]
    assert [a["action"] for a in store.audits] == [action]
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.token_version == 1
        if name != "logout_all":
            assert user.reset_token_hash is None and user.reset_token_expires is None
            assert verify_password(NEW_PASSWORD, user.password_hash)
        if name == "change_password":
            claims = decode_token(result["access_token"])
            assert claims["tv"] == 1 and claims.get("at") and claims["exp"] > claims["at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["User", "Member", "actor_demoted", "actor_logout"])
async def test_register_preallocates_uuid_member_and_revalidates_superadmin(store, monkeypatch, which):
    uid = UUID(int=299)
    # Patch UUID allocation only; actual locks, policy, password hashing remain real.
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: uid)
    payload = SimpleNamespace(email="registered@example.invalid", password=PASSWORD,
                              name="Registered", company_id=str(C))
    async def register(db, actor):
        return await routes.register(payload, db, actor)
    key = (locks.UserKey(uid) if which == "User" else locks.MemberKey(C, uid)
           if which == "Member" else locks.UserKey(A))
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        if which.startswith("actor"):
            actor, _, _ = await account_owner(owner, A)
        else:
            await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running_route(store, register, actor_id=A) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, key)
            async with store.factory() as check:
                assert await check.get(User, uid) is None
                assert await check.get(UserCompany, (uid, C)) is None
            if which == "actor_demoted":
                actor.is_superadmin = False
            elif which == "actor_logout":
                actor.token_version = 1
            await owner.commit()
            if which.startswith("actor"):
                with pytest.raises(HTTPException) as exc:
                    await asyncio.wait_for(task, 15)
                assert exc.value.status_code == (401 if which == "actor_logout" else 403)
            else:
                response = await asyncio.wait_for(task, 15)
                assert response.user.id == str(uid) and state.handler_commits == 0
    async with store.factory() as check:
        if which.startswith("actor"):
            assert await check.get(User, uid) is None
        else:
            user, member = await check.get(User, uid), await check.get(UserCompany, (uid, C))
            assert user.role == "user" and user.company_id == C and not user.is_superadmin
            assert member.role == "user" and member.role_id is None


@pytest.mark.asyncio
async def test_demo_preserves_legacy_mixed_case_lookup(store, monkeypatch):
    monkeypatch.setenv("DEMO_SPACE_USER", EMAIL.upper())
    monkeypatch.delenv("DEMO_SPACE_SECRET", raising=False)
    async with store.factory() as db:
        (await db.get(User, U)).email = EMAIL.upper()
        await db.commit()
    async with running_route(store, invoke("demo_session")) as (task, state):
        response = await asyncio.wait_for(task, 15)
    assert response.user.email == EMAIL.upper() and state.handler_commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["token", "accepted", "revoked", "expired", "email", "company", "latest", "none"])
async def test_invitation_resend_uses_company_then_invitation_row_and_rechecks_state(store, change):
    invitation_email = "invited@example.invalid"
    async with store.factory() as setup:
        setup.add(Invitation(id=I, company_id=C, email=invitation_email, role="user",
                             token_hash=routes._hash_token("invite-old"), status="pending",
                             expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                             created_at=datetime.now(timezone.utc)))
        await setup.commit()
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        # Company X is the real complete earlier guard, not an invented invite key.
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), X),
            locks.LockRequest(locks.CompanyKey(D), S))))
        inv = await owner.get(Invitation, I)
        async def resend(db, actor):
            return await routes.forgot_password(SimpleNamespace(email=invitation_email), db)
        async with running_route(store, resend) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.CompanyKey(C))
            if change == "token":
                inv.token_hash = routes._hash_token("invite-replaced")
            elif change == "accepted":
                inv.status = "accepted"
            elif change == "revoked":
                inv.status = "revoked"
            elif change == "expired":
                inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            elif change == "email":
                inv.email = "another@example.invalid"
            elif change == "company":
                inv.company_id = D
            elif change == "latest":
                owner.add(Invitation(id=uuid4(), company_id=C, email=invitation_email,
                    role="user", token_hash=routes._hash_token("invite-latest"), status="pending",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    created_at=inv.created_at + timedelta(seconds=1)))
            await owner.commit()
            assert await asyncio.wait_for(task, 15) == {"ok": True}
            assert state.handler_commits == 0
            assert state.rollbacks == int(change != "none")
    assert bool(store.deliveries) == (change == "none")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "email", "company"])
async def test_forgot_user_identity_drift_is_always200_whole_root_abort(store, change):
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        user, _, _ = await account_owner(owner, extra_companies=(D,), member_company=C)
        async with running_route(store, invoke("forgot_password")) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            if change == "deleted":
                await owner.delete(await owner.get(UserCompany, (U, C)))
                await owner.flush()
                await owner.delete(user)
            elif change == "email":
                user.email = "moved@example.invalid"
            else:
                user.company_id = D
            await owner.commit()
            assert await asyncio.wait_for(task, 15) == {"ok": True}
            assert state.rollbacks == 1 and state.handler_commits == 0
    assert not store.deliveries
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user is None or user.reset_token_hash == routes._hash_token(RESET)


@pytest.mark.asyncio
async def test_forgot_does_not_mask_wrong_execution_state(store):
    async with store.factory() as db:
        async with db.begin_nested():
            with pytest.raises(locks.ScopedLockError, match="non-nested"):
                await routes.forgot_password(SimpleNamespace(email=EMAIL), db)
        await db.rollback()
    assert not store.deliveries


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["login", "reset_password"])
async def test_expiry_clock_is_frozen_after_the_wait_without_real_sleep(store, monkeypatch, name):
    before = datetime.now(timezone.utc)
    clock = SimpleNamespace(now=before)
    class RouteClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now if tz is not None else clock.now.replace(tzinfo=None)
    monkeypatch.setattr(routes, "datetime", RouteClock)
    async with store.factory() as setup:
        user = await setup.get(User, U)
        if name == "login":
            user.locked_until = before + timedelta(minutes=1)
        else:
            user.reset_token_expires = before + timedelta(minutes=1)
        await setup.commit()
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await account_owner(owner)
        async with running_route(store, invoke(name)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            clock.now = before + timedelta(minutes=2)
            await owner.rollback()
            if name == "login":
                result = await asyncio.wait_for(task, 15)
                assert result.user.email == EMAIL
            else:
                with pytest.raises(HTTPException) as exc:
                    await asyncio.wait_for(task, 15)
                assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_account_rows_follow_all_advisories_no_late_acquire_and_cap_dies_on_commit(store):
    statements = []
    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(store.engine.sync_engine, "before_cursor_execute", trace)
    try:
        async with store.factory() as db:
            actor = await db.get(User, U)
            with native_claims_context({"sub": str(U), "tv": 0}, None):
                write = await native.prepare_auth_write(db, target_id=U, actor=actor)
            user = write.user
            user.token_version = 1
            write.require(db)  # dirty authorized state is permitted
            await db.flush()
            write.require(db)
            await db.commit()
            with pytest.raises(locks.ScopedLockError):
                write.require(db)
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", trace)
    advisory = [i for i, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql]
    company = next(i for i, sql in enumerate(statements) if ".companies" in sql and "for share" in sql)
    user = next(i for i, sql in enumerate(statements) if ".users" in sql and "for update" in sql)
    update = next(i for i, sql in enumerate(statements) if sql.startswith("update ") and ".users" in sql)
    assert max(advisory) < company < user < update


@pytest.mark.asyncio
async def test_invite_expiring_by_clock_during_wait_aborts_silently_without_resend(store, monkeypatch):
    before = datetime.now(timezone.utc)
    clock = SimpleNamespace(now=before)
    class RouteClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now
    monkeypatch.setattr(routes, "datetime", RouteClock)
    email = "expiring@example.invalid"
    async with store.factory() as setup:
        setup.add(Invitation(id=I, company_id=C, email=email, role="user", status="pending",
            token_hash=routes._hash_token("unchanged"), expires_at=before + timedelta(minutes=1),
            created_at=before))
        await setup.commit()
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), X),)))
        async def resend(db, actor):
            return await routes.forgot_password(SimpleNamespace(email=email), db)
        async with running_route(store, resend) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.CompanyKey(C))
            clock.now = before + timedelta(minutes=2)
            await owner.rollback()
            assert await asyncio.wait_for(task, 15) == {"ok": True}
            assert state.rollbacks == 1 and state.handler_commits == 0
    assert not store.deliveries
    async with store.factory() as check:
        assert (await check.get(Invitation, I)).token_hash == routes._hash_token("unchanged")


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status,detail", [
    ("forbidden", 403, "Регистрация доступна только суперадмину"),
    ("duplicate", 409, "Пользователь с таким email уже существует"),
    ("company", 400, "Невалидный company_id"),
])
async def test_register_legacy_error_precedence_before_mutation(store, case, status, detail):
    async with store.factory() as db:
        actor = await db.get(User, U if case == "forbidden" else A)
        body = SimpleNamespace(email=EMAIL if case != "company" else "new@example.invalid",
                               password=PASSWORD, name="Synthetic", company_id="missing-company")
        with native_claims_context({"sub": str(actor.id), "tv": 0}, None):
            with pytest.raises(HTTPException) as exc:
                await routes.register(body, db, actor)
        assert (exc.value.status_code, exc.value.detail) == (status, detail)
        assert not db.new and not db.dirty and not db.deleted
        await db.rollback()


@pytest.mark.asyncio
async def test_normal_twofa_setup_enable_disable_preserves_version_and_audits(store):
    async with running_route(store, invoke("twofa_setup"), actor_id=U) as (task, state):
        setup = await asyncio.wait_for(task, 15)
        assert set(setup) == {"secret", "uri"} and setup["uri"].startswith("otpauth://totp/")
        assert state.handler_commits == 1
    code = totp._code(setup["secret"], int(TOTP_AT // totp.STEP))
    for name, enabled in (("twofa_enable", True), ("twofa_disable", False)):
        async with running_route(store, invoke(name, otp=code), actor_id=U) as (task, state):
            assert await asyncio.wait_for(task, 15) == {"enabled": enabled}
            assert state.handler_commits == 1
        async with store.factory() as check:
            user = await check.get(User, U)
            assert user.token_version == 0 and user.totp_enabled is enabled
            assert (user.totp_secret is not None) is enabled
    assert [a["action"] for a in store.audits] == ["auth.2fa_enabled", "auth.2fa_disabled"]


@pytest.mark.asyncio
async def test_normal_forgot_reset_link_flush_and_ttl_leave_commit_to_caller(store):
    async with running_route(store, invoke("forgot_password")) as (task, state):
        assert await asyncio.wait_for(task, 15) == {"ok": True}
        assert state.handler_commits == 0 and state.rollbacks == 0
    assert len(store.deliveries) == 1
    kind, (email, token) = store.deliveries[0]
    assert kind == "reset" and email == EMAIL
    async with store.factory() as check:
        user = await check.get(User, U)
        assert user.reset_token_hash == routes._hash_token(token)
        assert datetime.now(timezone.utc) + timedelta(minutes=59) < user.reset_token_expires
        assert user.token_version == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_current,equal,detail", [
    (True, True, "Текущий пароль не подходит"),
    (False, True, "Новый пароль должен отличаться от текущего"),
])
async def test_change_password_normal_error_order_is_unchanged(store, wrong_current, equal, detail):
    async def change(db, actor):
        password = "wrong" if wrong_current else PASSWORD
        return await routes.change_password(SimpleNamespace(
            currentPassword=password, newPassword=password if equal else NEW_PASSWORD), actor, db)
    async with running_route(store, change, actor_id=U) as (task, state):
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(task, 15)
        assert (exc.value.status_code, exc.value.detail) == (400, detail)
        assert state.commits == 0
    assert not store.audits


INVITE_TOKEN = "synthetic-public-accept"


async def accept_fixture(store, *, existing=True, scope="space"):
    email = EMAIL if existing else "new-invited@example.invalid"
    async with store.factory() as db:
        db.add_all([CompanyRole(id=rid, company_id=C, name=f"role-{rid.int}", modules=[], is_system=False)
                    for rid in (R1, R2)])
        await db.flush()
        (await db.get(UserCompany, (U, C))).role_id = R1
        db.add(Invitation(id=I, company_id=C, email=email, role="admin", status="pending",
            scope=scope, position="Invited position", party_type="partner",
            token_hash=invitations._hash(INVITE_TOKEN),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            created_at=datetime.now(timezone.utc)))
        await db.commit()
    return SimpleNamespace(name="Invited" if not existing else None,
                           password=PASSWORD if not existing else None, position="  Actual position  ")


def accepting(payload):
    async def route(db, actor):
        return await invitations.accept_invite(INVITE_TOKEN, payload, db)
    return route


@pytest.mark.asyncio
@pytest.mark.parametrize("existing,scope", [(True, "company"), (False, "company"),
                                           (True, "space"), (False, "space")])
async def test_public_accept_existing_new_company_space_parity_without_admin(store, monkeypatch, existing, scope):
    payload = await accept_fixture(store, existing=existing, scope=scope)
    monkeypatch.setattr(invitations.uuid, "uuid4", lambda: N)
    async with running_route(store, accepting(payload)) as (task, state):
        result = await asyncio.wait_for(task, 15)
        assert state.handler_commits == 0
    uid = U if existing else N
    if existing:
        assert result == {"joined": True, "user_exists": True}
    else:
        assert result.user.id == str(N) and result.user.role == "admin"
        assert decode_token(result.access_token)["sub"] == str(N)
    async with store.factory() as check:
        user = await check.get(User, uid)
        assert not user.is_superadmin and user.company_id == C
        assert verify_password(PASSWORD, user.password_hash)
        assert (await check.get(Invitation, I)).status == "accepted"
        for cid in (C, D) if scope == "space" else (C,):
            member = await check.get(UserCompany, (uid, cid))
            assert member is not None
            if existing and cid == C:
                assert member.role == "user" and member.role_id == R1
            else:
                assert member.role == "admin" and member.role_id is None
                assert member.position == "Actual position" and member.party_type == "partner"
        if not existing and scope == "company":
            assert await check.get(UserCompany, (uid, D)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("existing,guarded", [(True, "user"), (False, "user"),
    (True, "company-d"), (False, "company-d"), (True, "member-c"),
    (True, "member-d"), (False, "member-d"), (True, "old-role")])
async def test_space_accept_full_user_company_role_member_plan_before_any_flush(store, monkeypatch, existing, guarded):
    payload = await accept_fixture(store, existing=existing)
    monkeypatch.setattr(invitations.uuid, "uuid4", lambda: N)
    uid = U if existing else N
    key = {"user": locks.UserKey(uid), "company-d": locks.CompanyKey(D),
           "member-c": locks.MemberKey(C, uid), "member-d": locks.MemberKey(D, uid),
           "old-role": locks.RoleKey(C, R1)}[guarded]
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        async with running_route(store, accepting(payload)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, key)
            async with store.factory() as check:
                assert (await check.get(Invitation, I)).status == "pending"
                assert await check.get(UserCompany, (uid, D)) is None
                if not existing:
                    assert await check.get(User, uid) is None
            await owner.rollback()
            await asyncio.wait_for(task, 15)


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [("token", 404), ("revoked", 410),
    ("accepted", 410), ("expired", 410), ("email", 409), ("scope", 409), ("targets", 409)])
async def test_accept_repeats_public_admission_and_observed_target_set_after_wait(store, change, status):
    payload = await accept_fixture(store)
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), X), locks.LockRequest(locks.CompanyKey(E), X))))
        inv = await owner.get(Invitation, I)
        async with running_route(store, accepting(payload)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.CompanyKey(C))
            if change == "token":
                inv.token_hash = invitations._hash("reissued")
            elif change in ("revoked", "accepted"):
                inv.status = change
            elif change == "expired":
                inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            elif change == "email":
                inv.email = "moved@example.invalid"
            elif change == "scope":
                inv.scope = "company"
            else:
                owner.add(Company(id=E, slug="synthetic-new-target", name="New", profile_id="energy"))
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == status
    async with store.factory() as check:
        assert await check.get(UserCompany, (U, D)) is None
        assert (await check.get(UserCompany, (U, C))).role_id == R1


@pytest.mark.asyncio
async def test_accept_changed_existing_named_role_pointer_aborts_without_late_role_acquire(store):
    payload = await accept_fixture(store)
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await account_owner(owner, member_company=C, roles=((C, R1), (C, R2)))
        async with running_route(store, accepting(payload)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.UserKey(U))
            (await owner.get(UserCompany, (U, C))).role_id = R2
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == 409
    async with store.factory() as check:
        assert await check.get(UserCompany, (U, D)) is None
        assert (await check.get(Invitation, I)).status == "pending"


@pytest.mark.asyncio
async def test_public_invitation_consumed_once_by_two_existing_user_requests(store):
    payload = await accept_fixture(store)
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), X),)))
        async with running_route(store, accepting(payload)) as (first, state1):
            async with running_route(store, accepting(payload)) as (second, state2):
                await wait_blocked(observer, state1.pid, owner_pid, locks.CompanyKey(C))
                await wait_blocked(observer, state2.pid, owner_pid, locks.CompanyKey(C))
                await owner.rollback()
                results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 15)
    assert sum(r == {"joined": True, "user_exists": True} for r in results) == 1
    errors = [r for r in results if isinstance(r, HTTPException)]
    # If discovery saw absent Member D then the first added it, pointer drift
    # fails409 before the second's invitation readmission; otherwise accepted410.
    assert len(errors) == 1 and errors[0].status_code in (409, 410)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["name", "password"])
async def test_new_public_invitee_keeps_name_password_requirements(store, missing):
    payload = await accept_fixture(store, existing=False)
    setattr(payload, missing, None)
    async with running_route(store, accepting(payload)) as (task, state):
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(task, 15)
        assert (exc.value.status_code, exc.value.detail) == (400, "Укажите имя и пароль")
    async with store.factory() as check:
        assert (await check.execute(select(User.id).where(
            User.email == "new-invited@example.invalid"))).scalar_one_or_none() is None
        assert (await check.get(Invitation, I)).status == "pending"


async def wait_invitation_row(observer, waiter_pid, owner_pid):
    deadline = monotonic() + 15
    while monotonic() < deadline:
        blockers = (await observer.execute(text("SELECT pg_blocking_pids(:pid)"),
                                          {"pid": waiter_pid})).scalar_one()
        waiting = (await observer.execute(text("""
            SELECT count(*) FROM pg_locks WHERE pid=:pid AND NOT granted
            AND locktype IN ('transactionid','tuple')
        """), {"pid": waiter_pid})).scalar_one()
        if owner_pid in blockers and waiting:
            return
    raise AssertionError("Expected real invitation UPDATE row wait")


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [("token", 404), ("revoked", 410), ("expired", 410)])
async def test_public_admission_is_repeated_after_final_invitation_row_wait(store, change, status):
    payload = await accept_fixture(store)
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), S),)))
        await owner.execute(select(Company).where(Company.id == C).with_for_update(read=True))
        inv = (await owner.execute(select(Invitation).where(
            Invitation.id == I, Invitation.company_id == C).with_for_update())).scalar_one()
        async with running_route(store, accepting(payload)) as (task, state):
            await wait_invitation_row(observer, state.pid, owner_pid)
            if change == "token":
                inv.token_hash = invitations._hash("reissued-after-row-wait")
            elif change == "revoked":
                inv.status = "revoked"
            else:
                inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == status
    async with store.factory() as check:
        assert await check.get(UserCompany, (U, D)) is None


@pytest.mark.asyncio
async def test_accept_legacy_cross_company_named_role_fails409_without_repair(store):
    payload = await accept_fixture(store)
    async with store.factory() as setup:
        # Deliberate synthetic corruption permitted by the actual single Role FK.
        setup.add(CompanyRole(id=E, company_id=D, name="Foreign", modules=[], is_system=False))
        await setup.flush()
        (await setup.get(UserCompany, (U, C))).role_id = E
        await setup.commit()
    async with running_route(store, accepting(payload)) as (task, state):
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(task, 15)
        assert exc.value.status_code == 409
    async with store.factory() as check:
        assert (await check.get(UserCompany, (U, C))).role_id == E
        assert await check.get(UserCompany, (U, D)) is None
        assert (await check.get(Invitation, I)).status == "pending"


@pytest.mark.asyncio
async def test_new_invitee_email_appearing_during_wait_aborts_without_switching_user_key(store, monkeypatch):
    payload = await accept_fixture(store, existing=False)
    monkeypatch.setattr(invitations.uuid, "uuid4", lambda: N)
    other = UUID(int=209)
    async with store.factory() as owner, store.factory() as observer:
        owner_pid = await pid(owner)
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((
            locks.LockRequest(locks.CompanyKey(C), X), locks.LockRequest(locks.UserKey(other), X))))
        async with running_route(store, accepting(payload)) as (task, state):
            await wait_blocked(observer, state.pid, owner_pid, locks.CompanyKey(C))
            owner.add(User(id=other, company_id=C, email="new-invited@example.invalid",
                           password_hash=hash_password(PASSWORD), name="Concurrent", role="user"))
            await owner.commit()
            with pytest.raises(HTTPException) as exc:
                await asyncio.wait_for(task, 15)
            assert exc.value.status_code == 409
    async with store.factory() as check:
        assert await check.get(User, N) is None
        assert await check.get(UserCompany, (other, C)) is None
        assert (await check.get(Invitation, I)).status == "pending"
