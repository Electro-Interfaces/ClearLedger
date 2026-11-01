"""Определения исходников / NOTRUN, включая collection.

Требуются изоляция до импорта и полная нативная временная схема владельца прогона.
Только новый синтетический world с родителями до потомков; старый не импортируется.
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

import ast
import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.audit import log_audit
from app.models import AuditEvent, DocAccessGrant, DocCard, DocCounter, DocEvent, NotificationRule, OutboxEvent, User
from app.routers import docs_router as docs
from app.services import after_root_commit as deferred, native_doc_register_locks as native, notify
from tests.test_doc_register_notice_policy_pg import grant_read, notice_world, only_recipient

pytestmark = pytest.mark.asyncio


async def enqueue(w, db, label="synthetic", *, doc=True):
    await log_audit(db, actor=None, company_id=w.cid,
        action="doc.register" if doc else "synthetic." + label,
        target=label, details={"manual_reason": "Synthetic private snapshot"},
        notification_timing="after_root_commit", **({"doc_notice_id": w.doc} if doc else {}))


@pytest.mark.parametrize("manual", [False, True])
async def test_actual_register_root_visibility_and_reference_only_after_retirement(notice_world, monkeypatch, manual):
    w = notice_world
    calls, attempts, failures = [], [], []
    async with w.factory() as db:
        def callback(cid, action, **kw):
            attempts.append((cid, action, kw))
            try:
                assert deferred._STATE not in db.sync_session.info
                assert db.sync_session not in native._SEALS
                assert kw == {"doc_notice_id": w.doc}
                assert type(kw["doc_notice_id"]) is UUID
                with Session(w.engine.sync_engine) as independent:
                    card = independent.get(DocCard, w.doc)
                    assert card.status == "registered" and card.reg_number and card.verify_token
                    assert card.case_id == w.case and card.retention_snapshot
                    assert independent.scalar(select(AuditEvent.id).where(
                        AuditEvent.company_id == cid, AuditEvent.action == action))
                    assert independent.scalar(select(DocEvent.id).where(
                        DocEvent.doc_id == w.doc, DocEvent.kind == "registered"))
                    outbox = independent.scalar(select(OutboxEvent).where(OutboxEvent.subject == str(w.doc)))
                    assert outbox and outbox.data["doc"]["regNumber"] == card.reg_number
                calls.append(action)
            except BaseException as error:
                failures.append(error)
                raise
        monkeypatch.setattr(notify, "dispatch_async", callback)
        actor = await db.get(User, w.admin if manual else w.author)
        payload = dict(reg_number="SYN-MANUAL", manual_reason="Synthetic private transfer") if manual else {}
        result = await docs.register_doc(str(w.doc), docs.RegisterIn(company_id=str(w.cid), **payload), db, actor)
        assert result["reg_number"] and calls == ["doc.register"]
        assert len(attempts) == 1 and not failures
        assert deferred._STATE not in db.sync_session.info
        await db.commit()  # Последующий пустой commit зависимости не повторяет доставку.
        assert len(attempts) == 1
    async with w.factory() as db:
        values = list(await db.scalars(select(DocCounter.next_value).where(DocCounter.company_id == w.cid)))
        assert values == ([] if manual else [1])


async def test_no_before_business_commit_and_detached_frozen_native_uuid_reference(notice_world):
    w = notice_world
    async with w.factory(expire_on_commit=True) as db:
        await enqueue(w, db)
        queue = db.sync_session.info[deferred._STATE]
        payload = next(iter(queue.items.values()))[0][1]
        assert isinstance(payload, deferred.DocNotice)
        assert [f.name for f in fields(payload)] == ["company_id", "doc_id"]
        assert type(payload.company_id) is type(payload.doc_id) is UUID
        with pytest.raises(FrozenInstanceError):
            payload.doc_id = uuid4()
        assert [f.name for f in fields(deferred.AuditNotification)] == ["company_id", "action", "who", "details"]
        await db.flush()
        assert not w.scheduled and not w.mail
        async with w.factory() as observer:
            assert not list(await observer.scalars(select(AuditEvent.id).where(AuditEvent.company_id == w.cid)))
        await db.commit()
        assert w.scheduled == [((w.cid, "doc.register"), {"doc_notice_id": w.doc})]
        assert deferred._STATE not in db.sync_session.info and not queue.items and not queue.successful
        await db.commit()
        assert len(w.scheduled) == 1


@pytest.mark.parametrize("change", ["grant", "revoke"])
@pytest.mark.parametrize("relative_to_commit", ["before", "after"])
async def test_enqueue_and_business_commit_never_freeze_recipient_authority(notice_world, change, relative_to_commit):
    w = notice_world
    await only_recipient(w, w.first)
    async with w.factory() as db:
        (await db.get(DocCard, w.doc)).confidentiality = "private"
        await db.commit()
    if change == "revoke":
        await grant_read(w, w.first)
    async def change_authority():
        if change == "grant":
            await grant_read(w, w.first)
        else:
            async with w.factory() as writer:
                await writer.execute(delete(DocAccessGrant).where(DocAccessGrant.company_id == w.cid))
                await writer.commit()
    async with w.factory() as business:
        await enqueue(w, business)
        await business.flush()
        if relative_to_commit == "before":
            await change_authority()
        assert not w.scheduled and not w.attempts
        await business.commit()
        if relative_to_commit == "after":
            await change_authority()
    assert len(w.scheduled) == 1
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == int(change == "grant")


@pytest.mark.parametrize("end", ["rollback", "close", "invalidate", "constraint_error", "cancel"])
async def test_abandoned_roots_discard_doc_variant_and_reuse_clean_session(notice_world, end):
    w = notice_world
    db = w.factory()
    try:
        await enqueue(w, db)
        if end == "constraint_error":
            next(row for row in db.new if isinstance(row, AuditEvent)).action = None
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()
        elif end == "cancel":
            ready, release = asyncio.Event(), asyncio.Event()
            async def owner():
                try:
                    await db.flush()
                    ready.set()
                    await release.wait()
                    await db.commit()
                finally:
                    await db.rollback()
            task = asyncio.create_task(owner())
            try:
                await asyncio.wait_for(ready.wait(), 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            await db.flush()
            await getattr(db, end)()
        assert not w.scheduled and deferred._STATE not in db.sync_session.info
        await enqueue(w, db, "new-root")
        await db.commit()
        assert w.scheduled == [((w.cid, "doc.register"), {"doc_notice_id": w.doc})]
        assert deferred._STATE not in db.sync_session.info
    finally:
        await db.close()


@pytest.mark.parametrize("child_commit,root_commit", [(True, True), (False, True), (True, False), (False, False)])
async def test_doc_and_legacy_mixed_savepoint_order_and_root_outcome(notice_world, child_commit, root_commit):
    w = notice_world
    async with w.factory() as db:
        await enqueue(w, db, "A", doc=False)
        child = await db.begin_nested()
        await enqueue(w, db, "B")
        await db.flush()
        await (child.commit() if child_commit else child.rollback())
        await enqueue(w, db, "C", doc=False)
        assert not w.scheduled
        await (db.commit() if root_commit else db.rollback())
        expected = ["synthetic.A", "doc.register", "synthetic.C"] if child_commit else ["synthetic.A", "synthetic.C"]
        assert [a[1] for a, _ in w.scheduled] == (expected if root_commit else [])
        assert deferred._STATE not in db.sync_session.info


async def test_nested_subtree_discard_and_committed_sibling_sequence(notice_world):
    w = notice_world
    async with w.factory() as db:
        await enqueue(w, db, "A", doc=False)
        outer = await db.begin_nested()
        await enqueue(w, db, "B")
        inner = await db.begin_nested()
        await enqueue(w, db, "C", doc=False)
        await inner.commit()
        await outer.rollback()
        async with db.begin_nested():
            await enqueue(w, db, "D")
        assert not w.scheduled
        await db.commit()
        assert [a[1] for a, _ in w.scheduled] == ["synthetic.A", "doc.register"]


@pytest.mark.parametrize("when", ["before", "after"])
async def test_core_savepoint_guard_and_sticky_poison_are_unchanged(notice_world, when):
    w = notice_world
    async with w.factory() as db:
        if when == "after":
            await enqueue(w, db)
        connection = await db.connection()
        core = await connection.begin_nested()
        if when == "before":
            with pytest.raises(ValueError, match="Core SAVEPOINT"):
                await enqueue(w, db)
            assert not db.new and deferred._STATE not in db.sync_session.info
        else:
            with pytest.raises(ValueError, match="Core SAVEPOINT"):
                await db.flush()
        await core.rollback()
        if when == "after":
            with pytest.raises(ValueError, match="roll back the entire root"):
                await db.commit()
        await db.rollback()
        assert not w.scheduled and deferred._STATE not in db.sync_session.info
        await enqueue(w, db, "reused", doc=False)
        await db.commit()
        assert [a[1] for a, _ in w.scheduled] == ["synthetic.reused"]


@pytest.mark.parametrize("join_mode", ["conditional_savepoint", "create_savepoint", "rollback_only", "control_fully"])
async def test_external_connection_cannot_enqueue_before_audit_add(notice_world, join_mode):
    w = notice_world
    async with w.engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(connection, join_transaction_mode=join_mode) as db:
            with pytest.raises(ValueError):
                await enqueue(w, db)
            assert not db.new and deferred._STATE not in db.sync_session.info
        assert outer.is_active and not w.scheduled
        await outer.rollback()


async def test_reentrant_callback_starts_clean_next_root_and_failure_is_log_only(notice_world, monkeypatch):
    w = notice_world
    attempts, failures = [], []
    async with w.factory() as db:
        def callback(cid, action, **kw):
            attempts.append(action)
            try:
                assert deferred._STATE not in db.sync_session.info
                if action == "doc.register":
                    db.add(AuditEvent(company_id=cid, user_id="system", user_name="Synthetic",
                                      action="synthetic.next"))
                    deferred.enqueue_audit_notification(db, company_id=cid, action="synthetic.next",
                                                         who=None, details=None)
            except BaseException as error:
                failures.append(error)
                raise
            if action == "doc.register":
                raise RuntimeError("Synthetic scheduler failure after starting new root")
        monkeypatch.setattr(notify, "dispatch_async", callback)
        await enqueue(w, db)
        await db.commit()
        assert attempts == ["doc.register"] and not failures
        await db.commit()
        assert attempts == ["doc.register", "synthetic.next"] and not failures
        assert deferred._STATE not in db.sync_session.info
    async with w.factory() as observer:
        assert list(await observer.scalars(select(AuditEvent.action).where(
            AuditEvent.company_id == w.cid).order_by(AuditEvent.action))) == ["doc.register", "synthetic.next"]


async def test_real_background_delivery_owns_session_after_commit(notice_world, monkeypatch):
    w = notice_world
    # Обёртка наблюдает завершение/ошибку настоящей доставки с реальными Session
    # и синтетическими транспортами.
    finished, errors = asyncio.Event(), []
    original = notify.dispatch_doc_notice
    async def observe(cid, did):
        try:
            await original(cid, did)
        except BaseException as error:
            errors.append(error)
            raise
        finally:
            finished.set()
    monkeypatch.setattr(notify, "dispatch_doc_notice", observe)
    monkeypatch.setattr(notify, "dispatch_async", w.original_dispatch)
    async with w.factory() as db:
        await enqueue(w, db)
        await db.flush()
        await asyncio.sleep(0)
        assert not finished.is_set() and not w.mail
        await db.commit()
        await asyncio.wait_for(finished.wait(), 5)
        assert not errors and len(w.mail) == 2
    assert w.engine.pool.checkedout() == 0


@pytest.mark.parametrize("action,timing,identity", [
    ("user.create", "after_root_commit", "uuid"),
    ("doc.register", "immediate", "uuid"),
    ("doc.register", "after_root_commit", "text"),
])
async def test_invalid_optin_never_adds_or_falls_back(notice_world, action, timing, identity):
    w = notice_world
    async with w.factory() as db:
        with pytest.raises((ValueError, TypeError)):
            await log_audit(db, actor=None, company_id=w.cid, action=action,
                notification_timing=timing, doc_notice_id=w.doc if identity == "uuid" else str(w.doc))
        assert not db.new and not w.scheduled and deferred._STATE not in db.sync_session.info


async def test_other_audits_keep_immediate_snapshot_and_shared_channel_semantics(notice_world):
    w = notice_world
    async with w.factory() as db:
        await log_audit(db, actor=None, company_id=w.cid, action="user.create", target="Synthetic legacy")
        assert w.scheduled == [((w.cid, "user.create"), {"who": None, "details": "Synthetic legacy"})]
        assert deferred._STATE not in db.sync_session.info
        await db.rollback()
    assert len(w.scheduled) == 1  # Прежний immediate по-прежнему не зависит от commit.
    w.allow_shared = True
    # Прежний dispatcher работает без Doc-ссылки для остальных действий/проб.
    # Меняется только явный opt-in регистрации.
    async with w.factory() as db:
        rule = await db.get(NotificationRule, w.rule)
        rule.recipients = [str(w.first)]
        await db.commit()
        result = await notify.dispatch(db, w.cid, "doc.update", who="Synthetic legacy actor", details="legacy snapshot")
    assert result["chat"] is True and result["email"] is True and len(w.chat) == 1
    assert "Synthetic legacy actor" in w.mail[0][2] and "legacy snapshot" in w.mail[0][2]


async def test_all_other_105_audit_calls_remain_non_optin_source_inventory():
    root = Path(__file__).resolve().parents[1] / "app"
    calls = []
    for path in sorted(root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "log_audit":
                calls.append((path.relative_to(root).as_posix(), node))
    opted = [(path, node) for path, node in calls if any(kw.arg == "doc_notice_id" for kw in node.keywords)]
    assert len(calls) == 106 and len(opted) == 1
    assert opted[0][0] == "routers/docs_router.py"
    other = [node for _, node in calls if node is not opted[0][1]]
    assert len(other) == 105 and all(not any(kw.arg == "doc_notice_id" for kw in node.keywords) for node in other)
    rows = [(path, ast.dump(node, include_attributes=False)) for path, node in calls if node is not opted[0][1]]
    assert hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest() == (
        "ceac25cd6359642cec0211bc07ba2fdd51699f8927d44b35bb11823562be7e85")


async def test_legacy_dispatch_and_g3_guard_source_bodies_unchanged():
    root = Path(__file__).resolve().parents[1] / "app"
    pins = {
        "services/notify.py": {
            "_recipients": "e167b9d90dc64137836fad1dc2a58ea71b783a787d1d02465618bcdcac7f6646",
            "post_alert": "d86e2ace4798144cecf20f3d43cc65472e35de138d8cc315d110e2ea2e6d18b0",
            "_text": "2971a83d59977c8aa8d7d5ac6f2111072169d6cc975cc42a5feb6afad0230ab2",
            "dispatch": "36a21ccaacfbd36b8db88c9e07829c7f03814ab1305b59eb222f21d7736a6174",
        },
        "services/after_root_commit.py": {
            "AuditNotification": "958731e7a68d47f1585b30edfb79f0ceece27e433f1f707a3ab405a11ffa5c62",
            "_configuration": "c7d816ee229f88d2f3f3e93da010545c242831f0e86c534c47675ff890b46976",
            "_nested_ownership": "67ed89163edb027e8f2db5e639b6eca784e7bbb316bef6897cc3065e9f04fb0e",
            "_physical_root": "86fca270093d1f9bb19e3b881de97474457472b03adc6e3cba51088667b3a815",
            "validate_audit_notification_session": "ef035b8426815d448d2aaed5c8d6da94020bc9874b0a60ca37c8e898f0ca1523",
            "_scope": "a51c35e419266b3fd517f1ce883e8e6849c6244584da9e22967dc3d65fa8dd6b",
            "_discard": "26cda7f5128eece5ff3c28196b772fbe4963acc7f5c975391e23e0ab6378988a",
            "_guard_queue": "1a4adecd151fd2db34d45727636c72a2b6ec86d6faf97c50b7b6ca81667c60ff",
            "_after_begin": "361f29b20371c70f43a66a2186910e200182f290246fe6641d4576c43f8d918f",
            "_before_flush": "5d6741c93e3c66affdacd5a71b69e3ea285d9839c50325b3cf0759213ff49641",
            "_before_commit": "5f41a60cd536269e1ec9f631779012a3e9e1779fb37ca0f2bfc6fd29cde3fe56",
            "_after_commit": "6688777c2b12a0721452e39d90d2302256b57c5d50b71a9dd0171835c2d0ded0",
            "_after_rollback": "24745e1673202bf0a3dd56f3f877535ee876e095b5ddcd6432f3d5d7b38eaf79",
            "_after_soft_rollback": "8981bb54fd51462651161cfe796a63952074e4d990c12ef83c0161d24880e195",
        },
    }
    for file, expected in pins.items():
        source = (root / file).read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        nodes = {n.name: n for n in ast.parse(source).body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        for name, digest in expected.items():
            node = nodes[name]
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            body = "".join(lines[start - 1:node.end_lineno])
            assert hashlib.sha256(body.encode()).hexdigest() == digest, (file, name)
