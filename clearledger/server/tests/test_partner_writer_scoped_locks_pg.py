"""AUTHORED / NOTRUN, including collection. REAL opt-in PostgreSQL definitions.

Reuse the existing partner safety predicate, full-schema fixture and synthetic
HTTP helpers. No new runner/URL/admission, dependency patches or reduced schema.
URL UNSUPPLIED / execution NOT_GRANTED to this author. ROOT must freeze the
combined schema4/composition and isolate parent conftest BEFORE collection:
that conftest can DROP schemas before this module's own guard is evaluated.
Every capability below is issued by the actual helper on its real root.
"""
import os

import pytest
from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_PARTNER_IDENTITY_TESTS") != "1":
    pytest.skip("Existing partner opt-in required; author execution NOT_GRANTED", allow_module_level=True)
if error := partner_test_safety_error(os.environ):
    raise RuntimeError(error)
if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Existing isolated partner composition must use matching URLs")

# No app/SQLAlchemy/driver imports before the existing admission checks.
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import token_for
from app.models import App, CompanyApp, CompanyRole, PartnerSpace, User, UserCompany
from app.models_partner import (PartnerAuthorizationRequest, PartnerClient, PartnerCode, PartnerCredential,
    PartnerGrant, PartnerInstallation, PartnerResourceScope, PartnerSubject, PartnerToken, PartnerTokenFamily)
from app.routers import partner_oauth_router as oauth
from app.services import partner_identity as identity
from app.services import contract_write_locks as locks
from tests.conftest import _test_engine, _test_session_factory
from tests.test_partner_identity import (env, rsa_key, registration, pending, consent, exchange,
    tokens, refresh, SCOPES, REDIRECT, VERIFIER)

pytestmark = pytest.mark.asyncio(loop_scope="session")
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


async def pid(db):
    return await db.scalar(text("SELECT pg_backend_pid()"))


@asynccontextmanager
async def contender(invoke):
    """Signal from actual SQL on the actual request's Connection, no sleeps.

    Event PID is obtained from that Connection, not a guessed Session/pool slot.
    Tests always release the blocking root in finally before joining the task.
    """
    ready, details = asyncio.Event(), {"sql": []}
    def record(conn, cursor, statement, parameters, context, executemany):
        details["sql"].append(statement)
        if "pg_advisory_xact_lock" in statement and "CAST" in statement and not ready.is_set():
            details["pid"] = conn.scalar(text("SELECT pg_backend_pid()"))
            ready.set()
    event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
    task = asyncio.create_task(invoke())
    signal = asyncio.create_task(ready.wait())
    try:
        await asyncio.wait((task, signal), return_when=asyncio.FIRST_COMPLETED)
        assert ready.is_set(), "Request completed before any typed lock SQL"
        yield task, details
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", record)
        signal.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, signal, return_exceptions=True)


async def observed_wait(observer, task, waiter, owner, key=None):
    """Actual backend wait + catalog evidence, not a timing/sleep oracle."""
    while not task.done():
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:p)"), {"p": waiter})
        rows = (await observer.execute(text("SELECT locktype, mode, classid, objid, objsubid FROM pg_locks WHERE pid=:p AND NOT granted"), {"p": waiter})).all()
        if owner in blockers and rows:
            if key is not None:
                ns, number = locks.advisory_key(key)
                assert any(r.locktype == "advisory" and r.classid == ns
                           and r.objid == number & 0xFFFFFFFF and r.objsubid == 2 for r in rows)
            return rows
    raise AssertionError("Contender finished without expected real pg_blocking_pids/pg_locks wait")


async def token_rows(access):
    async with _test_session_factory() as db:
        row = await db.scalar(select(PartnerToken).where(PartnerToken.access_hash == identity.digest(access)))
        family = await db.get(PartnerTokenFamily, row.family_id)
        grant = await db.get(PartnerGrant, family.grant_id)
        return SimpleNamespace(tid=row.id, fid=family.id, gid=grant.id,
            iid=grant.installation_id, uid=grant.user_id, cid=grant.company_id)


async def counts(client_id):
    async with _test_session_factory() as db:
        grants = select(PartnerGrant.id).where(PartnerGrant.client_id == client_id)
        families = select(PartnerTokenFamily.id).where(PartnerTokenFamily.grant_id.in_(grants))
        return tuple([await db.scalar(select(func.count()).select_from(model).where(condition))
            for model, condition in ((PartnerTokenFamily, PartnerTokenFamily.grant_id.in_(grants)),
                (PartnerToken, PartnerToken.family_id.in_(families)), (PartnerCode, PartnerCode.client_id == client_id))])


async def test_real_seam_same_session_optionengine_original_cap_and_fresh_resources(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    # Real OptionEngine via execution_options; original helper must work here.
    option = _test_engine.execution_options(schema_translate_map={None: "public"})
    factory = async_sessionmaker(option, expire_on_commit=False)
    async with factory() as db:
        expected = await db.run_sync(identity.verify_access, issued["access_token"])
        writer = await db.run_sync(identity._prepare_partner_write, token_id=expected.token_id, mutation="userinfo")
        connection = await db.connection()
        root = db.sync_session.get_transaction()
        current = await db.run_sync(identity.verify_locked_partner_access, issued["access_token"],
            capability=writer.capability, expected=expected)
        assert current == expected and current is not expected
        assert db.sync_session.get_transaction() is root
        assert (await db.connection()).sync_connection is connection.sync_connection
        with pytest.raises(HTTPException) as error:
            await db.run_sync(identity.verify_locked_partner_access, issued["access_token"],
                capability=writer.capability, expected=replace(expected, grant_id=uuid4()))
        assert error.value.status_code == 409
        with pytest.raises(locks.ScopedLockError):
            await db.run_sync(locks.require_scoped_locks, writer.capability, writer.capability.plan.requests)


async def test_issued_cap_not_transferable_to_another_real_session_or_after_root_end(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    async with _test_session_factory() as db, _test_session_factory() as other:
        expected = await db.run_sync(identity.verify_access, issued["access_token"])
        writer = await db.run_sync(identity._prepare_partner_write, token_id=expected.token_id, mutation="userinfo")
        with pytest.raises(locks.ScopedLockError):
            await other.run_sync(identity.verify_locked_partner_access, issued["access_token"],
                capability=writer.capability, expected=expected)
        await db.rollback()
        with pytest.raises(locks.ScopedLockError):
            await db.run_sync(identity.verify_locked_partner_access, issued["access_token"],
                capability=writer.capability, expected=expected)


@pytest.mark.parametrize("change", ["client", "app", "installation", "ca", "credential", "grant", "user_tv", "user_lock", "member"])
async def test_access_rechecks_actual_current_authority_after_client_wait(env, change):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    data = await token_rows(issued["access_token"])
    key = locks.ClientKey(app["client_id"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, key)
                if change == "client": (await owner.get(PartnerClient, app["client_id"])).enabled = False
                if change == "app": (await owner.get(App, app["app_id"])).is_active = False
                if change == "installation": (await owner.get(PartnerInstallation, data.iid)).approved = False
                if change == "ca": (await owner.get(CompanyApp, data.iid)).enabled = False
                if change == "credential": (await owner.get(PartnerCredential, app["credential_id"])).enabled = False
                if change == "grant": (await owner.get(PartnerGrant, data.gid)).approved = False
                if change == "user_tv": (await owner.get(User, data.uid)).token_version += 1
                if change == "user_lock": (await owner.get(User, data.uid)).locked_until = identity.now() + timedelta(hours=1)
                if change == "member": await owner.delete(await owner.get(UserCompany, (data.uid, data.cid)))
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code in (401, 409)
    assert await counts(app["client_id"]) == (1, 1, 1)


@pytest.mark.parametrize("expiry", ["jwt", "family", "credential", "auth_time"])
async def test_access_expiry_after_real_family_row_wait(env, monkeypatch, expiry):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    data = await token_rows(issued["access_token"])
    if expiry == "credential":
        async with _test_session_factory() as setup:
            (await setup.get(PartnerCredential, app["credential_id"])).expires_at = identity.now() + timedelta(seconds=60)
            await setup.commit()
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        family = await owner.scalar(select(PartnerTokenFamily).where(PartnerTokenFamily.id == data.fid).with_for_update())
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})) as (task, info):
            try:
                # Dependency verifier would wait only for typed? It reads MVCC;
                # canonical row SHARE in writer is the observed actual wait.
                await observed_wait(observer, task, info["pid"], owner_pid)
                if expiry == "family": family.expires_at = identity.now() - timedelta(seconds=1)
                if expiry == "credential":
                    # Family SHARE waiter already holds credential SHARE, so
                    # expire its clock rather than introduce a reverse row lock.
                    cutoff = (await owner.get(PartnerCredential, app["credential_id"])).expires_at + timedelta(seconds=1)
                    monkeypatch.setattr(identity, "now", lambda: cutoff)
                if expiry == "auth_time": family.auth_time = 1
                if expiry == "jwt":
                    # Reuse canonical decoder; PyJWT reads its own datetime.
                    from datetime import datetime, timezone
                    import jwt.api_jwt
                    future = datetime.now(timezone.utc) + timedelta(hours=1)
                    class Clock(datetime):
                        @classmethod
                        def now(cls, tz=None): return future
                    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code == 401


async def test_family_then_old_token_rotation_and_durable_reuse_error(env):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    data = await token_rows(issued["access_token"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await owner.scalar(select(PartnerTokenFamily).where(PartnerTokenFamily.id == data.fid).with_for_update())
        owner_pid = await pid(owner)
        async with contender(lambda: refresh(env, app, issued["refresh_token"])) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid)
                # Canonical protocol has not requested Token UPDATE before Family.
                locked = [sql for sql in info["sql"] if "FOR UPDATE" in sql.upper()]
                assert any("partner_token_families" in sql for sql in locked)
                assert not any("partner_tokens" in sql and "FOR UPDATE" in sql.upper() for sql in locked)
            finally:
                await owner.rollback()
            response = await task
        assert response.status_code == 200
    reused = await refresh(env, app, issued["refresh_token"])
    assert reused.status_code == 400 and reused.json()["error"] == "invalid_grant"
    async with _test_session_factory() as fresh:
        assert (await fresh.get(PartnerTokenFamily, data.fid)).revoked is True
    assert (await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + response.json()["access_token"]})).status_code == 401


async def test_code_single_use_and_nonce_request_single_completion(env):
    app = await registration(env)
    code, params, rid = await consent(env, app)
    responses = await asyncio.gather(exchange(env, app, code), exchange(env, app, code))
    assert sorted(r.status_code for r in responses) == [200, 400]
    assert await counts(app["client_id"]) == (1, 1, 1)
    second = await env["client"].post(f"/api/developer/authorization-requests/{rid}/approve",
        headers=env["headers"], json={"companyId": str(env["company"].id), "scopes": SCOPES})
    assert second.status_code == 409
    repeated = await env["client"].get("/api/oauth2/authorize", params={**params, "state": uuid4().hex})
    assert repeated.status_code == 400
    async with _test_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(PartnerCode).where(
            PartnerCode.client_id == app["client_id"], PartnerCode.nonce == params["nonce"])) == 1


@pytest.mark.parametrize("principal", ["public", "confidential", "machine"])
async def test_real_protocol_principals_do_not_construct_core_users(env, principal):
    app = await registration(env, confidential=principal != "public",
        scopes=["docs:read"] if principal == "machine" else SCOPES)
    if principal != "machine":
        code, _, _ = await consent(env, app)
        response = await exchange(env, app, code)
        assert response.status_code == 200 and "id_token" in response.json()
    else:
        response = await env["client"].post(f"/api/developer/installations/{app['installation_id']}/machine-grants",
            headers=env["headers"], json={"scopes": ["docs:read"]})
        assert response.status_code == 201
        response = await env["client"].post("/api/oauth2/token", auth=(app["client_id"], app["secret"]),
            data={"grant_type": "client_credentials", "grant_id": response.json()["grantId"], "scope": "docs:read"})
        assert response.status_code == 200 and "id_token" not in response.json()
    async with _test_session_factory() as db:
        verified = await db.run_sync(identity.verify_access, response.json()["access_token"])
        assert verified.is_machine == (principal == "machine")
        assert (verified.user_id is None) == (principal == "machine")


async def test_revocation_unknown_repeated_and_pre_revoked_grant_remain_idempotent(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    data = await token_rows(issued["access_token"])
    async with _test_session_factory() as db:
        (await db.get(PartnerGrant, data.gid)).approved = False
        await db.commit()
    for value in ("unknown-" + uuid4().hex, issued["refresh_token"], issued["refresh_token"]):
        response = await env["client"].post("/api/oauth2/revoke", data={"client_id": app["client_id"], "token": value})
        assert response.status_code == 200 and response.json() == {}
    async with _test_session_factory() as db:
        assert (await db.get(PartnerTokenFamily, data.fid)).revoked


@pytest.mark.parametrize("expiry", ["jwt", "max_session"])
async def test_native_actual_bearer_expiry_after_nonce_wait(env, monkeypatch, expiry):
    app = await registration(env)
    rid, params = await pending(env, app)
    native_headers = env["headers"]
    if expiry == "max_session":
        native_headers = {"Authorization": "Bearer " + token_for(env["user"],
            auth_time=int(identity.time.time()) - identity.MAX_SESSION_DAYS * 86400 + 60,
            expires_at=identity.now() + timedelta(hours=1))}
    nonce = int(identity.digest(app["client_id"] + ":" + params["nonce"])[:16], 16)
    if nonce >= 2**63: nonce -= 2**64
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await owner.execute(select(func.pg_advisory_xact_lock(nonce)))
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].post(f"/api/developer/authorization-requests/{rid}/approve",
                headers=native_headers, json={"companyId": str(env["company"].id), "scopes": SCOPES})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid)
                # Actual locked native rows stay stable; move only the decoder
                # clock, with the original bearer and canonical decoder intact.
                from datetime import datetime, timezone
                import jwt.api_jwt
                future = datetime.now(timezone.utc) + (timedelta(days=identity.MAX_SESSION_DAYS + 1)
                    if expiry == "jwt" else timedelta(seconds=120))
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None): return future
                if expiry == "jwt":
                    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
                else:
                    import app.auth
                    monkeypatch.setattr(app.auth, "datetime", Clock)
            finally:
                await owner.rollback()
            response = await task
        assert response.status_code == 401
        assert await counts(app["client_id"]) == (0, 0, 0)


async def test_real_visit_bearer_is_rejected_before_identity_writer(env):
    app = await registration(env)
    from app.auth import VISIT_SCOPE
    async with _test_session_factory() as db:
        partner = PartnerSpace(id=uuid4(), company_id=env["company"].id,
            role="vendor", code=uuid4().hex, name="Synthetic visit", is_active=True)
        db.add(partner)
        await db.commit()
    bearer = token_for(env["user"], extra={"scp": VISIT_SCOPE,
        "cid": str(env["company"].id), "pvs": str(partner.id)})
    response = await env["client"].post(f"/api/developer/clients/{app['client_id']}/status",
        headers={"Authorization": "Bearer " + bearer}, json={"enabled": False})
    assert response.status_code == 403
    async with _test_session_factory() as db:
        assert (await db.get(PartnerClient, app["client_id"])).enabled is True


@pytest.mark.parametrize("change", ["tv", "admin", "role_pointer", "transient_grant"])
async def test_native_membership_role_and_session_after_typed_wait(env, change):
    app = await registration(env)
    rid, _ = await pending(env, app)
    key = locks.ClientKey(app["client_id"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].post(f"/api/developer/authorization-requests/{rid}/approve",
                headers=env["headers"], json={"companyId": str(env["company"].id), "scopes": SCOPES})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, key)
                member = await owner.get(UserCompany, (env["user"].id, env["company"].id))
                if change == "tv": (await owner.get(User, env["user"].id)).token_version += 1
                if change == "admin": member.role, member.modules = "user", []
                if change == "role_pointer":
                    role = CompanyRole(id=uuid4(), company_id=env["company"].id, name="new role", modules=[])
                    owner.add(role); await owner.flush(); member.role_id = role.id
                if change == "transient_grant": await owner.delete(member)
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code in (401, 403, 409, 422)
    assert await counts(app["client_id"]) == (0, 0, 0)


async def test_missing_ca_conflict_rolls_back_whole_root_without_other_install_key(env):
    app = await registration(env, installation=False)
    key = locks.ClientKey(app["client_id"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner)
        actual = uuid4()
        async with contender(lambda: env["client"].post(f"/api/developer/clients/{app['client_id']}/installations",
                headers=env["headers"], json={"companyId": str(env["company"].id), "scopes": SCOPES})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, key)
                owner.add(CompanyApp(id=actual, company_id=env["company"].id, app_id=app["app_id"], enabled=False))
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code == 409
    async with _test_session_factory() as db:
        assert await db.get(PartnerInstallation, actual) is None
        assert (await db.get(CompanyApp, actual)).enabled is False


async def test_same_client_blocks_and_different_client_progresses_without_global_lock(env):
    first, second = await registration(env), await registration(env)
    key = locks.ClientKey(first["client_id"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].post(f"/api/developer/clients/{first['client_id']}/status",
                headers=env["headers"], json={"enabled": False})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, key)
                independent = await env["client"].post(f"/api/developer/clients/{second['client_id']}/status",
                    headers=env["headers"], json={"enabled": False})
                assert independent.status_code == 200 and not task.done()
            finally:
                await owner.rollback()
            assert (await task).status_code == 200


async def test_conditional_get_writes_and_self_grant_revoke_without_admin(env):
    app = await registration(env)
    rid, _ = await pending(env, app)
    detail = await env["client"].get(f"/api/developer/authorization-requests/{rid}", headers=env["headers"])
    assert detail.status_code == 200
    async with _test_session_factory() as db:
        assert (await db.get(PartnerAuthorizationRequest, UUID(rid))).user_id == env["user"].id
    issued, _ = await tokens(env, app)
    data = await token_rows(issued["access_token"])
    info = await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})
    assert info.status_code == 200
    async with _test_session_factory() as db:
        assert (await db.get(PartnerSubject, (data.uid, app["client_id"]))).subject == info.json()["sub"]
        member = await db.get(UserCompany, (data.uid, data.cid))
        member.role, member.modules = "user", []
        await db.commit()
    revoked = await env["client"].delete(f"/api/developer/grants/{data.gid}", headers=env["headers"])
    assert revoked.status_code == 200


async def test_post_token_flush_denial_rolls_back_family_token_code_consumption(env, monkeypatch):
    app = await registration(env)
    code, _, _ = await consent(env, app)
    before = await counts(app["client_id"])
    original = identity.PartnerOpenIDCode.generate_user_info
    def after_token_flush(extension, user, scope):
        # Real DB token INSERT has happened before the unordered OIDC hook.
        assert extension.server.db.scalar(select(func.count()).select_from(PartnerToken)) > 0
        original(extension, user, scope)
        from authlib.oauth2.rfc6749 import InvalidGrantError
        raise InvalidGrantError()
    monkeypatch.setattr(identity.PartnerOpenIDCode, "generate_user_info", after_token_flush)
    response = await exchange(env, app, code)
    assert response.status_code == 400
    assert await counts(app["client_id"]) == before
    async with _test_session_factory() as db:
        assert (await db.get(PartnerCode, identity.digest(code))).consumed is False


async def test_cancel_at_typed_wait_and_rollback_leave_no_partial_installation(env):
    app = await registration(env, installation=False)
    key = locks.ClientKey(app["client_id"])
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await locks.acquire_scoped_locks_async(owner, locks.LockPlan((locks.LockRequest(key, X),)))
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].post(f"/api/developer/clients/{app['client_id']}/installations",
                headers=env["headers"], json={"companyId": str(env["company"].id), "scopes": SCOPES})) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, key)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            finally:
                await owner.rollback()
    async with _test_session_factory() as db:
        assert await db.scalar(select(CompanyApp).where(CompanyApp.app_id == app["app_id"],
            CompanyApp.company_id == env["company"].id)) is None


async def test_ca_row_precedes_installation_row_under_actual_http_wait(env):
    app = await registration(env)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await owner.scalar(select(CompanyApp).where(CompanyApp.id == app["installation_id"]).with_for_update())
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].delete(
                f"/api/developer/installations/{app['installation_id']}", headers=env["headers"])) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid)
                locked = [sql for sql in info["sql"] if "FOR UPDATE" in sql.upper() or "FOR SHARE" in sql.upper()]
                assert any("eco_company_apps" in sql for sql in locked)
                assert not any("partner_installations" in sql for sql in locked)
            finally:
                await owner.rollback()
            assert (await task).status_code == 200
    async with _test_session_factory() as db:
        assert (await db.get(PartnerInstallation, app["installation_id"])).approved is False


@pytest.mark.parametrize("change", ["finished", "expired", "foreign_owner"])
async def test_consent_get_actual_request_wait_rechecks_single_use_and_owner(env, change):
    app = await registration(env)
    rid, _ = await pending(env, app)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        row = await owner.scalar(select(PartnerAuthorizationRequest).where(
            PartnerAuthorizationRequest.id == UUID(rid)).with_for_update())
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].get(
                f"/api/developer/authorization-requests/{rid}", headers=env["headers"])) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid)
                if change == "finished": row.finished = True
                if change == "expired": row.expires_at = identity.now() - timedelta(seconds=1)
                if change == "foreign_owner": row.user_id = env["member"].id
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code == {"finished": 409, "expired": 410, "foreign_owner": 404}[change]
    assert await counts(app["client_id"]) == (0, 0, 0)


@pytest.mark.parametrize("change", ["consume", "expire", "parent_expire"])
async def test_code_update_wait_rechecks_current_deadlines_and_consumption(env, change):
    app = await registration(env)
    code, _, _ = await consent(env, app)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        row = await owner.scalar(select(PartnerCode).where(PartnerCode.code_hash == identity.digest(code)).with_for_update())
        owner_pid = await pid(owner)
        async with contender(lambda: exchange(env, app, code)) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid)
                if change == "consume": row.consumed = True
                if change == "expire": row.expires_at = identity.now() - timedelta(seconds=1)
                if change == "parent_expire": row.parent_expires_at = identity.now() - timedelta(seconds=1)
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code == 400 and response.json()["error"] == "invalid_grant"
    assert await counts(app["client_id"]) == (0, 0, 1)


async def test_selected_credential_does_not_replace_original_family_credential(env):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    second = await env["client"].post(f"/api/developer/clients/{app['client_id']}/credentials", headers=env["headers"])
    assert second.status_code == 201
    async with _test_session_factory() as db:
        (await db.get(PartnerCredential, app["credential_id"])).enabled = False
        await db.commit()
    response = await env["client"].post("/api/oauth2/token", auth=(app["client_id"], second.json()["clientSecret"]),
        data={"grant_type": "refresh_token", "refresh_token": issued["refresh_token"]})
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"
    assert await counts(app["client_id"]) == (1, 1, 1)


async def test_original_b1_borrowed_connection_root_rejects_late_plan(env):
    app = await registration(env)
    issued, _ = await tokens(env, app)
    async with _test_engine.connect() as connection:
        actual_root = await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="rollback_only", expire_on_commit=False) as db:
            expected = await db.run_sync(identity.verify_access, issued["access_token"])
            writer = await db.run_sync(identity._prepare_partner_write, token_id=expected.token_id, mutation="userinfo")
            await db.run_sync(locks.require_scoped_locks, writer.capability, writer.capability.plan.requests)
            with pytest.raises(locks.ScopedLockError):
                await db.run_sync(locks.acquire_scoped_locks, writer.capability.plan)
            await db.commit()  # ORM root ends; borrowed actual DB root remains.
        assert actual_root.is_active
        async with AsyncSession(bind=connection, join_transaction_mode="rollback_only") as successor:
            with pytest.raises(locks.ScopedLockError):
                await successor.run_sync(locks.acquire_scoped_locks, writer.capability.plan)
        await actual_root.rollback()


async def test_real_reader_cap_blocks_actual_credential_revoke_until_root_end(env):
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    async with _test_session_factory() as reader, _test_session_factory() as observer:
        expected = await reader.run_sync(identity.verify_access, issued["access_token"])
        writer = await reader.run_sync(identity._prepare_partner_write, token_id=expected.token_id, mutation="userinfo")
        await reader.run_sync(identity.verify_locked_partner_access, issued["access_token"],
            capability=writer.capability, expected=expected)
        reader_pid = await pid(reader)
        key = locks.ClientKey(app["client_id"])
        async with contender(lambda: env["client"].delete(
                f"/api/developer/clients/{app['client_id']}/credentials/{app['credential_id']}", headers=env["headers"])) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], reader_pid, key)
                assert (await observer.get(PartnerCredential, app["credential_id"])).enabled
                await reader.run_sync(locks.require_scoped_locks, writer.capability, writer.capability.plan.requests)
            finally:
                await reader.rollback()
            assert (await task).status_code == 200
    assert (await env["client"].get("/api/oauth2/userinfo", headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 401


async def test_final_native_denial_after_replacement_flush_restores_complete_old_sets(env, monkeypatch):
    app = await registration(env, resources={"objects": {"mode": "ALL", "ids": []}})
    from datetime import datetime, timezone
    import jwt.api_jwt
    future = datetime.now(timezone.utc) + timedelta(days=identity.MAX_SESSION_DAYS + 1)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return future
    fired = []
    def expire_after_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO") and "partner_resource_scopes" in statement:
            fired.append(statement)
            monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)
    event.listen(_test_engine.sync_engine, "after_cursor_execute", expire_after_insert)
    try:
        response = await env["client"].post(f"/api/developer/clients/{app['client_id']}/installations",
            headers=env["headers"], json={"companyId": str(env["company"].id), "scopes": SCOPES,
                "resourceScopes": {"objects": {"mode": "EMPTY", "ids": []}}})
    finally:
        event.remove(_test_engine.sync_engine, "after_cursor_execute", expire_after_insert)
    assert fired and response.status_code == 401
    async with _test_session_factory() as db:
        profiles = (await db.scalars(select(PartnerResourceScope).where(
            PartnerResourceScope.installation_id == app["installation_id"]))).all()
        assert [(p.kind, p.mode) for p in profiles] == [("objects", "ALL")]


@pytest.mark.parametrize("confidential", [False, True])
@pytest.mark.parametrize("token_field", ["access_token", "refresh_token"])
@pytest.mark.parametrize("extra_grant_type", [None, "refresh_token", "authorization_code", "client_credentials", "unknown"])
@pytest.mark.parametrize("contradictory", [False, True])
async def test_revoke_ignored_oauth_fields_only_discover_and_revoke_requested_family(
        env, monkeypatch, confidential, token_field, extra_grant_type, contradictory):
    # Includes PW-R1 exactly: grant_type=refresh_token, no refresh_token.
    # Contradictory fields name legitimate grants/tokens owned by the same
    # native administrator under a different client, never invented authority.
    app = await registration(env, confidential=confidential)
    other = await registration(env, confidential=confidential)
    issued, _ = await tokens(env, app)
    unrelated, _ = await tokens(env, other)
    actual = await token_rows(issued["access_token"])
    decoy = await token_rows(unrelated["access_token"])
    other_code, _, _ = await consent(env, other)
    form = {"token": issued[token_field]}
    if extra_grant_type is not None:
        form["grant_type"] = extra_grant_type
        # Supported hints retain the existing access-or-refresh fallback,
        # including a hint opposite to the requested token in half the cases.
        form["token_type_hint"] = ("refresh_token" if token_field == "access_token" else "access_token") if contradictory else token_field
    if contradictory:
        form.update(refresh_token=unrelated["refresh_token"], code=other_code, grant_id=str(decoy.gid))
    auth = (app["client_id"], app["secret"]) if confidential else None
    if auth is None:
        form["client_id"] = app["client_id"]
    original, prepared = oauth._prepare_partner_write, []
    def inspect_real_plan(sync, **kwargs):
        writer = original(sync, **kwargs)  # Actual helper-issued cap and locked rows.
        if kwargs.get("mutation") == "revoke":
            locks.require_scoped_locks(sync, writer.capability, writer.capability.plan.requests)
            for model, wanted, ignored in ((PartnerToken, actual.tid, decoy.tid),
                    (PartnerTokenFamily, actual.fid, decoy.fid), (PartnerGrant, actual.gid, decoy.gid)):
                assert writer.discovered(model, wanted) and not writer.discovered(model, ignored)
            assert not any(row.model is PartnerCode for row in writer.rows)
            keys = {request.key for request in writer.capability.plan.requests}
            assert locks.ClientKey(other["client_id"]) not in keys
            assert locks.InstallationKey(decoy.iid) not in keys
            assert any(row.model is PartnerTokenFamily and row.identity == (actual.fid,)
                       and row.update for row in writer.rows)
            prepared.append(writer)
        return writer
    monkeypatch.setattr(oauth, "_prepare_partner_write", inspect_real_plan)
    response = await env["client"].post("/api/oauth2/revoke", data=form, auth=auth)
    assert response.status_code == 200 and response.json() == {}
    assert len(prepared) == 1  # Same endpoint composer; no extra plan for ignored fields.
    async with _test_session_factory() as db:
        assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is True
        assert (await db.get(PartnerTokenFamily, decoy.fid)).revoked is False
        assert (await db.get(PartnerToken, decoy.tid)).refresh_used is False
        assert (await db.get(PartnerCode, identity.digest(other_code))).consumed is False
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 401
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + unrelated["access_token"]})).status_code == 200


@pytest.mark.parametrize("authorization,empty_body_id", [(None, False), (None, True),
    ("Basic !!!", False), ("Basic Og==", False), ("Basic OnNlY3JldA==", False), ("Digest fictional", False)])
@pytest.mark.parametrize("operation,status,error", [("authorization_code", 401, "invalid_client"),
    ("refresh_token", 401, "invalid_client"), ("client_credentials", 401, "invalid_client"),
    ("unknown", 400, "unsupported_grant_type"), ("password", 400, "unsupported_grant_type"),
    (None, 400, "unsupported_grant_type"), ("revoke", 401, "invalid_client")])
async def test_identity_free_http_preserves_canonical_errors_without_writer_or_sql(
        env, monkeypatch, authorization, empty_body_id, operation, status, error):
    # Valid real code/refresh/machine/revoke material proves the denial is due
    # to missing identity, before any lookup, nonce, cap, or mutating callback.
    app = await registration(env, confidential=True)
    issued, _ = await tokens(env, app)
    code, _, _ = await consent(env, app)
    approved = await env["client"].post(f"/api/developer/installations/{app['installation_id']}/machine-grants",
        headers=env["headers"], json={"scopes": ["docs:read"]})
    assert approved.status_code == 201
    actual = await token_rows(issued["access_token"])
    before = await counts(app["client_id"])
    form = {"code": code, "redirect_uri": REDIRECT, "code_verifier": VERIFIER,
        "refresh_token": issued["refresh_token"], "grant_id": approved.json()["grantId"],
        "scope": "docs:read", "token": issued["access_token"]}
    if operation is not None:
        form["grant_type"] = operation
    if empty_body_id:
        form["client_id"] = ""
    headers = {} if authorization is None else {"Authorization": authorization}
    reached, sql = [], []
    def forbidden(*args, **kwargs):
        reached.append("forbidden")
        raise AssertionError("Identity-free request reached a writer/lookup callback")
    def record(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)
    # Observers apply only to this HTTP call, not fixture setup or later reads.
    with monkeypatch.context() as guard:
        guard.setattr(oauth, "_prepare_partner_write", forbidden)
        guard.setattr(identity, "acquire_scoped_locks", forbidden)
        for owner, method in ((identity.PartnerAuthorizationServer, "query_client"),
                (identity.PartnerAuthorizationServer, "checkpoint"),
                (identity.PartnerAuthorizationServer, "issue_token"),
                (identity.PartnerAuthorizationServer, "save_token"),
                (identity.CodeGrant, "query_authorization_code"),
                (identity.RotatingRefreshGrant, "authenticate_refresh_token"),
                (identity.RevokeEndpoint, "query_token"), (identity.RevokeEndpoint, "revoke_token"),
                (identity.PartnerOpenIDCode, "exists_nonce")):
            guard.setattr(owner, method, forbidden)
        guard.setattr(identity, "pairwise_subject", forbidden)
        event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
        try:
            response = await env["client"].post("/api/oauth2/" + ("revoke" if operation == "revoke" else "token"),
                data=form, headers=headers)
        finally:
            event.remove(_test_engine.sync_engine, "before_cursor_execute", record)
    assert response.status_code == status and response.json() == {"error": error}
    methods = ["client_secret_basic"] if operation == "client_credentials" else ["client_secret_basic", "none"]
    challenge = ('Basic error="invalid_client", error_description="The client cannot authenticate with methods: '
        + str(methods) + '"') if status == 401 else None
    assert response.headers.get("www-authenticate") == challenge
    assert response.headers["cache-control"] == "no-store" and response.headers["pragma"] == "no-cache"
    assert reached == [] and sql == []  # No SELECT/locks/DML/FK/nonce, even if fixture material is valid.
    assert await counts(app["client_id"]) == before
    async with _test_session_factory() as db:
        assert (await db.get(PartnerCode, identity.digest(code))).consumed is False
        assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is False
        assert (await db.get(PartnerToken, actual.tid)).refresh_used is False


@pytest.mark.parametrize("operation", ["token", "revoke"])
async def test_unknown_token_and_malformed_basic_keep_original_401_challenge(env, monkeypatch, operation):
    # Exact PW-R2 empty graph counterexample: no body client id/secret.
    reached = []
    def forbidden(*args, **kwargs):
        reached.append(True)
        raise AssertionError("Empty negative graph must not enter composer")
    monkeypatch.setattr(oauth, "_prepare_partner_write", forbidden)
    form = {"token": "fictionalunknown"} if operation == "revoke" else {"grant_type": "password"}
    response = await env["client"].post("/api/oauth2/" + operation, data=form,
        headers={"Authorization": "Basic !!!"})
    assert reached == []
    if operation == "revoke":
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        assert response.headers["www-authenticate"] == ('Basic error="invalid_client", '
            'error_description="The client cannot authenticate with methods: [\'client_secret_basic\', \'none\']"')
    else:
        assert response.status_code == 400 and response.json() == {"error": "unsupported_grant_type"}
        assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("operation", ["token", "revoke"])
@pytest.mark.parametrize("unexpected", [(200, {"access_token": "must-not-publish"}, []),
    (302, {}, [("Location", "https://example.invalid")]), (400, {}, []), None])
async def test_identity_free_unexpected_nonerror_rolls_back_real_root(env, monkeypatch, operation, unexpected):
    def wrong_result(*args, **kwargs):
        return unexpected
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected validation result must never fall through to composer")
    monkeypatch.setattr(oauth, "_prepare_partner_write", forbidden)
    method = "create_endpoint_response" if operation == "revoke" else "create_token_response"
    monkeypatch.setattr(identity.PartnerAuthorizationServer, method, wrong_result)
    async with _test_session_factory() as db:
        await db.scalar(select(PartnerClient.id).limit(1))  # Actual root exists.
        with pytest.raises(locks.ScopedLockError, match="must only return an error"):
            await db.run_sync(oauth._protocol_response, identity.ProtocolRequest("POST", {}), operation == "revoke")
        assert not db.in_transaction()  # Whole root rollback, not a savepoint or successful publication.


@pytest.mark.parametrize("operation,auth_mode", [("authorization_code", "public"),
    ("refresh_token", "public"), ("revoke", "public"), ("authorization_code", "confidential"),
    ("refresh_token", "confidential"), ("client_credentials", "confidential"), ("revoke", "confidential"),
    ("authorization_code", "bad-secret"), ("refresh_token", "bad-secret"),
    ("client_credentials", "bad-secret"), ("revoke", "bad-secret"),
    ("authorization_code", "unknown-basic"), ("refresh_token", "unknown-basic"),
    ("client_credentials", "unknown-basic"), ("revoke", "unknown-basic")])
async def test_identity_present_controls_use_real_composer_once_and_canonical_auth(env, monkeypatch, operation, auth_mode):
    app = await registration(env, confidential=auth_mode != "public")
    issued, _ = await tokens(env, app)
    actual = await token_rows(issued["access_token"])
    code, _, _ = await consent(env, app)
    form = {"grant_type": operation, "code": code, "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER, "refresh_token": issued["refresh_token"], "token": issued["access_token"]}
    if operation == "client_credentials":
        approved = await env["client"].post(f"/api/developer/installations/{app['installation_id']}/machine-grants",
            headers=env["headers"], json={"scopes": ["docs:read"]})
        assert approved.status_code == 201
        form.update(grant_id=approved.json()["grantId"], scope="docs:read")
    client_id = "unknown-" + uuid4().hex if auth_mode == "unknown-basic" else app["client_id"]
    auth = None if auth_mode == "public" else (client_id,
        app["secret"] if auth_mode == "confidential" else "wrong-secret")
    if auth is None:
        form["client_id"] = client_id
    original, prepared = oauth._prepare_partner_write, []
    def inspect_real_plan(sync, **kwargs):
        writer = original(sync, **kwargs)
        locks.require_scoped_locks(sync, writer.capability, writer.capability.plan.requests)
        keys = {request.key for request in writer.capability.plan.requests}
        assert locks.ClientKey(client_id) in keys
        assert writer.rows and writer.discovered(PartnerClient, client_id) == (auth_mode != "unknown-basic")
        assert any(row.model is PartnerClient and row.identity == (client_id,)
                   and row.missing == (auth_mode == "unknown-basic") for row in writer.rows)
        if operation == "authorization_code":
            assert writer.discovered(PartnerCode, identity.digest(code))
        elif operation in {"refresh_token", "revoke"}:
            assert writer.discovered(PartnerToken, actual.tid) and writer.discovered(PartnerTokenFamily, actual.fid)
        else:
            assert writer.discovered(PartnerGrant, UUID(form["grant_id"]))
        prepared.append(writer)
        return writer
    monkeypatch.setattr(oauth, "_prepare_partner_write", inspect_real_plan)
    before = await counts(app["client_id"])
    response = await env["client"].post("/api/oauth2/" + ("revoke" if operation == "revoke" else "token"),
        data=form, auth=auth)
    assert len(prepared) == 1
    if auth_mode in {"bad-secret", "unknown-basic"}:
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        description = ("The client does not exist on this server." if auth_mode == "unknown-basic" else
            "The client cannot authenticate with methods: " + str(["client_secret_basic"] if operation == "client_credentials"
                else ["client_secret_basic", "none"]))
        assert response.headers["www-authenticate"] == ('Basic error="invalid_client", error_description="' + description + '"')
        assert await counts(app["client_id"]) == before
        async with _test_session_factory() as db:
            assert (await db.get(PartnerCode, identity.digest(code))).consumed is False
            assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is False
            assert (await db.get(PartnerToken, actual.tid)).refresh_used is False
    elif operation == "revoke":
        assert response.status_code == 200 and response.json() == {}
        async with _test_session_factory() as db:
            assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is True
    else:
        assert response.status_code == 200 and "www-authenticate" not in response.headers
        async with _test_session_factory() as db:
            current = await db.run_sync(identity.verify_access, response.json()["access_token"])
            assert current.client_id == app["client_id"] and current.is_machine == (operation == "client_credentials")


@pytest.mark.parametrize("confidential", [False, True])
@pytest.mark.parametrize("token_field", ["access_token", "refresh_token"])
async def test_revoke_extra_fields_preserve_unknown_repeat_wrong_client_and_hint_errors(env, confidential, token_field):
    app = await registration(env, confidential=confidential)
    other = await registration(env, confidential=confidential)
    issued, _ = await tokens(env, app)
    unrelated, _ = await tokens(env, other)
    actual, decoy = await token_rows(issued["access_token"]), await token_rows(unrelated["access_token"])
    other_code, _, _ = await consent(env, other)
    form = {"token": issued[token_field], "grant_type": "refresh_token",
        "refresh_token": unrelated["refresh_token"], "code": other_code, "grant_id": str(decoy.gid)}
    auth = (app["client_id"], app["secret"]) if confidential else None
    if auth is None:
        form["client_id"] = app["client_id"]
    unknown = await env["client"].post("/api/oauth2/revoke",
        data={**form, "token": "unknown-" + uuid4().hex}, auth=auth)
    assert unknown.status_code == 200 and unknown.json() == {}
    invalid_hint = await env["client"].post("/api/oauth2/revoke",
        data={**form, "token_type_hint": "unsupported"}, auth=auth)
    assert invalid_hint.status_code == 400 and invalid_hint.json()["error"] == "unsupported_token_type"
    foreign_auth = (other["client_id"], other["secret"]) if confidential else None
    foreign_form = dict(form)
    if foreign_auth is None:
        foreign_form["client_id"] = other["client_id"]
    wrong_client = await env["client"].post("/api/oauth2/revoke", data=foreign_form, auth=foreign_auth)
    assert wrong_client.status_code == 400 and wrong_client.json()["error"] == "invalid_grant"
    async with _test_session_factory() as db:
        assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is False
        assert (await db.get(PartnerTokenFamily, decoy.fid)).revoked is False
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 200
    for _ in range(2):
        response = await env["client"].post("/api/oauth2/revoke", data=form, auth=auth)
        assert response.status_code == 200 and response.json() == {}
    async with _test_session_factory() as db:
        assert (await db.get(PartnerTokenFamily, actual.fid)).revoked is True
        assert (await db.get(PartnerTokenFamily, decoy.fid)).revoked is False
        assert (await db.get(PartnerCode, identity.digest(other_code))).consumed is False
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + issued["access_token"]})).status_code == 401
    assert (await env["client"].get("/api/oauth2/userinfo",
        headers={"Authorization": "Bearer " + unrelated["access_token"]})).status_code == 200


@pytest.mark.parametrize("mutation,confidential", [("token-code", False), ("token-code", True),
    ("token-refresh", False), ("token-refresh", True), ("token-machine", True)])
async def test_token_branch_ignores_fields_of_other_protocol_branches(env, monkeypatch, mutation, confidential):
    app = await registration(env, confidential=confidential)
    other = await registration(env)
    unrelated, _ = await tokens(env, other)
    decoy = await token_rows(unrelated["access_token"])
    other_code, _, _ = await consent(env, other)
    form = {"token": unrelated["access_token"], "refresh_token": unrelated["refresh_token"],
        "code": other_code, "grant_id": str(decoy.gid), "redirect_uri": REDIRECT, "code_verifier": VERIFIER}
    actual_token_id = None
    if mutation == "token-code":
        code, _, _ = await consent(env, app)
        form.update(grant_type="authorization_code", code=code)
        async with _test_session_factory() as db:
            expected_grant = (await db.get(PartnerCode, identity.digest(code))).grant_id
    elif mutation == "token-refresh":
        issued, _ = await tokens(env, app)
        actual = await token_rows(issued["access_token"])
        actual_token_id, expected_grant = actual.tid, actual.gid
        form.update(grant_type="refresh_token", refresh_token=issued["refresh_token"])
    else:
        approved = await env["client"].post(f"/api/developer/installations/{app['installation_id']}/machine-grants",
            headers=env["headers"], json={"scopes": ["docs:read"]})
        assert approved.status_code == 201
        expected_grant = UUID(approved.json()["grantId"])
        form.update(grant_type="client_credentials", grant_id=str(expected_grant), scope="docs:read")
    auth = (app["client_id"], app["secret"]) if confidential else None
    if auth is None:
        form["client_id"] = app["client_id"]
    original, prepared = oauth._prepare_partner_write, []
    def inspect_real_plan(sync, **kwargs):
        writer = original(sync, **kwargs)
        if kwargs.get("mutation") == mutation:
            locks.require_scoped_locks(sync, writer.capability, writer.capability.plan.requests)
            assert writer.discovered(PartnerGrant, expected_grant)
            assert not writer.discovered(PartnerGrant, decoy.gid)
            assert not writer.discovered(PartnerToken, decoy.tid)
            assert not writer.discovered(PartnerTokenFamily, decoy.fid)
            if actual_token_id is not None:
                assert writer.discovered(PartnerToken, actual_token_id)
            if mutation != "token-code":
                assert not any(row.model is PartnerCode for row in writer.rows)
            keys = {request.key for request in writer.capability.plan.requests}
            assert locks.ClientKey(other["client_id"]) not in keys
            assert locks.InstallationKey(decoy.iid) not in keys
            prepared.append(writer)
        return writer
    monkeypatch.setattr(oauth, "_prepare_partner_write", inspect_real_plan)
    response = await env["client"].post("/api/oauth2/token", data=form, auth=auth)
    assert response.status_code == 200 and len(prepared) == 1
    async with _test_session_factory() as db:
        verified = await db.run_sync(identity.verify_access, response.json()["access_token"])
        assert verified.client_id == app["client_id"] and verified.grant_id == expected_grant
        assert verified.is_machine == (mutation == "token-machine")
        assert (await db.get(PartnerTokenFamily, decoy.fid)).revoked is False
        assert (await db.get(PartnerToken, decoy.tid)).refresh_used is False
        assert (await db.get(PartnerCode, identity.digest(other_code))).consumed is False
