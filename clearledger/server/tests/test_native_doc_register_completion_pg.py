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
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (AuditEvent, DocAcquaint, DocCard, DocCounter, DocEvent,
    DocKind, DocCase, EventSubscription, OutboxEvent, User)
from app.services import native_doc_register_locks as native, after_root_commit as deferred
from app.services import space_events, notify
from app.services import contract_write_locks as locks
from app.routers import docs_router as docs
from tests.test_native_doc_register_ownership_pg import world, tag, blocked, running, register

pytestmark = pytest.mark.asyncio


async def register_facts(db, w):
    doc = await db.get(DocCard, w.doc, populate_existing=True)
    counters = list((await db.execute(select(DocCounter.next_value).where(DocCounter.company_id == w.cid))).scalars())
    events = list((await db.execute(select(DocEvent.id).where(DocEvent.doc_id == w.doc,
        DocEvent.kind == "registered"))).scalars())
    audits = list((await db.execute(select(AuditEvent.id).where(AuditEvent.company_id == w.cid,
        AuditEvent.action == "doc.register"))).scalars())
    outbox = list((await db.execute(select(OutboxEvent).where(OutboxEvent.company_id == w.cid,
        OutboxEvent.subject == str(w.doc), OutboxEvent.type == "doc.registered"))).scalars())
    return doc, counters, events, audits, outbox


@pytest.mark.parametrize("manual", [False, True])
async def test_actual_atomic_success_retention_own_delta_g3_visibility_and_repeat(world, monkeypatch, manual):
    w = world
    async with w.factory() as setup:
        setup.add(DocAcquaint(company_id=w.cid, doc_id=w.doc, user_id=w.recipient,
            snapshot_sha256="a" * 64, status="pending", created_by=w.admin))
        await setup.commit()
    observed, failures = [], []
    def schedule(cid, action, **kw):
        if action != "doc.register":
            return
        try:
            with Session(w.engine.sync_engine) as independent:
                card = independent.get(DocCard, w.doc)
                assert card.status == "registered" and card.reg_number and card.verify_token
                assert card.case_id == w.case and card.storage_until.year == card.reg_date.year + 5
                assert independent.scalar(select(DocEvent.id).where(DocEvent.doc_id == w.doc,
                    DocEvent.kind == "registered"))
                assert independent.scalar(select(AuditEvent.id).where(AuditEvent.company_id == cid,
                    AuditEvent.action == action))
                outgoing = independent.scalar(select(OutboxEvent).where(OutboxEvent.subject == str(w.doc)))
                assert outgoing.data["doc"]["regNumber"] == card.reg_number
                assert independent.scalar(select(DocAcquaint.status).where(DocAcquaint.doc_id == w.doc)) == "superseded"
            observed.append((cid, action))
        except BaseException as exc:
            failures.append(exc)
            raise
    monkeypatch.setattr(notify, "dispatch_async", schedule)
    async with w.factory() as caller:
        args = dict(reg_number="SYN-MANUAL", manual_reason="Synthetic legacy journal") if manual else {}
        result = await register(w, caller, actor=w.admin if manual else w.uid, **args)
        assert result["reg_number"]
        assert caller.sync_session not in native._SEALS
        assert deferred._STATE not in caller.sync_session.info
        assert len(observed) == 1 and failures == []
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert counters == ([] if manual else [1])
        assert len(events) == len(audits) == len(outgoing) == 1
        assert doc.number_manual is manual and doc.retention_snapshot["case_id"] == str(w.case)
    async with w.factory() as repeated:
        with pytest.raises(HTTPException) as error:
            await register(w, repeated)
        assert error.value.status_code == 409 and "уже зарегистрирован" in error.value.detail
        await repeated.rollback()
    assert len(observed) == 1


@pytest.mark.parametrize("counter_exists", [False, True])
async def test_counter_upsert_last_wait_fresh_temporal_session_and_whole_root_rollback(world, monkeypatch, counter_exists):
    w = world
    key = f"synthetic|-|{w.year}"
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "counter"), await tag(caller, "register")
        holder.add(DocCounter(company_id=w.cid, scope_key=key, next_value=0))
        if counter_exists:
            await holder.commit()
            hp = await tag(holder, "counter")
            await holder.execute(select(DocCounter).where(DocCounter.company_id == w.cid).with_for_update())
        else:
            await holder.flush()  # Real absent-row ON CONFLICT unique-index wait.
        claims = {"sub": str(w.uid), "tv": 0, "at": datetime.now(timezone.utc).timestamp()}
        async with running(register(w, caller, claims=claims)) as task:
            rows = await blocked(observer, cp, hp)
            assert any(r.locktype == "transactionid" and not r.granted for r in rows)
            from app import auth
            monkeypatch.setattr(auth, "MAX_SESSION_DAYS", 0)
            await holder.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, 10)
            assert error.value.status_code == 401
            # Inspect real own counter DML BEFORE caller rollback; no number or
            # token has been written yet, and no G3 item can escape.
            assert await caller.scalar(select(DocCounter.next_value).where(DocCounter.company_id == w.cid)) == 1
            doc = await caller.get(DocCard, w.doc)
            assert doc.reg_number is None and doc.verify_token is None and doc.status == "draft"
            assert deferred._STATE not in caller.sync_session.info
            await caller.rollback()
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert counters == [0] and not events and not audits and not outgoing
        assert doc.reg_number is None


async def test_original_late_case_wait_retains_number_token_and_then_denies_fresh_session(world, monkeypatch):
    w = world
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "case"), await tag(caller, "register")
        await holder.execute(select(DocCase).where(DocCase.id == w.case).with_for_update())
        claims = {"sub": str(w.uid), "tv": 0, "at": datetime.now(timezone.utc).timestamp()}
        async with running(register(w, caller, claims=claims)) as task:
            await blocked(observer, cp, hp)
            writes = [sql for label, sql, _ in w.sql if label == "register"]
            assert any("insert into doc_counters" in sql for sql in writes)
            assert any("update doc_cards" in sql for sql in writes)
            from app import auth
            monkeypatch.setattr(auth, "MAX_SESSION_DAYS", 0)
            await holder.rollback()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, 10)
            assert error.value.status_code == 401
            doc = await caller.get(DocCard, w.doc)
            assert doc.reg_number and doc.verify_token and doc.status == "registered"
            assert doc.case_id == w.case and doc.retention_snapshot
            assert await caller.scalar(select(DocCounter.next_value).where(DocCounter.company_id == w.cid)) == 1
            assert not any(a[1] == "doc.register" for a, kw in w.notifications)
            await caller.rollback()
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert doc.reg_number is None and doc.verify_token is None and doc.case_id is None
        assert counters == [] and events == audits == outgoing == []


@pytest.mark.parametrize("owner_completion", ["commit", "rollback"])
async def test_final_flush_real_outbox_unique_wait_then_current_check_inside_old_try(world, monkeypatch, owner_completion):
    w, event_id = world, uuid4()
    async with w.factory() as owner, w.factory() as caller, w.factory() as observer:
        op, cp = await tag(owner, "unique-owner"), await tag(caller, "register")
        owner.add(OutboxEvent(event_id=event_id, subscription_id=w.sub, company_id=w.cid,
            type="doc.registered", subject="synthetic-other", occurred_at=datetime.now(timezone.utc), data={}))
        await owner.flush()
        monkeypatch.setattr(space_events.uuid, "uuid4", lambda: event_id)
        claims = {"sub": str(w.uid), "tv": 0, "at": datetime.now(timezone.utc).timestamp()}
        async with running(register(w, caller, claims=claims)) as task:
            await blocked(observer, cp, op)
            # Prove this is the final real outbox unique-index/FK stage, after
            # native Card/token/Case/audit work, not a synthetic lock substitute.
            rows = [sql for label, sql, _ in w.sql if label == "register"]
            assert any("insert into eco_outbox_events" in sql for sql in rows)
            assert any("insert into audit_events" in sql for sql in rows)
            from app import auth
            monkeypatch.setattr(auth, "MAX_SESSION_DAYS", 0)
            await getattr(owner, owner_completion)()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, 10)
            assert error.value.status_code == (409 if owner_completion == "commit" else 401)
            if owner_completion == "rollback":
                # The final native check ran AFTER the wait/flush. Evidence is
                # retained in the same actual root until its owner rolls back.
                doc = await caller.get(DocCard, w.doc)
                assert doc.reg_number and doc.verify_token and doc.retention_snapshot
                assert await caller.scalar(select(OutboxEvent.id).where(OutboxEvent.subject == str(w.doc)))
                assert deferred._STATE in caller.sync_session.info
                assert not any(a[1] == "doc.register" for a, kw in w.notifications)
                await caller.rollback()
            assert deferred._STATE not in caller.sync_session.info
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert doc.reg_number is None and not counters and not events and not audits and not outgoing


@pytest.mark.parametrize("kind", ["approval", "acquaint", "event"])
async def test_real_child_fk_insert_waits_for_register_card_x(world, kind):
    w = world
    from app.models import DocApproval
    async with w.factory() as counter, w.factory() as caller, w.factory() as writer, w.factory() as observer:
        bp, cp, wp = await tag(counter, "counter"), await tag(caller, "register"), await tag(writer, "child")
        counter.add(DocCounter(company_id=w.cid, scope_key=f"synthetic|-|{w.year}", next_value=0))
        await counter.commit()
        await counter.execute(select(DocCounter).where(DocCounter.company_id == w.cid).with_for_update())
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, bp)
            if kind == "approval":
                writer.add(DocApproval(company_id=w.cid, doc_id=w.doc, assignee_id=w.recipient))
            elif kind == "acquaint":
                writer.add(DocAcquaint(company_id=w.cid, doc_id=w.doc, user_id=w.recipient))
            else:
                writer.add(DocEvent(doc_id=w.doc, kind="field", user_id=w.recipient, actor_name="Synthetic"))
            async with running(writer.flush()) as wt:
                waits = await blocked(observer, wp, cp, relation="doc_cards")
                assert any(r.locktype == "transactionid" and not r.granted for r in waits)
                await counter.rollback()
                assert await asyncio.wait_for(rt, 10)
                await asyncio.wait_for(wt, 10)
                await writer.rollback()


@pytest.mark.parametrize("ending", ["commit", "rollback", "invalidate"])
async def test_clean_seal_sql_free_exact_root_and_session_reuse(world, ending):
    w = world
    async with w.factory() as db:
        actor = await db.get(User, w.uid)
        p = await native.prepare_register(db, actor, str(w.cid), str(w.doc))
        doc = (await db.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())).scalar_one()
        retained = native.retain_register(p, doc)
        await native.check_register(db, p, doc, retained, phase="final")
        native.seal_register(db, p)
        assert db.sync_session in native._SEALS
        baseline_sql = len(w.sql)
        db.add(AuditEvent(company_id=w.cid, user_id=str(w.uid), user_name="Synthetic", action="synthetic.sealed"))
        with pytest.raises(locks.ScopedLockError):
            await db.flush()
        assert len(w.sql) == baseline_sql, "Seal must reject without SQL"
        await db.rollback()  # Whole-root owner cleanup after denied flush.
        assert db.sync_session not in native._SEALS
        # A new native entrance is a new root, not a reused capability.
        actor = await db.get(User, w.uid)
        p2 = await native.prepare_register(db, actor, str(w.cid), str(w.doc))
        native.seal_register(db, p2)
        await getattr(db, ending)()
        assert db.sync_session not in native._SEALS
        db.add(AuditEvent(company_id=w.cid, user_id=str(w.uid), user_name="Synthetic", action="synthetic.next-root"))
        await db.flush()
        await db.rollback()


async def test_postseal_before_commit_dml_rejected_and_g3_queue_discarded(world):
    w = world
    async with w.factory() as db:
        def mutate(session):
            session.add(AuditEvent(company_id=w.cid, user_id=str(w.uid), user_name="Synthetic", action="synthetic.late"))
        event.listen(db.sync_session, "before_commit", mutate)
        try:
            with pytest.raises(locks.ScopedLockError):
                await register(w, db)
            assert deferred._STATE in db.sync_session.info
            assert not any(a[1] == "doc.register" for a, kw in w.notifications)
            await db.rollback()
            assert deferred._STATE not in db.sync_session.info and db.sync_session not in native._SEALS
        finally:
            event.remove(db.sync_session, "before_commit", mutate)
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert doc.reg_number is None and not counters and not events and not audits and not outgoing


@pytest.mark.parametrize("failure", ["after_commit", "postcommit_refresh"])
async def test_commit_refresh_ambiguity_never_reports_rollback_or_replay_success(world, monkeypatch, failure):
    w = world
    async with w.factory() as db:
        def committed_failure(session):
            raise RuntimeError("Synthetic response lost after actual commit")
        async def refresh_failure(*args, **kw):
            raise RuntimeError("Synthetic postcommit refresh failure")
        if failure == "after_commit":
            event.listen(db.sync_session, "after_commit", committed_failure)
        else:
            monkeypatch.setattr(db, "refresh", refresh_failure)
        try:
            with pytest.raises(RuntimeError):
                await register(w, db)
        finally:
            if failure == "after_commit":
                event.remove(db.sync_session, "after_commit", committed_failure)
        # No handler guess/rollback: reconcile from an independent real root.
        async with w.factory() as independent:
            doc, counters, events, audits, outgoing = await register_facts(independent, w)
            assert doc.status == "registered" and doc.reg_number and counters == [1]
            assert len(events) == len(audits) == len(outgoing) == 1
    async with w.factory() as retry:
        with pytest.raises(HTTPException) as error:
            await register(w, retry)
        assert error.value.status_code == 409
        await retry.rollback()


async def test_original_counter_then_case_order_avoids_mixed_root_cycle(world):
    w = world
    async with w.factory() as old_root, w.factory() as caller, w.factory() as observer:
        op, cp = await tag(old_root, "old-root"), await tag(caller, "register")
        # The actual old services retain their root and ordering. A Case SHARE
        # prelock in register would deadlock old counter -> Case X here.
        assert await docs.next_number(old_root, w.cid, f"synthetic|-|{w.year}") == 1
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, op)
            case = await asyncio.wait_for(docs._locked_case_or_404(old_root, w.cid, w.case), 5)
            assert case.id == w.case
            rows = [sql for label, sql, _ in w.sql if label == "register"]
            assert not any("doc_cases" in sql and ("for share" in sql or "for update" in sql) for sql in rows)
            await old_root.commit()
            assert await asyncio.wait_for(rt, 10)


async def test_early_ensure_token_integrity_error_remains_outside_old_commit409_catch(world, monkeypatch):
    w = world
    token = "synthetic-fixed-verification-token"
    async with w.factory() as setup:
        setup.add(DocCard(company_id=w.cid, kind_id=w.kind, title="Synthetic existing token",
            author_id=w.uid, verify_token=token))
        await setup.commit()
    from app.services import doc_verify
    monkeypatch.setattr(doc_verify.secrets, "token_urlsafe", lambda n: token)
    async with w.factory() as db:
        with pytest.raises(IntegrityError):
            await register(w, db)
        assert not any(a[1] == "doc.register" for a, kw in w.notifications)
        await db.rollback()
    async with w.factory() as check:
        doc, counters, events, audits, outgoing = await register_facts(check, w)
        assert doc.reg_number is None and doc.verify_token is None
        assert not counters and not events and not audits and not outgoing


@pytest.mark.parametrize("error_case,code,fragment", [
    ("registered", 409, "уже зарегистрирован"), ("state", 409, "только черновик"),
    ("approval", 409, "Во время согласования"), ("attrs", 409, "обязательный реквизит"),
    ("future", 400, "не может быть в будущем"), ("empty_manual", 400, "не может быть пустым"),
    ("manual_admin", 403, "администратор"), ("manual_reason", 409, "причину переноса"),
    ("manual_busy", 409, "уже занят"), ("invalid", 400, "doc_id"), ("missing", 404, "не найден"),
])
async def test_native_error_precedence_and_manual_counter_unchanged(world, error_case, code, fragment):
    w = world
    from datetime import timedelta
    args, actor, doc_id = {}, w.uid, str(w.doc)
    async with w.factory() as setup:
        doc, kind = await setup.get(DocCard, w.doc), await setup.get(DocKind, w.kind)
        if error_case == "registered":
            doc.reg_number, doc.status, doc.approval_status = "SYN-OLD", "executed", "pending"
        elif error_case == "state":
            doc.status, doc.approval_status = "executed", "pending"
        elif error_case == "approval":
            doc.approval_status = "pending"
        elif error_case == "attrs":
            kind.fields = [dict(code="required", label="Synthetic required", type="text", required=True)]
            args = dict(reg_date=datetime.now(timezone.utc).date() + timedelta(days=1))
        elif error_case == "future":
            args = dict(reg_date=datetime.now(timezone.utc).date() + timedelta(days=1), reg_number=" ")
        elif error_case == "empty_manual":
            args = dict(reg_number=" ")
        elif error_case in ("manual_admin", "manual_reason", "manual_busy"):
            args = dict(reg_number="SYN-BUSY", manual_reason="" if error_case != "manual_busy" else "Synthetic transfer")
            actor = w.uid if error_case == "manual_admin" else w.admin
            if error_case == "manual_busy":
                setup.add(DocCard(company_id=w.cid, kind_id=w.kind, title="Synthetic busy number",
                    author_id=w.uid, organization_id=w.org, reg_number="SYN-BUSY"))
        elif error_case == "invalid":
            doc_id = "synthetic-invalid-uuid"
        else:
            doc_id = str(uuid4())
        await setup.commit()
    async with w.factory() as db:
        user = await db.get(User, actor)
        with pytest.raises(HTTPException) as error:
            await docs.register_doc(doc_id, docs.RegisterIn(company_id=str(w.cid), **args), db, user)
        assert error.value.status_code == code and fragment in error.value.detail
        assert not await db.scalar(select(DocCounter.next_value).where(DocCounter.company_id == w.cid))
        assert not any(a[1] == "doc.register" for a, kw in w.notifications)
        await db.rollback()


async def test_native_selected_constraints_and_canonical_user_refs_are_real(world):
    w = world
    async with w.factory() as db:
        constraints = (await db.execute(text(
            "SELECT conname, contype, convalidated, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid IN ('doc_events'::regclass, 'doc_acquaints'::regclass, "
            "'eco_outbox_events'::regclass)"))).all()
        assert all(row.convalidated for row in constraints)
        assert any(row.contype == "f" and "FOREIGN KEY (doc_id)" in row.definition
                   and "REFERENCES doc_cards(id)" in row.definition for row in constraints)
        assert any(row.conname == "uq_eco_outbox_delivery" and row.contype == "u" for row in constraints)
        indexes = (await db.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('doc_cards','doc_cases','doc_kinds')"))).all()
        for name in ("uq_doc_cards_reg_number", "uq_doc_cards_verify_token", "uq_doc_cases_index", "uq_doc_kinds_code"):
            assert any(row.indexname == name and "UNIQUE" in row.indexdef for row in indexes)
        actor = await db.get(User, w.uid)
        prepared = await native.prepare_register(db, actor, str(w.cid), str(w.doc))
        from uuid import UUID
        assert all(type(uid) is UUID for uid in prepared.users)
        assert all(type(cid) is UUID for cid in prepared.companies)
        assert {w.uid, w.recipient, w.principal, w.admin, w.foreign} <= set(prepared.users)
        await db.rollback()


async def test_publish_one_selector_new_recipient_guard_and_exact_root_receipt(world):
    w = world
    async with w.factory() as caller, w.factory() as writer, w.factory() as other:
        actor = await caller.get(User, w.uid)
        p = await native.prepare_register(caller, actor, str(w.cid), str(w.doc))
        receipt = native.subscription_parents(caller, p)
        with pytest.raises(locks.ScopedLockError):
            await space_events.publish(other, w.cid, "doc.registered", str(w.doc), {}, expected_parents=receipt)
        assert not other.new
        await other.rollback()
        writer.add(EventSubscription(company_id=w.cid, label="Synthetic late consumer", target_kind="url",
            url="https://example.invalid/late", secret_enc=w.cipher, event_types=["doc.registered"]))
        await writer.commit()
        before = len(w.sql)
        with pytest.raises(HTTPException) as error:
            with caller.no_autoflush:
                await space_events.publish(caller, w.cid, "doc.registered", str(w.doc), {}, expected_parents=receipt)
        assert error.value.status_code == 409 and not caller.new
        selectors = [sql for _, sql, _ in w.sql[before:] if "from eco_event_subscriptions" in sql]
        assert len(selectors) == 1 and not any("for update" in sql or "for share" in sql for sql in selectors)
        await caller.rollback()


async def test_g3_callback_sees_retired_seal_before_reentrant_next_root(world, monkeypatch):
    w = world
    calls, failures = [], []
    async with w.factory() as db:
        def callback(cid, action, **kw):
            if action != "doc.register":
                return
            try:
                assert db.sync_session not in native._SEALS
                assert deferred._STATE not in db.sync_session.info
                with db.sync_session.begin():
                    db.sync_session.add(AuditEvent(company_id=cid, user_id=str(w.uid),
                        user_name="Synthetic callback", action="synthetic.callback-root"))
                    db.sync_session.flush()
                calls.append(action)
            except BaseException as exc:
                failures.append(exc)
                raise
        monkeypatch.setattr(notify, "dispatch_async", callback)
        assert await register(w, db)
        assert calls == ["doc.register"] and not failures
        assert db.sync_session not in native._SEALS


@pytest.mark.parametrize("organizations", ["zero", "one", "many"])
async def test_native_org_inference_and_ambiguity_precedes_manual_trim(world, organizations):
    w = world
    from app.models import Organization
    async with w.factory() as setup:
        doc, kind = await setup.get(DocCard, w.doc), await setup.get(DocKind, w.kind)
        doc.organization_id, kind.number_scope = None, "kind_org_year"
        kind.number_template = "{prefix}-{org}-{yyyy}-{n:04d}"
        if organizations == "zero":
            await setup.delete(await setup.get(Organization, w.org))
        elif organizations == "many":
            setup.add(Organization(company_id=w.cid, name="Synthetic second organization", inn=""))
        await setup.commit()
    async with w.factory() as caller:
        if organizations == "many":
            with pytest.raises(HTTPException) as error:
                await register(w, caller, reg_number=" ")
            assert error.value.status_code == 409 and "Выберите юрлицо" in error.value.detail
            assert not await caller.scalar(select(DocCounter.next_value).where(DocCounter.company_id == w.cid))
            await caller.rollback()
        else:
            result = await register(w, caller)
            assert result["organization_id"] == (str(w.org) if organizations == "one" else None)
            counter = (await caller.execute(select(DocCounter).where(DocCounter.company_id == w.cid))).scalar_one()
            assert counter.next_value == 1
            assert counter.scope_key == f"synthetic|{w.org if organizations == 'one' else '-'}|{w.year}"
