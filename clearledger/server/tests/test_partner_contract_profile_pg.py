"""AUTHOR ONLY / NOTRUN. ROOT supplies `profile_admin_factory`: an actual
async_sessionmaker on its admitted isolated schema4/Core READ COMMITTED target.
This module supplies NO runner, URL/env selection, approval or schema provisioning.
Ordinary pytest/collection is UNSAFE: parent conftest imports app/engine and DROP
before module guards. ROOT must compose preimports/fixtures separately first.
All verification below uses the real original B issuer and public native auth.
"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import token_for
from app.database import get_db
from app.models import (App, AuditEvent, Company, CompanyApp, Counterparty,
                        Organization, ServiceLocation, User, UserCompany)
from app.models_partner import PartnerClient, PartnerGrant, PartnerInstallation
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type)
from app.routers import partner_admin_router
from app.services import contract_write_locks as locks, partner_identity as identity
from app.services import partner_contract_profiles as profiles

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def world(profile_admin_factory, monkeypatch):
    factory = profile_admin_factory  # ROOT-owned admission, not conftest's factory.
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    monkeypatch.setattr(identity.settings, "partner_oauth_enabled", True)
    suffix = uuid4().hex
    async with factory() as db:
        assert await db.scalar(text("SHOW transaction_isolation")) == "read committed"
        assert await db.scalar(text("SELECT current_schema()")) == "core"
        company = Company(id=uuid4(), name="Synthetic profile", slug="pc-"+suffix, profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic home", slug="ph-"+suffix, profile_id="energy")
        db.add_all([company, other]); await db.flush()
        admin = User(id=uuid4(), company_id=company.id, name="Synthetic profile admin",
            email=suffix+"@profile.invalid", password_hash="synthetic", is_superadmin=False)
        member = User(id=uuid4(), company_id=other.id, name="Synthetic foreign-home member",
            email="m"+suffix+"@profile.invalid", password_hash="synthetic", is_superadmin=False)
        outsider = User(id=uuid4(), company_id=other.id, name="Synthetic outsider",
            email="o"+suffix+"@profile.invalid", password_hash="synthetic", is_superadmin=False)
        db.add_all([admin, member, outsider]); await db.flush()
        db.add_all([UserCompany(user_id=admin.id, company_id=company.id, role="admin"),
                    UserCompany(user_id=member.id, company_id=company.id, role="user")])
        app = App(id=uuid4(), code="pc-"+suffix, name="Synthetic partner", kind="partner", is_active=False)
        db.add(app); await db.flush()
        client_id = "pc-"+suffix
        db.add(PartnerClient(id=client_id, app_id=app.id, owner_company_id=other.id,
            auth_method="client_secret_basic", enabled=False, redirect_uris=[], allowed_scopes=[]))
        await db.flush()
        iid = uuid4()
        db.add(CompanyApp(id=iid, company_id=company.id, app_id=app.id, enabled=False)); await db.flush()
        db.add(PartnerInstallation(id=iid, company_id=company.id, client_id=client_id,
            approved=False, scopes=[], all_locations=False)); await db.flush()
        grant = PartnerGrant(id=uuid4(), installation_id=iid, company_id=company.id,
            client_id=client_id, kind="machine", approved=False, scopes=[])
        user_grant = PartnerGrant(id=uuid4(), installation_id=iid, company_id=company.id,
            client_id=client_id, kind="user", user_id=member.id, approved=False, scopes=[])
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic CP", aliases=[])
        org = Organization(id=uuid4(), company_id=company.id, name="Synthetic Org", inn="", prefix="S")
        foreign_cp = Counterparty(id=uuid4(), company_id=other.id, name="Foreign CP", aliases=[])
        loc = ServiceLocation(id="  ОПАК:"+suffix[:16]+"  ", company_id=company.id,
            code="pc-"+suffix, name="Synthetic location", source_bindings=[])
        db.add_all([grant, user_grant, cp, org, foreign_cp, loc]); await db.flush()
        code = "pc-"+suffix
        await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true)"), {"c": code})
        await db.commit()
        token = token_for(admin, expires_at=identity.now()+timedelta(minutes=20))
        nonadmin = token_for(member, expires_at=identity.now()+timedelta(minutes=20))
        w = SimpleNamespace(factory=factory, company=company.id, other=other.id, admin=admin.id,
            member=member.id, outsider=outsider.id, iid=iid, client_id=client_id, grant=grant.id,
            user_grant=user_grant.id, cp=cp.id, foreign_cp=foreign_cp.id, org=org.id, loc=loc.id,
            code=code, token=token, nonadmin=nonadmin)
    app = FastAPI()
    app.include_router(partner_admin_router.router, prefix="/api")
    async def sessions():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = sessions  # Real Session only, never auth/verifier.
    w.path = f"/api/developer/installations/{w.iid}/contract-create-profile"
    w.headers = {"Authorization": "Bearer "+w.token}
    w.body = dict(userIds=[str(w.member)], machineGrantIds=[str(w.grant)],
        organizationIds=[str(w.org)], counterpartyIds=[str(w.cp)], locationIds=[w.loc], typeCodes=[w.code])
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="https://synthetic.invalid") as client:
        w.http = client
        yield w


async def counts(w):
    async with w.factory() as db:
        profile = (await db.execute(select(Profile).where(Profile.installation_id == w.iid))).scalar_one_or_none()
        audit = await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.company))
        children = []
        for model in (Principal, Ref, Type):
            children.append(await db.scalar(select(func.count()).select_from(model).where(
                model.profile_id == (profile.id if profile else uuid4()))))
        return (profile.policy_generation if profile else None, audit, tuple(children))


async def put(w, body=None):
    return await w.http.put(w.path, headers=w.headers, json=w.body if body is None else body)


async def test_real_issuer_full_keys_current_auth_and_disabled_graph_cleanup(world, monkeypatch):
    w = world
    original = identity.acquire_scoped_locks
    seen = []
    def observe(db, plan):
        cap = original(db, plan)
        locks.require_scoped_locks(db, cap, plan.requests)
        seen.append((cap, plan, {r.key for r in plan.requests}))
        return cap  # The actual issuer's instance, never a manufactured success.
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    response = await put(w)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["policyGeneration"] == 1 and not result["userEnabled"] and not result["serviceEnabled"]
    assert result["locationIds"] == [w.loc] and result["userIds"] == [str(w.member)]
    assert len(seen) == 1
    keys = seen[0][2]
    assert {locks.CompanyKey(w.company), locks.CompanyKey(w.other), locks.InstallationKey(w.iid),
            locks.UserKey(w.admin), locks.UserKey(w.member), locks.MemberKey(w.company, w.member),
            locks.RefCompositeKey(w.company), locks.TypeCatalogKey(w.code)} <= keys
    assert not any(type(k) is locks.RoleKey for k in keys)  # Native admin policy does not read named roles.
    response = await put(w, {**w.body, "expectedGeneration": 1, "revoked": True})
    assert response.status_code == 200 and response.json()["policyGeneration"] == 2
    assert await counts(w) == (2, 2, (2, 3, 1))


async def test_readback_missing_coherent_share_no_presence_or_audit_dml(world, monkeypatch):
    w = world
    assert (await w.http.get(w.path, headers=w.headers)).status_code == 404
    assert (await put(w)).status_code == 200
    before = await counts(w)
    async with w.factory() as db:
        presence = (await db.get(User, w.admin)).last_seen_at
    modes = []
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        modes.extend(r.mode for r in plan.requests if type(r.key) is locks.CreateProfileKey)
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    response = await w.http.get(w.path, headers=w.headers)
    assert response.status_code == 200 and response.json()["policyGeneration"] == 1
    assert response.json()["typeCodes"] == [w.code]
    assert modes == [locks.LockMode.SHARED]
    assert await counts(w) == before
    async with w.factory() as db:
        assert (await db.get(User, w.admin)).last_seen_at == presence


@pytest.mark.parametrize("method", ["get", "put"])
async def test_false_flag_and_real_nonadmin_bearer_denied(world, monkeypatch, method):
    w = world
    async def call(headers):
        return await w.http.request(method, w.path, headers=headers, **({"json": w.body} if method == "put" else {}))
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", False)
    assert (await call(w.headers)).status_code == 503
    monkeypatch.setattr(identity.settings, "partner_contract_create_admin_enabled", True)
    assert (await call({"Authorization": "Bearer "+w.nonadmin})).status_code == 403
    assert (await call({"Authorization": "Bearer invalid"})).status_code == 401
    assert await counts(w) == (None, 0, (0, 0, 0))


@pytest.mark.parametrize("field", ["userEnabled", "serviceEnabled", "user_enabled", "service_enabled"])
async def test_activation_cannot_be_injected(world, field):
    assert (await put(world, {**world.body, field: True})).status_code == 422
    assert await counts(world) == (None, 0, (0, 0, 0))


@pytest.mark.parametrize("kind", ["foreign_ref", "missing_user", "nonmember", "user_grant", "missing_grant"])
async def test_foreign_references_and_actual_machine_identity_denied(world, kind):
    w = world
    change = {"foreign_ref": {"counterpartyIds": [str(w.foreign_cp)]},
              "missing_user": {"userIds": [str(uuid4())]}, "nonmember": {"userIds": [str(w.outsider)]},
              "user_grant": {"machineGrantIds": [str(w.user_grant)]},
              "missing_grant": {"machineGrantIds": [str(uuid4())]}}[kind]
    assert (await put(w, {**w.body, **change})).status_code == 422
    assert await counts(w) == (None, 0, (0, 0, 0))


async def test_cas_revoke_and_inactive_removal_but_no_new_inactive_type(world):
    w = world
    assert (await put(w)).status_code == 200
    assert (await put(w)).status_code == 409
    assert (await put(w, {**w.body, "expectedGeneration": 2})).status_code == 409
    async with w.factory() as db:
        await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": w.code})
        await db.commit()
    # Removal/revocation of existing inactive metadata remains possible.
    response = await put(w, {**w.body, "expectedGeneration": 1, "revoked": True, "typeCodes": []})
    assert response.status_code == 200 and response.json()["policyGeneration"] == 2
    assert (await put(w, {**w.body, "expectedGeneration": 2})).status_code == 422
    assert await counts(w) == (2, 2, (2, 3, 0))


async def test_commit_ack_loss_is_unknown_and_fresh_readback_recovers(world, monkeypatch):
    w = world
    original = AsyncSession.commit
    fired = False
    async def lost_ack(db):
        nonlocal fired
        await original(db)
        if not fired:
            fired = True
            raise ConnectionError("Synthetic loss AFTER actual commit")
    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", lost_ack)
        assert (await put(w)).status_code == 500
    result = await w.http.get(w.path, headers=w.headers)
    assert result.status_code == 200 and result.json()["policyGeneration"] == 1
    assert await counts(w) == (1, 1, (2, 3, 1))
    assert (await put(w)).status_code == 409  # Blind recreate is never successful replay.


def own_root_counts(db, w):
    """Actual SQL state in the writer root; no mapper/spy stands in for INSERTs."""
    pid = db.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
    children = tuple(db.scalar(select(func.count()).select_from(model).where(model.profile_id == pid))
                     for model in (Principal, Ref, Type))
    audit = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.company))
    return (int(pid is not None), *children, audit)


@pytest.mark.parametrize("phase", ["parent", "children_audit"])
async def test_actual_flush_fault_rolls_back_profile_children_and_audit(world, phase):
    w, seen = world, []
    expected = (1, 0, 0, 0, 0) if phase == "parent" else (1, 2, 3, 1, 1)
    marker = Profile if phase == "parent" else AuditEvent
    def after_flush(db, context):
        if any(type(row) is marker for row in db.identity_map.values()):
            actual = own_root_counts(db, w)
            assert actual == expected
            seen.append(actual)
            raise RuntimeError("Synthetic post-flush failure")
    from sqlalchemy.orm import Session
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        assert (await put(w)).status_code == 500
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
    assert seen == [expected]  # Failure AFTER the asserted real SQL rows existed.
    assert await counts(w) == (None, 0, (0, 0, 0))


async def blocked_reader(w, pid, blocker_pid):
    # Actual server lock observation, not task.done()/a sleep as proof of blocking.
    for _ in range(200):
        async with w.factory() as observer:
            blocked = await observer.scalar(text("SELECT :b=ANY(pg_blocking_pids(:p))"), {"p": pid, "b": blocker_pid})
            locks_seen = (await observer.execute(text("SELECT locktype,mode,granted FROM pg_locks WHERE pid=:p"), {"p": pid})).all()
        if blocked:
            assert any(not row.granted for row in locks_seen)
            return
        await asyncio.sleep(.01)
    raise AssertionError("Actual request PID never blocked behind the actual blocker")


@pytest.mark.parametrize("drift", ["absent_winner", "generation", "whole_child_set", "home_pointer"])
async def test_original_discovery_drift_during_actual_typed_wait_never_follows_new_parents(world, monkeypatch, drift):
    w = world
    if drift != "absent_winner":
        assert (await put(w)).status_code == 200
    before = await counts(w)
    pid_ready, pid_box = asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
        pid_ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        cap = await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        locks.require_scoped_locks(blocker.sync_session, cap, cap.plan.requests)
        task = asyncio.create_task(put(w, {**w.body, **({"expectedGeneration": 1} if drift != "absent_winner" else {})}))
        try:
            await asyncio.wait_for(pid_ready.wait(), 5)
            await blocked_reader(w, pid_box["pid"], blocker_pid)
            # Deliberately non-participating SQL models the drift negative. It
            # must cause root abort, never a newly discovered parent/key/lock.
            if drift == "absent_winner":
                blocker.add(Profile(id=uuid4(), installation_id=w.iid, company_id=w.company,
                    client_id=w.client_id, policy_generation=1, user_enabled=False, service_enabled=False, revoked=False))
            elif drift == "generation":
                await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE installation_id=:i"), {"i": w.iid})
            elif drift == "whole_child_set":
                old = await blocker.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
                await blocker.execute(text("DELETE FROM core.partner_contract_create_types WHERE profile_id=:p"), {"p": old})
            else:
                await blocker.execute(text("UPDATE core.users SET company_id=NULL WHERE id=:u"), {"u": w.member})
            await blocker.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 409, response.text
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    after = await counts(w)
    assert after[1] == before[1]  # Failed request never adds audit/profile children.


async def test_cancel_while_real_typed_wait_rolls_back_root(world, monkeypatch):
    w = world
    pid_ready, pid_box = asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); pid_ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.InstallationKey(w.iid), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(put(w))
        try:
            await asyncio.wait_for(pid_ready.wait(), 5)
            await blocked_reader(w, pid_box["pid"], bp)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    assert await counts(w) == (None, 0, (0, 0, 0))


async def test_real_foreign_machine_grant_never_substitutes_client_or_installation(world):
    w = world
    async with w.factory() as db:
        suffix = uuid4().hex
        app = App(id=uuid4(), code="foreign-"+suffix, name="Synthetic foreign client", kind="partner")
        db.add(app); await db.flush()
        client = PartnerClient(id="foreign-"+suffix, app_id=app.id, owner_company_id=w.other,
            auth_method="client_secret_basic", enabled=False, allowed_scopes=[], redirect_uris=[])
        db.add(client); await db.flush()
        iid = uuid4()
        db.add(CompanyApp(id=iid, company_id=w.other, app_id=app.id, enabled=False)); await db.flush()
        db.add(PartnerInstallation(id=iid, company_id=w.other, client_id=client.id, approved=False)); await db.flush()
        grant = PartnerGrant(id=uuid4(), installation_id=iid, company_id=w.other,
            client_id=client.id, kind="machine", approved=False)
        db.add(grant); await db.commit()
        foreign = grant.id
    assert (await put(w, {**w.body, "machineGrantIds": [str(foreign)]})).status_code == 422
    assert await counts(w) == (None, 0, (0, 0, 0))


async def test_generation_change_during_actual_profile_row_wait_is_root_rollback(world, monkeypatch):
    w = world
    assert (await put(w)).status_code == 200
    pid_ready, pid_box = asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        cap = original(db, plan)
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); pid_ready.set()
        return cap
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(select(Profile).where(Profile.installation_id == w.iid).with_for_update())
        task = asyncio.create_task(put(w, {**w.body, "expectedGeneration": 1}))
        try:
            await asyncio.wait_for(pid_ready.wait(), 5)
            await blocked_reader(w, pid_box["pid"], bp)
            await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE installation_id=:i"), {"i": w.iid})
            await blocker.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.status_code == 409, response.text
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    assert await counts(w) == (2, 1, (2, 3, 1))


async def test_current_public_native_authority_is_checked_after_actual_flush(world):
    w = world
    from sqlalchemy.orm import Session
    def revoke_in_actual_root(db, context):
        if any(type(row) is AuditEvent for row in db.identity_map.values()):
            assert own_root_counts(db, w) == (1, 2, 3, 1, 1)
            # A negative injection into the actual DB root, not a mocked verifier:
            # fresh public native session_valid must observe the changed version.
            db.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.admin})
    event.listen(Session, "after_flush_postexec", revoke_in_actual_root)
    try:
        response = await put(w)
        assert response.status_code == 401, response.text
    finally:
        event.remove(Session, "after_flush_postexec", revoke_in_actual_root)
    assert await counts(w) == (None, 0, (0, 0, 0))


async def test_actual_get_row_wait_keeps_generation_and_allowlists_coherent(world, monkeypatch):
    w = world
    assert (await put(w)).status_code == 200
    pid_ready, pid_box = asyncio.Event(), {}
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        cap = original(db, plan)
        pid_box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); pid_ready.set()
        return cap
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(select(Profile).where(Profile.installation_id == w.iid).with_for_update())
        task = asyncio.create_task(w.http.get(w.path, headers=w.headers))
        try:
            await asyncio.wait_for(pid_ready.wait(), 5)
            await blocked_reader(w, pid_box["pid"], bp)
            profile_id = await blocker.scalar(select(Profile.id).where(Profile.installation_id == w.iid))
            await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE id=:p"), {"p": profile_id})
            await blocker.execute(text("DELETE FROM core.partner_contract_create_types WHERE profile_id=:p"), {"p": profile_id})
            await blocker.commit()
            # It must not publish a mixed old-generation/new-children snapshot.
            assert (await asyncio.wait_for(task, 5)).status_code == 409
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    result = await w.http.get(w.path, headers=w.headers)
    assert result.status_code == 200
    assert result.json()["policyGeneration"] == 2 and result.json()["typeCodes"] == []
    assert await counts(w) == (2, 1, (2, 3, 0))


async def test_actual_capability_is_not_transferable_or_live_after_root_ends(world):
    w = world
    async with w.factory() as first, w.factory() as second:
        plan = locks.LockPlan((locks.LockRequest(locks.InstallationKey(w.iid), locks.LockMode.SHARED),))
        cap = await locks.acquire_scoped_locks_async(first, plan)
        locks.require_scoped_locks(first.sync_session, cap, plan.requests)
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(second.sync_session, cap, plan.requests)
        # A hand-built lookalike is a NEGATIVE, never a verifier success fixture.
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(first.sync_session, locks.ScopedLockCapability(plan), plan.requests)
        await first.rollback()
        with pytest.raises(locks.ScopedLockError):
            locks.require_scoped_locks(first.sync_session, cap, plan.requests)


@pytest.mark.parametrize("phase", ["parent", "children_audit"])
async def test_cancellation_after_actual_flush_rolls_back_all_rows(world, phase):
    w, seen = world, []
    expected = (1, 0, 0, 0, 0) if phase == "parent" else (1, 2, 3, 1, 1)
    marker = Profile if phase == "parent" else AuditEvent
    from sqlalchemy.orm import Session
    def cancel_after_flush(db, context):
        if any(type(row) is marker for row in db.identity_map.values()):
            actual = own_root_counts(db, w)
            assert actual == expected
            seen.append(actual)
            raise asyncio.CancelledError()
    event.listen(Session, "after_flush_postexec", cancel_after_flush)
    try:
        with pytest.raises(asyncio.CancelledError):
            await put(w)
    finally:
        event.remove(Session, "after_flush_postexec", cancel_after_flush)
    assert seen == [expected]
    assert await counts(w) == (None, 0, (0, 0, 0))
