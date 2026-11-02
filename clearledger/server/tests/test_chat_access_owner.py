"""M04-P3 goldens; execution belongs to ROOT through the frozen runner."""
import os

if os.environ.get("RUN_CHAT_ACCESS_OWNER_TESTS") != "1":
    raise RuntimeError("ROOT-approved chat access runner required")

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.models import AuditEvent, ChatParticipant, ChatRoom, User, UserCompany
from app.routers import chat_router
from app.services import (chat_access as owner, context_chats, project_work_context,
                          task_access, ticket_communications, work_links)

pytestmark = pytest.mark.asyncio(loop_scope="session")


def actor(**kwargs):
    return NS(**dict(dict(id=uuid.uuid4(), company_id=uuid.uuid4(), name="Тест",
                         is_superadmin=False, mail_only=False), **kwargs))


def room(cid, **kwargs):
    return NS(**dict(dict(id=uuid.uuid4(), company_id=cid, type="group", name="Тест",
                         is_active=True, scope_product=None, scope_ticket_id=None,
                         scope_task_id=None), **kwargs))


def session(value, participant=True):
    db = NS(get=AsyncMock(return_value=value), execute=AsyncMock(return_value=NS(
        scalar_one_or_none=lambda: uuid.uuid4() if participant else None)),
        add=Mock(), flush=AsyncMock(), commit=AsyncMock())
    return db


@pytest.mark.parametrize("case,status,trace", [
    ("missing", 404, ["get"]), ("inactive", 404, ["get"]),
    ("foreign", 404, ["get", "company"]),
    ("company-denied", 403, ["get", "company"]),
    ("ticket-denied", 404, ["get", "company", "ticket"]),
    ("task-denied", 403, ["get", "company", "task"]),
    ("not-participant", 404, ["get", "company", "participant"]),
    ("scoped", 404, ["get", "company", "participant", "scope"]),
])
async def test_negative_goldens_preserve_sql_before_denial(monkeypatch, case, status, trace):
    user = actor()
    r = room(user.company_id)
    events = []

    async def get(model, key):
        assert model is ChatRoom and key == r.id
        events.append("get")
        return None if case == "missing" else r

    async def company(who, db):
        assert who is user
        events.append("company")
        if case == "company-denied":
            raise HTTPException(403, "membership")
        return uuid.uuid4() if case == "foreign" else user.company_id

    async def execute(statement):
        events.append("participant")
        compiled = statement.compile()
        assert set(compiled.params.values()) == {r.id, user.id}
        assert "chat_participants.room_id =" in str(compiled)
        assert "chat_participants.user_id =" in str(compiled)
        return NS(scalar_one_or_none=lambda: None if case == "not-participant" else 1)

    async def scope(*args):
        events.append("scope")
        return "support"

    async def ticket(*args):
        events.append("ticket")
        raise HTTPException(404, "ticket")

    async def task(*args):
        events.append("task")
        raise HTTPException(403, "task product")

    r.is_active = case != "inactive"
    r.scope_ticket_id = uuid.uuid4() if case == "ticket-denied" else None
    r.scope_task_id = uuid.uuid4() if case == "task-denied" else None
    monkeypatch.setattr(ticket_communications, "assert_staff_room", ticket)
    monkeypatch.setattr(task_access, "assert_task_room", task)
    db = session(r)
    db.get, db.execute = AsyncMock(side_effect=get), AsyncMock(side_effect=execute)
    audit = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await owner.assert_participant(r.id, user, db, company_of=company,
                                       chat_scope=scope, audit_foreign=audit)
    assert error.value.status_code == status
    assert events == trace
    audit.assert_not_awaited()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("kind", ["direct", "ticket", "task", "ordinary"])
async def test_allow_keeps_subject_acl_and_scope_exemptions(monkeypatch, kind):
    user = actor()
    r = room(user.company_id, type="direct" if kind == "direct" else "group")
    r.scope_ticket_id = uuid.uuid4() if kind == "ticket" else None
    r.scope_task_id = uuid.uuid4() if kind == "task" else None
    db = session(r)
    company, scope, audit = AsyncMock(return_value=user.company_id), AsyncMock(return_value=None), AsyncMock()
    ticket, task = AsyncMock(), AsyncMock()
    monkeypatch.setattr(ticket_communications, "assert_staff_room", ticket)
    monkeypatch.setattr(task_access, "assert_task_room", task)
    assert await owner.assert_participant(r.id, user, db, company_of=company,
                                          chat_scope=scope, audit_foreign=audit) is r
    assert company.await_count == int(kind != "direct")
    assert scope.await_count == int(kind == "ordinary")
    assert ticket.await_count == int(kind == "ticket")
    assert task.await_count == int(kind == "task")
    audit.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_router_hooks_are_awaited_and_late_bound(monkeypatch):
    user = actor(is_superadmin=True)
    r = room(user.company_id)
    db = session(r, participant=False)
    company, scope, audit = AsyncMock(return_value=r.company_id), AsyncMock(return_value=None), AsyncMock()
    monkeypatch.setattr(chat_router, "_company_of", company)
    monkeypatch.setattr(chat_router, "_chat_scope", scope)
    monkeypatch.setattr(chat_router, "_audit_foreign_access", audit)
    assert await chat_router._assert_participant(r.id, user, db) is r
    company.assert_awaited_once_with(user, db)
    scope.assert_awaited_once_with(user, r.company_id, db)
    audit.assert_awaited_once_with(r, user, db)
    denied = AsyncMock(side_effect=HTTPException(403, "runtime scope"))
    monkeypatch.setattr(chat_router, "_chat_scope", denied)
    with pytest.raises(HTTPException) as error:
        await chat_router._assert_participant(r.id, user, db)
    assert error.value.status_code == 403
    assert audit.await_count == 1


async def test_default_owner_awaits_selected_company_principal(monkeypatch):
    from app import deps

    user = actor()
    selected = uuid.uuid4()
    r = room(selected)
    db = session(r)
    member = AsyncMock(return_value=selected)
    monkeypatch.setattr(deps, "assert_company_member", member)
    monkeypatch.setattr(owner, "chat_scope_of", AsyncMock(return_value=None))
    token = deps._active_company.set(str(selected))
    try:
        assert await owner.assert_participant(r.id, user, db) is r
        member.assert_awaited_once_with(str(selected), user, db)
        member.side_effect = HTTPException(403, "principal revoked")
        with pytest.raises(HTTPException) as error:
            await owner.assert_participant(r.id, user, db)
        assert error.value.status_code == 403
        assert db.execute.await_count == 1  # second denial precedes participant SQL
    finally:
        deps._active_company.reset(token)
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_superadmin_audit_is_shared_and_clearable_without_commit(monkeypatch):
    from app.services import notify

    user = actor(is_superadmin=True)
    r = room(user.company_id, type="direct", name=None)
    db = session(r, participant=False)
    notices = Mock()
    monkeypatch.setattr(notify, "dispatch_async", notices)
    assert chat_router._FOREIGN_SEEN is owner.FOREIGN_SEEN
    chat_router._FOREIGN_SEEN.clear()
    try:
        assert await owner.assert_participant(r.id, user, db) is r
        assert await chat_router._assert_participant(r.id, user, db) is r
        assert db.add.call_count == 1
        event = db.add.call_args.args[0]
        assert isinstance(event, AuditEvent)
        assert event.company_id == r.company_id and event.user_id == str(user.id)
        assert event.action == "chat.foreign_access"
        assert "личная переписка" in event.details and str(r.id) in event.details
        assert notices.call_count == 1
        chat_router._FOREIGN_SEEN.clear()
        await chat_router._assert_participant(r.id, user, db)
        assert db.add.call_count == notices.call_count == 2
        owner.FOREIGN_SEEN[(user.id, r.id)] -= timedelta(hours=2)
        await owner.assert_participant(r.id, user, db)
        assert db.add.call_count == notices.call_count == 3
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()
    finally:
        owner.FOREIGN_SEEN.clear()


async def test_router_audit_writer_remains_patchable(monkeypatch):
    user = actor(is_superadmin=True)
    r = room(user.company_id)
    writer = AsyncMock()
    monkeypatch.setattr(chat_router, "log_audit", writer)
    owner.FOREIGN_SEEN.clear()
    try:
        await chat_router._audit_foreign_access(r, user, session(r))
        writer.assert_awaited_once()
        assert writer.await_args.kwargs["action"] == "chat.foreign_access"
    finally:
        owner.FOREIGN_SEEN.clear()


@pytest.mark.parametrize("same", [False, True])
async def test_insider_uses_primary_company_async_without_membership(same):
    user = actor()
    cid = user.company_id if same else uuid.uuid4()
    assert await owner.is_insider(user, cid) is same
    assert await chat_router._is_insider(user, cid) is same


@pytest.mark.parametrize("cutoff", [None, datetime(2026, 10, 30, tzinfo=timezone.utc)])
async def test_history_nullable_and_query_is_exact(cutoff):
    user = actor()
    rid = uuid.uuid4()
    db = session(None)
    db.execute.return_value = NS(scalar_one_or_none=lambda: cutoff)
    assert await owner.history_from(rid, user, db) == cutoff
    assert await chat_router._history_from(rid, user, db) == cutoff
    statement = db.execute.await_args.args[0].compile()
    assert set(statement.params.values()) == {rid, user.id}
    assert "chat_participants.history_from" in str(statement)
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("case,status", [("partner", 403), ("mail-only", 400),
                                         ("foreign-primary", 400), ("no-membership", 400),
                                         ("valid", None)])
async def test_context_primary_membership_mail_only_and_flush_goldens(monkeypatch, case, status):
    user = actor()
    cid = uuid.uuid4() if case == "partner" else user.company_id
    person = actor(company_id=uuid.uuid4() if case == "foreign-primary" else cid,
                   mail_only=case == "mail-only")
    db = session(None)
    db.scalar = AsyncMock(return_value=None)
    db.get.side_effect = [person, None if case == "no-membership" else object()]
    monkeypatch.setattr(context_chats.work_contexts, "resolve", AsyncMock(return_value={
        "title": "Тест", "application": "projects"}))
    monkeypatch.setattr(chat_router, "_is_insider", AsyncMock(side_effect=AssertionError("old binding")))
    async def flush():
        for call in db.add.call_args_list:
            if isinstance(call.args[0], ChatRoom):
                call.args[0].id = uuid.uuid4()
    db.flush.side_effect = flush
    if status:
        with pytest.raises(HTTPException) as error:
            await context_chats.ensure_room(db, cid, user, "site:test", participant_ids=[person.id])
        assert error.value.status_code == status
        assert db.execute.await_count == int(case != "partner")
        db.add.assert_not_called()
        db.flush.assert_not_awaited()
    else:
        result = await context_chats.ensure_room(db, cid, user, "site:test", participant_ids=[person.id])
        assert result.company_id == cid and result.scope_ref == "site:test"
        parts = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ChatParticipant)]
        assert {(p.user_id, p.role) for p in parts} == {(user.id, "owner"), (person.id, "member")}
        assert db.flush.await_count == 2
        assert db.execute.await_count == 1
    db.commit.assert_not_awaited()


async def test_existing_context_uses_owner_and_keeps_denial_before_writes(monkeypatch):
    user = actor()
    r = room(user.company_id)
    db = session(r, participant=False)
    db.scalar = AsyncMock(return_value=r)
    monkeypatch.setattr(context_chats.work_contexts, "resolve", AsyncMock(return_value={"title": "Тест"}))
    monkeypatch.setattr(chat_router, "_assert_participant", AsyncMock(side_effect=AssertionError("old binding")))
    with pytest.raises(HTTPException) as error:
        await context_chats.ensure_room(db, user.company_id, user, "site:test")
    assert error.value.status_code == 404
    assert db.execute.await_count == 2  # advisory lock, then participation SQL
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_project_suggestions_require_primary_company_and_non_mail_user(monkeypatch):
    user = actor()
    people = [actor(company_id=user.company_id), actor(company_id=user.company_id, mail_only=True), actor()]
    site = NS(id=uuid.uuid4(), owner_user_id=None, project_no=None, title="Тест",
              city="Тест", location_id=None)
    db = session(None)
    db.scalar = AsyncMock(return_value=site)
    db.scalars = AsyncMock(side_effect=[NS(all=lambda: [p.id for p in people]), NS(all=lambda: people)])
    monkeypatch.setattr(project_work_context.project_scenarios, "scenario", lambda _: None)
    monkeypatch.setattr(chat_router, "_is_insider", AsyncMock(side_effect=AssertionError("old binding")))
    result = await project_work_context.ProjectsContext().resolve(db, user.company_id, user, str(site.id))
    assert result["suggested_people"] == [{"id": str(people[0].id), "name": people[0].name}]
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("case,allowed", [("null", True), ("before", False),
                                         ("equal", True), ("after", True),
                                         ("nonparticipant", False), ("deleted", False)])
async def test_origin_keeps_participation_deletion_and_history_cutoff(monkeypatch, case, allowed):
    user = actor()
    moment = datetime(2026, 10, 30, tzinfo=timezone.utc)
    message = NS(id=uuid.uuid4(), room_id=uuid.uuid4(), created_at=moment, deleted_at=moment if case == "deleted" else None)
    cutoff = None if case == "null" else moment + timedelta(seconds={"before": 1, "after": -1}.get(case, 0))
    db = session(message)
    db.scalar = AsyncMock(return_value=None if case == "nonparticipant" else uuid.uuid4())
    db.execute.return_value = NS(scalar_one_or_none=lambda: cutoff)
    monkeypatch.setattr(work_links, "readable_entity", AsyncMock(return_value=NS(source_ref=f"chat:{message.id}")))
    monkeypatch.setattr(chat_router, "_history_from", AsyncMock(side_effect=AssertionError("old binding")))
    result = await work_links.origin(db, user.company_id, user, "doc", uuid.uuid4())
    assert result == ({"room_id": str(message.room_id), "message_id": str(message.id)} if allowed else None)
    assert db.execute.await_count == int(case not in ("deleted", "nonparticipant"))
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
