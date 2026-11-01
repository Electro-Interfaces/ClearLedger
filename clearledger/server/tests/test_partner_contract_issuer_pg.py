"""AUTHOR ONLY / NOTRUN, including collection. See fixture module's ROOT gate.

All positive paths use real HTTP/Authlib tokens, canonical policy, B and SQL.
Observers delegate originals; negative drift injections never return fake allow.
"""
import asyncio
from copy import copy
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import await_only
from sqlalchemy.orm import Session

from app.models import (App, AuditEvent, CompanyApp, CompanyRole, Contract, ContractLocation,
                        Organization, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant,
    PartnerInstallation, PartnerInstallationLocation, PartnerResourceItem, PartnerResourceScope,
    PartnerToken, PartnerTokenFamily)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type, PartnerContractSuccessIntent as Intent,
    PartnerContractIntentLocation as IntentLocation)
from app.services import partner_contract_authority as authority
from app.services import partner_identity as identity, contract_write_locks as locks
from app.services.partner_contract_commands import create_partner_contract
from app.services.native_contract_commands import create_native_contract
from app.schemas import ContractCreate
from tests.partner_contract_issuer_fixture import (
    issuer_world, issue_machine, issue_user, make_body, state, add_opaque_locations,
    native_org_admin, native_org_delete,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def execute(w, body=None, bearer=None, commit=True):
    async with w.factory() as db:
        result = await create_partner_contract(db, bearer or w.bearer, body or w.body)
        if commit:
            await db.commit()
        return result


@pytest.mark.parametrize("kind", ["user", "machine"])
async def test_real_authlib_sql_issuer_consumer_atomic_commit_and_native_nulls(issuer_world, kind):
    w = issuer_world
    before = await state(w)
    result = await execute(w, bearer=w.machine if kind == "machine" else w.bearer)
    assert not result.replayed
    assert await state(w) == tuple(n+1 for n in before)
    async with w.factory() as db:
        card = await db.get(Contract, result.contract_id)
        intent = await db.scalar(select(Intent).where(Intent.current_contract_id == result.contract_id))
        assert (card.creation_key, card.creation_actor_id, card.creation_request_hash) == (None, None, None)
        assert (card.scope_type, card.is_closed, card.type_code) == ("locations", False, w.code)
        assert (intent.actor_kind, intent.actor_key, intent.current_user_id) == (
            ("machine", w.client_id, None) if kind == "machine" else ("user", str(w.user), w.user))
        assert intent.original_grant_id == (w.machine_grant if kind == "machine" else w.user_grant)
        assert tuple(await db.scalars(select(IntentLocation.location_id).where(IntentLocation.intent_id == intent.id))) == (w.loc,)


async def test_service_leaves_commit_to_caller_and_fresh_reader_sees_atomic_rollback(issuer_world):
    w = issuer_world
    before = await state(w)
    await execute(w, commit=False)
    assert await state(w) == before


async def test_one_complete_original_b_and_legacy_order_before_any_row_lock(issuer_world, monkeypatch):
    w, plans, events = issuer_world, [], []
    original, legacy = identity.acquire_scoped_locks, authority.lock_manual_creation
    def observe(db, plan):
        cap = original(db, plan)
        plans.append(plan); events.append("B")
        return cap
    async def observe_legacy(db, cid, entity):
        events.append(entity)
        return await legacy(db, cid, entity)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    monkeypatch.setattr(authority, "lock_manual_creation", observe_legacy)
    await execute(w)
    assert len(plans) == 1 and events == ["B", "counterparty", "contract"]
    keys = {r.key for r in plans[0].requests}
    assert {locks.CompanyKey(w.company), locks.CompanyKey(w.other), locks.AppKey(w.app_id),
        locks.ClientKey(w.client_id), locks.InstallationKey(w.iid), locks.UserKey(w.user),
        locks.MemberKey(w.company, w.user), locks.RoleKey(w.company, w.role),
        locks.CreateProfileKey(w.profile), locks.RefCompositeKey(w.company), locks.TypeCatalogKey(w.code)} <= keys


@pytest.mark.parametrize("gate", ["user_enabled", "service_enabled", "revoked", "principal", "type", "org", "cp", "loc"])
async def test_profile_false_empty_or_unlisted_denies_real_token(issuer_world, gate):
    w = issuer_world
    async with w.factory() as db:
        if gate in {"user_enabled", "service_enabled", "revoked"}:
            await db.execute(text("UPDATE core.partner_contract_create_profiles SET " + gate + "=:v WHERE id=:p"),
                             {"v": gate == "revoked", "p": w.profile})
        elif gate == "principal":
            await db.execute(delete(Principal).where(Principal.profile_id == w.profile))
        elif gate == "type":
            await db.execute(delete(Type).where(Type.profile_id == w.profile))
        else:
            await db.execute(delete(Ref).where(Ref.profile_id == w.profile,
                Ref.kind == {"org": "organization", "cp": "counterparty", "loc": "location"}[gate]))
        await db.commit()
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, bearer=w.machine if gate == "service_enabled" else w.bearer)
    assert denied.value.status_code == 403 and await state(w) == before


@pytest.mark.parametrize("restriction", ["role", "membership", "own_org", "user_objects", "grant_locations",
    "client_scope", "installation_scope", "grant_scope", "credential", "inactive_type", "foreign_cp"])
async def test_actual_current_policy_and_every_reference_intersection(issuer_world, restriction):
    w, body = issuer_world, issuer_world.body
    async with w.factory() as db:
        if restriction == "role":
            (await db.get(CompanyRole, w.role)).modules = []
        elif restriction == "membership":
            await db.execute(delete(UserCompany).where(UserCompany.user_id == w.user, UserCompany.company_id == w.company))
        elif restriction == "own_org":
            org = Organization(id=uuid4(), company_id=w.company, name="Synthetic other own", inn="", prefix="O")
            db.add(org); await db.flush()
            (await db.get(UserCompany, (w.user, w.company))).own_organization_id = org.id
        elif restriction == "user_objects":
            (await db.get(UserCompany, (w.user, w.company))).object_scope = []
        elif restriction == "grant_locations":
            await db.execute(delete(PartnerInstallationLocation).where(PartnerInstallationLocation.installation_id == w.iid))
        elif restriction == "client_scope":
            (await db.get(PartnerClient, w.client_id)).allowed_scopes = ["contracts:read"]
        elif restriction == "installation_scope":
            (await db.get(PartnerInstallation, w.iid)).scopes = ["contracts:read"]
        elif restriction == "grant_scope":
            (await db.get(PartnerGrant, w.user_grant)).scopes = ["contracts:read"]
        elif restriction == "credential":
            (await db.get(PartnerCredential, w.credential)).enabled = False
        elif restriction == "inactive_type":
            await db.execute(text("UPDATE core.contract_types SET is_active=false WHERE code=:c"), {"c": w.code})
        else:
            body = make_body(w, counterpartyId=str(w.foreign_cp))
        await db.commit()
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, body)
    assert denied.value.status_code in {401, 403} and await state(w) == before


@pytest.mark.parametrize("kind,mode", [("objects", "EMPTY"), ("counterparties", "EMPTY"),
    ("objects", "SET"), ("counterparties", "SET"), ("objects", "ALL"), ("counterparties", "ALL")])
async def test_explicit_all_set_empty_are_not_collapsed(issuer_world, kind, mode):
    w = issuer_world
    async with w.factory() as db:
        await db.execute(delete(PartnerResourceItem).where(PartnerResourceItem.installation_id == w.iid,
            PartnerResourceItem.kind == kind))
        (await db.get(PartnerResourceScope, (w.iid, kind))).mode = mode
        await db.commit()
    before = await state(w)
    if mode == "ALL":
        assert not (await execute(w)).replayed  # Still intersected with profile refs.
    else:
        with pytest.raises(HTTPException):
            await execute(w)
        assert await state(w) == before


async def test_read_scope_and_hash_or_receipt_never_authorize_create(issuer_world):
    w = issuer_world
    read = await issue_machine(w, scope="contracts:read")
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, bearer=read)
    assert denied.value.status_code == 403 and await state(w) == before


async def test_machine_requires_actual_confidential_grant_user_null(issuer_world):
    w = issuer_world
    async with w.factory() as db:
        grant = await db.get(PartnerGrant, w.machine_grant)
        assert grant.kind == "machine" and grant.user_id is None
        assert (await db.get(PartnerClient, w.client_id)).auth_method == "client_secret_basic"
        verified = await db.run_sync(identity.verify_access, w.machine)
        assert verified.is_machine and verified.user_id is None
        (await db.get(PartnerClient, w.client_id)).auth_method = "none"
        await db.commit()
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, bearer=w.machine)
    assert denied.value.status_code == 401 and await state(w) == before


async def test_original_actor_binding_does_not_transfer_between_user_and_machine(issuer_world):
    w = issuer_world
    result = await execute(w, bearer=w.machine)
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, bearer=w.bearer)
    assert denied.value.status_code == 403 and str(result.contract_id) not in str(denied.value.detail)
    assert await state(w) == before


@pytest.mark.parametrize("revoked", ["app", "client", "installation", "company_app", "grant", "token", "family", "user"])
async def test_canonical_public_auth_remains_live_for_create(issuer_world, revoked):
    w = issuer_world
    async with w.factory() as db:
        verified = await db.run_sync(identity.verify_access, w.bearer)
        token = await db.get(PartnerToken, verified.token_id)
        if revoked == "app": (await db.get(App, w.app_id)).is_active = False
        elif revoked == "client": (await db.get(PartnerClient, w.client_id)).enabled = False
        elif revoked == "installation": (await db.get(PartnerInstallation, w.iid)).approved = False
        elif revoked == "company_app": (await db.get(CompanyApp, w.iid)).enabled = False
        elif revoked == "grant": (await db.get(PartnerGrant, w.user_grant)).approved = False
        elif revoked == "token": token.revoked = True
        elif revoked == "family": (await db.get(PartnerTokenFamily, token.family_id)).revoked = True
        else: (await db.get(User, w.user)).mail_only = True
        await db.commit()
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w)
    assert denied.value.status_code == 401 and await state(w) == before


@pytest.mark.parametrize("forgery", ["copy", "replace", "manual_stamp", "manual_admission", "caller_binding", "wrong_body", "wrong_namespace", "other_session"])
async def test_only_exact_issued_instance_body_namespace_and_session_work(issuer_world, forgery):
    w = issuer_world
    async with w.factory() as db, w.factory() as other:
        admission = await authority.prepare_create(db, w.bearer, w.body)
        await authority.require_create(db, admission, w.body)  # Actual positive issuer.
        candidate, body, target = admission, w.body, db
        if forgery == "copy": candidate = copy(admission)
        elif forgery == "replace": candidate = replace(admission)
        elif forgery == "manual_stamp": candidate = authority.CreateAdmission(authority._SQLStamp(1))
        elif forgery == "manual_admission": candidate = authority.CreateAdmission(admission._stamp)
        elif forgery == "caller_binding": candidate = {"session": db, "stamp": admission._stamp, "allowed": True}
        elif forgery == "wrong_body": body = make_body(w, creationKey=str(w.body.creationKey), comment="changed")
        elif forgery == "wrong_namespace": body = make_body(w)
        else: target = other
        with pytest.raises(locks.ScopedLockError):
            await authority.require_create(target, candidate, body)
        await db.rollback()


@pytest.mark.parametrize("ending", ["commit", "rollback", "savepoint", "invalidate"])
async def test_sql_stamp_lifetime_uses_existing_capability_lifetime(issuer_world, ending):
    w = issuer_world
    async with w.factory() as db:
        admission = await authority.prepare_create(db, w.bearer, w.body)
        if ending == "commit": await db.commit()
        elif ending == "rollback": await db.rollback()
        elif ending == "savepoint": await db.begin_nested()
        else: await db.invalidate()
        with pytest.raises(locks.ScopedLockError):
            await authority.require_create(db, admission, w.body)


async def test_borrowed_db_root_cannot_be_reentered_by_another_session(issuer_world):
    w = issuer_world
    async with w.factory.kw["bind"].connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, join_transaction_mode="rollback_only") as first:
            admission = await authority.prepare_create(first, w.bearer, w.body)
            await first.commit()  # rollback_only leaves the borrowed DB root alive.
            with pytest.raises(locks.ScopedLockError):
                await authority.require_create(first, admission, w.body)
        if transaction.is_active:
            async with AsyncSession(bind=connection, join_transaction_mode="rollback_only") as second:
                with pytest.raises(locks.ScopedLockError):
                    await authority.prepare_create(second, w.bearer, w.body)
        await connection.rollback()


async def test_autocommit_connection_cannot_issue_stamp(issuer_world):
    w = issuer_world
    engine = w.factory.kw["bind"].execution_options(isolation_level="AUTOCOMMIT")
    async with AsyncSession(engine) as db:
        with pytest.raises(locks.ScopedLockError):
            await authority.prepare_create(db, w.bearer, w.body)


async def test_multibind_root_cannot_issue_stamp(issuer_world):
    w = issuer_world
    async with w.factory.kw["bind"].connect() as other:
        async with AsyncSession(bind=w.factory.kw["bind"], binds={AuditEvent: other}) as db:
            await db.execute(select(AuditEvent).where(AuditEvent.company_id == w.company))
            with pytest.raises(locks.ScopedLockError):
                await authority.prepare_create(db, w.bearer, w.body)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_actual_connection_end_invalidates_stamp_even_if_session_retains_root(issuer_world, finish):
    w = issuer_world
    async with w.factory() as db:
        admission = await authority.prepare_create(db, w.bearer, w.body)
        connection = await db.connection()
        await (connection.commit() if finish == "commit" else connection.rollback())
        with pytest.raises(locks.ScopedLockError):
            await authority.require_create(db, admission, w.body)


async def test_no_reentry_or_savepoint_before_issuance(issuer_world):
    w = issuer_world
    async with w.factory() as db:
        await authority.prepare_create(db, w.bearer, w.body)
        with pytest.raises(locks.ScopedLockError):
            await authority.prepare_create(db, w.bearer, w.body)
    async with w.factory() as db:
        await db.begin_nested()
        with pytest.raises(locks.ScopedLockError):
            await authority.prepare_create(db, w.bearer, w.body)


async def test_same_key_same_original_grant_new_family_replays_without_read_scope(issuer_world):
    w = issuer_world
    original = await execute(w, bearer=w.machine)
    before = await state(w)
    fresh = await issue_machine(w)  # Real new family in SAME actual grant.
    replay = await execute(w, bearer=fresh)
    assert replay.replayed and replay.contract_id == original.contract_id
    assert await state(w) == before


async def test_new_credential_in_same_grant_can_replay_after_real_reauth(issuer_world):
    w = issuer_world
    original = await execute(w, bearer=w.machine)
    secret = uuid4().hex+uuid4().hex
    async with w.factory() as db:
        old = await db.get(PartnerCredential, w.credential)
        db.add(PartnerCredential(id=uuid4(), client_id=w.client_id, secret_hash=identity.digest(secret),
            enabled=True, expires_at=old.expires_at))
        await db.commit()
    fresh = await issue_machine(w, secret=secret)
    assert (await execute(w, bearer=fresh)).contract_id == original.contract_id


async def test_renewed_grant_never_inherits_original_receipt(issuer_world):
    w = issuer_world
    original = await execute(w, bearer=w.machine)
    async with w.factory() as db:
        renewed = PartnerGrant(id=uuid4(), installation_id=w.iid, company_id=w.company,
            client_id=w.client_id, kind="machine", approved=True, scopes=["contracts:create"])
        db.add(renewed); await db.flush()
        db.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="machine", machine_grant_id=renewed.id))
        await db.commit(); renewed_id = renewed.id
    token = await issue_machine(w, grant_id=renewed_id)
    with pytest.raises(HTTPException) as denied:
        await execute(w, bearer=token)
    assert denied.value.status_code == 403 and str(original.contract_id) not in str(denied.value.detail)


async def test_hash_mismatch_conflict_only_after_current_full_create_authorization(issuer_world):
    w = issuer_world
    await execute(w)
    mismatch = make_body(w, creationKey=str(w.body.creationKey), comment="changed")
    with pytest.raises(HTTPException) as conflict:
        await execute(w, mismatch)
    assert conflict.value.status_code == 409
    async with w.factory() as db:
        (await db.get(Profile, w.profile)).user_enabled = False
        await db.commit()
    with pytest.raises(HTTPException) as denied:
        await execute(w, mismatch)
    assert denied.value.status_code == 403 and "different content" not in str(denied.value.detail)


async def test_replay_rechecks_current_original_refs_and_has_no_read_fallback(issuer_world):
    w = issuer_world
    result = await execute(w)
    before = await state(w)
    async with w.factory() as db:
        await db.execute(delete(Ref).where(Ref.profile_id == w.profile, Ref.kind == "location"))
        await db.commit()
    with pytest.raises(HTTPException) as denied:
        await execute(w)
    assert denied.value.status_code == 403 and str(result.contract_id) not in str(denied.value.detail)
    assert await state(w) == before


async def test_unknown_commit_recovery_new_root_same_key_current_auth(issuer_world):
    w = issuer_world
    class LostAck(ConnectionError): pass
    async with w.factory() as db:
        result = await create_partner_contract(db, w.machine, w.body)
        with pytest.raises(LostAck):
            await db.commit()  # Actual commit; the synthetic fault is AFTER it.
            raise LostAck("Synthetic lost ACK after actual commit")
    before = await state(w)
    fresh = await issue_machine(w)
    replay = await execute(w, bearer=fresh)
    assert replay.replayed and replay.contract_id == result.contract_id and await state(w) == before


async def test_current_generation_issued_on_each_new_root_not_historical_intent(issuer_world):
    w = issuer_world
    await execute(w)
    async with w.factory() as db:
        (await db.get(Profile, w.profile)).policy_generation = 2
        await db.commit()
    async with w.factory() as db:
        admission = await authority.prepare_create(db, w.bearer, w.body)
        assert admission._stamp.generation == 2
        await authority.require_create(db, admission, w.body)
    assert (await execute(w)).replayed


async def blocked(w, pid, blocker_pid):
    for _ in range(300):
        async with w.factory() as observer:
            waiting = await observer.scalar(text("SELECT :b=ANY(pg_blocking_pids(:p))"), {"b": blocker_pid, "p": pid})
            rows = (await observer.execute(text("SELECT locktype,mode,granted FROM pg_locks WHERE pid=:p"), {"p": pid})).all()
        if waiting:
            assert any(not row.granted for row in rows)
            return
        await asyncio.sleep(.01)
    raise AssertionError("Writer's actual PID never blocked behind blocker PID")


@pytest.mark.parametrize("drift", ["generation", "flags", "principal", "refs", "types", "home_pointer", "absence"])
async def test_full_sets_and_absence_rechecked_after_actual_b_wait(issuer_world, monkeypatch, drift):
    w, box, ready = issuer_world, {}, asyncio.Event()
    missing_member = uuid4()
    if drift == "absence":
        async with w.factory() as seed:
            seed.add(User(id=missing_member, company_id=w.other, name="Synthetic unselected principal",
                email=missing_member.hex+"@issuer.invalid", password_hash="synthetic"))
            await seed.flush()
            seed.add(Principal(id=uuid4(), profile_id=w.profile, actor_kind="user", user_id=missing_member))
            await seed.commit()  # User exists; this exact company member is absent.
    before = await state(w)
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.TypeCatalogKey(w.code), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(execute(w))
        try:
            await asyncio.wait_for(ready.wait(), 5); await blocked(w, box["pid"], bp)
            if drift == "generation":
                await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE id=:p"), {"p": w.profile})
            elif drift == "flags":
                await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET user_enabled=false WHERE id=:p"), {"p": w.profile})
            elif drift == "principal":
                await blocker.execute(delete(Principal).where(Principal.profile_id == w.profile, Principal.user_id == w.user))
            elif drift == "refs":
                await blocker.execute(delete(Ref).where(Ref.profile_id == w.profile, Ref.kind == "location"))
            elif drift == "types":
                await blocker.execute(delete(Type).where(Type.profile_id == w.profile))
            elif drift == "home_pointer":
                await blocker.execute(text("UPDATE core.users SET company_id=NULL WHERE id=:u"), {"u": w.user})
            else:
                blocker.add(UserCompany(user_id=missing_member, company_id=w.company, role="user", modules=[]))
            await blocker.commit()
            with pytest.raises(HTTPException) as changed:
                await asyncio.wait_for(task, 5)
            assert changed.value.status_code == 409
        finally:
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    assert await state(w) == before


@pytest.mark.parametrize("drift", ["generation", "principal", "refs", "types"])
async def test_actual_profile_row_wait_rechecks_whole_current_policy(issuer_world, monkeypatch, drift):
    w, box, ready = issuer_world, {}, asyncio.Event()
    before = await state(w)
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        cap = original(db, plan)
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return cap
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await blocker.execute(select(Profile).where(Profile.id == w.profile).with_for_update())
        task = asyncio.create_task(execute(w))
        try:
            await asyncio.wait_for(ready.wait(), 5); await blocked(w, box["pid"], bp)
            if drift == "generation":
                await blocker.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE id=:p"), {"p": w.profile})
            else:
                model = {"principal": Principal, "refs": Ref, "types": Type}[drift]
                await blocker.execute(delete(model).where(model.profile_id == w.profile))
            await blocker.commit()
            with pytest.raises(HTTPException) as changed:
                await asyncio.wait_for(task, 5)
            assert changed.value.status_code == 409
        finally:
            if not task.done(): task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await blocker.rollback()
    assert await state(w) == before


@pytest.mark.parametrize("marker", [Contract, ContractLocation, Intent, IntentLocation])
@pytest.mark.parametrize("fault", ["generation", "principal", "refs", "types", "public_auth", "cancel"])
async def test_each_actual_flush_checks_current_generation_and_auth_or_rolls_back(issuer_world, marker, fault):
    w, observed, pending = issuer_world, [], set()
    before = await state(w)
    def before_flush(db, context, instances):
        if any(type(row) is marker for row in db.new):
            pending.add(db)
    def after_flush(db, context):
        if observed or db not in pending:
            return
        pending.remove(db)
        if marker is IntentLocation:
            actual = db.scalar(select(func.count()).select_from(IntentLocation).join(Intent,
                IntentLocation.intent_id == Intent.id).where(Intent.company_id == w.company))
        else:
            actual = db.scalar(select(func.count()).select_from(marker).where(marker.company_id == w.company))
        assert actual == 1
        observed.append(db.scalar(select(Contract.id).where(Contract.company_id == w.company)))
        assert observed[0] is not None  # SQL parent exists in actual root first.
        if fault == "cancel": raise asyncio.CancelledError()
        if fault == "generation":
            db.execute(text("UPDATE core.partner_contract_create_profiles SET policy_generation=2 WHERE id=:p"), {"p": w.profile})
        elif fault in {"principal", "refs", "types"}:
            model = {"principal": Principal, "refs": Ref, "types": Type}[fault]
            db.execute(delete(model).where(model.profile_id == w.profile))
        else:
            db.execute(text("UPDATE core.users SET token_version=token_version+1 WHERE id=:u"), {"u": w.user})
    event.listen(Session, "before_flush", before_flush)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        with pytest.raises(asyncio.CancelledError if fault == "cancel" else HTTPException):
            await execute(w)
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
        event.remove(Session, "before_flush", before_flush)
    assert len(observed) == 1 and await state(w) == before


async def test_cancel_actual_b_wait_rolls_back_entire_root(issuer_world, monkeypatch):
    w, box, ready = issuer_world, {}, asyncio.Event()
    before = await state(w)
    original = identity.acquire_scoped_locks
    def observe(db, plan):
        box["pid"] = db.scalar(text("SELECT pg_backend_pid()")); ready.set()
        return original(db, plan)
    monkeypatch.setattr(identity, "acquire_scoped_locks", observe)
    async with w.factory() as blocker:
        bp = await blocker.scalar(text("SELECT pg_backend_pid()"))
        await locks.acquire_scoped_locks_async(blocker, locks.LockPlan((
            locks.LockRequest(locks.InstallationKey(w.iid), locks.LockMode.EXCLUSIVE),)))
        task = asyncio.create_task(execute(w))
        try:
            await asyncio.wait_for(ready.wait(), 5); await blocked(w, box["pid"], bp)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        finally:
            await blocker.rollback()
            if not task.done(): task.cancel(); await asyncio.gather(task, return_exceptions=True)
    assert await state(w) == before


async def test_native_duplicate_matcher_serialization_and_hidden_ids(issuer_world):
    w = issuer_world
    async with w.factory() as db:
        user = await db.get(User, w.user)
        native = ContractCreate(company_id=str(w.company), number=w.body.number, date=w.body.date,
            counterpartyId=str(w.cp), organizationId=str(w.org), type=w.body.type, typeCode=w.code)
        card = await create_native_contract(db, native, user)
        await db.commit(); original_id = card.id
    before = await state(w)
    with pytest.raises(HTTPException) as conflict:
        await execute(w)
    assert conflict.value.status_code == 409 and str(original_id) not in str(conflict.value.detail)
    assert await state(w) == before


async def test_dedicated_fk_wait_is_not_claimed_by_flush_observation(issuer_world):
    """No dedicated FK wait is reachable for participating writers: all actual
    FK parents are SHARE-locked before DML. A conflicting DELETE/key UPDATE must
    wait at that earlier parent row phase. ROOT must independently confirm this
    invariant; post-flush generation injections above are NOT FK-wait evidence.
    """
    w = issuer_world
    async with w.factory() as db:
        admission = await authority.prepare_create(db, w.bearer, w.body)
        await authority.require_create(db, admission, w.body)
        async with w.factory() as contender:
            with pytest.raises(Exception) as blocked_parent:
                await contender.execute(select(Organization).where(Organization.id == w.org,
                    Organization.company_id == w.company).with_for_update(nowait=True))
            assert getattr(blocked_parent.value.orig, "sqlstate", None) == "55P03"
            await contender.rollback()


@pytest.mark.parametrize("kind", ["user", "machine"])
async def test_multiple_opaque_locations_ignore_snapshot_order_and_same_key_replays(issuer_world, monkeypatch, kind):
    w = issuer_world
    locations = await add_opaque_locations(w)
    body = make_body(w, coverage={"kind": "locations", "locationIds": list(reversed(locations))})
    before, observed = await state(w), set()
    with pytest.raises(ValueError):
        make_body(w, coverage={"kind": "locations", "locationIds": [*locations, locations[0]]})
    original = authority._rows
    def reordered_rows(db, statement):
        rows = original(db, statement)  # Actual SQL; never replaces verifier/policy/proof.
        columns = tuple((c.table.name, c.key) for c in getattr(statement, "selected_columns", ()))
        if columns in (((ContractLocation.__tablename__, "company_id"), (ContractLocation.__tablename__, "location_id")),
                       ((IntentLocation.__tablename__, "intent_id"), (IntentLocation.__tablename__, "location_id"))):
            if len(rows) >= 2:
                # Deliberately opposite to Python order, regardless of target collation.
                # Every value and duplicate is retained from original SQL return.
                observed.add(columns[0][0])
                return tuple(sorted(rows, reverse=True))
        return rows
    monkeypatch.setattr(authority, "_rows", reordered_rows)
    bearer = w.machine if kind == "machine" else w.bearer
    result = await execute(w, body, bearer)
    assert not result.replayed
    after = await state(w)
    assert after == tuple(n + delta for n, delta in zip(before, (1, len(locations), 1, 1, len(locations))))
    assert observed == {ContractLocation.__tablename__, IntentLocation.__tablename__}
    async with w.factory() as db:
        card_rows = tuple(await db.scalars(select(ContractLocation.location_id).where(
            ContractLocation.contract_id == result.contract_id)))
        intent = await db.scalar(select(Intent).where(Intent.current_contract_id == result.contract_id))
        intent_rows = tuple(await db.scalars(select(IntentLocation.location_id).where(IntentLocation.intent_id == intent.id)))
        assert len(card_rows) == len(intent_rows) == len(locations) == len(set(locations))
        assert sorted(card_rows) == sorted(intent_rows) == sorted(locations)
    # Replay preservation, not a claim that R01 previously affected replay.
    same_key = make_body(w, **{**body.model_dump(mode="json"),
        "coverage": {"kind": "locations", "locationIds": sorted(locations)}})
    replay = await execute(w, same_key, bearer)
    assert replay.replayed and replay.contract_id == result.contract_id
    assert await state(w) == after


@pytest.mark.parametrize("snapshot", ["card", "receipt"])
@pytest.mark.parametrize("fault", ["missing", "duplicate", "different_id"])
async def test_multiple_location_snapshot_drift_keeps_exact_cardinality_and_rolls_back(issuer_world, monkeypatch, snapshot, fault):
    w = issuer_world
    locations = await add_opaque_locations(w)
    body = make_body(w, coverage={"kind": "locations", "locationIds": list(locations)})
    before, observed = await state(w), []
    original = authority._rows
    model, parent = (ContractLocation, "company_id") if snapshot == "card" else (IntentLocation, "intent_id")
    def negative_rows(db, statement):
        rows = original(db, statement)
        columns = tuple((c.table.name, c.key) for c in getattr(statement, "selected_columns", ()))
        if columns == ((model.__tablename__, parent), (model.__tablename__, "location_id")) and rows:
            # Negative snapshot fault only, AFTER actual full multi-row SQL flush.
            # No new authority or fabricated positive rows; original rows exist.
            assert len(rows) == len(locations)
            observed.append(len(rows))
            if fault == "missing": return rows[:-1]
            if fault == "duplicate": return (*rows, rows[0])
            return ((rows[0][0], rows[0][1] + " "), *rows[1:])
        return rows
    monkeypatch.setattr(authority, "_rows", negative_rows)
    with pytest.raises(HTTPException) as drift:
        await execute(w, body)
    assert drift.value.status_code == 409 and observed == [len(locations)]
    assert await state(w) == before  # All five atomic parts absent in fresh SQL.


@pytest.mark.parametrize("ceiling", ["profile", "resource", "membership", "installation"])
async def test_multiple_locations_one_uncovered_exact_id_denies_whole_create(issuer_world, ceiling):
    w = issuer_world
    locations = await add_opaque_locations(w)
    missing = locations[-1]
    body = make_body(w, coverage={"kind": "locations", "locationIds": list(locations)})
    async with w.factory() as db:
        if ceiling == "profile":
            await db.execute(delete(Ref).where(Ref.profile_id == w.profile, Ref.location_id == missing))
        elif ceiling == "resource":
            await db.execute(delete(PartnerResourceItem).where(PartnerResourceItem.installation_id == w.iid,
                PartnerResourceItem.kind == "objects", PartnerResourceItem.object_id == missing))
        elif ceiling == "membership":
            (await db.get(UserCompany, (w.user, w.company))).object_scope = list(locations[:-1])
        else:
            await db.execute(delete(PartnerInstallationLocation).where(
                PartnerInstallationLocation.installation_id == w.iid, PartnerInstallationLocation.location_id == missing))
        await db.commit()
    before = await state(w)
    with pytest.raises(HTTPException) as denied:
        await execute(w, body)
    assert denied.value.status_code == 403 and await state(w) == before


@pytest.mark.parametrize("snapshot", ["card", "receipt"])
async def test_multiple_locations_actual_sql_child_drift_after_flush_rolls_back(issuer_world, snapshot):
    w = issuer_world
    locations = await add_opaque_locations(w)
    requested = locations[1:]
    body = make_body(w, coverage={"kind": "locations", "locationIds": list(requested)})
    before, observed, pending = await state(w), [], set()
    marker = ContractLocation if snapshot == "card" else IntentLocation
    def before_flush(db, context, instances):
        if any(type(row) is marker for row in db.new):
            pending.add(db)
    def after_flush(db, context):
        if observed or db not in pending:
            return
        pending.remove(db)
        card = db.scalar(select(Contract.id).where(Contract.company_id == w.company))
        assert card is not None
        if snapshot == "card":
            actual = tuple(db.scalars(select(ContractLocation.location_id).where(ContractLocation.contract_id == card)))
            assert sorted(actual) == sorted(requested)
            db.execute(delete(ContractLocation).where(ContractLocation.contract_id == card,
                ContractLocation.location_id == requested[0]))
        else:
            iid = db.scalar(select(Intent.id).where(Intent.current_contract_id == card))
            actual = tuple(db.scalars(select(IntentLocation.location_id).where(IntentLocation.intent_id == iid)))
            assert sorted(actual) == sorted(requested)
            # Real extra immutable child in its birth transaction; no trigger bypass.
            db.execute(IntentLocation.__table__.insert().values(intent_id=iid, location_id=locations[0]))
        observed.append(len(actual))
    event.listen(Session, "before_flush", before_flush)
    event.listen(Session, "after_flush_postexec", after_flush)
    try:
        with pytest.raises(HTTPException) as drift:
            await execute(w, body)
        assert drift.value.status_code == 409
    finally:
        event.remove(Session, "after_flush_postexec", after_flush)
        event.remove(Session, "before_flush", before_flush)
    assert observed == [len(requested)] and await state(w) == before


async def org_wait_evidence(w, waiter, holder):
    """Bounded polling is only pacing; actual PID graph and SQL locks are proof."""
    for _ in range(300):
        async with w.factory() as reader:
            blockers = tuple(await reader.scalar(text("SELECT pg_blocking_pids(:p)"), {"p": waiter}))
            rows = (await reader.execute(text(
                "SELECT pid,locktype,mode,granted,relation::regclass::text AS relation,transactionid::text "
                "FROM pg_locks WHERE pid IN (:w,:h) ORDER BY pid,locktype,mode"),
                {"w": waiter, "h": holder})).mappings().all()
            query = await reader.scalar(text("SELECT query FROM pg_stat_activity WHERE pid=:p"), {"p": waiter})
        if holder in blockers:
            assert any(row["pid"] == waiter and not row["granted"] for row in rows)
            assert any(row["pid"] == holder and row["granted"] for row in rows)
            evidence = {"waiter": waiter, "holder": holder, "blockers": blockers,
                        "locks": [dict(row) for row in rows], "query": query}
            if not hasattr(w, "org_order_evidence"):
                w.org_order_evidence = []
            w.org_order_evidence.append(evidence)  # ROOT may retain actual raw observations.
            return evidence
        await asyncio.sleep(.01)
    raise AssertionError("Expected real Org lock edge was not observed")


def org_delete_signals():
    return {"attempted": asyncio.Event(), "flushed": asyncio.Event(), "release": asyncio.Event()}


def canonical_share_statement(statement, model):
    return (getattr(statement, "_for_update_arg", None) is not None
            and statement._for_update_arg.read
            and any(column.get("entity") is model for column in getattr(statement, "column_descriptions", ())))


@pytest.mark.parametrize("creator_finish", ["commit", "rollback"])
async def test_org_delete_creator_first_waits_at_org_before_ri_member(issuer_world, monkeypatch, creator_finish):
    """1848-byte G-ORG01 plan, AFTER FIX: real MemberS implies earlier OrgS."""
    w = issuer_world
    native = await native_org_admin(w)
    before = await state(w)
    signals, member_locked, resume = org_delete_signals(), asyncio.Event(), asyncio.Event()
    observed, parent_stages = [], []
    original_parents = authority.CreateOperation.lock_parents
    def parents(operation):
        result = original_parents(operation)
        parent_stages.append("complete")
        return result
    monkeypatch.setattr(authority.CreateOperation, "lock_parents", parents)
    async with w.factory() as creator, w.factory() as deleter:
        creator_pid = await creator.scalar(text("SELECT pg_backend_pid()"))
        def after_actual_member(context):
            result = context.invoke_statement()
            if canonical_share_statement(context.statement, UserCompany) and not member_locked.is_set():
                assert parent_stages == ["complete"]
                observed.append("real_MemberS")
                member_locked.set()
                await_only(resume.wait())
            return result
        event.listen(creator.sync_session, "do_orm_execute", after_actual_member, retval=True)
        async def create():
            result = await create_partner_contract(creator, w.bearer, w.body)
            assert not result.replayed
            if creator_finish == "commit":
                await creator.commit()
            else:
                await creator.rollback()
            return result
        task = asyncio.create_task(create())
        native_task = None
        try:
            await asyncio.wait_for(member_locked.wait(), 10)
            assert await state(w) == before  # No business DML at the canonical Member pause.
            native_task = asyncio.create_task(native_org_delete(w, deleter, native, signals, finish="commit"))
            await asyncio.wait_for(signals["attempted"].wait(), 10)
            evidence = await org_wait_evidence(w, signals["pid"], creator_pid)
            assert "delete" in evidence["query"].lower() and "organizations" in evidence["query"].lower()
            # Blocked at original Org DELETE, BEFORE RI can UPDATE Member.
            assert not any(row["pid"] == signals["pid"] and row["mode"] == "RowExclusiveLock"
                           and row["relation"] in {"core.user_companies", "user_companies"}
                           for row in evidence["locks"])
            assert not signals["flushed"].is_set()
            resume.set()
            await asyncio.wait_for(task, 10)  # 40P01/cancellation/partial success are failures.
            expected = tuple(n+1 for n in before) if creator_finish == "commit" else before
            assert await state(w) == expected  # Fresh reader: all five parts commit or roll back.
            signals["release"].set()
            try:
                await asyncio.wait_for(native_task, 10)
            except DBAPIError as error:
                # Contract->Org NO ACTION or NOT NULL can legitimately reject
                # native deletion AFTER a successful CREATE. Never alter the FK.
                assert creator_finish == "commit"
                assert getattr(error.orig, "sqlstate", None) in {"23503", "23502"}
            assert observed == ["real_MemberS"] and await state(w) == expected
        finally:
            resume.set(); signals["release"].set()
            for pending in (task, native_task):
                if pending is not None and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
            event.remove(creator.sync_session, "do_orm_execute", after_actual_member)
            await creator.rollback(); await deleter.rollback()


@pytest.mark.parametrize("deleter_finish", ["commit", "rollback"])
async def test_org_delete_deleter_first_rechecks_without_null_scope_broadening(issuer_world, deleter_finish):
    """Actual native OrgX/RI MemberX first; CREATE waits before Member/business DML."""
    w = issuer_world
    native = await native_org_admin(w)
    before, signals = await state(w), org_delete_signals()
    shares, business_flushes = [], []
    async with w.factory() as creator, w.factory() as deleter:
        creator_pid = await creator.scalar(text("SELECT pg_backend_pid()"))
        def record_share(context):
            if canonical_share_statement(context.statement, UserCompany):
                shares.append("MemberS_attempt")
            return context.invoke_statement()
        def business_flush(session, context, instances):
            business_flushes.extend(type(row).__name__ for row in session.new
                if isinstance(row, (Contract, ContractLocation, Intent, IntentLocation, AuditEvent)))
        event.listen(creator.sync_session, "do_orm_execute", record_share, retval=True)
        event.listen(creator.sync_session, "before_flush", business_flush)
        native_task = asyncio.create_task(native_org_delete(w, deleter, native, signals, finish=deleter_finish))
        task = None
        try:
            await asyncio.wait_for(signals["flushed"].wait(), 10)
            assert deleter.in_transaction()  # DELETE/RI were flushed, never committed yet.
            assert await deleter.get(Organization, w.org, populate_existing=True) is None
            member = await deleter.get(UserCompany, (w.user, w.company), populate_existing=True)
            assert member.own_organization_id is None  # Real installed RI, not a synthetic UPDATE.
            assert await state(w) == before
            async def create():
                result = await create_partner_contract(creator, w.bearer, w.body)
                await creator.commit()
                return result
            task = asyncio.create_task(create())
            evidence = await org_wait_evidence(w, creator_pid, signals["pid"])
            assert "organizations" in evidence["query"].lower() and "for share" in evidence["query"].lower()
            assert any(row["pid"] == signals["pid"] and row["granted"]
                       and row["mode"] == "RowExclusiveLock"
                       and row["relation"] in {"core.user_companies", "user_companies"}
                       for row in evidence["locks"])
            assert shares == [] and business_flushes == []
            signals["release"].set()
            await asyncio.wait_for(native_task, 10)
            if deleter_finish == "commit":
                with pytest.raises(HTTPException) as denied:
                    await asyncio.wait_for(task, 10)
                assert denied.value.status_code in {403, 409}
                assert shares == [] and business_flushes == []
                assert await state(w) == before
                async with w.factory() as reader:
                    assert await reader.get(Organization, w.org) is None
                    assert (await reader.get(UserCompany, (w.user, w.company))).own_organization_id is None
                assert not creator.in_transaction()  # Issuer rolled the whole root back.
            else:
                result = await asyncio.wait_for(task, 10)
                assert not result.replayed and shares and business_flushes
                assert await state(w) == tuple(n+1 for n in before)
                async with w.factory() as reader:
                    assert (await reader.get(UserCompany, (w.user, w.company))).own_organization_id == w.org
        finally:
            signals["release"].set()
            for pending in (task, native_task):
                if pending is not None and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
            event.remove(creator.sync_session, "do_orm_execute", record_share)
            event.remove(creator.sync_session, "before_flush", business_flush)
            await creator.rollback(); await deleter.rollback()


async def test_org_parent_stage_runs_for_machine_with_no_canonical_member_rows(issuer_world, monkeypatch):
    w = issuer_world
    async with w.factory() as db:
        await db.execute(delete(Principal).where(Principal.profile_id == w.profile, Principal.actor_kind == "user"))
        await db.commit()
    before, stages = await state(w), []
    original = authority.CreateOperation.lock_parents
    def parents(operation):
        assert operation.verified.is_machine
        assert not any(spec.model is UserCompany for spec in operation.ordered)
        result = original(operation)  # Actual parent SQL and every original policy checkpoint.
        stages.append("real_parent_stage_without_Member")
        return result
    monkeypatch.setattr(authority.CreateOperation, "lock_parents", parents)
    async with w.factory() as creator, w.factory() as deleter:
        native = await native_org_admin(w)
        signals = org_delete_signals()
        admission = await authority.prepare_create(creator, w.machine, w.body)
        assert stages == ["real_parent_stage_without_Member"]
        creator_pid = await creator.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(native_org_delete(w, deleter, native, signals, finish="rollback"))
        try:
            await asyncio.wait_for(signals["attempted"].wait(), 10)
            evidence = await org_wait_evidence(w, signals["pid"], creator_pid)
            assert "organizations" in evidence["query"].lower() and "delete" in evidence["query"].lower()
            await authority.require_create(creator, admission, w.body)
            await creator.rollback()
            signals["release"].set()
            await asyncio.wait_for(task, 10)
        finally:
            signals["release"].set()
            if not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await creator.rollback(); await deleter.rollback()
    assert await state(w) == before
