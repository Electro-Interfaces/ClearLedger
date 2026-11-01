"""Определения исходников / NOTRUN, включая collection.

Владелец прогона до импорта изолирует ancestor conftest, поднимает полную нативную
схему/миграции/codecs/constraints и удаляет собственную временную БД.
Определения не создают и не ослабляют схему, не используют старую register fixture.
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
import logging
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import auth, database
from app.audit import log_audit
from app.models import (
    AuditEvent, ChatRoom, Company, CompanyRole, Counterparty, DocAccessGrant, DocApproval,
    DocBreakGlassAccess, DocCard, DocCase, DocInboxItem, DocKind, EventSubscription,
    NotificationRule, Organization, User, UserCompany, UserSubstitution,
)
from app.notify_catalog import action_label, category_for
from app.routers import docs_router as docs
from app.scope import (
    current_object_scope, current_organization, set_request_organization, set_request_scope,
)
from app.services import doc_access, doc_notice_access, notify, space_events, web_push

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def notice_world(monkeypatch, caplog):
    """Нативные партии родителей; удалением БД/схемы владеет владелец прогона."""
    w = SimpleNamespace(**{name: uuid4() for name in (
        "cid", "other", "author", "first", "second", "admin", "sa", "foreign",
        "role", "org", "cp", "case", "kind", "doc", "sub", "rule")})
    w.engine = create_async_engine(_URL, pool_size=8, max_overflow=0,
                                  isolation_level="READ COMMITTED")
    w.factory = async_sessionmaker(w.engine, expire_on_commit=False)
    w.scheduled, w.attempts, w.mail, w.errors, w.chat, w.push = [], [], [], [], [], []
    w.on_mail, w.allow_shared = None, False
    # Один согласованный бизнес-день даже при переходе года между setup/register.
    w.reg_date = datetime.now(docs._BUSINESS_TIMEZONE).date()
    w.expected_notify_errors = []  # Только явно проверенные SQL/SMTP исключения.
    caplog.set_level(logging.WARNING, logger=notify.logger.name)
    w.original_dispatch = notify.dispatch_async
    objects, organization = current_object_scope(), current_organization()
    monkeypatch.setattr(database, "async_session_factory", w.factory)
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: w.scheduled.append((a, kw)))

    async def mail(to, subject, body, *args, **kw):
        attempt = (list(to), subject, body)
        w.attempts.append(attempt)
        try:
            assert len(to) == 1, "document notices must have one To"
            if w.on_mail:
                await w.on_mail(attempt)
            w.mail.append(attempt)
            return True
        except BaseException as error:
            w.errors.append(error)  # Сохраняется и при production log-only catch.
            raise

    async def chat(*args, **kwargs):
        w.chat.append((args, kwargs))
        return True

    monkeypatch.setattr(notify.email_service, "send_notice", mail)
    monkeypatch.setattr(notify, "post_alert", chat)
    monkeypatch.setattr(web_push, "push_room_async", lambda *a, **kw: w.push.append((a, kw)))
    monkeypatch.setenv("EVENTS_SECRET_KEY", "synthetic-notice-encryption-key")
    try:
        with doc_notice_access.doc_notice_context():
            async with w.factory() as db:
                db.add_all([Company(id=cid, slug="notice-" + cid.hex,
                    name="Synthetic company secret", profile_id="energy") for cid in (w.cid, w.other)])
                await db.flush()
                # Все FK-родители идут до Case, без расчёта на ORM relationships.
                db.add_all([User(id=uid, company_id=w.other if uid == w.foreign else w.cid,
                    email=f"{uid.hex}@example.invalid", name="Synthetic actor secret",
                    password_hash="synthetic-noncredential", is_superadmin=(uid == w.sa))
                    for uid in (w.author, w.first, w.second, w.admin, w.sa, w.foreign)])
                db.add(CompanyRole(id=w.role, company_id=w.cid, name="Synthetic docs", modules=["docs"]))
                db.add(Organization(id=w.org, company_id=w.cid, name="Synthetic org secret", inn="", prefix="S"))
                db.add(Counterparty(id=w.cp, company_id=w.cid, name="Synthetic cp secret", aliases=[]))
                await db.flush()
                db.add(DocCase(id=w.case, company_id=w.cid, organization_id=w.org,
                    year=w.reg_date.year, index="01-01", title="Synthetic case",
                    storage_years=5, retention_class="temporary", status="open"))
                await db.flush()
                db.add(DocKind(id=w.kind, company_id=w.cid, code="notice", name="Synthetic kind",
                    default_case_id=w.case, number_scope="kind_year", number_prefix="SYN"))
                db.add_all([UserCompany(user_id=uid, company_id=w.cid,
                    role="admin" if uid == w.admin else "user", role_id=w.role if uid in (w.first, w.second) else None,
                    modules=["docs"], object_scope=["synthetic-object"], own_organization_id=w.org)
                    for uid in (w.author, w.first, w.second, w.admin, w.sa)])
                cipher = space_events.encrypt_secret("whsec_MDEyMzQ1Njc4OWFiY2RlZg==")
                assert cipher is not None
                db.add(EventSubscription(id=w.sub, company_id=w.cid, label="Synthetic consumer",
                    target_kind="url", url="https://example.invalid/events", secret_enc=cipher,
                    event_types=["doc.registered"], enabled=True))
                db.add(NotificationRule(id=w.rule, company_id=w.cid, category=category_for("doc.register"),
                    enabled=True, via_chat=True, via_email=True, recipients=[str(w.first), str(w.second)]))
                await db.flush()
                db.add(DocCard(id=w.doc, company_id=w.cid, kind_id=w.kind, kind_code="notice",
                    title="Synthetic current title", author_id=w.author, organization_id=w.org,
                    counterparty_id=w.cp, summary="Synthetic summary secret", attrs={}))
                await db.commit()
        yield w
    finally:
        set_request_scope(objects)
        set_request_organization(organization)
        try:
            # Внешний oracle охватывает candidate/source-read и весь recipient check:
            # production log-only catch не должен превращать RuntimeError в отказ READ.
            warnings = [record for phase in ("setup", "call", "teardown")
                        for record in caplog.get_records(phase)
                        if record.name == notify.logger.name and record.levelno >= logging.WARNING]
            assert len(warnings) == len(w.expected_notify_errors) and all(
                record.levelno == logging.WARNING
                and record.msg == "Доставка уведомления о регистрации сорвалась: %s"
                and isinstance(record.args, tuple) and len(record.args) == 1
                and record.args[0] is error and record.exc_info is None
                for record, error in zip(warnings, w.expected_notify_errors)
            ), f"unexpected notify warnings/errors: {[(r.levelname, r.getMessage()) for r in warnings]!r}"
            assert not w.errors, f"transport oracle errors: {w.errors!r}; attempts={w.attempts!r}"
            assert w.allow_shared or (not w.chat and not w.push), "shared chat/push forbidden"
            assert w.engine.pool.checkedout() == 0, "recipient/business roots must all close"
        finally:
            await w.engine.dispose()


async def test_registration_business_date_definition_at_utc_year_boundary():
    # Фиксированные UTC-моменты определяют нативный день, без clock/policy подмен.
    assert docs._BUSINESS_TIMEZONE.key == "Europe/Moscow"
    before = datetime(2026, 12, 31, 20, 59, 59, tzinfo=timezone.utc)
    boundary = datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)
    assert before.astimezone(docs._BUSINESS_TIMEZONE).date() == date(2026, 12, 31)
    agreed_reg_date = boundary.astimezone(docs._BUSINESS_TIMEZONE).date()
    assert agreed_reg_date == date(2027, 1, 1)
    assert agreed_reg_date.year != boundary.year


async def only_recipient(w, uid):
    async with w.factory() as db:
        rule = await db.get(NotificationRule, w.rule)
        rule.recipients = [str(uid)]
        await db.commit()


async def grant_read(w, uid, *, denied=None):
    async with w.factory() as db:
        db.add(DocAccessGrant(company_id=w.cid, scope_type="doc", scope_id=w.doc,
            subject_type="user", subject_id=uid, permissions=["read"], denied_permissions=denied or []))
        await db.commit()


async def native_read(w, uid, permission="read"):
    with doc_notice_access.doc_notice_context():
        async with w.factory() as db:
            user, doc = await db.get(User, uid), await db.get(DocCard, w.doc)
            await auth.assert_company_product(str(w.cid), user, db, "docs")
            return await doc_access._can_doc(db, w.cid, doc, user, permission,
                                             record_break_glass_use=False)


@pytest.mark.parametrize("confidentiality,granted", [
    ("company", False), ("private", False), ("private", True), ("strict", False), ("strict", True),
])
async def test_exact_native_read_and_current_content_only(notice_world, confidentiality, granted):
    w = notice_world
    await only_recipient(w, w.first)
    async with w.factory() as db:
        doc = await db.get(DocCard, w.doc)
        doc.confidentiality, doc.reg_number, doc.title = confidentiality, "SYN-CURRENT", "X" * 250
        await db.commit()
    if granted:
        await grant_read(w, w.first)
    expected = await native_read(w, w.first)
    assert expected == (confidentiality == "company" or granted)
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == int(expected) and w.attempts == w.mail
    if expected:
        assert w.mail == [([f"{w.first.hex}@example.invalid"], action_label("doc.register"),
                           f"{action_label('doc.register')}\nSYN-CURRENT\n{'X' * 200}")]
        assert str(w.doc) not in w.mail[0][2]


async def test_read_without_download_is_delivered(notice_world):
    w = notice_world
    await only_recipient(w, w.first)
    async with w.factory() as db:
        (await db.get(DocCard, w.doc)).confidentiality = "strict"
        await db.commit()
    await grant_read(w, w.first, denied=["download"])
    assert await native_read(w, w.first)
    assert not await native_read(w, w.first, "download")
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == 1 and w.attempts == w.mail


async def test_native_assignment_read_and_no_new_org_object_policy_or_inbox(notice_world):
    w = notice_world
    await only_recipient(w, w.first)
    async with w.factory() as db:
        doc = await db.get(DocCard, w.doc)
        doc.confidentiality, doc.organization_id = "private", None
        db.add(DocApproval(company_id=w.cid, doc_id=w.doc, assignee_id=w.first))
        await db.commit()
        before = (await db.scalar(select(func.count()).select_from(ChatRoom).where(ChatRoom.company_id == w.cid)),
                  await db.scalar(select(func.count()).select_from(DocInboxItem).where(DocInboxItem.company_id == w.cid)))
    assert await native_read(w, w.first)
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == 1 and not w.chat and not w.push
    async with w.factory() as db:
        after = (await db.scalar(select(func.count()).select_from(ChatRoom).where(ChatRoom.company_id == w.cid)),
                 await db.scalar(select(func.count()).select_from(DocInboxItem).where(DocInboxItem.company_id == w.cid)))
        assert before == after == (0, 0)


async def test_smtp_failure_isolated_per_recipient_with_external_error_ledger(notice_world):
    w = notice_world
    async def fail_first(attempt):
        if len(w.attempts) == 1:
            raise RuntimeError("Synthetic one-recipient SMTP failure")
    w.on_mail = fail_first
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.attempts) == 2 and len(w.mail) == 1
    assert len(w.errors) == 1 and type(w.errors[0]) is RuntimeError
    assert str(w.errors[0]) == "Synthetic one-recipient SMTP failure"
    assert w.mail == w.attempts[1:]
    w.expected_notify_errors.extend(w.errors)
    w.errors.clear()


@pytest.mark.parametrize("state", ["active", "revoked", "expired"])
async def test_strict_superadmin_breakglass_no_use_or_audit_write(notice_world, state):
    w = notice_world
    await only_recipient(w, w.sa)
    now = datetime.now(timezone.utc)
    async with w.factory() as db:
        (await db.get(DocCard, w.doc)).confidentiality = "strict"
        access = DocBreakGlassAccess(company_id=w.cid, doc_id=w.doc, user_id=w.sa,
            reason="Synthetic private manual reason", permissions=["read"], use_count=7,
            created_at=now - timedelta(days=2), expires_at=now + timedelta(hours=1),
            last_used_at=now - timedelta(hours=1))
        if state == "revoked":
            access.revoked_at = now
        if state == "expired":
            access.expires_at = now - timedelta(hours=1)
        db.add(access)
        await db.commit()
        aid, last = access.id, access.last_used_at
        before = list(await db.scalars(select(AuditEvent.id).where(AuditEvent.company_id == w.cid)))
    assert await native_read(w, w.sa) == (state == "active")
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == int(state == "active") and w.attempts == w.mail
    async with w.factory() as db:
        access = await db.get(DocBreakGlassAccess, aid)
        assert access.use_count == 7 and access.last_used_at == last
        assert list(await db.scalars(select(AuditEvent.id).where(AuditEvent.company_id == w.cid))) == before
        assert not db.new and not db.dirty


@pytest.mark.parametrize("loss", ["member", "user", "role_product", "member_product", "doc", "tenant", "company", "foreign"])
async def test_missing_current_refs_tenant_and_native_product_loss_skip(notice_world, loss):
    w = notice_world
    await only_recipient(w, w.foreign if loss == "foreign" else w.first)
    async with w.factory() as db:
        if loss == "member":
            await db.delete(await db.get(UserCompany, (w.first, w.cid)))
        elif loss == "user":
            await db.delete(await db.get(User, w.first))
        elif loss == "role_product":
            (await db.get(CompanyRole, w.role)).modules = ["info"]
        elif loss == "member_product":
            member = await db.get(UserCompany, (w.first, w.cid))
            member.role_id, member.modules = None, ["info"]
        elif loss == "doc":
            await db.delete(await db.get(DocCard, w.doc))
        elif loss == "tenant":
            (await db.get(DocCard, w.doc)).company_id = w.other
        elif loss == "company":
            # Отсутствующая ссылка не заменяется slug/названием компании.
            pass
        await db.commit()
    await notify.dispatch_doc_notice(uuid4() if loss == "company" else w.cid, w.doc)
    assert w.mail == w.attempts == []


@pytest.mark.parametrize("state", ["active", "expired", "revoked"])
async def test_substitution_read_follows_current_native_rules(notice_world, state):
    w = notice_world
    await only_recipient(w, w.first)
    today = datetime.now(timezone.utc).date()
    async with w.factory() as db:
        doc = await db.get(DocCard, w.doc)
        doc.confidentiality, doc.signatory_id, doc.status = "private", w.author, "draft"
        db.add(UserSubstitution(company_id=w.cid, user_id=w.author, deputy_id=w.first,
            starts_on=today - timedelta(days=2), ends_on=today + timedelta(days=1),
            is_active=state != "revoked", created_by=w.admin))
        if state == "expired":
            next(row for row in db.new if isinstance(row, UserSubstitution)).ends_on = today - timedelta(days=1)
        await db.commit()
    assert await native_read(w, w.first) == (state == "active")
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert len(w.mail) == int(state == "active")


@pytest.mark.parametrize("first", ["revoke", "handoff"])
async def test_committed_revoke_before_check_suppresses_inflight_cannot_recall(notice_world, first):
    w = notice_world
    await only_recipient(w, w.first)
    async with w.factory() as db:
        (await db.get(DocCard, w.doc)).confidentiality = "private"
        await db.commit()
    await grant_read(w, w.first)
    async def revoke():
        async with w.factory() as db:
            await db.execute(delete(DocAccessGrant).where(DocAccessGrant.company_id == w.cid))
            await db.commit()
    if first == "revoke":
        await revoke()
        await notify.dispatch_doc_notice(w.cid, w.doc)
        assert not w.attempts
    else:
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(attempt):
            entered.set()
            await asyncio.wait_for(release.wait(), 5)
        w.on_mail = slow
        task = asyncio.create_task(notify.dispatch_doc_notice(w.cid, w.doc))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await revoke()
            release.set()
            await asyncio.wait_for(task, 5)
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert len(w.mail) == 1  # Уже передано: отзыва и exactly-once не обещаем.
    assert not await native_read(w, w.first)


@pytest.mark.parametrize("change", ["role", "member_product", "member", "user", "grant", "rule",
    "via_email", "category", "missing_rule", "admins_only", "audience", "email", "empty_email", "title"])
async def test_each_handoff_reopens_all_fresh_state_after_slow_first_smtp(notice_world, change):
    w = notice_world
    async with w.factory() as db:
        (await db.get(DocCard, w.doc)).confidentiality = "private"
        await db.commit()
    await grant_read(w, w.first)
    await grant_read(w, w.second)
    order = []
    async def slow(attempt):
        if order:
            return
        order.append(attempt[0][0])
        first_id = w.first if attempt[0] == [f"{w.first.hex}@example.invalid"] else w.second
        remaining = w.second if first_id == w.first else w.first
        async with w.factory() as writer:
            if change == "role":
                (await writer.get(CompanyRole, w.role)).modules = ["info"]
            elif change == "member_product":
                member = await writer.get(UserCompany, (remaining, w.cid))
                member.role_id, member.modules = None, ["info"]
            elif change == "member":
                await writer.delete(await writer.get(UserCompany, (remaining, w.cid)))
            elif change == "user":
                await writer.delete(await writer.get(User, remaining))
            elif change == "grant":
                await writer.execute(delete(DocAccessGrant).where(DocAccessGrant.company_id == w.cid,
                    DocAccessGrant.subject_id == remaining))
            elif change == "rule":
                (await writer.get(NotificationRule, w.rule)).enabled = False
            elif change == "via_email":
                (await writer.get(NotificationRule, w.rule)).via_email = False
            elif change == "category":
                (await writer.get(NotificationRule, w.rule)).category = "other"
            elif change == "missing_rule":
                await writer.delete(await writer.get(NotificationRule, w.rule))
            elif change == "admins_only":
                (await writer.get(Company, w.cid)).customization = {"system_notifications_admin_only": True}
            elif change == "audience":
                (await writer.get(NotificationRule, w.rule)).recipients = [str(first_id)]
            elif change == "email":
                (await writer.get(User, remaining)).email = "current-recipient@example.invalid"
            elif change == "empty_email":
                (await writer.get(User, remaining)).email = ""
            else:
                doc = await writer.get(DocCard, w.doc)
                doc.title, doc.reg_number = "CURRENT " + "Y" * 240, "SYN-NEW"
            await writer.commit()
        await asyncio.sleep(0)  # Ожидание транспорта между проверками получателей.
    w.on_mail = slow
    await notify.dispatch_doc_notice(w.cid, w.doc)
    assert w.attempts == w.mail
    assert len(w.mail) == (2 if change in ("email", "title") else 1)
    if change == "email":
        assert w.mail[1][0] == ["current-recipient@example.invalid"]
    if change == "title":
        assert w.mail[1][2] == f"{action_label('doc.register')}\nSYN-NEW\n{('CURRENT ' + 'Y' * 240)[:200]}"


@pytest.mark.parametrize("path", ["allow", "deny", "product_deny", "sql_error", "transport_error", "cancel"])
async def test_all_inherited_public_contexts_restored_on_every_path(notice_world, monkeypatch, path):
    w = notice_world
    await only_recipient(w, w.first)
    inherited_objects, inherited_org = ["synthetic-inherited"], uuid4()
    claims = {"sub": "synthetic-actor", "scp": "visit", "tv": 991}
    visit = w.other
    set_request_scope(inherited_objects)
    set_request_organization(inherited_org)
    async with w.factory() as db:
        if path == "deny":
            (await db.get(DocCard, w.doc)).confidentiality = "private"
        elif path == "product_deny":
            (await db.get(CompanyRole, w.role)).modules = ["info"]
        await db.commit()
    async def fail(attempt):
        raise RuntimeError("Synthetic SMTP error")
    async def cancel(attempt):
        raise asyncio.CancelledError()
    if path in ("transport_error", "cancel"):
        w.on_mail = fail if path == "transport_error" else cancel
    sql_attempts, sql_errors = [], []
    def sql_failure(conn, cursor, statement, parameters, context, executemany):
        if "doc_access_grants" in statement:
            sql_attempts.append(statement)
            error = RuntimeError("Synthetic SQL observation failure")
            sql_errors.append(error)
            raise error
    if path == "sql_error":
        event.listen(w.engine.sync_engine, "before_cursor_execute", sql_failure)
    try:
        with auth.native_claims_context(claims, visit):
            if path == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await notify.dispatch_doc_notice(w.cid, w.doc)
            else:
                await notify.dispatch_doc_notice(w.cid, w.doc)
            assert current_object_scope() is inherited_objects
            assert current_organization() == inherited_org
            assert auth.current_token_claims() is claims and auth.visit_company() == visit
    finally:
        if path == "sql_error":
            event.remove(w.engine.sync_engine, "before_cursor_execute", sql_failure)
    if path in ("transport_error", "cancel"):
        assert len(w.errors) == 1
        assert isinstance(w.errors[0], RuntimeError if path == "transport_error" else asyncio.CancelledError)
        if path == "transport_error":
            assert str(w.errors[0]) == "Synthetic SMTP error"
            w.expected_notify_errors.extend(w.errors)
        w.errors.clear()  # Cancellation не порождает warning; SQL/SMTP разрешены по identity.
    if path == "sql_error":
        assert len(sql_attempts) == len(sql_errors) == 1, "the native READ SQL failure must actually be reached"
        assert type(sql_errors[0]) is RuntimeError and str(sql_errors[0]) == "Synthetic SQL observation failure"
        w.expected_notify_errors.extend(sql_errors)
    assert len(w.mail) == int(path == "allow")


async def test_native_constraints_and_uuid_codec_are_not_relaxed(notice_world):
    w = notice_world
    async with w.factory() as db:
        assert type((await db.get(User, w.first)).id) is UUID
        doc = await db.get(DocCard, w.doc)
        assert isinstance(doc.id, UUID) and doc.company_id == w.cid
        rows = (await db.execute(text(
            "SELECT c.contype::text AS kind, c.convalidated, c.conrelid, c.confrelid "
            "FROM pg_constraint c WHERE c.conrelid IN "
            "('doc_cards'::regclass,'doc_kinds'::regclass,'doc_cases'::regclass,'user_companies'::regclass)"))).all()
        assert rows and all(row.convalidated for row in rows)
        expected = await db.scalar(text("SELECT 'doc_kinds'::regclass::oid"))
        assert any(row.kind == "f" and row.confrelid == expected for row in rows)
        assert any(row.kind == "u" for row in rows)
