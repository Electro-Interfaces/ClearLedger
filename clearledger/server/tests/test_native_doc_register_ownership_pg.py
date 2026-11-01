"""AUTHORED / NOTRUN (including collection).

The runtime owner must isolate ancestor conftest BEFORE import and provide the
full native schema, codecs, constraints and disposable cleanup. No schema,
codec, copied policy, replacement Session or transaction runner is defined here.
"""
import os
import sys
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_DOC_REGISTER_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (_URL and _URL == os.environ.get("NATIVE_DOC_REGISTER_APPROVED_URL")
        and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
        and os.environ.get("NATIVE_DOC_REGISTER_PREIMPORT") == "reviewed-isolated"
        and os.environ.get("NATIVE_DOC_REGISTER_SCHEMA") == "full-native"
        and os.environ.get("NATIVE_DOC_REGISTER_CLEANUP") == "owner-disposable"
        and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
        and _TARGET.port and _TARGET.password and not _TARGET.query and not _TARGET.fragment
        and _TARGET.path.startswith("/native_doc_register_test_")
        and len(_TARGET.path) > len("/native_doc_register_test_")
        and not any(n == "conftest" or n.endswith(".conftest") for n in sys.modules)):
    raise RuntimeError("Reviewed pre-import isolation/full native disposable schema required")

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import (AuditEvent, Company, CompanyRole, Counterparty, DocAccessGrant,
    DocAcquaint, DocApproval, DocCard, DocCase, DocCounter, DocEvent, DocKind,
    EventSubscription, Organization, OutboxEvent, PartnerSpace, User, UserCompany,
    UserSubstitution)
from app.routers import docs_router as docs
from app.scope import set_request_organization, set_request_scope
from app.services import native_doc_register_locks as native
from app.services import contract_write_locks as locks
from app.services import doc_approvals, acquaint_requests

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world(monkeypatch):
    w = SimpleNamespace(**{name: uuid4() for name in (
        "cid", "home", "other", "uid", "admin", "principal", "recipient", "foreign",
        "role", "org", "cp", "kind", "case", "doc", "sub", "partner")})
    w.year = datetime.now(docs._BUSINESS_TIMEZONE).year
    w.engine = create_async_engine(_URL, pool_size=10, max_overflow=0,
                                  isolation_level="READ COMMITTED")
    w.factory = async_sessionmaker(w.engine, expire_on_commit=False)
    w.sql, w.notifications = [], []
    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-register-encryption-key")
    w.secret = "whsec_MDEyMzQ1Njc4OWFiY2RlZg=="
    w.cipher = docs.space_events.encrypt_secret(w.secret)
    assert w.cipher is not None and docs.space_events.decrypt_secret(w.cipher) == w.secret
    def trace(conn, cursor, statement, parameters, context, executemany):
        w.sql.append((conn.info.get("register_label"), statement.lower(), parameters))
    event.listen(w.engine.sync_engine, "before_cursor_execute", trace)
    from app.services import notify
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: w.notifications.append((a, kw)))
    try:
        async with w.factory() as db:
            db.add_all([Company(id=c, slug="reg-" + c.hex,
                name="Synthetic register", profile_id="energy") for c in (w.cid, w.home, w.other)])
            await db.flush()
            db.add_all([User(id=u, company_id=w.home if u != w.foreign else w.other,
                email=f"{u.hex}@example.invalid", name="Synthetic participant",
                password_hash="synthetic-noncredential", is_superadmin=False,
                token_version=0) for u in (w.uid, w.admin, w.principal, w.recipient, w.foreign)])
            db.add(CompanyRole(id=w.role, company_id=w.cid, name="Synthetic docs", modules=["docs"]))
            db.add(Organization(id=w.org, company_id=w.cid, name="Synthetic organization", inn="", prefix="S"))
            db.add(Counterparty(id=w.cp, company_id=w.cid, name="Synthetic correspondent", aliases=[]))
            await db.flush()
            db.add(DocCase(id=w.case, company_id=w.cid, organization_id=w.org,
                year=w.year, index="01-01", title="Synthetic case", storage_years=5,
                retention_class="temporary", status="open"))
            db.add(PartnerSpace(id=w.partner, company_id=w.cid, code="synthetic-" + w.partner.hex,
                name="Synthetic issuer", role="vendor", is_active=True,
                base_url="https://example.invalid"))
            await db.flush()
            db.add(DocKind(id=w.kind, company_id=w.cid, code="synthetic", name="Synthetic kind",
                number_scope="kind_year", number_prefix="SYN", number_template="{prefix}-{yyyy}-{n:04d}",
                default_case_id=w.case))
            db.add_all([UserCompany(user_id=u, company_id=w.cid, role="admin" if u == w.admin else "user",
                role_id=w.role if u == w.uid else None, modules=["docs"],
                own_organization_id=w.org if u == w.uid else None)
                for u in (w.uid, w.admin, w.principal, w.recipient)])
            db.add(EventSubscription(id=w.sub, company_id=w.cid, label="Synthetic consumer",
                target_kind="url", url="https://example.invalid/events", secret_enc=w.cipher,
                event_types=["doc.registered"], enabled=True))
            await db.flush()
            db.add(DocCard(id=w.doc, company_id=w.cid, kind_id=w.kind, kind_code="synthetic",
                title="Synthetic draft", author_id=w.uid, responsible_id=w.recipient,
                signatory_id=w.principal, registered_by=w.admin, archive_accepted_by=w.foreign,
                organization_id=w.org, counterparty_id=w.cp, attrs={}))
            await db.commit()
        w.sql.clear()
        set_request_scope(None)
        set_request_organization(None)
        with native_claims_context(None, None):
            yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        event.remove(w.engine.sync_engine, "before_cursor_execute", trace)
        assert w.engine.pool.checkedout() == 0, "Every caller/observer root must be closed"
        await w.engine.dispose()


async def tag(db, label):
    conn = await db.connection()
    await conn.run_sync(lambda c: c.info.update(register_label=label))
    await db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def blocked(observer, waiter, holder, *, key=None, relation=None):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        pids = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
        if holder in pids:
            rows = (await observer.execute(text("SELECT locktype, mode, granted, classid, objid, objsubid, "
                "relation::regclass::text AS relation FROM pg_locks WHERE pid=:pid"), {"pid": waiter})).all()
            assert any(not row.granted for row in rows)
            if key is not None:
                ns, value = locks.advisory_key(key)
                assert any(r.locktype == "advisory" and not r.granted and r.classid == ns
                    and r.objid == value & 0xffffffff and r.objsubid == 2 for r in rows)
            if relation is not None:
                assert any(r.relation == relation for r in rows)
            return rows
        await asyncio.sleep(0.01)
    raise AssertionError("Expected actual PostgreSQL blocker/PID/pg_locks was not observed")


@asynccontextmanager
async def running(coro):
    task = asyncio.create_task(coro)
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def register(w, db, *, actor=None, claims=None, **payload):
    user = await db.get(User, actor or w.uid)
    with native_claims_context(claims, w.cid if claims and claims.get("scp") == "visit" else None):
        return await docs.register_doc(str(w.doc), docs.RegisterIn(company_id=str(w.cid), **payload), db, user)


def no_register_dml(w):
    assert not any(label == "register" and sql.lstrip().startswith(("insert ", "update ", "delete "))
                   for label, sql, _ in w.sql)
    assert not any(a[1] == "doc.register" for a, kw in w.notifications)


async def seed_substitution(w, db):
    row = UserSubstitution(company_id=w.cid, user_id=w.principal, deputy_id=w.uid,
        starts_on=datetime.now(timezone.utc).date() - timedelta(days=1),
        ends_on=datetime.now(timezone.utc).date() + timedelta(days=1), created_by=w.admin)
    db.add(row)
    await db.commit()
    return row.id


async def grant(w, db, *, deny=False):
    admin = await db.get(User, w.admin)
    return await docs.save_access_grant(docs.AccessGrantIn(company_id=str(w.cid),
        scope_type="kind", scope_id=str(w.kind), subject_type="user", subject_id=str(w.uid),
        permissions=[] if deny else ["edit"], denied_permissions=["edit"] if deny else []), db, admin)


@pytest.mark.parametrize("parent", ["company", "home", "other_home", "actor", "author",
    "responsible", "signatory", "registered_by", "archive_accepted_by", "role", "org", "cp", "member", "subscription", "kind", "card"])
async def test_complete_original_parents_before_card_and_dml(world, parent):
    w = world
    model, identity = {
        "company": (Company, w.cid), "home": (Company, w.home), "other_home": (Company, w.other),
        "actor": (User, w.uid), "author": (User, w.uid), "responsible": (User, w.recipient),
        "signatory": (User, w.principal), "registered_by": (User, w.admin),
        "archive_accepted_by": (User, w.foreign), "role": (CompanyRole, w.role),
        "org": (Organization, w.org), "cp": (Counterparty, w.cp),
        "member": (UserCompany, None), "subscription": (EventSubscription, w.sub),
        "kind": (DocKind, w.kind), "card": (DocCard, w.doc),
    }[parent]
    async with w.factory() as owner, w.factory() as caller, w.factory() as observer:
        op, cp = await tag(owner, "owner"), await tag(caller, "register")
        statement = select(model).where(model.id == identity) if identity else select(UserCompany).where(
            UserCompany.company_id == w.cid, UserCompany.user_id == w.uid)
        await owner.execute(statement.with_for_update())
        async with running(register(w, caller)) as task:
            await blocked(observer, cp, op)
            no_register_dml(w)
            await owner.rollback()
            assert (await asyncio.wait_for(task, 10))["status"] == "registered"


@pytest.mark.parametrize("first", ["register", "writer"])
async def test_actual_kind_grant_save_both_orders_and_phantom_epoch(world, first):
    w = world
    async with w.factory() as setup:
        existing = await grant(w, setup)
    async with w.factory() as blocker, w.factory() as writer, w.factory() as caller, w.factory() as observer:
        bp, wp, cp = await tag(blocker, "blocker"), await tag(writer, "grant"), await tag(caller, "register")
        if first == "register":
            await blocker.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
            async with running(register(w, caller)) as rt:
                await blocked(observer, cp, bp)
                async with running(grant(w, writer, deny=True)) as wt:
                    await blocked(observer, wp, cp)
                    await blocker.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    assert await asyncio.wait_for(wt, 10)
        else:
            await blocker.execute(select(DocAccessGrant).where(DocAccessGrant.id == UUID(existing["id"])).with_for_update())
            async with running(grant(w, writer, deny=True)) as wt:
                await blocked(observer, wp, bp)
                async with running(register(w, caller)) as rt:
                    await blocked(observer, cp, wp)
                    no_register_dml(w)
                    await blocker.rollback()
                    assert await asyncio.wait_for(wt, 10)
                    with pytest.raises(HTTPException) as error:
                        await asyncio.wait_for(rt, 10)
                    assert error.value.status_code == 403
                    await caller.rollback()


@pytest.mark.parametrize("first", ["register", "writer"])
async def test_actual_stop_substitution_both_orders(world, first):
    w = world
    async with w.factory() as setup:
        sub = await seed_substitution(w, setup)
    async with w.factory() as blocker, w.factory() as writer, w.factory() as caller, w.factory() as observer:
        bp, wp, cp = await tag(blocker, "blocker"), await tag(writer, "substitution"), await tag(caller, "register")
        async def stop():
            admin = await writer.get(User, w.admin)
            return await docs.stop_substitution(str(sub), str(w.cid), writer, admin)
        if first == "register":
            await blocker.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
            async with running(register(w, caller)) as rt:
                await blocked(observer, cp, bp)
                async with running(stop()) as wt:
                    await blocked(observer, wp, cp, key=locks.UserKey(w.uid))
                    await blocker.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    assert await asyncio.wait_for(wt, 10)
        else:
            await blocker.execute(select(UserSubstitution).where(UserSubstitution.id == sub).with_for_update())
            async with running(stop()) as wt:
                await blocked(observer, wp, bp)
                async with running(register(w, caller)) as rt:
                    await blocked(observer, cp, wp, key=locks.UserKey(w.uid))
                    await blocker.rollback()
                    assert await asyncio.wait_for(wt, 10)
                    assert await asyncio.wait_for(rt, 10)


@pytest.mark.parametrize("reverse", [False, True])
async def test_actual_reciprocal_substitutions_sorted_mixed_user_modes(world, reverse):
    w = world
    async with w.factory() as blocker, w.factory() as a, w.factory() as b, w.factory() as observer:
        bp, ap, bpid = await tag(blocker, "blocker"), await tag(a, "a"), await tag(b, "b")
        await blocker.execute(select(User).where(User.id == min(w.uid, w.principal)).with_for_update())
        async def create(db, principal, deputy):
            admin = await db.get(User, w.admin)
            day = datetime.now(timezone.utc).date()
            return await docs.create_substitution(docs.SubstitutionIn(company_id=str(w.cid),
                user_id=str(principal), deputy_id=str(deputy), starts_on=day, ends_on=day), db, admin)
        pair = (w.principal, w.uid) if reverse else (w.uid, w.principal)
        async with running(create(a, *pair)) as at:
            await blocked(observer, ap, bp)
            async with running(create(b, *reversed(pair))) as bt:
                await blocked(observer, bpid, ap)
                await blocker.rollback()
                assert await asyncio.wait_for(at, 10)
                assert await asyncio.wait_for(bt, 10)


@pytest.mark.parametrize("first", ["register", "inbound"])
async def test_actual_inbound_acquaint_parent_card_before_children(world, first):
    w = world
    async with w.factory() as blocker, w.factory() as inbound, w.factory() as caller, w.factory() as observer:
        bp, ip, cp = await tag(blocker, "blocker"), await tag(inbound, "inbound"), await tag(caller, "register")
        await blocker.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
        async def request():
            row = await acquaint_requests.request(inbound, w.cid, "synthetic-request", dict(
                process_id="synthetic-process", doc_id=str(w.doc), user_ids=[str(w.recipient)]))
            assert inbound.in_transaction(), "Inbound helper must retain caller root"
            await inbound.commit()
            return row.id
        owner_db, owner_pid, follower_pid = (caller, cp, ip) if first == "register" else (inbound, ip, cp)
        first_call = register(w, caller) if first == "register" else request()
        second_call = request() if first == "register" else register(w, caller)
        async with running(first_call) as first_task:
            await blocked(observer, owner_pid, bp)
            async with running(second_call) as second_task:
                await blocked(observer, follower_pid, bp)
                assert not any(label == "inbound" and sql.lstrip().startswith(("insert ", "update ", "delete "))
                               for label, sql, _ in w.sql)
                await blocker.rollback()
                assert await asyncio.wait_for(first_task, 10)
                try:
                    assert await asyncio.wait_for(second_task, 10)
                except HTTPException as error:
                    assert first == "inbound" and error.status_code == 409
                    await caller.rollback()


@pytest.mark.parametrize("first", ["register", "writer"])
async def test_actual_kind_grant_delete_both_orders(world, first):
    w = world
    async with w.factory() as setup:
        existing = await grant(w, setup, deny=first == "writer")
    async with w.factory() as blocker, w.factory() as writer, w.factory() as caller, w.factory() as observer:
        bp, wp, cp = await tag(blocker, "blocker"), await tag(writer, "delete-grant"), await tag(caller, "register")
        async def delete():
            admin = await writer.get(User, w.admin)
            return await docs.delete_access_grant(existing["id"], str(w.cid), None, writer, admin)
        if first == "register":
            await blocker.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
            async with running(register(w, caller)) as rt:
                await blocked(observer, cp, bp)
                async with running(delete()) as wt:
                    await blocked(observer, wp, cp)
                    await blocker.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    assert (await asyncio.wait_for(wt, 10))["deleted"] is True
        else:
            await blocker.execute(select(DocAccessGrant).where(DocAccessGrant.id == UUID(existing["id"])).with_for_update())
            async with running(delete()) as wt:
                await blocked(observer, wp, bp)
                async with running(register(w, caller)) as rt:
                    await blocked(observer, cp, wp)
                    no_register_dml(w)
                    await blocker.rollback()
                    assert (await asyncio.wait_for(wt, 10))["deleted"] is True
                    assert await asyncio.wait_for(rt, 10)


@pytest.mark.parametrize("parent", ["future_principal", "child_user", "child_creator"])
async def test_complete_original_child_refs_and_future_principals_resolve_canonical_users(world, parent):
    w = world
    ids = {label: uuid4() for label in ("future_principal", "child_user", "child_creator")}
    async with w.factory() as setup:
        setup.add_all([User(id=uid, company_id=w.other, email=f"{uid.hex}@example.invalid",
            name="Synthetic child-only parent", password_hash="synthetic-noncredential") for uid in ids.values()])
        await setup.flush()
        day = datetime.now(timezone.utc).date() + timedelta(days=30)
        setup.add(UserSubstitution(company_id=w.cid, deputy_id=w.uid, user_id=ids["future_principal"],
            starts_on=day, ends_on=day + timedelta(days=1), created_by=ids["child_creator"]))
        setup.add(DocAcquaint(company_id=w.cid, doc_id=w.doc, user_id=ids["child_user"],
            created_by=ids["child_creator"], status="pending"))
        setup.add(DocApproval(company_id=w.cid, doc_id=w.doc, assignee_id=ids["child_user"],
            decided_by=ids["child_creator"], status="pending"))
        await setup.commit()
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "child-parent"), await tag(caller, "register")
        await holder.execute(select(User).where(User.id == ids[parent]).with_for_update())
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, hp)
            no_register_dml(w)
            await holder.rollback()
            assert await asyncio.wait_for(rt, 10)


async def test_actual_foreign_role_owner_is_fenced_without_new_foreign_ban(world):
    w, role_id = world, uuid4()
    async with w.factory() as setup:
        setup.add(CompanyRole(id=role_id, company_id=w.other, name="Synthetic actual foreign owner", modules=["docs"]))
        await setup.flush()
        membership = await setup.get(UserCompany, (w.uid, w.cid))
        membership.role_id = role_id
        await setup.commit()
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "actual-role-owner"), await tag(caller, "register")
        await holder.execute(select(CompanyRole).where(CompanyRole.id == role_id).with_for_update())
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, hp)
            ns, value = locks.advisory_key(locks.RoleKey(w.other, role_id))
            held = await observer.scalar(text("SELECT count(*) FROM pg_locks WHERE pid=:pid "
                "AND locktype='advisory' AND classid=:ns AND objid=:key AND objsubid=2 AND granted"),
                {"pid": cp, "ns": ns, "key": value & 0xffffffff})
            assert held == 1
            await holder.rollback()
            assert await asyncio.wait_for(rt, 10)


async def test_current_and_default_case_orgs_are_both_in_original_parent_set(world):
    w, default_org, current_case = world, uuid4(), uuid4()
    async with w.factory() as setup:
        setup.add(Organization(id=default_org, company_id=w.cid, name="Synthetic unused default org", inn=""))
        setup.add(DocCase(id=current_case, company_id=w.cid, organization_id=w.org,
            year=w.year, index="CURRENT", title="Synthetic current case", storage_years=5))
        await setup.flush()
        default = await setup.get(DocCase, w.case)
        default.organization_id = default_org
        doc = await setup.get(DocCard, w.doc)
        doc.case_id = current_case
        await setup.commit()
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "default-case-org"), await tag(caller, "register")
        await holder.execute(select(Organization).where(Organization.id == default_org).with_for_update())
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, hp)
            no_register_dml(w)
            await holder.rollback()
            assert (await asyncio.wait_for(rt, 10))["case_id"] == str(current_case)


async def test_card_disappears_during_actual_row_wait_is_drift409_not_missing500(world):
    """Physical delete probe; no claim about a new supported delete adapter."""
    w = world
    async with w.factory() as owner, w.factory() as caller, w.factory() as observer:
        op, cp = await tag(owner, "physical-delete"), await tag(caller, "register")
        doc = (await owner.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())).scalar_one()
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, op)
            no_register_dml(w)
            await owner.delete(doc)
            await owner.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(rt, 10)
            assert error.value.status_code == 409
            await caller.rollback()
