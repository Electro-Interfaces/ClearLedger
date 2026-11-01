"""AUTHOR DEFINITIONS / NOTRUN: canonical Authlib + actual PostgreSQL only.

ROOT must separately admit partner_contract_issuer_factory and its independent
connections/READ ONLY REPEATABLE READ override. No URL/env/provision/driver,
positive verifier/Session replacement, or execution is authorized by this file.
Observational wrappers always call the actual function before any assertions.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyApp, CompanyRole, Contract, Counterparty, Organization, ServiceLocation, User, UserCompany
from app.models_partner import (PartnerGrant, PartnerInstallation, PartnerInstallationLocation,
    PartnerResourceItem, PartnerResourceScope)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref, PartnerContractCreateType as Type)
from app.product_api import access, budget, contract_create_options as options
from app.product_api.app import create_product_api
from app.services import partner_contract_authority as authority, partner_identity as identity
from tests.partner_contract_issuer_fixture import (issuer_world, issue_machine, issue_user,
    make_body, state, add_opaque_locations)

pytestmark = pytest.mark.asyncio(loop_scope="session")
PATH = "/api/v1/contracts/create-options"


@pytest_asyncio.fixture(loop_scope="session")
async def options_world(issuer_world, monkeypatch):
    w = issuer_world
    sessions, lifetimes, statements, snapshot_sql = [], [], [], []
    close = AsyncSession.close

    async def observed_close(db):
        await close(db)
        if db in sessions:
            lifetimes.append(("closed", db))

    monkeypatch.setattr(AsyncSession, "close", observed_close)

    @asynccontextmanager
    async def actual_sessions():
        async with w.factory() as db:
            assert isinstance(db, AsyncSession) and not db.in_transaction()
            sessions.append(db)
            lifetimes.append(("open", db))
            try:
                yield db
            finally:
                lifetimes.append(("closing", db))

    async with w.factory() as db:
        engine = (await db.connection()).engine.sync_engine

    def observe_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append((connection, statement))

    def after_sql(connection, cursor, statement, parameters, context, executemany):
        if "pg_current_snapshot()" in statement and "statement_timeout" in statement:
            execution = connection.get_execution_options()
            assert execution["isolation_level"] == "REPEATABLE READ"
            assert execution["postgresql_readonly"] is True
            snapshot_sql.append((connection, statement))  # Actual completed SQL, not Python entry.

    event.listen(engine, "before_cursor_execute", observe_sql)
    event.listen(engine, "after_cursor_execute", after_sql)
    child = create_product_api(session_factory=actual_sessions, enabled=True,
        issuer="https://issuer.synthetic.invalid", cursor_key=b"synthetic-options-existing-key-32bytes",
        budget_policy=budget.Policy(enabled=False))
    app = FastAPI()
    app.mount("/api/v1", child)
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="https://issuer.synthetic.invalid") as http:
            yield SimpleNamespace(w=w, child=child, app=app, http=http, sessions=sessions,
                lifetimes=lifetimes, statements=statements, snapshot_sql=snapshot_sql)
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)
        event.remove(engine, "after_cursor_execute", after_sql)


async def get(h, resource="location", bearer=None, **query):
    return await h.http.get(PATH, params=dict(resource=resource, **query),
        headers={"Authorization": "Bearer " + (bearer or h.w.bearer)})


def problem(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code and body["status"] == status
    assert set(body) == {"type", "title", "status", "code", "requestId", "detail"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == body["requestId"]
    assert response.headers["content-type"].startswith("application/problem+json")
    if status in (401, 403):
        assert response.headers["www-authenticate"].startswith("Bearer ")


def values(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"resource", "items", "selectionVersion", "nextCursor"}
    assert all(set(item) == {"value"} for item in body["items"])
    return [item["value"] for item in body["items"]]


def closed(h):
    assert all(not db.in_transaction() and not db.new and not db.dirty and not db.deleted for db in h.sessions)
    assert [kind for kind, _ in h.lifetimes] == [kind for _ in h.sessions for kind in ("open", "closing", "closed")]


@pytest.mark.parametrize("kind", ["user", "machine"])
@pytest.mark.parametrize("resource", options.RESOURCES)
async def test_real_canonical_create_choices_with_contracts_read_empty(options_world, kind, resource):
    h, w = options_world, options_world.w
    before, issued = await state(w), len(authority._ISSUED)
    expected = {"organization": str(w.org), "counterparty": str(w.cp), "location": w.loc, "type": w.code}
    response = await get(h, resource, w.machine if kind == "machine" else w.bearer)
    assert values(response) == [expected[resource]]
    assert response.json()["nextCursor"] is None
    assert len(response.json()["selectionVersion"]) == 43
    assert response.headers["cache-control"] == "no-store"
    assert await state(w) == before and len(authority._ISSUED) == issued
    assert len(h.sessions) == 2 and h.sessions[0] is not h.sessions[1]
    closed(h)
    sql = [statement.lower() for _, statement in h.statements]
    assert not any("for update" in s or "for share" in s or "advisory" in s for s in sql)
    assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in sql)


@pytest.mark.parametrize("side", ["before_t0", "after_t0"])
async def test_revoke_commit_both_sides_of_actual_mvcc_t0(options_world, monkeypatch, side):
    h, w, observed = options_world, options_world.w, []
    original_preflight, enforce = access.options_preflight, budget.enforce
    h.child.state.product_settings = replace(h.child.state.product_settings,
        budget_policy=lambda: budget.Policy(enabled=True, request_limit=20))

    async def revoke():
        async with w.factory() as db:
            (await db.get(Profile, w.profile)).revoked = True
            await db.commit()
        observed.append("committed")

    async def after_quota(*args):
        await enforce(*args)
        assert h.lifetimes[-1][0] == "closed"
        if side == "before_t0":
            assert not h.snapshot_sql  # Selection Connection has executed no t0 SQL.
            await revoke()

    async def after_real_snapshot(request, db, bearer, *, bind=False):
        result = await original_preflight(request, db, bearer, bind=bind)
        if bind and side == "after_t0":
            assert len(h.snapshot_sql) == 1
            assert h.snapshot_sql[0][0] is (await db.connection()).sync_connection
            assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert await db.scalar(text("SHOW transaction_read_only")) == "on"
            await revoke()
            # Canonical recheck inside the same RR sees the original profile.
            assert (await db.get(Profile, w.profile, populate_existing=True)).revoked is False
        return result

    monkeypatch.setattr(budget, "enforce", after_quota)
    monkeypatch.setattr(access, "options_preflight", after_real_snapshot)
    before = await state(w)
    response = await get(h)
    assert observed == ["committed"]
    if side == "before_t0":
        problem(response, 403, "access_denied")
    else:
        assert values(response) == [w.loc]  # Advisory t0, not fresh-after-wait.
        # New POST and a new GET both recheck the now-revoked profile.
        post = await h.http.post("/api/v1/contracts", json=make_body(w).model_dump(mode="json"),
            headers={"Authorization": "Bearer " + w.bearer})
        problem(post, 403, "access_denied")
        problem(await get(h), 403, "access_denied")
    assert await state(w) == before
    closed(h)


async def test_actual_repeatable_read_root_and_connection_are_one_and_readonly(options_world, monkeypatch):
    h, original, observations = options_world, access.options_preflight, []

    async def observe(request, db, bearer, *, bind=False):
        result = await original(request, db, bearer, bind=bind)
        if bind or options._DB in request.scope:
            root, conn = db.sync_session.get_transaction(), (await db.connection()).sync_connection
            observations.append((db, root, conn))
            assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert await db.scalar(text("SHOW transaction_read_only")) == "on"
            assert not db.sync_session.get_nested_transaction()
            assert result[1].permissions == () and result[1].database_permissions == ()
            assert result[1].receipt_read_binding is None and result[1].create_preflight is None
        return result

    monkeypatch.setattr(access, "options_preflight", observe)
    assert values(await get(h)) == [h.w.loc]
    assert len(observations) == 2 and observations[0] == observations[1]
    assert observations[0][0] is h.sessions[1]
    assert len(h.snapshot_sql) == 1 and h.snapshot_sql[0][0] is observations[0][2]
    closed(h)


@pytest.mark.parametrize("fault", ["expiry", "jwt_expiry", "process", "product_gate"])
async def test_final_same_canonical_verifier_wall_clock_and_process_gates(options_world, monkeypatch, fault):
    h, original, reached = options_world, options._load, []

    def after_load(db, current):
        result = original(db, current)
        reached.append(current)
        if fault == "expiry":
            monkeypatch.setattr(identity, "now", lambda: current.expires_at + timedelta(seconds=1))
        elif fault == "jwt_expiry":
            class ExpiredJWTClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return current.expires_at + timedelta(seconds=1)
            monkeypatch.setattr(identity.jwt.api_jwt, "datetime", ExpiredJWTClock)
        elif fault == "process":
            monkeypatch.setattr(identity.settings, "partner_oauth_enabled", False)
        else:
            h.child.state.product_settings = replace(h.child.state.product_settings, enabled=lambda: False)
        return result

    monkeypatch.setattr(options, "_load", after_load)
    before = await state(h.w)
    response = await get(h)
    assert len(reached) == 1
    problem(response, 401 if fault in {"expiry", "jwt_expiry"} else 503,
        "invalid_credentials" if fault in {"expiry", "jwt_expiry"} else "api_unavailable")
    assert await state(h.w) == before
    closed(h)


@pytest.mark.parametrize("condition", ["revoked", "user_disabled", "machine_disabled", "no_actor", "no_scope"])
async def test_current_profile_or_coarse_denial403(options_world, condition):
    h, w = options_world, options_world.w
    token = w.machine if condition == "machine_disabled" else w.bearer
    async with w.factory() as db:
        profile = await db.get(Profile, w.profile)
        if condition == "revoked": profile.revoked = True
        elif condition == "user_disabled": profile.user_enabled = False
        elif condition == "machine_disabled": profile.service_enabled = False
        elif condition == "no_actor":
            await db.execute(delete(Principal).where(Principal.profile_id == w.profile, Principal.actor_kind == "user"))
        await db.commit()
    if condition == "no_scope":
        token = await issue_machine(w, scope="contracts:read")
    before = await state(w)
    problem(await get(h, bearer=token), 403, "access_denied")
    assert await state(w) == before
    closed(h)


@pytest.mark.parametrize("resource", options.RESOURCES)
async def test_legal_empty_domains_return200(options_world, resource):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        if resource == "type":
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": w.code})
        else:
            await db.execute(delete(Ref).where(Ref.profile_id == w.profile, Ref.kind == resource))
        await db.commit()
    assert values(await get(h, resource)) == []
    closed(h)


@pytest.mark.parametrize("role", ["admin", "user"])
@pytest.mark.parametrize("scope", [None, []])
async def test_member_none_and_empty_remain_distinct_for_all_roles(options_world, role, scope):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        member = await db.get(UserCompany, (w.user, w.company))
        member.role, member.object_scope = role, scope
        await db.commit()
    assert values(await get(h)) == ([w.loc] if scope is None else [])
    closed(h)


@pytest.mark.parametrize("case", ["absent_member", "inactive_user", "foreign_role", "home", "inactive_machine", "wrong_machine_kind", "foreign_machine"])
async def test_whole_profile_unrelated_principals_preserve_baseline_and_validate_bindings(options_world, case):
    h, w, uid = options_world, options_world.w, uuid4()
    async with w.factory() as db:
        if case in {"inactive_machine", "wrong_machine_kind", "foreign_machine"}:
            if case == "wrong_machine_kind":
                grant_id = w.user_grant
            else:
                grant_id, iid, cid = uuid4(), w.iid, w.company
                if case == "foreign_machine":
                    iid, cid = uuid4(), w.other
                    db.add(CompanyApp(id=iid, company_id=cid, app_id=w.app_id, enabled=True)); await db.flush()
                    db.add(PartnerInstallation(id=iid, company_id=cid, client_id=w.client_id,
                        approved=True, all_locations=True, scopes=["contracts:create"])); await db.flush()
                    w.owned["installations"] += (iid,)
                db.add(PartnerGrant(id=grant_id, company_id=cid, client_id=w.client_id,
                    installation_id=iid, kind="machine", user_id=None, approved=False, scopes=["contracts:create"]))
                await db.flush()
            db.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="machine", machine_grant_id=grant_id))
        else:
            db.add(User(id=uid, company_id=w.other, name="Synthetic unrelated", email=str(uid)+"@issuer.invalid",
                password_hash="synthetic", mail_only=case == "inactive_user"))
            await db.flush()
            w.owned["users"] += (uid,)
            db.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="user", user_id=uid))
            if case == "foreign_role":
                role_id = uuid4()
                db.add(CompanyRole(id=role_id, company_id=w.other, name="Synthetic foreign", modules=["references"]))
                await db.flush()
                db.add(UserCompany(user_id=uid, company_id=w.company, role="user", role_id=role_id, object_scope=[]))
        await db.commit()
    response = await get(h, "type")  # Not the unrelated principal or refs requested.
    if case in {"foreign_role", "wrong_machine_kind", "foreign_machine"}:
        problem(response, 403, "access_denied")
    else:
        assert values(response) == [w.code]
    closed(h)


@pytest.mark.parametrize("kind", ["organization", "counterparty", "location"])
async def test_every_reference_kind_validated_even_when_requesting_type(options_world, kind):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        ref = await db.scalar(select(Ref).where(Ref.profile_id == w.profile, Ref.kind == kind))
        if kind == "counterparty": ref.counterparty_id = w.foreign_cp
        elif kind == "organization":
            foreign = Organization(id=uuid4(), company_id=w.other, name="Synthetic foreign", inn="", prefix="F")
            db.add(foreign); await db.flush(); ref.organization_id = foreign.id
        else:
            foreign = ServiceLocation(id="foreign-"+uuid4().hex[:24], company_id=w.other,
                code=uuid4().hex, name="Synthetic foreign", source_bindings=[])
            db.add(foreign); await db.flush(); ref.location_id = foreign.id
        await db.commit()
    problem(await get(h, "type"), 403, "access_denied")
    closed(h)


@pytest.mark.parametrize("kind", ["user", "machine", "organization", "counterparty", "location", "type"])
async def test_limit101_full_closure_never_partial200(options_world, kind):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        for index in range(100):  # Existing one + 100 is overflow.
            ident = uuid4()
            if kind == "user":
                db.add(User(id=ident, company_id=w.other, name="Synthetic bound", email=str(ident)+"@issuer.invalid", password_hash="synthetic"))
                await db.flush()
                w.owned["users"] += (ident,)
                db.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="user", user_id=ident))
            elif kind == "machine":
                db.add(PartnerGrant(id=ident, installation_id=w.iid, company_id=w.company, client_id=w.client_id,
                    kind="machine", user_id=None, approved=False, scopes=["contracts:create"]))
                await db.flush()
                db.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="machine", machine_grant_id=ident))
            elif kind == "type":
                code = "bound-"+ident.hex
                await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true)"), {"c": code})
                w.owned["type_codes"] += (code,)
                db.add(Type(profile_id=w.profile, type_code=code))
            else:
                if kind == "organization":
                    model = Organization(id=ident, company_id=w.company, name="Synthetic bound", inn="", prefix="B")
                elif kind == "counterparty":
                    model = Counterparty(id=ident, company_id=w.company, name="Synthetic bound", aliases=[])
                else:
                    ident = "bound-"+ident.hex
                    model = ServiceLocation(id=ident, company_id=w.company, code=ident, name="Synthetic bound", source_bindings=[])
                db.add(model); await db.flush()
                db.add(Ref(id=uuid4(), profile_id=w.profile, kind=kind, **{kind+"_id": ident}))
        await db.commit()
    before = await state(w)
    problem(await get(h, "type" if kind != "type" else "organization"), 503, "api_unavailable")
    assert await state(w) == before
    closed(h)


async def test_opaque_paging_newtoken_binding_ttl_and_generation(options_world, monkeypatch):
    h, w = options_world, options_world.w
    all_values = await add_opaque_locations(w)
    first = await get(h, pageSize=1)
    seen = values(first)
    cursor = first.json()["nextCursor"]
    assert cursor and len(cursor) <= 2048
    for changes in (dict(pageSize=2), dict(resource="type"), dict(bearer=await issue_user(w))):
        query = dict(pageSize=1, cursor=cursor) | changes
        resource = query.pop("resource", "location")
        problem(await get(h, resource, **query), 400, "invalid_cursor")
    while cursor:
        page = await get(h, pageSize=1, cursor=cursor)
        seen += values(page)
        assert page.json()["selectionVersion"] == first.json()["selectionVersion"]
        cursor = page.json()["nextCursor"]
    assert seen == sorted(all_values, key=lambda value: value.encode("utf-8"))
    original_time = options.time.time
    cursor = first.json()["nextCursor"]
    with monkeypatch.context() as clock:
        clock.setattr(options.time, "time", lambda: original_time() + 301)
        problem(await get(h, pageSize=1, cursor=cursor), 400, "invalid_cursor")
    async with w.factory() as db:
        (await db.get(Profile, w.profile)).policy_generation += 1
        await db.commit()
    problem(await get(h, pageSize=1, cursor=cursor), 400, "invalid_cursor")
    assert values(await get(h)) == sorted(all_values, key=lambda value: value.encode("utf-8"))
    closed(h)


@pytest.mark.parametrize("pair", [("\x01"*255+"a", "\x01"*255+"b"),
    ("\U00010000"*256, "\U00010000"*255+"\U00010001"), ("  Type A  ", "  Type B  ")])
async def test_actual_legal_type_pair_has_bounded_cursor_and_lossless_second_page(options_world, pair):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        await db.execute(delete(Type).where(Type.profile_id == w.profile))
        for code in pair:
            await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true)"), {"c": code})
            w.owned["type_codes"] += (code,)
            db.add(Type(profile_id=w.profile, type_code=code))
        await db.commit()
    before, stamps = await state(w), len(authority._ISSUED)
    first = await get(h, "type", pageSize=1)
    assert values(first) == [pair[0]]
    cursor = first.json()["nextCursor"]
    assert cursor and len(cursor) <= 1470 < 2048
    second = await get(h, "type", pageSize=1, cursor=cursor)
    assert values(second) == [pair[1]] and second.json()["nextCursor"] is None
    assert first.json()["selectionVersion"] == second.json()["selectionVersion"]
    assert await state(w) == before and len(authority._ISSUED) == stamps
    closed(h)


@pytest.mark.parametrize("query", [{}, dict(resource="wrong"), dict(resource="type", pageSize=0),
    dict(resource="type", unknown="query")])
async def test_actual_invalid_query422_consumes_real_quota_then_preserves_original429(options_world, monkeypatch, query):
    h, w, failures = options_world, options_world.w, []
    h.child.state.product_settings = replace(h.child.state.product_settings,
        budget_policy=lambda: budget.Policy(enabled=True, request_limit=1))
    enforce = budget.enforce

    async def observe_original_enforce(*args):
        try:
            return await enforce(*args)
        except budget.BudgetExceeded as error:
            failures.append(error)
            assert h.lifetimes[-1][0] == "closed"
            raise

    monkeypatch.setattr(budget, "enforce", observe_original_enforce)
    before, stamps = await state(w), len(authority._ISSUED)
    first = await h.http.get(PATH, params=query, headers={"Authorization": "Bearer " + w.bearer})
    problem(first, 422, "invalid_request")
    assert len(h.sessions) == 3 and len(h.snapshot_sql) == 1 and not failures
    closed(h)
    second = await get(h, "type")
    problem(second, 429, "rate_limited")
    assert len(failures) == 1 and second.headers["retry-after"] == failures[0].headers["Retry-After"]
    assert int(second.headers["retry-after"]) >= 1
    assert len(h.sessions) == 5 and len(h.snapshot_sql) == 1
    async with w.factory() as reader:
        assert await reader.scalar(text("SELECT used FROM core.product_api_budgets WHERE company_id=:c AND installation_id=:i AND client_id=:cl"),
            {"c": w.company, "i": w.iid, "cl": w.client_id}) == 2
    assert await state(w) == before and len(authority._ISSUED) == stamps
    closed(h)


async def test_quota_closed_before_readonly_root_and_no_business_dml(options_world, monkeypatch):
    h, w, actual = options_world, options_world.w, []
    h.child.state.product_settings = replace(h.child.state.product_settings,
        budget_policy=lambda: budget.Policy(enabled=True, request_limit=1))
    original = access.options_preflight

    async def observe(request, db, bearer, *, bind=False):
        result = await original(request, db, bearer, bind=bind)
        if bind:
            assert len(h.sessions) == 3 and h.lifetimes[-2][0] == "closed"
            assert not h.sessions[0].in_transaction() and not h.sessions[1].in_transaction()
            async with w.factory() as reader:
                assert await reader.scalar(text("SELECT used FROM core.product_api_budgets WHERE company_id=:c AND installation_id=:i AND client_id=:cl"),
                    {"c": w.company, "i": w.iid, "cl": w.client_id}) == 1
            actual.append(db)
        return result

    monkeypatch.setattr(access, "options_preflight", observe)
    before, stamps = await state(w), len(authority._ISSUED)
    assert values(await get(h)) == [w.loc]
    response = await get(h)
    problem(response, 429, "rate_limited")
    assert int(response.headers["retry-after"]) >= 1 and len(actual) == 1
    assert len(h.sessions) == 5 and await state(w) == before and len(authority._ISSUED) == stamps
    writes = [statement.lower() for _, statement in h.statements if statement.lstrip().lower().startswith(("insert", "update", "delete", "with expired"))]
    assert writes and all("product_api_budgets" in statement for statement in writes)
    closed(h)


@pytest.mark.parametrize("fault", ["cancel", "deadline", "load_error", "root_reset", "nested"])
async def test_real_session_error_cancel_deadline_and_ownership_cleanup(options_world, monkeypatch, fault):
    h, original, reached = options_world, access.options_preflight, asyncio.Event()
    hold = asyncio.Event()

    async def observe(request, db, bearer, *, bind=False):
        result = await original(request, db, bearer, bind=bind)
        if bind:
            reached.set()
            if fault in {"cancel", "deadline"}:
                if fault == "deadline":
                    request.scope[options._DEADLINE].reschedule(asyncio.get_running_loop().time())
                await hold.wait()
            elif fault == "root_reset":
                await db.rollback()
            elif fault == "nested":
                await db.begin_nested()
            else:
                raise RuntimeError("Synthetic incomplete closure")
        return result

    monkeypatch.setattr(access, "options_preflight", observe)
    before, stamps = await state(h.w), len(authority._ISSUED)
    pending = asyncio.create_task(get(h))
    try:
        await asyncio.wait_for(reached.wait(), timeout=30)
        if fault == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            problem(await asyncio.wait_for(pending, timeout=30), 503, "api_unavailable")
    finally:
        if not pending.done():
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
    assert await state(h.w) == before and len(authority._ISSUED) == stamps
    closed(h)


@pytest.mark.parametrize("params", [dict(resource="wrong"), dict(pageSize=0), dict(pageSize=101),
    dict(cursor="x"*2049), dict(q="unknown")])
async def test_actual_query422_and_allow_get405(options_world, params):
    h = options_world
    query = dict(resource="location") | params
    resource = query.pop("resource")
    problem(await get(h, resource, **query), 422, "invalid_request")
    response = await h.http.delete(PATH)
    problem(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"
    closed(h)


@pytest.mark.parametrize("phase", ["preflight", "quota"])
async def test_global_deadline_covers_phases_before_snapshot(options_world, monkeypatch, phase):
    h, preflight, enforce = options_world, access.options_preflight, budget.enforce
    deadlines, reached = [], []

    async def observe(request, db, bearer, *, bind=False):
        result = await preflight(request, db, bearer, bind=bind)
        if not bind:
            deadlines.append(request.scope[options._DEADLINE])
            if phase == "preflight":
                reached.append(phase)
                deadlines[-1].reschedule(asyncio.get_running_loop().time())
                await asyncio.Event().wait()
        return result

    async def observe_quota(*args):
        await enforce(*args)
        if phase == "quota":
            assert h.lifetimes[-1][0] == "closed"
            reached.append(phase)
            deadlines[-1].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()

    monkeypatch.setattr(access, "options_preflight", observe)
    monkeypatch.setattr(budget, "enforce", observe_quota)
    before = await state(h.w)
    problem(await asyncio.wait_for(get(h), timeout=30), 503, "api_unavailable")
    assert reached == [phase] and not h.snapshot_sql
    assert await state(h.w) == before
    closed(h)


async def test_external_actual_connection_is_not_borrowed_for_snapshot(options_world):
    h, sessions, calls = options_world, options_world.child.state.product_settings.sessions, []
    async with h.w.factory() as external:
        connection = await external.connection()
        original_root = external.sync_session.get_transaction()

        @asynccontextmanager
        async def borrowed():
            calls.append(True)
            if len(calls) == 1:
                async with sessions() as db:
                    yield db
            else:
                # Actual SQLAlchemy Session bound to an actual caller Connection:
                # a negative ownership case, never a positive Session stand-in.
                async with AsyncSession(bind=connection) as db:
                    h.sessions.append(db)
                    h.lifetimes.append(("open", db))
                    try:
                        yield db
                    finally:
                        h.lifetimes.append(("closing", db))

        h.child.state.product_settings = replace(h.child.state.product_settings, sessions=borrowed)
        problem(await get(h), 503, "api_unavailable")
        assert not h.snapshot_sql and external.sync_session.get_transaction() is original_root
        assert original_root.is_active and connection.in_transaction()
    closed(h)


async def test_close_failure_never_returns_success(options_world, monkeypatch):
    h, close, failed = options_world, AsyncSession.close, []

    async def fail_close(db):
        if db in h.sessions and len(h.sessions) == 2 and db is h.sessions[1] and not failed:
            failed.append(db)
            assert not db.in_transaction()  # Selection rollback precedes close.
            raise RuntimeError("Synthetic actual Session.close failure")
        await close(db)

    monkeypatch.setattr(AsyncSession, "close", fail_close)
    before = await state(h.w)
    try:
        problem(await get(h), 503, "api_unavailable")
        assert failed == [h.sessions[1]] and not failed[0].in_transaction()
        assert h.lifetimes[-1] == ("closing", failed[0])
        assert ("closed", failed[0]) not in h.lifetimes
        assert await state(h.w) == before
    finally:
        for db in failed:
            await close(db)  # Actual cleanup after observing failure.
    closed(h)


@pytest.mark.parametrize("mode", ["ALL", "EMPTY"])
async def test_canonical_unused_raw_items_do_not_add_native_veto(options_world, mode):
    h, w = options_world, options_world.w
    async with w.factory() as db:
        profile = await db.scalar(select(PartnerResourceScope).where(
            PartnerResourceScope.installation_id == w.iid, PartnerResourceScope.kind == "contracts"))
        profile.mode = mode
        # Native X would inspect raw ALL/EMPTY items. Canonical I deliberately
        # ignores these, and CREATE options must preserve that policy.
        foreign_org = Organization(id=uuid4(), company_id=w.other, name="Synthetic foreign raw", inn="", prefix="F")
        db.add(foreign_org); await db.flush()
        foreign_card = Contract(id=uuid4(), company_id=w.other, counterparty_id=w.foreign_cp,
            organization_id=foreign_org.id, number="Synthetic unused", date="2026-11-01", type="Synthetic")
        db.add(foreign_card); await db.flush()
        db.add(PartnerResourceItem(installation_id=w.iid, kind="contracts", contract_id=foreign_card.id))
        await db.commit()
    assert values(await get(h, "type")) == [w.code]
    closed(h)


async def test_actual_metadata17_and_required_nullable_choices(options_world):
    from app.api_contracts import policy_registry
    from app.product_api.app import curated_openapi, export_runtime_registry
    from tests.test_product_http_profile import assert_product_manifest, assert_product_policy_manifest
    h = options_world
    schema = curated_openapi(h.child)
    assert_product_manifest(schema, export_runtime_registry(h.child))
    assert_product_policy_manifest(policy_registry(h.child))
    operation = schema["paths"]["/contracts/create-options"]["get"]
    assert operation["security"] == [{"ProductOAuth": ["contracts:create"]}, {"ProductServiceOAuth": ["contracts:create"]}]
    assert operation["tags"] == ["Договоры"] and "requestBody" not in operation
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    response_schema = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
    assert set(response_schema["required"]) == {"resource", "items", "selectionVersion", "nextCursor"}
    assert any(item.get("type") == "null" for item in response_schema["properties"]["nextCursor"]["anyOf"])
    assert not h.sessions  # Metadata assembly is not a positive auth/SQL probe.


@pytest.mark.parametrize("constraint", ["own_organization", "counterparty_scope", "installation_locations", "object_scope"])
async def test_effective_domains_recomputed_on_every_page(options_world, constraint):
    h, w = options_world, options_world.w
    await add_opaque_locations(w)
    first = await get(h, pageSize=1)
    assert values(first) and first.json()["nextCursor"]
    async with w.factory() as db:
        if constraint == "own_organization":
            other_org = Organization(id=uuid4(), company_id=w.company, name="Synthetic different own", inn="", prefix="O")
            db.add(other_org); await db.flush()
            (await db.get(UserCompany, (w.user, w.company))).own_organization_id = other_org.id
        elif constraint == "counterparty_scope":
            scope = await db.scalar(select(PartnerResourceScope).where(
                PartnerResourceScope.installation_id == w.iid, PartnerResourceScope.kind == "counterparties"))
            scope.mode = "EMPTY"
        elif constraint == "installation_locations":
            await db.execute(delete(PartnerInstallationLocation).where(PartnerInstallationLocation.installation_id == w.iid))
        else:
            (await db.get(UserCompany, (w.user, w.company))).object_scope = []
        await db.commit()
    problem(await get(h, pageSize=1, cursor=first.json()["nextCursor"]), 400, "invalid_cursor")
    # All four domains/constraints bind every page, even for a different resource.
    fresh = await get(h)
    assert fresh.status_code == 200 and fresh.json()["selectionVersion"] != first.json()["selectionVersion"]
    closed(h)


async def test_actual_database_refuses_test_write_on_selection_root(options_world, monkeypatch):
    h, original, states = options_world, options._load, []

    def readonly_probe(db, current):
        result = original(db, current)  # Whole real SELECT projection first.
        try:
            db.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=policy_generation WHERE id=:p"),
                {"p": h.w.profile})  # Negative test probe; never production SQL.
        except Exception as failure:
            cause = getattr(failure, "orig", failure)
            states.append(getattr(cause, "sqlstate", getattr(cause, "pgcode", None)))
            raise
        raise AssertionError("PostgreSQL accepted a write in the selection transaction")

    monkeypatch.setattr(options, "_load", readonly_probe)
    before = await state(h.w)
    problem(await get(h), 503, "api_unavailable")
    assert states == ["25006"]  # Actual read_only_sql_transaction server refusal.
    assert await state(h.w) == before
    closed(h)
