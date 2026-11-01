"""AUTHOR ONLY / NOTRUN (also collection). ROOT must provide the admitted
activation_admin_factory on isolated schema4/Core, READ COMMITTED. No runner,
environment/URL selection, approval, DDL or positive auth/SQL stand-ins here.
Parent conftest is destructive; do not collect without ROOT's composition.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth import token_for
from app.database import get_db
from app.models import (App, AuditEvent, Company, CompanyApp, CompanyRole, Contract,
                        Counterparty, Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerGrant, PartnerInstallation,
                                PartnerResourceScope, PartnerResourceItem)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type, PartnerContractSuccessIntent as Intent)
from app.routers import partner_admin_router
from app.services import partner_identity as identity, contract_write_locks as locks
from app.services import partner_contract_activation as activation
from tests.partner_contract_issuer_fixture import issuer_world, native_org_admin

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(activation_admin_factory, monkeypatch):
    factory = activation_admin_factory
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    monkeypatch.setattr(identity.settings, "partner_oauth_enabled", True)
    suffix = uuid4().hex
    async with factory() as db:
        assert await db.scalar(text("SHOW transaction_isolation")) == "read committed"
        assert await db.scalar(text("SELECT current_schema()")) == "core"
        company = Company(id=uuid4(), name="Synthetic activation", slug="ac-"+suffix, profile_id="energy")
        home = Company(id=uuid4(), name="Synthetic home", slug="ah-"+suffix, profile_id="energy")
        db.add_all([company, home]); await db.flush()
        admin = User(id=uuid4(), company_id=company.id, name="Activation admin",
            email="a"+suffix+"@activation.invalid", password_hash="synthetic", is_superadmin=False)
        member = User(id=uuid4(), company_id=home.id, name="Activation member",
            email="m"+suffix+"@activation.invalid", password_hash="synthetic", is_superadmin=False)
        role = CompanyRole(id=uuid4(), company_id=company.id, name="Synthetic role", modules=None)
        db.add_all([admin, member, role]); await db.flush()
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Profile CP", aliases=[])
        extra_cp = Counterparty(id=uuid4(), company_id=company.id, name="Member CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Profile Org", inn="", prefix="S")
        extra_org = Organization(id=uuid4(), company_id=company.id, name="Admin Org", inn="", prefix="T")
        loc = ServiceLocation(id="  ОПАК:"+suffix[:16]+"  ", company_id=company.id,
            code="al-"+suffix, name="Profile location", source_bindings=[])
        extra_loc = ServiceLocation(id="extra-"+suffix[:16], company_id=company.id,
            code="ax-"+suffix, name="Canonical location", source_bindings=[])
        db.add_all([cp, extra_cp, org, extra_org, loc, extra_loc]); await db.flush()
        db.add_all([UserCompany(user_id=admin.id, company_id=company.id, role="admin",
                                own_organization_id=extra_org.id),
                    UserCompany(user_id=member.id, company_id=company.id, role="user",
                                role_id=role.id, organization_id=extra_cp.id,
                                own_organization_id=org.id, object_scope=None)])
        app = App(id=uuid4(), code="ac-"+suffix, name="Synthetic partner", kind="partner", is_active=False)
        db.add(app); await db.flush()
        client_id = "ac-"+suffix
        db.add(PartnerClient(id=client_id, app_id=app.id, owner_company_id=home.id,
            auth_method="client_secret_basic", enabled=False, redirect_uris=[], allowed_scopes=[]))
        await db.flush()
        iid = uuid4()
        db.add(CompanyApp(id=iid, company_id=company.id, app_id=app.id, enabled=False)); await db.flush()
        db.add(PartnerInstallation(id=iid, company_id=company.id, client_id=client_id,
            approved=False, scopes=[], all_locations=True)); await db.flush()
        grant = PartnerGrant(id=uuid4(), installation_id=iid, company_id=company.id,
            client_id=client_id, kind="machine", user_id=None, approved=False, scopes=[])
        db.add(grant)
        db.add_all([PartnerResourceScope(installation_id=iid, kind="counterparties", mode="ALL"),
                    PartnerResourceScope(installation_id=iid, kind="objects", mode="SET")])
        await db.flush()
        db.add_all([PartnerResourceItem(installation_id=iid, kind="objects", object_id=loc.id),
                    PartnerResourceItem(installation_id=iid, kind="objects", object_id=extra_loc.id)])
        code, inactive = "ac-"+suffix, "ai-"+suffix
        await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true),(:i,'Inactive',false)"),
                         {"c": code, "i": inactive})
        await db.commit()
        w = SimpleNamespace(factory=factory, company=company.id, home=home.id, admin=admin.id,
            member=member.id, role=role.id, iid=iid, client_id=client_id, grant=grant.id,
            cp=cp.id, extra_cp=extra_cp.id, org=org.id, extra_org=extra_org.id,
            loc=loc.id, extra_loc=extra_loc.id, code=code, inactive=inactive)
        # Both tokens are signed from their actual own User, never ID-substituted claims.
        w.headers = {"Authorization": "Bearer "+token_for(admin, expires_at=identity.now()+timedelta(minutes=20))}
        w.member_headers = {"Authorization": "Bearer "+token_for(member, expires_at=identity.now()+timedelta(minutes=20))}
    app = FastAPI()
    app.include_router(partner_admin_router.router, prefix="/api")
    async def sessions():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = sessions  # Actual AsyncSession; native auth untouched.
    w.base = f"/api/developer/installations/{iid}/contract-create-profile"
    w.path = w.base+"/activation"
    w.selection = dict(userIds=[str(w.member)], machineGrantIds=[str(w.grant)],
        organizationIds=[str(w.org)], counterpartyIds=[str(w.cp)], locationIds=[w.loc],
        typeCodes=[w.code, w.inactive])
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="https://synthetic.invalid") as http:
        w.http = http
        # Existing replace forbids adding inactive types. First create with the
        # active code, then deactivate that unrelated second selected code.
        async with factory() as db:
            await db.execute(text("UPDATE core.contract_types SET is_active=true WHERE code=:c"), {"c": inactive})
            await db.commit()
        response = await http.put(w.base, headers=w.headers, json=w.selection)
        assert response.status_code == 200, response.text
        assert response.json()["userEnabled"] is False and response.json()["serviceEnabled"] is False
        async with factory() as db:
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": inactive})
            await db.commit()
        yield w


async def put(w, generation=1, user=True, service=True, headers=None):
    return await w.http.put(w.path, headers=w.headers if headers is None else headers,
        json=dict(expectedGeneration=generation, userEnabled=user, serviceEnabled=service))


async def state(w):
    """Independent fresh SQL, including full child rows and business counts."""
    async with w.factory() as db:
        profile = (await db.execute(select(Profile).where(Profile.installation_id == w.iid))).scalar_one()
        children = []
        for model in (Principal, Ref, Type):
            rows = (await db.execute(select(*model.__table__.c).where(model.profile_id == profile.id))).all()
            children.append(tuple(sorted(tuple(map(str, row)) for row in rows)))
        audit = (await db.execute(select(AuditEvent.action, AuditEvent.details).where(
            AuditEvent.company_id == w.company).order_by(AuditEvent.timestamp, AuditEvent.id))).all()
        counts = tuple([await db.scalar(select(func.count()).select_from(model).where(
            model.company_id == w.company)) for model in (Contract, Intent, PartnerGrant)])
        return dict(generation=profile.policy_generation, user=profile.user_enabled,
            service=profile.service_enabled, children=tuple(children), audit=tuple(audit), counts=counts)


async def assert_unchanged(w, before):
    assert await state(w) == before


async def test_enable_same_flags_disable_and_new_cas_rollback_keep_children_and_counts(world):
    w = world
    before = await state(w)
    for generation, user, service in [(1, True, True), (2, True, True), (3, False, False), (4, True, False)]:
        result = await put(w, generation, user, service)
        assert result.status_code == 200, result.text
        assert result.json()["policyGeneration"] == generation+1
        assert (result.json()["userEnabled"], result.json()["serviceEnabled"]) == (user, service)
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    events = [json.loads(details) for action, details in after["audit"] if action == "partner.contract_profile.activation"]
    assert [e["generation"] for e in events] == [2, 3, 4, 5]
    assert all(set(e) == {"profileId", "generation", "userEnabled", "serviceEnabled"} for e in events)
    assert (await put(w, 1)).status_code == 409


async def test_real_native_nonadmin_invalid_bearer_and_closed_gate(world, monkeypatch):
    w = world
    before = await state(w)
    assert (await put(w, headers=w.member_headers)).status_code == 403
    assert (await put(w, headers={"Authorization": "Bearer invalid"})).status_code == 401
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    assert (await put(w)).status_code == 503
    await assert_unchanged(w, before)


@pytest.mark.parametrize("case", ["missing", "stale", "overflow", "revoked"])
async def test_missing_cas_overflow_and_revoked_enable_denied(world, case):
    w = world
    async with w.factory() as db:
        if case == "missing":
            await db.execute(text("DELETE FROM core.partner_contract_create_profiles WHERE installation_id=:i"), {"i": w.iid})
        elif case == "overflow":
            await db.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=9223372036854775807 WHERE installation_id=:i"), {"i": w.iid})
        elif case == "revoked":
            await db.execute(text("UPDATE core.partner_contract_create_profiles SET revoked=true WHERE installation_id=:i"), {"i": w.iid})
        await db.commit()
    if case == "missing":
        assert (await put(w)).status_code == 404
        return
    before = await state(w)
    response = await put(w, 2 if case == "stale" else before["generation"])
    assert response.status_code == 409, response.text
    await assert_unchanged(w, before)
    if case == "revoked":
        assert (await put(w, 1, False, False)).status_code == 200


@pytest.mark.parametrize("empty", ["user", "machine", "org", "cp", "loc", "types", "member_scope", "own_org", "objects", "counterparties", "installation"])
async def test_true_requires_corresponding_principal_and_nonempty_legal_selection(world, empty):
    w = world
    async with w.factory() as db:
        pid = await db.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
        if empty in {"user", "machine"}:
            await db.execute(text("DELETE FROM core.partner_contract_create_principals WHERE profile_id=:p AND actor_kind=:k"), {"p": pid, "k": empty})
        elif empty in {"org", "cp", "loc"}:
            kind = {"org": "organization", "cp": "counterparty", "loc": "location"}[empty]
            await db.execute(text("DELETE FROM core.partner_contract_create_refs WHERE profile_id=:p AND kind=:k"), {"p": pid, "k": kind})
        elif empty == "types":
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": w.code})
        elif empty == "member_scope":
            await db.execute(text("UPDATE core.user_companies SET object_scope='[]'::jsonb WHERE user_id=:u AND company_id=:c"), {"u": w.member, "c": w.company})
        elif empty == "own_org":
            await db.execute(text("UPDATE core.user_companies SET own_organization_id=:o WHERE user_id=:u AND company_id=:c"), {"o": w.extra_org, "u": w.member, "c": w.company})
        elif empty in {"objects", "counterparties"}:
            await db.execute(text("UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:i AND kind=:k"), {"i": w.iid, "k": empty})
        else:
            await db.execute(text("UPDATE core.partner_installations SET all_locations=false WHERE id=:i"), {"i": w.iid})
        await db.commit()
    before = await state(w)
    # User-only constraints cannot incorrectly veto a requested machine-only enable.
    response = await put(w, user=empty != "machine", service=empty not in {"user", "member_scope", "own_org"})
    assert response.status_code == 409, response.text
    await assert_unchanged(w, before)
    assert (await put(w, user=False, service=False)).status_code == 200


async def test_one_original_b_exact_x_keys_full_closure_and_physical_parent_union(world, monkeypatch):
    w, observed, sql, dml = world, [], [], []
    original = identity.acquire_scoped_locks
    original_activation = activation.activate_partner_contract_create_profile
    contexts = []
    def observe(db, plan):
        cap = original(db, plan)
        locks.require_scoped_locks(db, cap, plan.requests)
        observed.append((db, db.get_transaction(), db.connection(), cap, plan))
        return cap
    def on_actual_session(db, *args):
        root, connection = db.get_transaction(), db.connection()
        result = original_activation(db, *args)
        assert len(observed) == 1
        actual, acquired_root, acquired_connection, cap, plan = observed[0]
        assert actual is db and acquired_root is root and acquired_connection is connection
        assert db.get_transaction() is root and db.connection() is connection
        locks.require_scoped_locks(db, cap, plan.requests)
        contexts.append((db, root, connection))
        return result
    def statements(conn, cursor, statement, params, context, many):
        if "FOR SHARE" in statement or "FOR UPDATE" in statement:
            sql.append((statement, str(params)))
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            dml.append(statement)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    monkeypatch.setattr(activation, "activate_partner_contract_create_profile", on_actual_session)
    engine = w.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", statements)
    try:
        assert (await put(w)).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", statements)
    assert len(observed) == 1
    assert len(contexts) == 1
    assert len(dml) == 2
    assert all("core.partner_contract_create_profiles" in statement or "core.audit_events" in statement for statement in dml)
    db, root, connection, cap, plan = observed[0]
    assert len(plan.requests) == len({r.key for r in plan.requests})
    keys = {r.key: r.mode for r in plan.requests}
    assert keys[locks.InstallationKey(w.iid)] == locks.LockMode.EXCLUSIVE
    assert keys[locks.CreateProfileKey(UUID((await w.http.get(w.base, headers=w.headers)).json()["profileId"]))] == locks.LockMode.EXCLUSIVE
    assert {locks.CompanyKey(w.home), locks.RoleKey(w.company, w.role), locks.UserKey(w.member)} <= keys.keys()
    member_index = next(i for i, (statement, _) in enumerate(sql) if "core.user_companies" in statement)
    for table, ids in [("core.counterparties", [w.cp, w.extra_cp]),
                       ("core.organizations", [w.org, w.extra_org]),
                       ("core.service_locations", [w.loc, w.extra_loc])]:
        entries = [(i, params) for i, (statement, params) in enumerate(sql) if table in statement]
        assert len(entries) == len(ids) and all(i < member_index for i, _ in entries)
        assert all(any(str(ident) in params for _, params in entries) for ident in ids)
    with pytest.raises(locks.ScopedLockError):
        locks.require_scoped_locks(db, cap, plan.requests)  # Completed original root.


async def blocked(w, pid, blocker_pid):
    for _ in range(300):
        async with w.factory() as observer:
            waiting = await observer.scalar(text("SELECT :b=ANY(pg_blocking_pids(:p))"), {"b": blocker_pid, "p": pid})
            rows = (await observer.execute(text("SELECT granted FROM pg_locks WHERE pid=:p"), {"p": pid})).all()
        if waiting:
            assert any(not row.granted for row in rows)
            return
        await asyncio.sleep(.01)
    raise AssertionError("Actual request PID did not wait on the actual blocker")


@pytest.mark.parametrize("phase", ["typed", "parent", "profile", "type", "children"])
@pytest.mark.parametrize("change", ["token", "admin", "closed_gate", "member_pointer"])
async def test_actual_last_wait_rechecks_current_native_and_full_member_pointers(world, monkeypatch, phase, change):
    w, ready, pid_box = world, asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        assert bp != pid_box.get("pid")
        if phase == "typed":
            await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
                locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        elif phase == "parent":
            await blocker.execute(select(Organization).where(Organization.id == w.extra_org).with_for_update())
        elif phase == "profile":
            await blocker.execute(select(Profile).where(Profile.installation_id == w.iid).with_for_update())
        elif phase == "type":
            await blocker.execute(text("SELECT code FROM core.contract_types WHERE code=:c FOR UPDATE"), {"c": w.code})
        else:
            pid = await blocker.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
            await blocker.execute(select(Principal).where(Principal.profile_id == pid).with_for_update())
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, pid_box["pid"], bp)
            injected = []
            marker = {"typed": "pg_advisory_xact_lock", "parent": "core.organizations",
                      "profile": "core.partner_contract_create_profiles",
                      "type": "core.contract_types", "children": "core.partner_contract_create_principals"}[phase]
            def after_actual_wait(conn, cursor, statement, params, context, many):
                if injected or marker not in statement or not (
                        phase == "typed" or "FOR SHARE" in statement or "FOR UPDATE" in statement):
                    return
                if conn.scalar(text("SELECT pg_backend_pid()")) != pid_box["pid"]:
                    return
                injected.append(True)
                # Deliberate negative injection into the ACTUAL request root
                # immediately after its proven SQL wait returns. No verifier,
                # auth result or lock success is mocked; same-root UPDATE also
                # works after this request already holds User/Member SHARE.
                if change == "closed_gate":
                    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
                elif change == "member_pointer":
                    conn.execute(text("UPDATE core.user_companies SET own_organization_id=:o WHERE user_id=:u AND company_id=:c"),
                                 {"o": w.extra_org, "u": w.member, "c": w.company})
                elif change == "token":
                    conn.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.admin})
                else:
                    conn.execute(text("UPDATE core.user_companies SET role='user' WHERE user_id=:u AND company_id=:c"),
                                 {"u": w.admin, "c": w.company})
            engine = w.factory.kw["bind"].sync_engine
            event.listen(engine, "after_cursor_execute", after_actual_wait)
            try:
                await blocker.commit()
                response = await asyncio.wait_for(task, 5)
                assert response.status_code in {401, 403, 409, 503}, response.text
                assert injected == [True]
            finally:
                event.remove(engine, "after_cursor_execute", after_actual_wait)
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    await assert_unchanged(w, before)


@pytest.mark.parametrize("failure", ["fault", "cancel", "token", "admin", "closed_gate"])
async def test_actual_flush_flags_audit_and_public_auth_failure_roll_back_whole_root(world, monkeypatch, failure):
    w, seen = world, []
    before = await state(w)
    def after_flush(db, context):
        actions = db.scalars(select(AuditEvent).where(AuditEvent.company_id == w.company,
                            AuditEvent.action == "partner.contract_profile.activation")).all()
        if not actions:
            return
        profile = db.scalar(select(Profile).where(Profile.installation_id == w.iid))
        assert profile.policy_generation == 2 and profile.user_enabled and profile.service_enabled
        assert len(actions) == 1
        seen.append(profile.policy_generation)
        if failure == "fault":
            raise RuntimeError("Synthetic fault AFTER actual SQL flush")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "token":
            db.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.admin})
        elif failure == "admin":
            db.execute(text("UPDATE core.user_companies SET role='user' WHERE user_id=:u AND company_id=:c"), {"u": w.admin, "c": w.company})
        else:
            monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await put(w)
        else:
            assert (await put(w)).status_code in {401, 403, 409, 500, 503}
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
    assert seen == [2]
    await assert_unchanged(w, before)


@pytest.mark.parametrize("contender", ["replace", "revoke", "activation"])
async def test_concurrent_activation_replace_revoke_are_one_winner_stale_409(world, contender):
    w = world
    before = await state(w)
    other = (put(w, 1, False, False) if contender == "activation" else
        w.http.put(w.base, headers=w.headers, json={**w.selection,
            "typeCodes": [w.code], "expectedGeneration": 1, "revoked": contender == "revoke"}))
    responses = await asyncio.gather(put(w), other)
    assert sorted(r.status_code for r in responses) == [200, 409]
    after = await state(w)
    assert after["generation"] == 2 and len(after["audit"]) == len(before["audit"])+1
    assert after["counts"] == before["counts"]


async def test_unknown_commit_ack_requires_fresh_current_auth_readback_and_new_cas(world, monkeypatch):
    w, original, fired = world, AsyncSession.commit, False
    before = await state(w)
    async def lost_ack(db):
        nonlocal fired
        await original(db)
        if not fired:
            fired = True
            raise ConnectionError("Synthetic loss AFTER commit; outcome unknown to caller")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", lost_ack)
        assert (await put(w)).status_code == 500
    result = await w.http.get(w.base, headers=w.headers)
    assert result.status_code == 200 and result.json()["policyGeneration"] == 2
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    assert len(after["audit"]) == len(before["audit"])+1
    assert (await put(w)).status_code == 409
    assert (await put(w, 2, False, False)).status_code == 200


async def test_cancel_during_actual_typed_wait_does_not_mutate(world, monkeypatch):
    w, ready, box = world, asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.InstallationKey(w.iid), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, box["pid"], bp)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    await assert_unchanged(w, before)


@pytest.mark.parametrize("disabled", ["app", "grant", "both"])
async def test_structural_activation_never_restores_actual_external_oauth_or_post_authority(issuer_world, monkeypatch, disabled):
    """Ratified msg_cc8cade6fd88: configuration can precede OAuth readiness.

The SAME Authlib-issued bearer first passes the real canonical verifier, then
loses actual SQL eligibility, then stays denied after successful activation.
"""
    from app.product_api.app import create_product_api
    from app.product_api import budget
    w = issuer_world
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    async with w.factory() as db:
        current = await identity.verify_partner_access_token(w.machine, db)
        assert current.is_machine and current.grant_id == w.machine_grant
        assert "contracts:create" in current.scopes
    admin_token = await native_org_admin(w)  # Actual new admin SQL + own signed claims.
    headers = {"Authorization": "Bearer "+admin_token}
    parent = FastAPI()
    parent.include_router(partner_admin_router.router, prefix="/api")
    async def get_sessions():
        async with w.factory() as db:
            yield db
    parent.dependency_overrides[get_db] = get_sessions
    path = f"/api/developer/installations/{w.iid}/contract-create-profile/activation"
    async with AsyncClient(transport=ASGITransport(app=parent), base_url="https://synthetic.invalid") as http:
        off = await http.put(path, headers=headers,
            json=dict(expectedGeneration=1, userEnabled=False, serviceEnabled=False))
        assert off.status_code == 200 and off.json()["policyGeneration"] == 2
        async with w.factory() as db:
            if disabled in {"app", "both"}:
                (await db.get(App, w.app_id)).is_active = False
            if disabled in {"grant", "both"}:
                (await db.get(PartnerGrant, w.machine_grant)).approved = False
            await db.commit()
        async def oauth_state():
            async with w.factory() as db:
                queries = [select(*PartnerGrant.__table__.c).where(PartnerGrant.installation_id == w.iid),
                    select(*PartnerInstallation.__table__.c).where(PartnerInstallation.id == w.iid),
                    select(*CompanyApp.__table__.c).where(CompanyApp.id == w.iid),
                    select(*PartnerResourceScope.__table__.c).where(PartnerResourceScope.installation_id == w.iid),
                    select(*PartnerResourceItem.__table__.c).where(PartnerResourceItem.installation_id == w.iid)]
                return tuple(tuple(sorted(tuple(map(str, row)) for row in (await db.execute(query)).all()))
                             for query in queries)
        before, oauth_before = await state(w), await oauth_state()
        assert before["counts"][:2] == (0, 0)
        async with w.factory() as db:
            with pytest.raises(HTTPException) as error:
                await identity.verify_partner_access_token(w.machine, db)
            assert error.value.status_code == 401
        on = await http.put(path, headers=headers,
            json=dict(expectedGeneration=2, userEnabled=True, serviceEnabled=True))
        assert on.status_code == 200, on.text
        assert on.json()["policyGeneration"] == 3 and on.json()["userEnabled"] and on.json()["serviceEnabled"]
    async with w.factory() as db:
        with pytest.raises(HTTPException) as error:
            await identity.verify_partner_access_token(w.machine, db)
        assert error.value.status_code == 401
    @asynccontextmanager
    async def actual_sessions():
        async with w.factory() as db:
            yield db
    child = create_product_api(session_factory=actual_sessions, enabled=True,
        issuer="https://issuer.synthetic.invalid", cursor_key=b"synthetic-activation-key-32bytes!!",
        budget_policy=budget.Policy(enabled=False))
    external = FastAPI()
    external.mount("/api/v1", child)
    async with AsyncClient(transport=ASGITransport(app=external), base_url="https://issuer.synthetic.invalid") as http:
        denied = await http.post("/api/v1/contracts", headers={"Authorization": "Bearer "+w.machine,
                                 "Content-Type": "application/json"},
                                 content=w.body.model_dump_json())
    assert denied.status_code == 401
    after = await state(w)
    assert after["children"] == before["children"] and after["counts"] == before["counts"]
    assert len(after["audit"]) == len(before["audit"])+1
    assert await oauth_state() == oauth_before  # No consent/grant/resource issuance or rewrites.


async def test_exact_type_purpose_and_subclass_rejection_on_actual_native_session(world):
    from app.services.partner_contract_profiles import ProfileOperation, profile_core_user
    from app.schemas_partner import ActivateContractCreateProfile
    w = world
    class Child(activation.ActivationOperation):
        pass
    body = ActivateContractCreateProfile(expectedGeneration=1, userEnabled=False, serviceEnabled=False)
    for purpose, operation in [
            ("contract-profile-activation", Child(w.iid, body)),
            ("contract-profile-activation", ProfileOperation(w.iid, None)),
            ("contract-profile-read", activation.ActivationOperation(w.iid, body)),
            ("contract-profile-write", activation.ActivationOperation(w.iid, body)),
            ("contract-create", activation.ActivationOperation(w.iid, body))]:
        async with w.factory() as db:
            credentials = SimpleNamespace(credentials=w.headers["Authorization"][7:])
            actor = await profile_core_user(db, credentials)
            native = identity._native_authority(db, credentials, actor)
            with pytest.raises(locks.ScopedLockError):
                await db.run_sync(lambda sync: identity._prepare_partner_write(sync,
                    installation_id=w.iid, company_id=w.company, client_id=w.client_id,
                    admin_company=w.company, actor=actor, native=native,
                    mutation=purpose, contract_profile=operation))
            await db.rollback()


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_internal_service_leaves_original_root_completion_to_actual_caller(world, finish):
    from app.schemas_partner import ActivateContractCreateProfile
    from app.services.partner_contract_profiles import profile_core_user
    w = world
    before = await state(w)
    async with w.factory() as db:
        credentials = SimpleNamespace(credentials=w.headers["Authorization"][7:])
        actor = await profile_core_user(db, credentials)
        native = identity._native_authority(db, credentials, actor)
        root = db.sync_session.get_transaction()
        result = await db.run_sync(activation.activate_partner_contract_create_profile,
            w.iid, actor, native, ActivateContractCreateProfile(
                expectedGeneration=1, userEnabled=True, serviceEnabled=True))
        assert result.policyGeneration == 2 and db.sync_session.get_transaction() is root
        await assert_unchanged(w, before)  # Fresh SQL cannot see uncommitted flags/audit.
        if finish == "commit":
            await db.commit()
        else:
            await db.rollback()
    after = await state(w)
    if finish == "rollback":
        assert after == before
    else:
        assert after["generation"] == 2 and len(after["audit"]) == len(before["audit"])+1
        assert after["children"] == before["children"] and after["counts"] == before["counts"]


async def test_empty_actual_member_rows_keep_explicit_parent_boundary(world, monkeypatch):
    w = world
    async with w.factory() as db:
        await db.execute(text("DELETE FROM core.partner_contract_create_principals WHERE profile_id=(SELECT id FROM core.partner_contract_create_profiles WHERE installation_id=:i) AND actor_kind='user'"), {"i": w.iid})
        await db.execute(text("DELETE FROM core.user_companies WHERE company_id=:c"), {"c": w.company})
        await db.execute(text("UPDATE core.users SET is_superadmin=true WHERE id=:u"), {"u": w.admin})
        await db.commit()
    original = activation.ActivationOperation.lock_parents
    boundaries = []
    def boundary(operation):
        assert not operation.writer.db.execute(select(UserCompany.user_id).where(
            UserCompany.company_id == w.company)).all()
        boundaries.append(True)
        return original(operation)
    monkeypatch.setattr(activation.ActivationOperation, "lock_parents", boundary)
    response = await put(w, user=False, service=True)
    assert response.status_code == 200, response.text
    assert boundaries == [True]


@pytest.mark.parametrize("drift", ["home", "role", "member_cp", "children"])
async def test_external_committed_graph_drift_during_real_b_wait_never_expands_plan(world, monkeypatch, drift):
    w, ready, box, issued = world, asyncio.Event(), {}, []
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        issued.append(plan)
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    before = await state(w)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            await blocked(w, box["pid"], bp)
            if drift == "home":
                await blocker.execute(text("UPDATE core.users SET company_id=NULL WHERE id=:u"), {"u": w.member})
            elif drift == "role":
                await blocker.execute(text("UPDATE core.company_roles SET modules='[]'::jsonb WHERE id=:r"), {"r": w.role})
            elif drift == "member_cp":
                await blocker.execute(text("UPDATE core.user_companies SET organization_id=:p WHERE user_id=:u AND company_id=:c"),
                                      {"p": w.cp, "u": w.member, "c": w.company})
            else:
                await blocker.execute(text("DELETE FROM core.partner_contract_create_types WHERE type_code=:t AND profile_id=(SELECT id FROM core.partner_contract_create_profiles WHERE installation_id=:i)"),
                                      {"t": w.inactive, "i": w.iid})
            await blocker.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 409, response.text
            assert len(issued) == 1
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    after = await state(w)
    assert after["generation"] == before["generation"]
    assert after["audit"] == before["audit"] and after["counts"] == before["counts"]


@pytest.mark.parametrize("corruption", ["role_owner", "profile_ref_owner", "member_ref_owner"])
async def test_full_graph_foreign_owner_corruption_is_denied_before_b(world, monkeypatch, corruption):
    w, calls = world, []
    async with w.factory() as db:
        if corruption == "role_owner":
            await db.execute(text("UPDATE core.company_roles SET company_id=:c WHERE id=:r"), {"c": w.home, "r": w.role})
        else:
            rid = w.cp if corruption == "profile_ref_owner" else w.extra_cp
            await db.execute(text("UPDATE core.counterparties SET company_id=:c WHERE id=:p"), {"c": w.home, "p": rid})
        await db.commit()
    before = await state(w)
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        calls.append(plan)
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    response = await put(w)
    assert response.status_code in {409, 422}, response.text
    assert calls == []
    await assert_unchanged(w, before)
