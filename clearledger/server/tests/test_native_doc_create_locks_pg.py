"""AUTHORDEFINITIONS / NOTRUN, collection included.

Synthetic DATA on a ROOT-prepared full native SCHEMA with its real constraints
and triggers. This module does not provision or alter that schema. ROOT must isolate parent conftest BEFORE importing
this module; its local guard cannot protect against an earlier conftest import.
No runner, codec workaround, URL fallback or runtime permission is supplied.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_DOC_CREATE_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (_URL and _URL == os.environ.get("NATIVE_DOC_CREATE_ROOT_APPROVED_URL")
        and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
        and os.environ.get("NATIVE_DOC_CREATE_SOURCE_APPROVAL") == "reviewed-native-doc-create-v1"
        and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
        and _TARGET.port and _TARGET.password
        and _TARGET.path.startswith("/native_doc_create_test_")
        and len(_TARGET.path) > len("/native_doc_create_test_")
        and not _TARGET.query and not _TARGET.fragment):
    raise RuntimeError("ROOT-reviewed isolated preimport native composition required")

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import (
    AuditEvent, Company, CompanyRole, Counterparty, DocAccessGrant, DocBreakGlassAccess,
    DocCard, DocEvent, DocKind, Organization, PartnerSpace, User, UserCompany,
)
from app.routers import docs_router as docs, references_router as refs
from app.schemas import CounterpartyUpdate, OrganizationUpdate
from app.scope import set_request_organization, set_request_scope
from app.services import contract_write_locks as locks, native_doc_create_locks as native

_DEFAULT_CLAIMS = object()
S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def store(monkeypatch):
    # Distinct synthetic identities per authored case; ROOT disposes the DB.
    store = SimpleNamespace(**{name: uuid4() for name in (
        "cid", "home", "other", "aid", "rid", "admin", "role", "org", "cp", "kind", "partner")})
    engine = create_async_engine(_URL, pool_size=8, max_overflow=0, isolation_level="READ COMMITTED")
    scoped = engine
    statements, notifications = [], []
    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append((conn.info.get("doc_create_label"), statement.lower(), parameters))
    event.listen(scoped.sync_engine, "before_cursor_execute", trace)
    from app.services import notify
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: notifications.append((a, kw)))
    try:
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        async with factory() as db:
            db.add_all([Company(id=cid, slug=slug, name=slug, profile_id="energy")
                        for cid, slug in ((store.cid, "synthetic-docs-" + store.cid.hex[:12]), (store.home, "synthetic-home-" + store.home.hex[:12]), (store.other, "synthetic-other-" + store.other.hex[:12]))])
            await db.flush()
            db.add_all([User(id=uid, company_id=store.home, email=f"{uid.int}@example.invalid",
                name=f"Synthetic {uid.int}", password_hash="synthetic-not-a-credential",
                is_superadmin=False, token_version=0) for uid in (store.aid, store.rid, store.admin)])
            db.add(CompanyRole(id=store.role, company_id=store.cid, name="Synthetic docs role", modules=["docs"]))
            db.add(Organization(id=store.org, company_id=store.cid, name="Synthetic organization", inn=""))
            db.add(Counterparty(id=store.cp, company_id=store.cid, name="Synthetic correspondent", aliases=[]))
            db.add(DocKind(id=store.kind, company_id=store.cid, code="synthetic", name="Synthetic kind"))
            db.add(PartnerSpace(id=store.partner, company_id=store.cid, role="vendor", is_active=True,
                code="p-" + store.partner.hex[:12], name="Synthetic issuer", base_url="https://synthetic.invalid"))
            await db.flush()
            db.add_all([UserCompany(user_id=store.aid, company_id=store.cid, role="user", role_id=store.role, own_organization_id=store.org),
                        UserCompany(user_id=store.rid, company_id=store.cid, role="user", own_organization_id=store.org),
                        UserCompany(user_id=store.admin, company_id=store.cid, role="admin")])
            await db.commit()
        statements.clear()
        set_request_scope(None)
        set_request_organization(None)
        with native_claims_context(None, None):
            store.factory, store.engine, store.sql, store.notify = factory, scoped, statements, notifications
            yield store
    finally:
        set_request_scope(None)
        set_request_organization(None)
        event.remove(scoped.sync_engine, "before_cursor_execute", trace)
        await engine.dispose()


def body(store, **changes):
    values = dict(company_id=str(store.cid), kind_id=str(store.kind), title=" Synthetic new document ",
        organization_id=str(store.org), counterparty_id=str(store.cp), responsible_id=str(store.rid),
        signatory_id=str(store.aid))
    return docs.DocIn(**(values | changes))


async def tag(db, label):
    conn = await db.connection()
    await conn.run_sync(lambda c: c.info.update(doc_create_label=label))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def blocked(observer, waiter, owner):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
        if owner in blockers:
            return
        await asyncio.sleep(0)
    raise AssertionError("Expected physical PostgreSQL blocking was not observed")


def no_mutation(store, label="creator"):
    assert not any(sql.lstrip().startswith(("insert ", "update ", "delete "))
                   for owner, sql, _ in store.sql if owner == label)
    assert not store.notify


@asynccontextmanager
async def creator(store, *, payload=None, claims=_DEFAULT_CLAIMS, hold_commit=False):
    if claims is _DEFAULT_CLAIMS:
        claims = {"sub": str(store.aid), "tv": 0}
    state = SimpleNamespace(ready=asyncio.Event(), committing=asyncio.Event(), release=asyncio.Event())
    class Session(AsyncSession):
        async def commit(self):
            if hold_commit:
                state.committing.set()
                await state.release.wait()
            await super().commit()
    async def run():
        async with Session(bind=store.engine, expire_on_commit=False) as db:
            state.db, state.pid = db, await tag(db, "creator")
            state.actor = await db.get(User, store.aid)
            state.retained = [await db.get(model, key) for model, key in (
                (Company, store.cid), (UserCompany, (store.aid, store.cid)), (UserCompany, (store.rid, store.cid)),
                (CompanyRole, store.role), (Organization, store.org), (Counterparty, store.cp), (User, store.rid), (DocKind, store.kind))]
            state.ready.set()
            try:
                with native_claims_context(claims, store.cid if claims and claims.get("scp") == "visit" else None):
                    result = await docs.create_doc(payload or body(store), db, state.actor)
                    state.fresh = dict(actor_name=state.actor.name,
                        actor_same=state.actor is await db.get(User, store.aid),
                        member_modules=state.retained[1].modules,
                        org_name=state.retained[4].name, cp_name=state.retained[5].name,
                        reference_name=state.retained[6].name,
                        reference_home=state.retained[6].company_id)
                    return result
            except BaseException:
                # The test records failure BEFORE caller-owned rollback.
                state.pending_before_rollback = (tuple(db.new), tuple(db.dirty), tuple(db.deleted))
                no_mutation(store)
                raise
            finally:
                await db.rollback()
    task = asyncio.create_task(run())
    await asyncio.wait_for(state.ready.wait(), 10)
    state.task = task
    try:
        yield state
    finally:
        state.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_actual_legacy_org_delete_first_with_actor_and_selected_member_setnull(store, completion):
    async with store.factory() as deleter, store.factory() as observer:
        owner = await tag(deleter, "deleter")
        admin = await deleter.get(User, store.admin)
        await refs.delete_organization(str(store.org), deleter, admin)
        await deleter.flush()  # actual Org DELETE + FK SET NULL on store.aid and store.rid
        async with creator(store) as c:
            await blocked(observer, c.pid, owner)
            no_mutation(store)
            # Old Member-first order deadlocks here; creator must wait on Org.
            assert not any("user_companies" in sql and "for share" in sql
                           for label, sql, _ in store.sql if label == "creator")
            await getattr(deleter, completion)()
            if completion == "commit":
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(c.task, 10)
                assert error.value.status_code == 409
                assert c.pending_before_rollback == ((), (), ())
                no_mutation(store)
            else:
                result = await asyncio.wait_for(c.task, 10)
                assert result["organization_id"] == str(store.org)
                assert result["responsible_id"] == str(store.rid)


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_actual_create_first_blocks_actual_org_delete_until_native_commit(store, completion):
    async with creator(store, hold_commit=True) as c:
        await asyncio.wait_for(c.committing.wait(), 10)
        async with store.factory() as deleter, store.factory() as observer:
            pid = await tag(deleter, "deleter")
            admin = await deleter.get(User, store.admin)
            await refs.delete_organization(str(store.org), deleter, admin)
            deletion = asyncio.create_task(deleter.flush())
            try:
                await blocked(observer, pid, c.pid)
                c.release.set()
                result = await asyncio.wait_for(c.task, 10)
                await asyncio.wait_for(deletion, 10)
                await getattr(deleter, completion)()
                async with store.factory() as check:
                    card = await check.get(DocCard, UUID(result["id"]))
                    member = await check.get(UserCompany, (store.rid, store.cid))
                    expected = None if completion == "commit" else store.org
                    assert card.organization_id == member.own_organization_id == expected
                    assert await check.scalar(select(func.count()).select_from(DocEvent).join(DocCard, DocCard.id == DocEvent.doc_id).where(DocCard.company_id == store.cid)) == 1
            finally:
                if not deletion.done():
                    deletion.cancel()
                await asyncio.gather(deletion, return_exceptions=True)
                await deleter.rollback()


@pytest.mark.parametrize("completion", ["commit", "rollback"])
@pytest.mark.parametrize("first", ["update", "create"])
async def test_source8_actual_org_update_and_create_both_orders(store, completion, first):
    async with store.factory() as updater, store.factory() as observer:
        owner = await tag(updater, "updater")
        admin = await updater.get(User, store.admin)
        async def update():
            return await refs.update_organization(str(store.org), OrganizationUpdate(name="Synthetic renamed"), updater, admin)
        if first == "update":
            await update()
            async with creator(store) as c:
                await blocked(observer, c.pid, owner)
                no_mutation(store)
                await getattr(updater, completion)()
                await asyncio.wait_for(c.task, 10)
                assert c.fresh["org_name"] == ("Synthetic renamed" if completion == "commit" else "Synthetic organization")
        else:
            async with creator(store, hold_commit=True) as c:
                await asyncio.wait_for(c.committing.wait(), 10)
                task = asyncio.create_task(update())
                try:
                    await blocked(observer, owner, c.pid)
                    c.release.set()
                    await asyncio.wait_for(c.task, 10)
                    await asyncio.wait_for(task, 10)
                    await getattr(updater, completion)()
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await updater.rollback()


@pytest.mark.parametrize("change,status", [("role", 403), ("session", 401), ("home", 409)])
async def test_actual_fresh_authority_after_initial_B_wait_no_document_event_or_notify(store, change, status):
    key = locks.RoleKey(store.cid, store.role) if change == "role" else locks.UserKey(store.aid)
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await locks.acquire_scoped_locks_async(peer, locks.LockPlan((locks.LockRequest(key, X),)))
        async with creator(store) as c:
            await blocked(observer, c.pid, owner)
            if change == "role":
                (await peer.get(CompanyRole, store.role)).modules = []
            else:
                actor = await peer.get(User, store.aid)
                if change == "session":
                    actor.token_version = 1
                else:
                    actor.company_id = store.other
            await peer.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(c.task, 10)
            assert error.value.status_code == status
            assert c.pending_before_rollback == ((), (), ())
            no_mutation(store)


async def test_native_visit_revoked_during_last_kind_row_wait(store):
    claims = dict(sub=str(store.aid), tv=0, scp="visit", cid=str(store.cid), pvs=str(store.partner))
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await peer.execute(select(DocKind).where(DocKind.id == store.kind).with_for_update())
        async with creator(store, claims=claims) as c:
            await blocked(observer, c.pid, owner)
            (await peer.get(PartnerSpace, store.partner)).is_active = False
            await peer.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(c.task, 10)
            assert error.value.status_code == 401
            no_mutation(store)


async def test_manual_replay_and_native_error_order(store):
    token = uuid4()
    payload = body(store, source_ref="contract-document:{" + str(token).upper() + "}")
    async with store.factory() as db:
        actor = await db.get(User, store.aid)
        first = await docs.create_doc(payload, db, actor)
        second = await docs.create_doc(payload, db, actor)
        assert first == second
        assert first["source_ref"] == f"contract-document:{token}"
        assert await db.scalar(select(func.count()).select_from(DocEvent).join(DocCard, DocCard.id == DocEvent.doc_id).where(DocCard.company_id == store.cid)) == 1
        await db.rollback()
    async with store.factory() as db:
        actor = await db.get(User, store.aid)
        with pytest.raises(HTTPException) as error:
            await docs.create_doc(body(store, kind_id="bad", organization_id="bad",
                                       source_ref="contract-document:bad"), db, actor)
        assert error.value.status_code == 400
        assert "kind_id" in error.value.detail
        await db.rollback()


async def test_real_helper_receipt_lives_until_caller_rollback_then_cannot_be_reused(store):
    async with store.factory() as db:
        actor = await db.get(User, store.aid)
        prepared = await native.prepare_doc_create(db, actor, str(store.cid), kind_id=str(store.kind),
            organization_id=str(store.org), counterparty_id=str(store.cp), responsible_id=str(store.rid))
        prepared.require(db)
        assert prepared.actor is actor
        assert actor.company_id == store.home
        assert locks.RefCompositeKey(store.cid) in {r.key for r in prepared.plan.requests}
        assert locks.RoleKey(store.cid, store.role) in {r.key for r in prepared.plan.requests}
        await db.rollback()
        with pytest.raises(locks.ScopedLockError):
            prepared.require(db)


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_retained_actor_member_and_reference_user_are_fresh_after_advisory_wait(store, completion):
    requests = (locks.LockRequest(locks.UserKey(store.aid), X),
                locks.LockRequest(locks.UserKey(store.rid), X),
                locks.LockRequest(locks.MemberKey(store.cid, store.aid), X))
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await locks.acquire_scoped_locks_async(peer, locks.LockPlan(requests))
        async with creator(store) as c:
            await blocked(observer, c.pid, owner)
            (await peer.get(User, store.aid)).name = "Synthetic refreshed actor"
            (await peer.get(User, store.rid)).name = "Synthetic refreshed reference"
            (await peer.get(UserCompany, (store.aid, store.cid))).modules = ["docs:changed"]
            await getattr(peer, completion)()
            result = await asyncio.wait_for(c.task, 10)
            expected_name = "Synthetic refreshed actor" if completion == "commit" else f"Synthetic {store.aid.int}"
            assert c.fresh["actor_same"]
            assert c.fresh["actor_name"] == expected_name
            assert c.fresh["member_modules"] == (["docs:changed"] if completion == "commit" else None)
            assert c.fresh["reference_home"] == store.home
            assert c.fresh["reference_name"] == ("Synthetic refreshed reference" if completion == "commit" else f"Synthetic {store.rid.int}")
            async with store.factory() as check:
                created = (await check.execute(select(DocEvent).where(
                    DocEvent.doc_id == UUID(result["id"]), DocEvent.kind == "created"))).scalar_one()
                assert created.actor_name == expected_name


async def test_manual_last_wait_refreshes_visit_and_does_not_extend_keys(store):
    token = uuid4()
    source_ref = f"contract-document:{token}"
    claims = dict(sub=str(store.aid), tv=0, scp="visit", cid=str(store.cid), pvs=str(store.partner))
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await peer.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"doc-create:{store.cid}:{source_ref}"})
        async with creator(store, payload=body(store, source_ref=source_ref), claims=claims) as c:
            await blocked(observer, c.pid, owner)
            (await peer.get(PartnerSpace, store.partner)).is_active = False
            await peer.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(c.task, 10)
            assert error.value.status_code == 401
            no_mutation(store)
            # The number/order of two-int B locks is the single initial plan.
            params = [repr(p) for label, sql, p in store.sql if label == "creator"
                      and "cast(" in sql and "pg_advisory_xact_lock" in sql]
            assert params
            assert len(params) == len(set(params))


async def test_replay_previous_user_parent_drift_after_last_wait_fails_before_acl_or_event(store):
    source_ref = f"contract-document:{uuid4()}"
    payload = body(store, source_ref=source_ref)
    async with store.factory() as initial:
        first = await docs.create_doc(payload, initial, await initial.get(User, store.aid))
    store.sql.clear()
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await peer.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"doc-create:{store.cid}:{source_ref}"})
        async with creator(store, payload=payload) as c:
            await blocked(observer, c.pid, owner)
            previous = await peer.get(DocCard, UUID(first["id"]))
            previous.signatory_id = store.admin  # deliberately unplanned old/replay parent
            await peer.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(c.task, 10)
            assert error.value.status_code == 409
            no_mutation(store)


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_strict_superadmin_replay_preserves_actual_breakglass_audit_pending_and_notify(store, completion):
    source_ref = f"contract-document:{uuid4()}"
    payload = body(store, source_ref=source_ref, confidentiality="strict")
    async with store.factory() as setup:
        actor = await setup.get(User, store.aid)
        actor.is_superadmin = True
        await setup.commit()
        result = await docs.create_doc(payload, setup, actor)
        access = DocBreakGlassAccess(company_id=store.cid, doc_id=UUID(result["id"]),
            user_id=store.aid, permissions=["read"], reason="Synthetic replay acceptance",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        setup.add(access)
        await setup.commit()
        access_id = access.id
    store.sql.clear()
    async with store.factory() as db:
        actor = await db.get(User, store.aid)
        replay = await docs.create_doc(payload, db, actor)
        assert replay["id"] == result["id"]
        # Native replay returns before committing; original get_db owns it.
        assert any(isinstance(row, AuditEvent) for row in db.new)
        assert any(isinstance(row, DocBreakGlassAccess) for row in db.dirty)
        assert len(store.notify) == 1
        assert not any(isinstance(row, DocEvent) for row in db.new)
        await getattr(db, completion)()
    async with store.factory() as check:
        access = await check.get(DocBreakGlassAccess, access_id)
        assert access.use_count == (1 if completion == "commit" else 0)
        assert await check.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.company_id == store.cid, AuditEvent.action == "doc.break_glass.use")) == (1 if completion == "commit" else 0)


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_actual_counterparty_update_precedes_create_and_refreshes_retained_parent(store, completion):
    async with store.factory() as updater, store.factory() as observer:
        owner = await tag(updater, "updater")
        admin = await updater.get(User, store.admin)
        await refs.update_counterparty(str(store.cp), CounterpartyUpdate(name="Synthetic fresh CP"), updater, admin)
        async with creator(store) as c:
            await blocked(observer, c.pid, owner)
            no_mutation(store)
            await getattr(updater, completion)()
            result = await asyncio.wait_for(c.task, 10)
            expected = "Synthetic fresh CP" if completion == "commit" else "Synthetic correspondent"
            assert result["counterparty_name"] == c.fresh["cp_name"] == expected


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
async def test_actual_pending_entry_preserved_before_caller_rollback_without_sql(store, pending):
    async with store.factory() as db:
        await tag(db, "pending")
        actor = await db.get(User, store.aid)
        if pending == "new":
            marker = Organization(company_id=store.cid, name="Synthetic pending", inn="")
            db.add(marker)
        elif pending == "dirty":
            marker = actor
            actor.name = "Synthetic pending actor"
        else:
            marker = await db.get(Counterparty, store.cp)
            await db.delete(marker)
        before = len(store.sql)
        with pytest.raises(locks.ScopedLockError, match="clean entry"):
            await docs.create_doc(body(store), db, actor)
        assert marker in getattr(db, pending)
        assert len(store.sql) == before
        assert not store.notify
        assert not any(isinstance(row, DocEvent) for row in db.new)
        await db.rollback()


async def test_cancelled_actual_B_wait_has_no_partial_write_and_requires_whole_root_rollback(store):
    async with store.factory() as peer, store.factory() as observer:
        owner = await tag(peer, "peer")
        await locks.acquire_scoped_locks_async(peer, locks.LockPlan((
            locks.LockRequest(locks.RefCompositeKey(store.cid), X),)))
        async with creator(store) as c:
            await blocked(observer, c.pid, owner)
            c.task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(c.task, 10)
            assert c.pending_before_rollback == ((), (), ())
            no_mutation(store)
        await peer.rollback()


async def test_observed_replay_old_user_is_in_initial_B_even_when_not_in_new_payload(store):
    source_ref = f"contract-document:{uuid4()}"
    async with store.factory() as initial:
        await docs.create_doc(body(store, source_ref=source_ref, responsible_id=str(store.admin)),
                              initial, await initial.get(User, store.aid))
    async with store.factory() as db:
        actor = await db.get(User, store.aid)
        # Requires ROOT's canonical mapping prerequisite for actual raw replay
        # FK producers. The helper must consume them without a local cast.
        prepared = await native.prepare_doc_create(db, actor, str(store.cid), kind_id=str(store.kind),
            source_ref=source_ref, responsible_id=str(store.rid), signatory_id=str(store.aid),
            organization_id=str(store.org), counterparty_id=str(store.cp))
        keys = {r.key for r in prepared.plan.requests}
        assert locks.UserKey(store.admin) in keys
        assert locks.UserKey(store.rid) in keys
        assert locks.CompanyKey(store.home) in keys
        prepared.require(db)
        await db.rollback()
