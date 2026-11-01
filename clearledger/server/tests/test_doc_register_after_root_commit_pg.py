"""Native register definitions on the owner's disposable, unmodified schema.

AUTHORED/NOTRUN. ROOT must isolate ancestor conftest BEFORE import, bootstrap
all native constraints/codecs and clean the database; this local guard is later.
Direct handler calls exercise native policy/SQL, not HTTP authentication wiring.
"""
import os

import pytest

if os.environ.get("AUDIT_ROOT_COMMIT_ISOLATED") != "1":
    pytest.skip("requires owner-provided pre-import isolation", allow_module_level=True)

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent, DocAccessGrant, DocBreakGlassAccess, DocCard, DocCounter,
    DocEvent, DocKind, EventSubscription, OutboxEvent, User, UserCompany,
)
from app.routers import docs_router
from app.services import after_root_commit as deferred, notify
from tests.test_audit_after_root_commit_pg import audit_pg_company, audit_pg_factory

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def native_register_data(audit_pg_factory, audit_pg_company):
    cid = audit_pg_company
    uid, other, kind_id, doc_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with audit_pg_factory() as db:
        for user_id, label in ((uid, "Автор"), (other, "Читатель")):
            db.add(User(id=user_id, company_id=cid, name=label,
                        email=f"{user_id.hex}@example.invalid", password_hash="synthetic"))
        await db.flush()
        db.add_all([
            UserCompany(user_id=uid, company_id=cid, role="admin"),
            UserCompany(user_id=other, company_id=cid, role="user", modules=["docs"]),
            DocKind(id=kind_id, company_id=cid, code="synthetic", name="Тестовый вид",
                    number_scope="kind_year", number_prefix="SYN",
                    number_template="{prefix}-{yyyy}-{n:04d}"),
            EventSubscription(company_id=cid, label="Синтетическая подписка",
                              target_kind="url", url="https://example.invalid/events",
                              event_types=["doc.registered"], enabled=True),
        ])
        await db.flush()
        db.add(DocCard(id=doc_id, company_id=cid, kind_id=kind_id,
                       kind_code="synthetic", title="Синтетический документ",
                       author_id=uid, attrs={}))
        await db.commit()
    return cid, uid, other, kind_id, doc_id


@pytest.fixture
def register_dispatch_spy(monkeypatch, audit_pg_factory):
    calls = []
    engine = audit_pg_factory.kw["bind"].sync_engine

    def record(cid, action, who=None, details=None):
        assert action == "doc.register"
        # Independent Session/connection, before recording callback invocation.
        with Session(engine) as independent:
            audit = independent.scalars(select(AuditEvent).where(
                AuditEvent.company_id == cid, AuditEvent.action == action)).all()
            assert any(row.details == details for row in audit)
            outbox = independent.scalars(select(OutboxEvent).where(
                OutboxEvent.company_id == cid, OutboxEvent.type == "doc.registered")).all()
            assert outbox
            for outgoing in outbox:
                doc = independent.scalar(select(DocCard).where(
                    DocCard.company_id == cid,
                    DocCard.reg_number == outgoing.data["doc"]["regNumber"]))
                assert str(doc.id) == outgoing.subject
                assert doc.reg_number and doc.status == "registered" and doc.verify_token
                assert doc.registered_by is not None
                assert independent.scalars(select(DocEvent).where(
                    DocEvent.doc_id == doc.id, DocEvent.kind == "registered")).first()
        calls.append((cid, action, who, details))

    monkeypatch.setattr(notify, "dispatch_async", record)
    return calls


async def _register(factory, data, *, actor_id=None, doc_id=None, **payload):
    cid, uid, _, _, default_doc = data
    async with factory() as db:
        actor = await db.get(User, actor_id or uid)
        return await docs_router.register_doc(
            str(doc_id or default_doc),
            docs_router.RegisterIn(company_id=str(cid), **payload), db=db, current_user=actor)


async def _counters(db, cid):
    return [(row.scope_key, row.next_value) for row in (await db.scalars(select(DocCounter).where(
        DocCounter.company_id == cid).order_by(DocCounter.scope_key))).all()]


@pytest.mark.parametrize("manual", [False, True])
async def test_native_register_atomic_success_and_repeat_409(
        audit_pg_factory, native_register_data, register_dispatch_spy, manual):
    cid, uid, _, _, doc_id = native_register_data
    async with audit_pg_factory() as db:
        before = await _counters(db, cid)
        actor = await db.get(User, uid)
        commits = []
        def before_commit(session):
            assert not register_dispatch_spy
            commits.append(session.get_transaction())
        event.listen(db.sync_session, "before_commit", before_commit)
        args = {"reg_number": "LEGACY-001", "manual_reason": "Перенос тестового журнала"} if manual else {}
        result = await docs_router.register_doc(str(doc_id), docs_router.RegisterIn(
            company_id=str(cid), **args), db=db, current_user=actor)
        assert commits and len(register_dispatch_spy) == 1
        assert result["reg_number"] == ("LEGACY-001" if manual else result["reg_number"])
        assert deferred._STATE not in db.sync_session.info
        after = await _counters(db, cid)
        assert (after == before) if manual else (after != before)
    with pytest.raises(HTTPException) as error:
        await _register(audit_pg_factory, native_register_data)
    assert error.value.status_code == 409 and len(register_dispatch_spy) == 1
    async with audit_pg_factory() as independent:
        doc = await independent.get(DocCard, doc_id)
        assert doc.number_manual is manual
        assert len(list(await independent.scalars(select(OutboxEvent).where(
            OutboxEvent.company_id == cid)))) == 1
        assert len(list(await independent.scalars(select(DocEvent).where(
            DocEvent.doc_id == doc_id, DocEvent.kind == "registered")))) == 1


async def test_native_manual_collision_keeps_counter_and_no_second_notification(
        audit_pg_factory, native_register_data, register_dispatch_spy):
    cid, uid, _, kind_id, doc_id = native_register_data
    await _register(audit_pg_factory, native_register_data,
                    reg_number="TAKEN-001", manual_reason="Перенос тестового журнала")
    second = uuid4()
    async with audit_pg_factory() as db:
        db.add(DocCard(id=second, company_id=cid, kind_id=kind_id, kind_code="synthetic",
                       title="Второй синтетический документ", author_id=uid, attrs={}))
        await db.commit()
        before = await _counters(db, cid)
    with pytest.raises(HTTPException) as error:
        await _register(audit_pg_factory, native_register_data, doc_id=second,
                        reg_number="TAKEN-001", manual_reason="Перенос тестового журнала")
    assert error.value.status_code == 409 and len(register_dispatch_spy) == 1
    async with audit_pg_factory() as db:
        assert await _counters(db, cid) == before
        assert (await db.get(DocCard, second)).reg_number is None


@pytest.mark.parametrize("policy", ["private", "deny_edit", "deny_read", "read_only"])
async def test_native_register_ordinary_acl_denies_without_audit(
        audit_pg_factory, native_register_data, register_dispatch_spy, policy):
    cid, _, other, _, doc_id = native_register_data
    async with audit_pg_factory() as db:
        doc = await db.get(DocCard, doc_id)
        if policy == "private":
            doc.confidentiality = "private"
        else:
            db.add(DocAccessGrant(company_id=cid, scope_type="doc", scope_id=doc_id,
                                  subject_type="user", subject_id=other,
                                  permissions=["read"], denied_permissions=(
                                      ["edit"] if policy == "deny_edit" else
                                      ["read"] if policy == "deny_read" else [])))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await _register(audit_pg_factory, native_register_data, actor_id=other)
    assert error.value.status_code == 403 and not register_dispatch_spy
    async with audit_pg_factory() as independent:
        assert (await independent.get(DocCard, doc_id)).reg_number is None
        assert not list(await independent.scalars(select(AuditEvent).where(AuditEvent.company_id == cid)))
        assert not list(await independent.scalars(select(OutboxEvent).where(OutboxEvent.company_id == cid)))


async def test_strict_superadmin_read_breakglass_does_not_authorize_register(
        audit_pg_factory, native_register_data, register_dispatch_spy):
    cid, uid, _, _, doc_id = native_register_data
    bgid = uuid4()
    async with audit_pg_factory() as db:
        actor = await db.get(User, uid)
        actor.is_superadmin = True
        (await db.get(DocCard, doc_id)).confidentiality = "strict"
        db.add(DocBreakGlassAccess(id=bgid, company_id=cid, doc_id=doc_id,
                                  user_id=uid, permissions=["read", "download", "print"],
                                  reason="Синтетическое чтение", use_count=0,
                                  expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await docs_router.register_doc(str(doc_id), docs_router.RegisterIn(
                company_id=str(cid)), db=db, current_user=actor)
        assert error.value.status_code == 403
        # Assert before owner rollback: a deny must not consume the read grant.
        grant = await db.get(DocBreakGlassAccess, bgid)
        assert grant.use_count == 0 and grant.last_used_at is None
        assert not list(await db.scalars(select(AuditEvent).where(AuditEvent.company_id == cid)))
        assert not register_dispatch_spy and deferred._STATE not in db.sync_session.info
        await db.rollback()


async def test_actual_register_commit_constraint_failure_rolls_back_all_effects(
        audit_pg_factory, native_register_data, register_dispatch_spy):
    cid, uid, _, _, doc_id = native_register_data
    async with audit_pg_factory() as db:
        actor = await db.get(User, uid)
        before = await _counters(db, cid)
        observed = []
        def fail_native_flush(session):
            assert deferred._STATE in session.info and not register_dispatch_spy
            observed.append(True)
            # Actual DB NOT NULL failure in commit's native flush, after audit
            # enqueue and outbox construction. Commit/events remain real.
            session.add(AuditEvent(company_id=cid, user_id="system", user_name="Платформа",
                                   action=None, details="synthetic constraint failure"))
        event.listen(db.sync_session, "before_commit", fail_native_flush, once=True)
        with pytest.raises(HTTPException) as error:
            await docs_router.register_doc(str(doc_id), docs_router.RegisterIn(
                company_id=str(cid)), db=db, current_user=actor)
        assert error.value.status_code == 409 and observed and not register_dispatch_spy
        assert deferred._STATE not in db.sync_session.info
    async with audit_pg_factory() as independent:
        doc = await independent.get(DocCard, doc_id)
        assert doc.status == "draft" and doc.reg_number is None and doc.verify_token is None
        assert doc.registered_by is None
        assert await _counters(independent, cid) == before
        assert not list(await independent.scalars(select(DocEvent).where(DocEvent.doc_id == doc_id)))
        assert not list(await independent.scalars(select(AuditEvent).where(AuditEvent.company_id == cid)))
        assert not list(await independent.scalars(select(OutboxEvent).where(OutboxEvent.company_id == cid)))
