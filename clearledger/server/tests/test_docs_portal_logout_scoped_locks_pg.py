"""AUTHORED / NOTRUN, including collection: actual docs logout PG definitions.

Both existing docs/partner opt-ins are needed for unchanged shared helpers.
Module guards DO NOT admit parent conftest, which imports app/engine and drops
schemas. A fresh ROOT-owned combined HEAD/schema4/URL/approval/receipt is required
BEFORE collection/import; none is supplied or created here. No runner changes.
Inherited driver UUID exact-type prerequisite was reported by ROOT in
msg_428ad8a783cc (relayed msg_ed2dca1de15c); no local casts or oracle weakening.
"""
import os

import pytest
from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_DOCS_PORTAL_TESTS") != "1" or os.environ.get("RUN_PARTNER_IDENTITY_TESTS") != "1":
    pytest.skip("Both existing docs/partner opt-ins required; author runtime NOT_GRANTED", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_DOCS_PORTAL_TESTS"):
    raise RuntimeError(error)
if os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Only an admitted matching isolated composition is permitted")

import asyncio
import re
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.util import await_only

from app.auth import token_for
from app.models import App, Company, CompanyApp, CompanyRole, User, UserCompany
from app.models_docs_portal import DocsPortalSession
from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation, PartnerToken, PartnerTokenFamily
from app.services import docs_portal as portal, partner_identity as identity, contract_write_locks as locks
from tests.conftest import _test_engine, _test_session_factory
from tests.test_docs_portal import env, session, ORIGIN, CALLBACK, VERIFIER, CHALLENGE
from tests.test_partner_identity import registration
from tests.test_partner_writer_scoped_locks_pg import contender, observed_wait, pid

pytestmark = pytest.mark.asyncio(loop_scope="session")
URL = portal.PREFIX + "/session"


def proof(raw, **extra):
    return {"Cookie": portal.COOKIE + "=" + raw, "Origin": ORIGIN, "X-Docs-CSRF": portal.csrf(raw), **extra}


def private(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def closed_wire(response):
    assert response.status_code == 204 and response.content == b"", response.text
    private(response)
    cookie = response.headers["set-cookie"]
    assert all(v in cookie for v in (portal.COOKIE + "=", "Max-Age=0", "expires=", "HttpOnly", "Secure", "SameSite=strict", "Path=" + portal.PREFIX))
    assert "location" not in response.headers and "www-authenticate" not in response.headers


async def browser(env):
    response, access = await session(env)
    raw = env["client"].cookies.get(portal.COOKIE)
    assert raw and response.json()["csrfToken"] == portal.csrf(raw)
    async with _test_session_factory() as db:
        token = await db.scalar(select(PartnerToken).where(PartnerToken.access_hash == identity.digest(access)))
        family = await db.get(PartnerTokenFamily, token.family_id)
        grant = await db.get(PartnerGrant, family.grant_id)
        return SimpleNamespace(raw=raw, access=access, tid=token.id, fid=family.id, gid=grant.id,
            cid=grant.company_id, iid=grant.installation_id, uid=grant.user_id, client_id=grant.client_id)


async def state(data):
    """Always a new observer root; never accept an identity-map flag as durability."""
    async with _test_session_factory() as db:
        row = await db.get(DocsPortalSession, identity.digest(data.raw))
        token = await db.get(PartnerToken, data.tid)
        family = await db.get(PartnerTokenFamily, data.fid)
        grant = await db.get(PartnerGrant, data.gid)
        return (None if row is None else row.revoked, None if family is None else family.revoked,
            None if token is None else (token.revoked, token.family_id), None if grant is None else grant.approved)


async def verify(access):
    async with _test_session_factory() as db:
        return await identity.verify_partner_access_token(access, db)


async def issue(env, scopes=None, client_id=None):
    """A distinct real consent/code exchange; no constant-nonce fixture reuse."""
    scopes = scopes or ["openid", "docs:read"]
    client_id = client_id or env["registration"]["clientId"]
    ac = env["client"]
    response = await ac.get("/api/oauth2/authorize", params={"client_id": client_id, "response_type": "code",
        "redirect_uri": CALLBACK, "scope": " ".join(scopes), "state": uuid4().hex, "nonce": uuid4().hex,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    assert response.status_code == 302, response.text
    rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
    headers = {"Authorization": "Bearer " + env["core"]}
    assert (await ac.get("/api/developer/authorization-requests/" + rid, headers=headers)).status_code == 200
    accepted = await ac.post("/api/developer/authorization-requests/" + rid + "/approve", headers=headers,
        json={"companyId": str(env["company"].id), "scopes": scopes})
    assert accepted.status_code == 200, accepted.text
    code = parse_qs(urlsplit(accepted.json()["redirectUrl"]).query)["code"][0]
    result = await ac.post("/api/oauth2/token", data={"client_id": client_id, "grant_type": "authorization_code",
        "redirect_uri": CALLBACK, "code": code, "code_verifier": VERIFIER})
    assert result.status_code == 200, result.text
    return result.json()["access_token"]


@contextmanager
def sql_log():
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", record)


async def row_owner(db, data, kind):
    if kind == "typed":
        await locks.acquire_scoped_locks_async(db, locks.LockPlan((locks.LockRequest(locks.ClientKey(data.client_id), locks.LockMode.EXCLUSIVE),)))
    elif kind == "family":
        await db.scalar(select(PartnerTokenFamily).where(PartnerTokenFamily.id == data.fid).with_for_update())
    elif kind == "docs":
        await db.scalar(select(DocsPortalSession).where(DocsPortalSession.cookie_hash == identity.digest(data.raw)).with_for_update())
    else:
        raise AssertionError(kind)


@contextmanager
def row_signal():
    """Identify the actual request Connection at any canonical lock, no sleeps."""
    ready, info = asyncio.Event(), {}
    def record(conn, cursor, statement, parameters, context, executemany):
        if not ready.is_set() and ("pg_advisory_xact_lock" in statement or "FOR UPDATE" in statement):
            info["pid"] = conn.scalar(text("SELECT pg_backend_pid()"))
            ready.set()
    event.listen(_test_engine.sync_engine, "before_cursor_execute", record)
    try:
        yield ready, info
    finally:
        event.remove(_test_engine.sync_engine, "before_cursor_execute", record)


async def test_logout_success_persists_only_bound_docs_and_family_before_response(env):
    data = await browser(env)
    async with _test_session_factory() as db:
        constraints = (await db.execute(text("""SELECT child.relname, parent.relname,
            c.convalidated, c.condeferrable FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_class child ON child.oid=c.conrelid
            JOIN pg_catalog.pg_class parent ON parent.oid=c.confrelid
            WHERE c.contype='f' AND c.conrelid IN (
              to_regclass('partner_docs_sessions'),to_regclass('partner_tokens'),
              to_regclass('partner_token_families'))"""))).all()
        pairs = {(row[0], row[1]) for row in constraints if row[2] and not row[3]}
        assert {("partner_docs_sessions", "partner_tokens"), ("partner_tokens", "partner_token_families"),
            ("partner_token_families", "partner_grants")} <= pairs
    before = await state(data)
    closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    after = await state(data)
    assert before[:2] == (False, False) and after[:2] == (True, True)
    assert after[2:] == before[2:]
    with pytest.raises(HTTPException) as denied:
        await verify(data.access)
    assert denied.value.status_code == 401
    assert (await env["client"].get(portal.PREFIX + "/ui", headers={"Cookie": portal.COOKIE + "=" + data.raw})).status_code == 401


async def test_logout_unknown_cookie_is_noop_and_missing_cookie_is403(env, monkeypatch):
    calls, flushes = [], []
    original = identity._prepare_partner_write
    def observed(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(identity, "_prepare_partner_write", observed)
    def before_flush(sync, context, instances): flushes.append(sync)
    event.listen(Session, "before_flush", before_flush)
    try:
        with sql_log() as statements:
            closed_wire(await env["client"].delete(URL, headers=proof("synthetic-unknown-cookie")))
    finally:
        event.remove(Session, "before_flush", before_flush)
    assert not calls and not flushes and not any(s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for s in statements)
    for raw in (None, ""):
        headers = {"Origin": ORIGIN, **({"Cookie": portal.COOKIE + "=" + raw} if raw is not None else {})}
        response = await env["client"].delete(URL, headers=headers)
        assert response.status_code == 403 and response.json() == {"detail": "Docs CSRF proof required"}
        assert "set-cookie" not in response.headers
        private(response)


@pytest.mark.parametrize("cause", ["repeat", "docs_revoked", "token_revoked", "family_revoked", "docs_expired", "token_expired", "family_expired"])
async def test_logout_repeated_and_already_revoked_keep_cleanup_semantics(env, cause):
    data = await browser(env)
    if cause == "repeat":
        closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    else:
        async with _test_session_factory() as db:
            model, key = (DocsPortalSession, identity.digest(data.raw)) if cause.startswith("docs") else (
                (PartnerToken, data.tid) if cause.startswith("token") else (PartnerTokenFamily, data.fid))
            row = await db.get(model, key)
            if cause.endswith("expired"):
                row.expires_at = identity.now() - timedelta(seconds=1)
            else:
                row.revoked = True
            await db.commit()
    closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    assert (await state(data))[:2] == (True, True)
    assert (await env["client"].delete(URL, headers={"Origin": ORIGIN})).status_code == 403


@pytest.mark.parametrize("cause,status,detail", [
    ("query", 400, "Documentation configuration overrides are forbidden"),
    ("origin", 403, "Same-space Origin required"), ("csrf", 403, "Docs CSRF proof required"),
    ("missing_csrf", 403, "Docs CSRF proof required"), ("disabled", 503, None)])
async def test_logout_origin_csrf_and_query_errors_preserve_precedence(env, monkeypatch, cause, status, detail):
    data = await browser(env)
    headers, url = proof(data.raw), URL
    if cause == "query":
        url += "?token=ignored"; headers.update(Origin="https://foreign.invalid", **{"X-Docs-CSRF": "wrong"})
    if cause == "origin": headers.update(Origin="https://foreign.invalid", **{"X-Docs-CSRF": "wrong"})
    if cause == "csrf": headers["X-Docs-CSRF"] = "wrong"
    if cause == "missing_csrf": del headers["X-Docs-CSRF"]
    if cause == "disabled": monkeypatch.setattr(portal.settings, "partner_docs_enabled", False)
    before = await state(data)
    response = await env["client"].delete(url, headers=headers)
    assert response.status_code == status and "set-cookie" not in response.headers
    if detail: assert response.json() == {"detail": detail}
    private(response)
    assert await state(data) == before


@pytest.mark.parametrize("selector", ["native", "partner", "company", "json", "form"])
async def test_logout_uses_cookie_graph_not_foreign_actor_company_or_body(env, selector):
    data = await browser(env)
    other = await issue(env)
    other_verified = await verify(other)
    headers, kwargs = proof(data.raw), {}
    if selector == "native": headers["Authorization"] = "Bearer " + env["core"]
    if selector == "partner": headers["Authorization"] = "Bearer " + other
    if selector == "company": headers["X-Company-Id"] = str(uuid4())
    if selector in ("json", "form"):
        kwargs["json" if selector == "json" else "data"] = {"token": other, "grant_id": str(other_verified.grant_id), "client_id": other_verified.client_id}
    closed_wire(await env["client"].request("DELETE", URL, headers=headers, **kwargs))
    assert (await state(data))[:2] == (True, True)
    assert (await verify(other)).token_id == other_verified.token_id


@pytest.mark.parametrize("wrong_raw", ["other", "unknown"])
async def test_logout_wrong_csrf_for_another_session_cannot_revoke_either(env, wrong_raw):
    data = await browser(env)
    other = await issue(env)
    created = await env["client"].post(URL, headers={"Origin": ORIGIN, "X-Docs-CSRF": "bootstrap", "Authorization": "Bearer " + other})
    assert created.status_code == 200, created.text
    other_raw = env["client"].cookies.get(portal.COOKIE)
    raw = other_raw if wrong_raw == "other" else "synthetic-unknown-cookie"
    response = await env["client"].delete(URL, headers={**proof(raw), "X-Docs-CSRF": portal.csrf(data.raw)})
    assert response.status_code == 403 and "set-cookie" not in response.headers
    private(response)
    assert (await state(data))[:2] == (False, False)
    assert (await verify(data.access)).token_id == data.tid
    await verify(other)
    async with _test_session_factory() as db:
        assert not (await db.get(DocsPortalSession, identity.digest(other_raw))).revoked


@pytest.mark.parametrize("change", ["docs_token", "token_family", "family_grant"])
async def test_logout_original_docs_token_binding_drift_rolls_back(env, change):
    data = await browser(env)
    other = await issue(env)
    other_verified = await verify(other)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        other_token = await owner.get(PartnerToken, other_verified.token_id)
        other_family = await owner.get(PartnerTokenFamily, other_token.family_id)
        await row_owner(owner, data, "typed")
        owner_pid = await pid(owner)
        async with contender(lambda: env["client"].delete(URL, headers=proof(data.raw))) as (task, info):
            try:
                await observed_wait(observer, task, info["pid"], owner_pid, locks.ClientKey(data.client_id))
                if change == "docs_token": (await owner.get(DocsPortalSession, identity.digest(data.raw))).token_id = other_token.id
                if change == "token_family": (await owner.get(PartnerToken, data.tid)).family_id = other_family.id
                if change == "family_grant": (await owner.get(PartnerTokenFamily, data.fid)).grant_id = other_family.grant_id
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
        assert response.status_code == 409 and "set-cookie" not in response.headers
        private(response)
    assert (await state(data))[:2] == (False, False)
    assert (await verify(other)).token_id == other_verified.token_id


@pytest.mark.parametrize("wait,change", [
    ("typed", "native_tv"), ("typed", "member"), ("typed", "role"),
    ("typed", "grant"), ("typed", "client"), ("typed", "installation"), ("typed", "ca"),
    ("family", "family_expired"), ("family", "token_revoked"),
    ("docs", "docs_expired"), ("docs", "docs_revoked")])
async def test_logout_native_and_partner_revocation_after_wait_still_allows_cleanup(env, wait, change):
    data = await browser(env)
    role_id = None
    if change == "role":
        async with _test_session_factory() as db:
            role = CompanyRole(company_id=data.cid, name="Synthetic logout role", modules=["developer:docs"])
            db.add(role); await db.flush()
            member = await db.get(UserCompany, (data.uid, data.cid))
            member.role = "user"; member.role_id = role.id
            role_id = role.id
            await db.commit()
        await verify(data.access)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        await row_owner(owner, data, wait)
        owner_pid = await pid(owner)
        with row_signal() as (ready, info):
            task = asyncio.create_task(env["client"].delete(URL, headers=proof(data.raw)))
            try:
                await ready.wait()
                await observed_wait(observer, task, info["pid"], owner_pid, locks.ClientKey(data.client_id) if wait == "typed" else None)
                # At Family/Docs waits upstream authority SHARE rows are already
                # held. Mutate only the blocker's actual downstream row there;
                # native/parent revocations use the earlier typed Client wait.
                if change == "docs_expired":
                    (await owner.get(DocsPortalSession, identity.digest(data.raw))).expires_at = identity.now() - timedelta(seconds=1)
                elif change == "docs_revoked":
                    (await owner.get(DocsPortalSession, identity.digest(data.raw))).revoked = True
                elif change == "native_tv": (await owner.get(User, data.uid)).token_version += 1
                elif change == "member": await owner.delete(await owner.get(UserCompany, (data.uid, data.cid)))
                elif change == "role":
                    (await owner.get(CompanyRole, role_id)).modules = []
                elif change == "grant": (await owner.get(PartnerGrant, data.gid)).approved = False
                elif change == "client": (await owner.get(PartnerClient, data.client_id)).enabled = False
                elif change == "installation": (await owner.get(PartnerInstallation, data.iid)).approved = False
                elif change == "ca": (await owner.get(CompanyApp, data.iid)).enabled = False
                elif change == "family_expired": (await owner.get(PartnerTokenFamily, data.fid)).expires_at = identity.now() - timedelta(seconds=1)
                elif change == "token_revoked": (await owner.get(PartnerToken, data.tid)).revoked = True
                await owner.commit()
                response = await task
            finally:
                await owner.rollback()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        closed_wire(response)
    assert (await state(data))[:2] == (True, True)
    with pytest.raises(HTTPException): await verify(data.access)


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
@pytest.mark.parametrize("raw_kind", ["known", "empty"])
async def test_logout_dirty_expired_entry_rejects_without_sql_flush_or_expire(env, monkeypatch, pending, raw_kind):
    data = await browser(env)
    async with _test_session_factory() as db:
        user = await db.get(User, data.uid)
        docs = await db.get(DocsPortalSession, identity.digest(data.raw))
        db.expire(user); db.expire(docs)
        if pending == "new": db.add(Company(name="Never flushed", slug="pending-" + uuid4().hex, profile_id="energy"))
        elif pending == "dirty": user.name = "Never persisted"
        else: await db.delete(docs)
        root = db.sync_session.get_transaction()
        calls = []
        original_flush, original_expire = db.sync_session.flush, db.sync_session.expire
        def flush(*a, **k): calls.append("flush"); return original_flush(*a, **k)
        def expire(*a, **k): calls.append("expire"); return original_expire(*a, **k)
        monkeypatch.setattr(db.sync_session, "flush", flush)
        monkeypatch.setattr(db.sync_session, "expire", expire)
        with sql_log() as statements:
            with pytest.raises(locks.ScopedLockError):
                await db.run_sync(portal.close_session, data.raw if raw_kind == "known" else "")
        assert not statements and not calls and db.sync_session.get_transaction() is root
        await db.rollback()
    assert (await state(data))[:2] == (False, False)


async def test_logout_actual_lock_order_and_original_capability(env, monkeypatch):
    data = await browser(env)
    original, issued = locks.acquire_scoped_locks, []
    def acquire(sync, plan):
        cap = original(sync, plan)
        locks.require_scoped_locks(sync, cap, plan.requests)
        issued.append((sync, sync.get_transaction(), cap))
        return cap
    # identity's imported alias calls the actual issuer, not a fabricated cap.
    monkeypatch.setattr(identity, "acquire_scoped_locks", acquire)
    with sql_log() as statements:
        closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    assert len(issued) == 1
    plan = issued[0][2].plan
    expected = (locks.ClientKey(data.client_id), locks.CompanyKey(data.cid), locks.InstallationKey(data.iid),
        locks.UserKey(data.uid), locks.MemberKey(data.cid, data.uid))
    assert all(any(r.key == key and r.mode is locks.LockMode.SHARED for r in plan.requests) for key in expected)
    def locked(table, mode):
        pattern = r'\bFROM\s+(?:[\w"]+\.)?"?' + table + r'"?\b'
        return next(i for i, s in enumerate(statements) if re.search(pattern, s) and mode in s)
    family = locked("partner_token_families", "FOR UPDATE")
    token = locked("partner_tokens", "FOR SHARE")
    docs = locked("partner_docs_sessions", "FOR UPDATE")
    writes = [i for i, s in enumerate(statements) if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
    assert family < token < docs < min(writes)
    family_write = next(i for i in writes if "partner_token_families" in statements[i])
    docs_write = next(i for i in writes if "partner_docs_sessions" in statements[i])
    assert family_write < docs_write and len(writes) == 2
    async with _test_session_factory() as fresh:
        with pytest.raises(locks.ScopedLockError):
            await fresh.run_sync(locks.require_scoped_locks, issued[0][2], plan.requests)


@pytest.mark.parametrize("stage", ["family", "docs", "checkpoint"])
async def test_logout_rollback_after_callback_flush_restores_both_rows(env, monkeypatch, stage):
    data = await browser(env)
    target, counts = {}, {}
    original_close, original_checkpoint = portal.close_session, identity._PartnerWrite.checkpoint
    def close(sync, raw):
        target["sync"] = sync
        return original_close(sync, raw)
    def after_flush(sync, context):
        if sync is target.get("sync"):
            counts["flush"] = counts.get("flush", 0) + 1
            if (stage == "family" and counts["flush"] == 1) or (stage == "docs" and counts["flush"] == 2):
                raise RuntimeError("controlled post-flush failure")
    def checkpoint(writer):
        result = original_checkpoint(writer)
        if writer.db is target.get("sync") and stage == "checkpoint" and counts.get("flush", 0) >= 2:
            raise HTTPException(409, "controlled final checkpoint refusal")
        return result
    monkeypatch.setattr(portal, "close_session", close)
    monkeypatch.setattr(identity._PartnerWrite, "checkpoint", checkpoint)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        if stage == "checkpoint":
            response = await env["client"].delete(URL, headers=proof(data.raw))
            assert response.status_code == 409 and "set-cookie" not in response.headers
        else:
            with pytest.raises(RuntimeError, match="controlled post-flush failure"):
                await env["client"].delete(URL, headers=proof(data.raw))
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
    assert counts["flush"] == (1 if stage == "family" else 2)
    assert (await state(data))[:2] == (False, False)
    assert (await verify(data.access)).token_id == data.tid


@pytest.mark.parametrize("stage", ["family", "docs", "precommit"])
async def test_logout_cancel_before_commit_restores_both_rows_and_releases_locks(env, monkeypatch, stage):
    data = await browser(env)
    original, ready, release = portal.close_session, asyncio.Event(), asyncio.Event()
    if stage == "precommit":
        def paused(sync, raw):
            result = original(sync, raw)
            ready.set()
            await_only(release.wait())
            return result
        monkeypatch.setattr(portal, "close_session", paused)
    async with _test_session_factory() as owner, _test_session_factory() as observer:
        if stage != "precommit": await row_owner(owner, data, stage)
        owner_pid = await pid(owner)
        with row_signal() as (locked, info):
            task = asyncio.create_task(env["client"].delete(URL, headers=proof(data.raw)))
            try:
                if stage == "precommit": await ready.wait()
                else:
                    await locked.wait()
                    await observed_wait(observer, task, info["pid"], owner_pid)
                task.cancel()
                result, = await asyncio.gather(task, return_exceptions=True)
                assert isinstance(result, asyncio.CancelledError)
            finally:
                release.set()
                await owner.rollback()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert (await state(data))[:2] == (False, False)
    async with _test_session_factory() as db:
        await row_owner(db, data, "family")
        await row_owner(db, data, "docs")
        await db.rollback()


async def test_logout_failed_commit_has_no_success_response(env, monkeypatch):
    data = await browser(env)
    original, target = portal.close_session, {}
    def close(sync, raw):
        result = original(sync, raw)
        target["sync"] = sync
        return result
    def refuse(sync):
        if sync is target.get("sync"):
            raise RuntimeError("controlled before-commit refusal")
    monkeypatch.setattr(portal, "close_session", close)
    event.listen(Session, "before_commit", refuse)
    try:
        with pytest.raises(RuntimeError, match="controlled before-commit refusal"):
            await env["client"].delete(URL, headers=proof(data.raw))
    finally:
        event.remove(Session, "before_commit", refuse)
    assert (await state(data))[:2] == (False, False)
    assert (await verify(data.access)).token_id == data.tid
    # No inference about errors after PostgreSQL committed but lost its ACK.


@pytest.mark.parametrize("when", ["initial", "after_parent_rows", "empty_graph"])
async def test_logout_cascade_missing_and_already_deleted_noop(env, monkeypatch, when):
    data = await browser(env)
    original = identity._prepare_partner_write
    if when == "initial":
        async with _test_session_factory() as db:
            await db.execute(delete(PartnerToken).where(PartnerToken.id == data.tid))
            await db.commit()
        assert (await state(data))[0] is None  # Real CASCADE, not disabled constraints.
    else:
        def prepare(sync, **kwargs):
            if when == "after_parent_rows":
                writer = original(sync, **kwargs)
                # Another real root deletes Docs only: no parent lock inverse.
                async def remove():
                    async with _test_session_factory() as other:
                        await other.execute(delete(DocsPortalSession).where(DocsPortalSession.cookie_hash == identity.digest(data.raw)))
                        await other.commit()
                await_only(remove())
                return writer
            # Before original composer discovery; actual Token CASCADE removes Docs.
            async def cascade():
                async with _test_session_factory() as other:
                    await other.execute(delete(PartnerToken).where(PartnerToken.id == data.tid))
                    await other.commit()
            await_only(cascade())
            return original(sync, **kwargs)
        monkeypatch.setattr(identity, "_prepare_partner_write", prepare)
    closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    result = await state(data)
    assert result[0] is None and result[1] is False


@pytest.mark.parametrize("other_kind", ["same_grant", "business", "machine", "other_company"])
async def test_logout_does_not_cross_family_for_same_grant_or_other_company(env, other_kind):
    data = await browser(env)
    if other_kind == "machine":
        pe = {**env, "headers": {"Authorization": "Bearer " + env["core"]}}
        app = await registration(pe, confidential=True, scopes=["objects:read"])
        grant = await env["client"].post(f'/api/developer/installations/{app["installation_id"]}/machine-grants',
            headers=pe["headers"], json={"scopes": ["objects:read"]})
        assert grant.status_code == 201, grant.text
        result = await env["client"].post("/api/oauth2/token", auth=(app["client_id"], app["secret"]),
            data={"grant_type": "client_credentials", "grant_id": grant.json()["grantId"], "scope": "objects:read"})
        assert result.status_code == 200, result.text
        other = result.json()["access_token"]
    elif other_kind == "other_company":
        async with _test_session_factory() as db:
            company = Company(name="Foreign synthetic logout", slug="logout-" + uuid4().hex, profile_id="energy")
            db.add(company); await db.flush()
            user = User(company_id=company.id, email=uuid4().hex + "@example.test", name="Foreign synthetic user",
                password_hash=env["user"].password_hash, role="user", is_superadmin=False)
            db.add(user); await db.flush()
            db.add(UserCompany(user_id=user.id, company_id=company.id, role="admin")); await db.commit()
            foreign = {**env, "company": company, "user": user, "core": token_for(user, expires_at=identity.now() + timedelta(minutes=20))}
        installed = await env["client"].post(f'/api/developer/clients/{data.client_id}/installations',
            headers={"Authorization": "Bearer " + foreign["core"]}, json={"companyId": str(company.id),
                "scopes": ["openid", "docs:read"], "locationIds": None, "resourceScopes": {}})
        assert installed.status_code == 201, installed.text
        other = await issue(foreign)
    else:
        other = await issue(env, ["objects:read"] if other_kind == "business" else None)
        if other_kind == "same_grant":
            # Real FK-consistent sibling family under the same grant. Alter only
            # the test setup link; same user/client/scope/installation remain.
            other_verified = await verify(other)
            async with _test_session_factory() as db:
                token = await db.get(PartnerToken, other_verified.token_id)
                family = await db.get(PartnerTokenFamily, token.family_id)
                family.grant_id = data.gid
                await db.commit()
    verified = await verify(other)
    closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
    assert (await state(data))[:2] == (True, True)
    assert (await verify(other)) == verified
    if other_kind == "machine": assert verified.is_machine and verified.user_id is None
    if other_kind == "other_company": assert verified.company_id != data.cid


async def test_existing17_retain_source_contracts_and_public_outcomes(env):
    data = await browser(env)
    # Existing17 remains protected byte/AST; exercise ordinary public revoke
    # compatibility with real Authlib authentication and current handler here.
    wrong = await registration({**env, "headers": {"Authorization": "Bearer " + env["core"]}}, scopes=["openid", "docs:read"])
    before = await state(data)
    denied = await env["client"].post("/api/oauth2/revoke", data={"client_id": wrong["client_id"], "token": data.access})
    assert denied.status_code == 400 and denied.json() == {"error": "invalid_grant"}
    assert await state(data) == before
    for value in ("synthetic-unknown-token", data.access, data.access):
        response = await env["client"].post("/api/oauth2/revoke", data={"client_id": data.client_id, "token": value})
        assert response.status_code == 200 and response.json() == {}
        assert response.headers["cache-control"] == "no-store"
    hint = await env["client"].post("/api/oauth2/revoke", data={"client_id": data.client_id, "token": data.access, "token_type_hint": "unknown"})
    assert hint.status_code == 400 and hint.json() == {"error": "unsupported_token_type"}
    closed_wire(await env["client"].delete(URL, headers=proof(data.raw)))
