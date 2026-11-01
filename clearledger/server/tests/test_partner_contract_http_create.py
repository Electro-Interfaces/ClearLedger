"""AUTHOR DEFINITIONS / NOTRUN, including imports and collection.

ROOT supplies partner_contract_issuer_factory through the existing real issuer
fixture after its external actual-target admission. No runner, URL, environment,
provisioning, fixture edits or positive auth/SQL-authority substitutions here.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import copy
from dataclasses import replace
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_contracts.context import CREATE_PREFLIGHT_KEY, ScopeMode
from app.models import ContractLocation, ServiceLocation, UserCompany
from app.models_partner import (PartnerGrant, PartnerInstallationLocation,
    PartnerResourceItem, PartnerResourceScope)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreateRef as Ref, PartnerContractIntentLocation as IntentLocation,
    PartnerContractSuccessIntent as Intent)
from app.product_api import access, budget, dto
from app.product_api.app import (_RequestMetadataMiddleware, create_product_api,
    curated_openapi, public_client_openapi)
from app.security_context import SecurityContext, current as current_security_context
from app.services import partner_contract_authority as authority, partner_contract_commands as commands
from app.services import partner_identity as identity, contract_write_locks as locks
from tests.partner_contract_issuer_fixture import issuer_world, issue_machine, issue_user, make_body, state

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def http_world(issuer_world, monkeypatch):
    w = issuer_world
    sessions, lifetimes = [], []
    close = AsyncSession.close

    async def observed_close(db):
        await close(db)
        if db in sessions:
            lifetimes.append(("closed", db))

    monkeypatch.setattr(AsyncSession, "close", observed_close)

    @asynccontextmanager
    async def actual_sessions():
        async with w.factory() as db:
            sessions.append(db)
            lifetimes.append(("open", db))
            try:
                yield db
            finally:
                lifetimes.append(("closing", db))

    child = create_product_api(session_factory=actual_sessions, enabled=True,
        issuer="https://issuer.synthetic.invalid", cursor_key=b"synthetic-http-create-key-32bytes!!",
        budget_policy=budget.Policy(enabled=False))  # Original canonical verifier.
    parent = FastAPI()
    parent.mount("/api/v1", child)
    yield SimpleNamespace(w=w, app=parent, child=child, sessions=sessions, lifetimes=lifetimes)


def wire(w, **changes):
    return make_body(w, **changes).model_dump_json().encode()


async def request(h, *, bearer=None, chunks=None, raw=None, headers=None, method="POST",
                  path="/api/v1/contracts", spec_version="2.4"):
    """Actual ASGI HTTP boundary, with a counted receive, including chunking.

    Default ASGI 2.4 also supports the historical StreamingResponse boundary.
    Explicit 2.3 cases verify that metadata adds no disconnect-listener task.
    """
    messages, count, started = [], 0, False
    chunks = list(chunks if chunks is not None else [raw if raw is not None else wire(h.w)])
    header_list = [(b"host", b"issuer.synthetic.invalid"), (b"content-type", b"application/json")]
    if bearer is not False:
        header_list.append((b"authorization", ("Bearer " + (bearer or h.w.bearer)).encode()))
    if headers:
        replace_names = {k.lower() for k, _ in headers}
        header_list = [(k, v) for k, v in header_list if k not in replace_names] + headers

    async def receive():
        nonlocal count
        if chunks:
            count += 1
            chunk = chunks.pop(0)
            if chunk is None:
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal started
        if message["type"] == "http.response.start":
            started = True
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1", "scheme": "https", "method": method, "path": path,
        "raw_path": path.encode(), "root_path": "", "query_string": b"", "headers": header_list,
        "client": ("127.0.0.1", 1234), "server": ("issuer.synthetic.invalid", 443)}
    try:
        await h.app(scope, receive, send)
    except Exception:
        # ServerErrorMiddleware re-raises after emitting its safe 500. Retain
        # failures without a response; do not hide faulty ASGI/test composition.
        if not started:
            raise
    response = next(m for m in messages if m["type"] == "http.response.start")
    content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return SimpleNamespace(status=response["status"], headers=dict(response["headers"]),
        body=json.loads(content), body_reads=count, content=content, scope=scope)


def problem(r, status, code):
    assert r.status == status and r.body["code"] == code
    assert set(r.body) == {"type", "title", "status", "code", "requestId", "detail"}
    assert r.headers[b"cache-control"] == b"no-store"
    assert r.headers[b"x-request-id"].decode() == r.body["requestId"]
    assert r.headers[b"content-type"].startswith(b"application/problem+json")
    if status in (401, 403):
        assert r.headers[b"www-authenticate"].startswith(b"Bearer ")


@pytest.mark.parametrize("kind", ["user", "machine"])
async def test_actual_http_authlib_create_replay_empty_read_scope_and_five_parts(http_world, kind):
    h, w = http_world, http_world.w
    token = w.machine if kind == "machine" else w.bearer
    before = await state(w)
    raw = wire(w)
    first = await request(h, bearer=token, raw=raw)
    assert first.status == 201 and first.body_reads == 1
    assert set(first.body) == {"contractId", "replayed"} and first.body["replayed"] is False
    assert b"location" not in first.headers
    assert await state(w) == tuple(n + 1 for n in before)
    second = await request(h, bearer=token, raw=raw)
    assert second.status == 200 and second.body == {**first.body, "replayed": True}
    assert await state(w) == tuple(n + 1 for n in before)
    async with w.factory() as db:
        scopes = await db.scalar(select(PartnerResourceScope).where(
            PartnerResourceScope.installation_id == w.iid, PartnerResourceScope.kind == "contracts"))
        assert scopes.mode == "EMPTY"
    read_token = await issue_machine(w, scope="contracts:create contracts:read")
    denied = await request(h, bearer=read_token, method="GET")
    problem(denied, 403, "access_denied")  # Default read guard still requires resources.


async def test_actual_user_and_machine_create_ignore_unrequested_whitespace_object_grant(http_world):
    h, w, extra = http_world, http_world.w, " "
    # A real same-company parent and BOTH live ceilings contain this exact ID.
    # It is deliberately absent from ProfileRef/body: schema4 forbids a blank
    # profile location, whereas canonical installation/object grants allow it.
    async with w.factory() as db:
        db.add(ServiceLocation(id=extra, company_id=w.company, code="synthetic-extra-blank",
            name="Synthetic unrequested object", source_bindings=[]))
        await db.flush()
        db.add(PartnerInstallationLocation(installation_id=w.iid, location_id=extra))
        db.add(PartnerResourceItem(installation_id=w.iid, kind="objects", object_id=extra))
        (await db.get(UserCompany, (w.user, w.company))).object_scope = [w.loc, extra]
        await db.commit()
    tokens = (await issue_user(w), await issue_machine(w))  # Real Authlib flows.
    for is_machine, token in zip((False, True), tokens):
        async with w.factory() as db:
            current = await identity.verify_partner_access_token(token, db)
            assert current.is_machine is is_machine
            assert current.resource_scopes["objects"].mode == "SET"
            assert current.resource_scopes["objects"].ids == frozenset((w.loc, extra))
            assert current.location_ids == frozenset((w.loc, extra))
            assert current.resource_scopes["contracts"].mode == "EMPTY"
            refs = tuple(await db.scalars(select(Ref.location_id).where(
                Ref.profile_id == w.profile, Ref.kind == "location")))
            assert refs == (w.loc,) and extra not in refs
        body = make_body(w)
        assert body.coverage.locationIds == (w.loc,)
        raw, before = body.model_dump_json().encode(), await state(w)
        first = await request(h, bearer=token, raw=raw)
        assert first.status == 201 and first.body_reads == 1
        assert set(first.body) == {"contractId", "replayed"} and first.body["replayed"] is False
        assert await state(w) == tuple(n + 1 for n in before)  # All five actual parts.
        second = await request(h, bearer=token, raw=raw)
        assert second.status == 200 and second.body_reads == 1
        assert second.body == {**first.body, "replayed": True}
        assert await state(w) == tuple(n + 1 for n in before)
        async with w.factory() as db:
            assert tuple(await db.scalars(select(ContractLocation.location_id).where(
                ContractLocation.contract_id == UUID(first.body["contractId"])))) == (w.loc,)
            assert not tuple(await db.scalars(select(IntentLocation.location_id).join(
                Intent, Intent.id == IntentLocation.intent_id).where(
                Intent.company_id == w.company, IntentLocation.location_id == extra)))
            scopes = await db.scalar(select(PartnerResourceScope).where(
                PartnerResourceScope.installation_id == w.iid, PartnerResourceScope.kind == "contracts"))
            assert scopes.mode == "EMPTY"


async def test_same_actual_session_root_connection_complete_one_b_and_lifetime(http_world, monkeypatch):
    h, w, seen, plans = http_world, http_world.w, [], []
    consume, prepare, acquire = commands.create_partner_contract, authority._prepare, identity.acquire_scoped_locks

    def observe_b(db, plan):
        cap = acquire(db, plan)
        plans.append(plan)
        return cap

    def observe_prepare(db, async_db, bearer, body):
        issued = prepare(db, async_db, bearer, body)
        seen.append(("issuer", async_db, db.get_transaction(), db.connection()))
        return issued

    async def observe_consumer(db, bearer, body):
        root, connection = db.sync_session.get_transaction(), db.sync_session.connection()
        seen.append(("before", db, root, connection))
        result = await consume(db, bearer, body)
        seen.append(("after", db, db.sync_session.get_transaction(), db.sync_session.connection()))
        assert await state(w) == before  # No result/business rows escape before caller commit.
        return result

    monkeypatch.setattr(identity, "acquire_scoped_locks", observe_b)
    monkeypatch.setattr(authority, "_prepare", observe_prepare)
    monkeypatch.setattr(commands, "create_partner_contract", observe_consumer)
    before = await state(w)
    result = await request(h)
    assert result.status == 201
    assert len(h.sessions) == 2 and h.sessions[0] is not h.sessions[1]
    assert [x[0] for x in h.lifetimes] == ["open", "closing", "closed", "open", "closing", "closed"]
    assert len(seen) == 3 and all(x[1:] == seen[0][1:] for x in seen)
    assert seen[0][1] is h.sessions[1] and not h.sessions[1].in_transaction()
    assert len(plans) == 1
    keys = {r.key for r in plans[0].requests}
    assert {locks.CompanyKey(w.company), locks.CompanyKey(w.other), locks.AppKey(w.app_id),
        locks.ClientKey(w.client_id), locks.InstallationKey(w.iid), locks.UserKey(w.user),
        locks.MemberKey(w.company, w.user), locks.RoleKey(w.company, w.role),
        locks.CreateProfileKey(w.profile), locks.RefCompositeKey(w.company), locks.TypeCatalogKey(w.code)} <= keys
    assert all(key not in result.scope for key in (CREATE_PREFLIGHT_KEY, "elsy.product.create_db", "elsy.product.create_context"))


@pytest.mark.parametrize("denial", ["missing", "tampered", "read_only", "revoked", "profile", "principal", "membership"])
async def test_prebody_actual_auth_profile_denial_reads_zero_business_zero(http_world, denial):
    h, w = http_world, http_world.w
    token = w.bearer
    if denial == "missing":
        token = False
    elif denial == "tampered":
        token += "x"
    elif denial == "read_only":
        token = await issue_machine(w, scope="contracts:read")
    else:
        async with w.factory() as db:
            if denial == "revoked":
                (await db.get(PartnerGrant, w.user_grant)).approved = False
            elif denial == "profile":
                (await db.get(Profile, w.profile)).user_enabled = False
            elif denial == "principal":
                await db.execute(text("DELETE FROM core.partner_contract_create_principals WHERE profile_id=:p AND actor_kind='user'"), {"p": w.profile})
            else:
                await db.execute(delete(UserCompany).where(UserCompany.user_id == w.user, UserCompany.company_id == w.company))
            await db.commit()
    before = await state(w)
    result = await request(h, bearer=token)
    assert result.status in (401, 403) and result.body_reads == 0
    problem(result, result.status, "invalid_credentials" if result.status == 401 else "access_denied")
    assert await state(w) == before


async def test_actual_enabled_budget_separate_commit_and_429_prebody(http_world):
    h, w = http_world, http_world.w
    h.child.state.product_settings = replace(h.child.state.product_settings,
        budget_policy=lambda: budget.Policy(enabled=True, request_limit=1))
    before = await state(w)
    invalid = await request(h, raw=b"{}")
    problem(invalid, 422, "invalid_request")
    assert len(h.sessions) == 3
    assert [x[0] for x in h.lifetimes[:6]] == ["open", "closing", "closed", "open", "closing", "closed"]
    async with w.factory() as db:
        used = await db.scalar(text("SELECT used FROM core.product_api_budgets WHERE company_id=:c AND installation_id=:i AND client_id=:cl"),
            {"c": w.company, "i": w.iid, "cl": w.client_id})
        assert used == 1  # quota survived request-root validation rollback.
    denied = await request(h)
    problem(denied, 429, "rate_limited")
    assert denied.body_reads == 0 and int(denied.headers[b"retry-after"]) >= 1
    assert len(h.sessions) == 5  # No request write root opened on exhaustion.
    assert await state(w) == before


async def test_current_reauth_after_quota_refuses_revoked_grant_without_body(http_world, monkeypatch):
    h, w = http_world, http_world.w
    enforce = budget.enforce

    async def revoke_after_quota(*args):
        await enforce(*args)
        assert [x[0] for x in h.lifetimes] == ["open", "closing", "closed"]
        async with w.factory() as db:
            (await db.get(PartnerGrant, w.user_grant)).approved = False
            await db.commit()

    monkeypatch.setattr(budget, "enforce", revoke_after_quota)
    before = await state(w)
    result = await request(h)
    assert result.status in (401, 403) and result.body_reads == 0
    assert await state(w) == before and len(h.sessions) == 2


@pytest.mark.parametrize("size,expected", [(16383, 201), (16384, 201), (16385, 413)])
@pytest.mark.parametrize("length", [None, b"0", b"1", b"999999"])
async def test_actual_stream_byte_boundary_inclusive_false_content_length(http_world, size, expected, length):
    h, w = http_world, http_world.w
    raw = wire(w)
    raw += b" " * (size - len(raw))
    before = await state(w)
    result = await request(h, chunks=[raw[:13], raw[13:8192], raw[8192:]],
        headers=[] if length is None else [(b"content-length", length)])
    assert result.status == expected
    if expected == 413:
        problem(result, 413, "request_too_large")
        assert await state(w) == before
    else:
        assert await state(w) == tuple(n+1 for n in before)


@pytest.mark.parametrize("headers", [[(b"content-type", b"text/plain")],
    [(b"content-type", b"application/json; charset=latin1")], [(b"content-encoding", b"gzip")],
    [(b"content-type", b"application/json"), (b"content-type", b"application/json")]])
async def test_media_and_gzip_denied_before_stream(http_world, headers):
    before = await state(http_world.w)
    result = await request(http_world, headers=headers)
    problem(result, 415, "unsupported_media_type")
    assert result.body_reads == 0 and await state(http_world.w) == before


@pytest.mark.parametrize("raw", [b"{}", b"[]", b'{"kind":"contract-card","kind":"contract-card"}',
    b'{"coverage":{"kind":"locations","kind":"locations"}}', b'{"number":NaN}', b"\xff", b'{"number":"\\ud800"}'])
async def test_strict_invalid_body_and_duplicate_json_are_private_atomic(http_world, raw):
    before = await state(http_world.w)
    result = await request(http_world, raw=raw)
    problem(result, 422, "invalid_request")
    assert result.body_reads == 1 and await state(http_world.w) == before
    assert b"NaN" not in result.content and b"coverage" not in result.content


async def test_chunked_unicode_and_oversized_chunk_stops_before_next_receive(http_world):
    h = http_world
    raw = wire(h.w, comment="Учебный пример")
    first = await request(h, chunks=[raw[i:i+1] for i in range(len(raw))])
    assert first.status == 201 and first.body_reads == len(raw)
    before = await state(h.w)
    oversized = await request(h, chunks=[b" " * 16385, b"not consumed"])
    problem(oversized, 413, "request_too_large")
    assert oversized.body_reads == 1 and await state(h.w) == before


@pytest.mark.parametrize("forgery", ["copy", "other_request"])
async def test_request_bound_preflight_cannot_be_copied_or_reused(http_world, monkeypatch, forgery):
    h, original, previous = http_world, access.create_preflight, []

    async def observe(request, db, bearer, *, bind=False):
        token, context = await original(request, db, bearer, bind=bind)
        if bind:
            assert context.permissions == ()
            assert context.permission("contracts", "read").resources.mode is ScopeMode.UNINITIALIZED
            assert token.resource_scopes["contracts"].mode == "EMPTY"
            assert not context.database_permissions and context.receipt_read_binding is None
            descriptor = context.create_preflight
            if forgery == "copy":
                context = replace(context, create_preflight=copy(descriptor))
            elif previous:
                context = replace(context, create_preflight=previous[0])
            else:
                previous.append(descriptor)
        return token, context

    monkeypatch.setattr(access, "create_preflight", observe)
    if forgery == "other_request":
        assert (await request(h)).status == 201
    before = await state(h.w)
    denied = await request(h)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 0 and await state(h.w) == before


@pytest.mark.parametrize("fault", ["denial", "serialization", "commit", "cancel"])
async def test_whole_root_rollback_after_actual_five_parts(http_world, monkeypatch, fault):
    h, w = http_world, http_world.w
    original, commit = commands.create_partner_contract, AsyncSession.commit
    reached = []

    async def observed(db, bearer, body):
        result = await original(db, bearer, body)
        reached.append(db)
        if fault == "denial":
            raise HTTPException(403, "synthetic private denial")
        if fault == "cancel":
            raise asyncio.CancelledError()
        return result

    async def fail_commit(db):
        if db in reached:
            raise RuntimeError("synthetic pre-commit failure")
        return await commit(db)

    def fail_serialization(*args, **kwargs):
        raise ValueError("synthetic serialization failure")

    monkeypatch.setattr(commands, "create_partner_contract", observed)
    if fault == "commit":
        monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    if fault == "serialization":
        monkeypatch.setattr(dto.ContractCreateResult, "model_dump", fail_serialization)
    before = await state(w)
    if fault == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await request(h)
    else:
        result = await request(h)
        problem(result, 403 if fault == "denial" else 500, "access_denied" if fault == "denial" else "internal_error")
    assert len(reached) == 1 and await state(w) == before
    assert all(not db.in_transaction() for db in h.sessions)
    assert h.lifetimes[-1][0] == "closed"


async def test_unknown_commit_new_root_same_key_current_auth_replays(http_world, monkeypatch):
    h, w, lost = http_world, http_world.w, []
    commit = AsyncSession.commit

    async def lost_ack(db):
        await commit(db)
        if db in h.sessions and db is h.sessions[-1] and len(h.sessions) == 2 and not lost:
            lost.append(db)
            raise ConnectionError("synthetic lost acknowledgement")

    monkeypatch.setattr(AsyncSession, "commit", lost_ack)
    before, raw = await state(w), wire(w)
    uncertain = await request(h, raw=raw)
    problem(uncertain, 500, "internal_error")
    assert await state(w) == tuple(n+1 for n in before)
    replay = await request(h, raw=raw)
    assert replay.status == 200 and replay.body["replayed"] is True
    assert h.sessions[-1] is not lost[0] and await state(w) == tuple(n+1 for n in before)
    async with w.factory() as db:
        (await db.get(Profile, w.profile)).user_enabled = False
        await db.commit()
    denied = await request(h, raw=raw)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 0


async def test_conflict_after_full_create_is_nonleaky_and_denial_wins(http_world):
    h, w = http_world, http_world.w
    body = make_body(w)
    raw = body.model_dump_json().encode()
    assert (await request(h, raw=raw)).status == 201
    changed = wire(w, creationKey=str(body.creationKey), number="Synthetic changed")
    result = await request(h, raw=changed)
    problem(result, 409, "conflict")
    assert str(body.creationKey).encode() not in result.content
    assert str(w.profile).encode() not in result.content and str(w.user_grant).encode() not in result.content
    before = await state(w)
    async with w.factory() as db:
        (await db.get(Profile, w.profile)).user_enabled = False
        await db.commit()
    denied = await request(h, raw=changed)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 0 and await state(w) == before


async def test_generic_429_is_not_budget_exhaustion(http_world, monkeypatch):
    async def fail(*args, **kwargs):
        raise HTTPException(429, "synthetic fault", headers={"Retry-After": "7"})
    monkeypatch.setattr(commands, "create_partner_contract", fail)  # Negative fault only.
    result = await request(http_world)
    problem(result, 429, "internal_error")
    assert result.headers[b"retry-after"] == b"7"


async def test_schema_exact_post_canonical_body_and_protected_public_projection(http_world):
    from app.product_api.contract_create_body import ContractCreateBody
    schema = curated_openapi(http_world.child)
    operations = [(method, path, item["operationId"]) for path, methods in schema["paths"].items()
        for method, item in methods.items() if method in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}]
    assert len(operations) == 16 and sum(m == "get" for m, _, _ in operations) == 15
    assert ("post", "/contracts", "createContract") in operations
    assert schema["info"]["version"] == "1.1.0"
    post = schema["paths"]["/contracts"]["post"]
    expected = ContractCreateBody.model_json_schema(by_alias=True, mode="validation", ref_template="#/components/schemas/{model}")
    definitions = expected.pop("$defs", {})
    body_reference = post["requestBody"]["content"]["application/json"]["schema"]
    assert body_reference == {"$ref": "#/components/schemas/ContractCreateBody"}
    assert schema["components"]["schemas"][body_reference["$ref"].rsplit("/", 1)[-1]] == expected
    assert all(schema["components"]["schemas"][k] == v for k, v in definitions.items())
    assert post["security"] == [{"ProductOAuth": ["contracts:create"]}, {"ProductServiceOAuth": ["contracts:create"]}]
    assert post["tags"] == ["Договоры"] and "validUntil" in expected["required"]
    assert {"200", "201", "401", "403", "409", "413", "415", "422", "429", "500", "503"} <= post["responses"].keys()
    public = public_client_openapi(schema)
    assert set(public["components"]["securitySchemes"]) == {"ProductOAuth"}
    assert public["paths"]["/contracts"]["post"]["security"] == [{"ProductOAuth": ["contracts:create"]}]
    assert "ProductServiceOAuth" in schema["components"]["securitySchemes"]
    result = await request(http_world, method="DELETE")
    assert result.status == 405 and result.headers[b"allow"] == b"GET, POST"


@pytest.mark.parametrize("kind", ["user", "machine"])
async def test_exact_profile_flag_and_principal_for_each_actual_kind(http_world, kind):
    h, w = http_world, http_world.w
    async with w.factory() as db:
        profile = await db.get(Profile, w.profile)
        if kind == "machine":
            profile.service_enabled = False
        else:
            profile.user_enabled = False
        await db.commit()
    before = await state(w)
    denied = await request(h, bearer=w.machine if kind == "machine" else w.bearer)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 0 and await state(w) == before


@pytest.mark.parametrize("part", ["organization", "counterparty", "location", "type"])
async def test_full_body_reference_policy_still_belongs_to_actual_issuer(http_world, part):
    h, w = http_world, http_world.w
    async with w.factory() as db:
        if part == "type":
            await db.execute(text("DELETE FROM core.partner_contract_create_types WHERE profile_id=:p"), {"p": w.profile})
        else:
            await db.execute(text("DELETE FROM core.partner_contract_create_refs WHERE profile_id=:p AND kind=:k"),
                {"p": w.profile, "k": part})
        await db.commit()
    before = await state(w)
    denied = await request(h)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 1  # Coarse gate is deliberately not complete CREATE.
    assert await state(w) == before


@pytest.mark.parametrize("first_kind", ["user", "machine"])
async def test_same_key_cannot_transfer_original_grant_or_actor(http_world, first_kind):
    h, w = http_world, http_world.w
    original, substitute = (w.bearer, w.machine) if first_kind == "user" else (w.machine, w.bearer)
    raw = wire(w)
    created = await request(h, bearer=original, raw=raw)
    assert created.status == 201
    before = await state(w)
    denied = await request(h, bearer=substitute, raw=raw)
    problem(denied, 403, "access_denied")
    assert denied.body_reads == 1 and await state(w) == before
    assert created.body["contractId"].encode() not in denied.content


async def test_required_nullable_valid_until_and_no_extras(http_world):
    h = http_world
    body = json.loads(wire(h.w))
    del body["validUntil"]
    before = await state(h.w)
    missing = await request(h, raw=json.dumps(body).encode())
    problem(missing, 422, "invalid_request")
    body["validUntil"] = None
    body["profileId"] = str(h.w.profile)
    extra = await request(h, raw=json.dumps(body).encode())
    problem(extra, 422, "invalid_request")
    assert await state(h.w) == before


async def test_disabled_api_503_is_prebody_without_any_session(http_world):
    h = http_world
    h.child.state.product_settings = replace(h.child.state.product_settings, enabled=lambda: False)
    denied = await request(h)
    problem(denied, 503, "api_unavailable")
    assert denied.body_reads == 0 and not h.sessions


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_cancel_actual_http_task_after_five_parts_rolls_back_before_close(http_world, monkeypatch, spec_version):
    h, w = http_world, http_world.w
    original, ready, hold = commands.create_partner_contract, asyncio.Event(), asyncio.Event()

    async def observe(db, bearer, body):
        result = await original(db, bearer, body)
        ready.set()
        await hold.wait()  # Cancellation arrives in the real request task.
        return result

    monkeypatch.setattr(commands, "create_partner_contract", observe)
    before = await state(w)
    pending = asyncio.create_task(request(h, spec_version=spec_version))
    try:
        # ROOT measured 5.9–6.3s to the real consumer; this is only a bounded
        # test readiness deadline, not a production timeout or a weaker oracle.
        await asyncio.wait_for(ready.wait(), timeout=30)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    finally:
        if not pending.done():
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
    assert await state(w) == before
    assert all(not db.in_transaction() for db in h.sessions)
    assert h.lifetimes[-1][0] == "closed"


async def test_failed_actual_session_close_has_no_success_marker(http_world, monkeypatch):
    h, w, reached, failed = http_world, http_world.w, [], []
    original, close = commands.create_partner_contract, AsyncSession.close

    async def denied_after_write(db, bearer, body):
        await original(db, bearer, body)
        reached.append(db)
        raise HTTPException(403, "synthetic denial after five parts")

    async def fail_close(db):
        if db in reached and not failed:
            failed.append(db)
            raise RuntimeError("synthetic actual Session.close failure")
        await close(db)

    monkeypatch.setattr(commands, "create_partner_contract", denied_after_write)
    monkeypatch.setattr(AsyncSession, "close", fail_close)
    before = await state(w)
    try:
        result = await request(h)
        problem(result, 500, "internal_error")
        assert len(reached) == 1 and failed == reached
        assert await state(w) == before
        assert all(not db.in_transaction() for db in h.sessions)
        assert h.lifetimes[-1] == ("closing", reached[0])
        assert ("closed", reached[0]) not in h.lifetimes
    finally:
        # Actual cleanup is separate from the failed close observation.
        for db in failed:
            await close(db)
    assert h.lifetimes[-1] == ("closed", reached[0])


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_receive_disconnect_rolls_back_actual_request_root(http_world, spec_version):
    h, w = http_world, http_world.w
    before = await state(w)
    result = await request(h, chunks=[wire(w)[:13], None], spec_version=spec_version)
    problem(result, 500, "internal_error")
    assert result.body_reads == 2 and await state(w) == before
    assert len(h.sessions) == 2
    assert all(not db.in_transaction() for db in h.sessions)
    assert [item[0] for item in h.lifetimes] == ["open", "closing", "closed", "open", "closing", "closed"]
    assert all(key not in result.scope for key in (
        CREATE_PREFLIGHT_KEY, "elsy.product.create_db", "elsy.product.create_context", "elsy.product.create_bearer"))


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_actual_http_metadata_prebody_errors_get405_and_create(http_world, monkeypatch, spec_version):
    h, w = http_world, http_world.w
    before = await state(w)
    denied = await request(h, bearer=False, spec_version=spec_version,
        headers=[(b"x-request-id", b"untrusted-client-value")])
    problem(denied, 401, "invalid_credentials")
    assert denied.body_reads == 0 and not h.sessions
    assert denied.headers[b"x-request-id"] != b"untrusted-client-value"
    for path, allowed in (("/api/v1/contracts", b"GET, POST"), ("/api/v1/objects", b"GET")):
        unsupported = await request(h, method="DELETE", path=path, spec_version=spec_version)
        problem(unsupported, 405, "method_not_allowed")
        assert unsupported.headers[b"allow"] == allowed and unsupported.body_reads == 0
    get_denied = await request(h, method="GET", bearer=False, spec_version=spec_version)
    problem(get_denied, 401, "invalid_credentials")
    assert get_denied.body_reads == 0
    created = await request(h, spec_version=spec_version)
    assert created.status == 201 and created.body_reads == 1
    assert created.headers[b"cache-control"] == b"no-store"
    assert UUID(created.headers[b"x-request-id"].decode())
    assert await state(w) == tuple(n+1 for n in before)
    original = commands.create_partner_contract

    async def fail_after_write(db, bearer, body):
        await original(db, bearer, body)
        raise RuntimeError("synthetic post-write metadata failure")

    monkeypatch.setattr(commands, "create_partner_contract", fail_after_write)
    before_error = await state(w)
    failed = await request(h, spec_version=spec_version)
    problem(failed, 500, "internal_error")
    assert failed.body_reads == 1 and await state(w) == before_error
    assert all(not db.in_transaction() for db in h.sessions)
    assert h.lifetimes[-1][0] == "closed"


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("trusted", [False, True])
async def test_metadata_wrapper_preserves_stream_messages_scope_receive_and_context(spec_version, trusted):
    # Protocol-only application; no replacement for auth or SQL admission.
    # Synthetic 206 metadata is passthrough evidence, not a product Range promise.
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": spec_version},
        "state": {"preserved": object()}, "headers": [(b"x-request-id", b"untrusted-client-value")]}
    state_object, messages, received = scope["state"], [], []
    start = {"type": "http.response.start", "status": 206, "headers": [
        (b"cache-control", b"public"), (b"cache-control", b"max-age=3600"),
        (b"x-request-id", b"stale"), (b"x-request-id", b"duplicate"),
        (b"content-type", b"application/octet-stream"), (b"content-length", b"3"),
        (b"content-range", b"bytes 0-2/6"), (b"accept-ranges", b"bytes"),
        (b"content-disposition", b"attachment; filename=synthetic.txt"), (b"x-content-type-options", b"nosniff")]}
    first = {"type": "http.response.body", "body": b"ab", "more_body": True}
    last = {"type": "http.response.body", "body": b"c", "more_body": False}

    async def receive():
        received.append(True)
        raise AssertionError("metadata must not read the body")

    async def send(message):
        messages.append(message)

    async def downstream(actual_scope, actual_receive, actual_send):
        assert actual_scope is scope and actual_scope["state"] is state_object
        assert actual_receive is receive and state_object["preserved"] is scope["state"]["preserved"]
        for message in (start, first, last):
            await actual_send(message)

    context = SecurityContext(request_id="80000000-0000-4000-8000-000000000001",
        ip="127.0.0.1", peer="synthetic", path="/synthetic", user_agent="synthetic") if trusted else None
    token = current_security_context.set(context)
    try:
        await _RequestMetadataMiddleware(downstream)(scope, receive, send)
        assert current_security_context.get() is context
    finally:
        current_security_context.reset(token)
    assert not received and all(actual is original for actual, original in zip(messages, (start, first, last)))
    assert len(messages) == 3 and start["status"] == 206
    headers = dict(start["headers"])
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"x-request-id"].decode() == state_object["request_id"]
    assert sum(k == b"cache-control" for k, _ in start["headers"]) == 1
    assert sum(k == b"x-request-id" for k, _ in start["headers"]) == 1
    assert headers[b"content-type"] == b"application/octet-stream" and headers[b"content-length"] == b"3"
    assert headers[b"content-range"] == b"bytes 0-2/6" and headers[b"accept-ranges"] == b"bytes"
    assert headers[b"content-disposition"] == b"attachment; filename=synthetic.txt"
    assert headers[b"x-content-type-options"] == b"nosniff"
    if trusted:
        assert state_object["request_id"] == context.request_id
    else:
        assert UUID(state_object["request_id"])


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_metadata_wrapper_nonhttp_passthrough(scope_type):
    scope, observed = {"type": scope_type}, []

    async def receive():
        raise AssertionError("unexpected receive")

    async def send(message):
        raise AssertionError("unexpected send")

    async def downstream(actual_scope, actual_receive, actual_send):
        observed.append((actual_scope, actual_receive, actual_send))

    await _RequestMetadataMiddleware(downstream)(scope, receive, send)
    assert len(observed) == 1
    assert observed[0][0] is scope and observed[0][1] is receive and observed[0][2] is send
    assert scope == {"type": scope_type}
