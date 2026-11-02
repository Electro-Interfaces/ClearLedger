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
async def native_register_data(audit_pg_factory, audit_pg_company, monkeypatch):
    cid = audit_pg_company
    uid, other, kind_id, doc_id = uuid4(), uuid4(), uuid4(), uuid4()
    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-event-encryption-test-key")
    subscription_secret = docs_router.space_events.encrypt_secret(
        "whsec_MDEyMzQ1Njc4OWFiY2RlZg==")
    assert subscription_secret is not None
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
                          secret_enc=subscription_secret,
                              event_types=["doc.registered"], enabled=True),
        ])
        await db.flush()
        db.add(DocCard(id=doc_id, company_id=cid, kind_id=kind_id,
                       kind_code="synthetic", title="Синтетический документ",
                       author_id=uid, attrs={}))
        await db.commit()
    return cid, uid, other, kind_id, doc_id


@pytest.fixture
def register_dispatch_spy(monkeypatch, audit_pg_factory, native_register_data):
    import json
    from uuid import UUID

    calls, attempts, failures = [], [], []
    engine = audit_pg_factory.kw["bind"].sync_engine
    expected_cid, expected_uid, _, expected_kind, expected_doc = native_register_data

    def verify_and_record(cid, action, *, doc_notice_id):
        assert cid == expected_cid
        assert action == "doc.register"
        assert type(doc_notice_id) is UUID and doc_notice_id == expected_doc
        # Независимое соединение читает точную карточку после фиксации корня.
        with Session(engine) as independent:
            doc = independent.scalars(select(DocCard).where(
                DocCard.company_id == cid, DocCard.id == doc_notice_id)).one()
            assert doc.reg_number and doc.status == "registered" and doc.verify_token
            assert doc.registered_by == expected_uid and doc.kind_id == expected_kind
            kind = independent.scalars(select(DocKind).where(
                DocKind.company_id == cid, DocKind.id == expected_kind)).one()
            registered = independent.scalars(select(DocEvent).where(
                DocEvent.doc_id == doc_notice_id, DocEvent.kind == "registered")).one()
            assert registered.user_id == expected_uid
            assert registered.to_value == doc.reg_number
            reason = "Перенос тестового журнала" if doc.number_manual else None
            assert registered.note == reason
            # Snapshot журнала проверяется отдельно от ссылочного callback.
            snapshot = {"title": doc.title[:200], "kind": kind.code,
                        "manual": doc.number_manual, "manual_reason": reason}
            audit = independent.scalars(select(AuditEvent).where(
                AuditEvent.company_id == cid, AuditEvent.action == action,
                AuditEvent.user_id == str(expected_uid))).one()
            assert audit.details == " · ".join((
                doc.reg_number, json.dumps(snapshot, ensure_ascii=False)))
            outgoing = independent.scalars(select(OutboxEvent).where(
                OutboxEvent.company_id == cid, OutboxEvent.type == "doc.registered",
                OutboxEvent.subject == str(doc_notice_id))).one()
            assert outgoing.data["doc"]["id"] == str(doc_notice_id)
            assert outgoing.data["doc"]["regNumber"] == doc.reg_number
            assert outgoing.data["doc"]["status"] == doc.status
            assert outgoing.data["manual"] is doc.number_manual
            assert outgoing.data["actor"]["id"] == str(expected_uid)

    def record(*args, **kwargs):
        # Запись до привязки аргументов: G3 может поглотить даже TypeError.
        attempt = (args, kwargs.copy())
        attempts.append(attempt)
        try:
            verify_and_record(*args, **kwargs)
        except BaseException as error:
            failures.append(error)
            raise
        calls.append(attempt)

    monkeypatch.setattr(notify, "dispatch_async", record)
    yield calls
    assert failures == [], f"callback oracle failures: {failures!r}; attempts={attempts!r}"
    assert attempts == calls, "every callback attempt must pass independent visibility"


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
        assert register_dispatch_spy == [((cid, "doc.register"), {"doc_notice_id": doc_id})]
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
    assert register_dispatch_spy == [((cid, "doc.register"), {"doc_notice_id": doc_id})]
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
    from app.services import native_doc_register_locks as native
    from app.services.contract_write_locks import ScopedLockError

    cid, uid, _, _, doc_id = native_register_data
    async with audit_pg_factory() as db:
        actor = await db.get(User, uid)
        before = await _counters(db, cid)
        root = db.sync_session.get_transaction()
        observed = []
        def fail_native_flush(session):
            queue = session.info[deferred._STATE]
            assert queue.root is root and session.get_transaction() is root
            assert queue.physical_root and not queue.poisoned
            assert queue.items == {root: [(0, deferred.DocNotice(cid, doc_id))]}
            assert native._SEALS[session][0]() is root
            assert not session.new and not session.dirty and not session.deleted
            assert not register_dispatch_spy
            observed.append(root)
            # Настоящий поздний DML в before_commit: защита чистой сессии должна отклонить
            # последующий нативный flush до проверки NOT NULL в SQL.
            session.add(AuditEvent(company_id=cid, user_id="system", user_name="Платформа",
                                   action=None, details="synthetic constraint failure"))
        event.listen(db.sync_session, "before_commit", fail_native_flush)
        try:
            with pytest.raises(ScopedLockError, match="Unexpected DML after native register final check"):
                await docs_router.register_doc(str(doc_id), docs_router.RegisterIn(
                    company_id=str(cid)), db=db, current_user=actor)
            assert observed == [root] and not register_dispatch_spy
            assert db.sync_session.get_transaction() is root
            assert db.sync_session.info[deferred._STATE].root is root
            assert native._SEALS[db.sync_session][0]() is root
        finally:
            event.remove(db.sync_session, "before_commit", fail_native_flush)
            await db.rollback()  # После ScopedLockError владелец откатывает весь корень.
        assert deferred._STATE not in db.sync_session.info
        assert db.sync_session not in native._SEALS
        assert db.sync_session.get_transaction() is None and not register_dispatch_spy
    async with audit_pg_factory() as independent:
        doc = await independent.get(DocCard, doc_id)
        assert doc.status == "draft" and doc.reg_number is None and doc.verify_token is None
        assert doc.registered_by is None
        assert await _counters(independent, cid) == before
        assert not list(await independent.scalars(select(DocEvent).where(DocEvent.doc_id == doc_id)))
        assert not list(await independent.scalars(select(AuditEvent).where(AuditEvent.company_id == cid)))
        assert not list(await independent.scalars(select(OutboxEvent).where(OutboxEvent.company_id == cid)))
        assert not register_dispatch_spy


async def test_actual_register_final_flush_not_null_failure_rolls_back_all_effects(
        audit_pg_factory, native_register_data, register_dispatch_spy):
    from sqlalchemy.exc import IntegrityError
    from app.services import native_doc_register_locks as native

    cid, uid, _, _, doc_id = native_register_data
    engine = audit_pg_factory.kw["bind"].sync_engine
    async with audit_pg_factory() as db:
        actor = await db.get(User, uid)
        before = await _counters(db, cid)
        root = db.sync_session.get_transaction()
        connection = (await db.connection()).sync_connection
        early_flushes, injected, commits, database_errors = [], [], [], []

        def inject_at_final_flush(session, flush_context, instances):
            pending = [row for row in session.new if isinstance(row, AuditEvent)
                       and row.company_id == cid and row.action == "doc.register"]
            assert session.get_transaction() is root
            assert session not in native._SEALS
            if not pending:
                # Ранние flush в ensure_token предшествуют log_audit и очереди DocNotice;
                # внедрённая там ошибка вышла бы за обработчик IntegrityError в register_doc.
                assert deferred._STATE not in session.info
                early_flushes.append(root)
                return
            assert len(pending) == 1 and pending[0].user_id == str(uid)
            queue = session.info[deferred._STATE]
            assert queue.root is root and session.get_transaction() is root
            assert queue.physical_root and not queue.poisoned
            assert queue.items == {root: [(0, deferred.DocNotice(cid, doc_id))]}
            assert not injected and not commits and not register_dispatch_spy
            outgoing = [row for row in session.new if isinstance(row, OutboxEvent)
                        and row.company_id == cid and row.type == "doc.registered"
                        and row.subject == str(doc_id)]
            assert len(outgoing) == 1
            assert outgoing[0].data["doc"]["status"] == "registered"
            assert outgoing[0].data["doc"]["regNumber"]
            assert any(isinstance(row, DocEvent) and row.doc_id == doc_id
                       and row.kind == "registered" for row in session.new)
            injected.append(root)
            # Добавляем лишь некорректные данные: реальный flush/драйвер/БД должны дать 23502.
            session.add(AuditEvent(company_id=cid, user_id="system", user_name="Платформа",
                                   action=None, details="synthetic final flush NOT NULL failure"))

        def observe_commit(session):
            commits.append(session.get_transaction())

        def observe_database_error(context):
            # Только наблюдение: без SQL, подмены исключения и искусственного raise.
            database_errors.append((context.original_exception, context.sqlalchemy_exception,
                                    context.connection, db.sync_session in native._SEALS))

        event.listen(db.sync_session, "before_flush", inject_at_final_flush)
        event.listen(db.sync_session, "before_commit", observe_commit)
        event.listen(engine, "handle_error", observe_database_error)
        try:
            with pytest.raises(HTTPException) as error:
                await docs_router.register_doc(str(doc_id), docs_router.RegisterIn(
                    company_id=str(cid)), db=db, current_user=actor)
            assert error.value.status_code == 409
            assert early_flushes and all(item is root for item in early_flushes)
            assert injected == [root] and commits == []
            assert len(database_errors) == 1
            original, wrapped, failed_connection, sealed = database_errors[0]
            assert isinstance(wrapped, IntegrityError) and wrapped.orig is original
            assert getattr(original, "sqlstate", None) == "23502"
            assert getattr(original.__cause__, "table_name", None) == "audit_events"
            assert getattr(original.__cause__, "column_name", None) == "action"
            assert failed_connection is connection and sealed is False
            # Корень должен откатить обработчик до вызова Session.close().
            assert db.sync_session.get_transaction() is None
            assert db.sync_session not in native._SEALS
            assert deferred._STATE not in db.sync_session.info
            assert not register_dispatch_spy
        finally:
            event.remove(engine, "handle_error", observe_database_error)
            event.remove(db.sync_session, "before_commit", observe_commit)
            event.remove(db.sync_session, "before_flush", inject_at_final_flush)
            await db.rollback()  # Очистка также при нарушении проверки или неожиданном исключении.
        assert deferred._STATE not in db.sync_session.info
    async with audit_pg_factory() as independent:
        doc = await independent.get(DocCard, doc_id)
        assert doc.status == "draft" and doc.reg_number is None and doc.verify_token is None
        assert doc.registered_by is None
        assert await _counters(independent, cid) == before
        assert not list(await independent.scalars(select(DocEvent).where(DocEvent.doc_id == doc_id)))
        assert not list(await independent.scalars(select(AuditEvent).where(AuditEvent.company_id == cid)))
        assert not list(await independent.scalars(select(OutboxEvent).where(OutboxEvent.company_id == cid)))
        assert not register_dispatch_spy
