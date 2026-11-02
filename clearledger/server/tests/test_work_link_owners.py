"""Fixed work/graph/edit goldens on ROOT-owned SQL; no standalone ACL grants."""
import os
if os.environ.get("RUN_WORK_LINK_OWNERS_TESTS") != "1":
    raise RuntimeError("ROOT-approved work link owners gate required")

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import InvalidRequestError

from app.auth import create_access_token
from app.main import app
from app.models import (AuditEvent, ChatMessage, ChatParticipant, ChatRoom, Department,
    DocAccessGrant, DocCard, DocKind, DocRelation, ServiceLocation, Task, TaskEvent,
    TaskParticipant, TaskWatcher, User, UserCompany)
from app.routers import tasks_router
from app.services import doc_subject_links, oversight, task_access, task_queries, work_links
from tests.test_task_projection_access import actors  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")
REF = "site:work-link-fixed"
TIDS = {name: uuid.UUID(f"b6100000-0000-4000-8000-{n:012x}") for n, name in enumerate(
    ("public", "private", "watched", "unassigned", "personal", "foreign", "other", "prefix", "object"), 1)}
DIDS = {name: uuid.UUID(f"d6100000-0000-4000-8000-{n:012x}") for n, name in enumerate(
    ("direct", "graph", "dual", "wrong-edge", "hidden", "foreign", "object-direct", "object-graph", "prefix", "other"), 1)}


@pytest.fixture
async def world(actors, db):
    companies, users, clients, _ = actors
    cid, other_cid = [c.id for c in companies]
    manager = User(company_id=cid, name="P6 manager", email=f"p6-{uuid.uuid4().hex}@example.test",
                   password_hash="!synthetic", role="user", task_notify=[])
    db.add(manager)
    await db.flush()
    parent = Department(company_id=cid, name="P6 parent", head_user_id=manager.id)
    db.add(parent)
    await db.flush()
    child = Department(company_id=cid, name="P6 child", parent_id=parent.id)
    db.add(child)
    await db.flush()
    db.add(UserCompany(user_id=manager.id, company_id=cid, role="user", modules=["docs"], department_id=parent.id))
    member = await db.get(UserCompany, (users["assignee"].id, cid))
    member.department_id = child.id
    users["manager"] = manager
    location = ServiceLocation(id="p6-" + uuid.uuid4().hex[:24], company_id=cid,
                               code="P6", name="P6 synthetic object")
    kinds = [DocKind(company_id=c.id, code="p6", name="P6 synthetic kind") for c in companies]
    db.add_all([location, *kinds])
    await db.flush()
    tasks = {}
    for name, visibility, company, assignee, subject in [
        ("public", "company", cid, users["assignee"].id, REF),
        ("private", "private", cid, users["assignee"].id, REF),
        ("watched", "private", cid, users["assignee"].id, REF),
        ("unassigned", "company", cid, None, None),
        ("personal", "personal", cid, users["assignee"].id, REF),
        ("foreign", "company", other_cid, users["assignee"].id, REF),
        ("other", "company", cid, None, "other:x"),
        ("prefix", "company", cid, None, "site:else"),
        ("object", "company", cid, None, f"object:{location.id}"),
    ]:
        row = Task(id=TIDS[name], company_id=company, title="P6 task " + name, visibility=visibility,
                   author_id=users["author"].id, assignee_id=assignee, subject_ref=subject,
                   stage_code="new", object_id=location.id if name == "public" else None)
        db.add(row)
        tasks[name] = row
    docs = {}
    for name in DIDS:
        foreign = name == "foreign"
        row = DocCard(id=DIDS[name], company_id=other_cid if foreign else cid,
            kind_id=kinds[int(foreign)].id, title="P6 doc " + name,
            author_id=users["author"].id, confidentiality="strict" if name == "hidden" else "company",
            subject_ref=REF if name in ("direct", "foreign") else "other:x" if name == "other" else None,
            object_id=location.id if name == "object-direct" else None)
        db.add(row)
        docs[name] = row
    await db.flush()
    db.add_all([TaskWatcher(task_id=TIDS["watched"], user_id=users[role].id) for role in ("watcher", "manager")])
    db.add(TaskParticipant(task_id=TIDS["watched"], user_id=users["participant"].id))
    for name, kind, ref, company in [
        # One canonical subject per company; direct also matches through graph.
        ("direct", "related", REF, cid),
        ("graph", "related", REF, cid), ("graph", "basis", REF, cid),
        ("dual", "related", REF, cid), ("hidden", "related", REF, cid),
        ("wrong-edge", "related", REF, other_cid), ("foreign", "related", REF, cid),
        ("graph", "object", f"object:{location.id}", cid),
        ("object-graph", "object", f"object:{location.id}", cid),
        ("prefix", "related", "site:else", cid),
    ]:
        db.add(DocRelation(company_id=company, doc_id=DIDS[name], kind=kind, target_ref=ref))
    for name in DIDS:
        if name != "foreign":
            db.add(DocRelation(company_id=cid, doc_id=DIDS[name], kind="outer", target_ref="noise:x"))
    await db.commit()
    yield NS(cid=cid, other_cid=other_cid, users=users, tasks=tasks, docs=docs,
             location=location, parent=parent, clients=clients)
    await db.execute(delete(DocCard).where(DocCard.id.in_(DIDS.values())))
    await db.execute(delete(Task).where(Task.id.in_(TIDS.values())))
    await db.commit()


async def snapshot(db):
    return {model.__tablename__: sorted(repr(tuple(row)) for row in
            (await db.execute(select(model.__table__))).all()) for model in (
                Task, TaskEvent, TaskWatcher, TaskParticipant, DocCard, DocRelation,
                DocAccessGrant, AuditEvent, Department, UserCompany, ChatRoom, ChatParticipant, ChatMessage)}


def auth(w, role):
    user = w.users[role]
    return {"Authorization": "Bearer " + create_access_token(str(user.id), user.email), "X-Company-Id": str(w.cid)}


async def union_rows(w, db, **kwargs):
    query = await work_links.visible_work(db, w.cid, w.users["watcher"], **kwargs)
    rows = (await db.execute(select(query).order_by(query.c.kind, query.c.id))).all()
    ids = [(row.kind, row.id) for row in rows]
    assert len(ids) == len(set(ids)), "graph multiplicity must not duplicate work or counts"
    return set(ids), query


@pytest.mark.parametrize("mode", ["all", "ref", "object", "both", "unlinked", "absent"])
async def test_union_fixed_ids_tenant_graph_acl_and_population(world, db, mode):
    w = world
    before = await snapshot(db)
    options = {"ref": {"ref": REF}, "object": {"object_id": w.location.id},
               "both": {"ref": REF, "object_id": w.location.id}, "unlinked": {"unlinked_prefix": "site"},
               "absent": {"ref": "site:absent"}}.get(mode, {})
    docs, tasks = {
        "all": ({"direct", "graph", "dual", "wrong-edge", "object-direct", "object-graph", "prefix", "other"},
                {"public", "watched", "unassigned", "other", "prefix", "object"}),
        "ref": ({"direct", "graph", "dual"}, {"public", "watched"}),
        "object": ({"graph", "object-direct", "object-graph"}, {"public", "object"}),
        "both": ({"graph"}, {"public"}),
        "unlinked": ({"wrong-edge", "object-direct", "object-graph", "other"}, {"unassigned", "other", "object"}),
        "absent": (set(), set()),
    }[mode]
    actual, query = await union_rows(w, db, **options)
    expected = {("doc", DIDS[k]) for k in docs} | {("task", TIDS[k]) for k in tasks}
    assert actual == expected
    assert await db.scalar(select(func.count()).select_from(query)) == len(expected)
    assert await snapshot(db) == before


async def test_shared_predicate_profiles_compile_and_fixed_rows(world, db):
    from app.services.doc_access import _readable_doc_clause
    w = world
    acl = await _readable_doc_clause(db, w.cid, w.users["watcher"])
    ordinary = select(DocCard.id).where(DocCard.company_id == w.cid, acl,
        doc_subject_links.subject_documents_clause(w.cid, REF))
    explicit = select(DocCard.id).where(DocCard.company_id == w.cid, acl,
        work_links.subject_clause(DocCard, w.cid, REF))
    dialect = postgresql.dialect()
    a, b = ordinary.compile(dialect=dialect), explicit.compile(dialect=dialect)
    assert str(a) == str(b) and a.params == b.params
    expected = {DIDS["direct"], DIDS["graph"], DIDS["dual"]}
    assert set((await db.scalars(ordinary)).all()) == set((await db.scalars(explicit)).all()) == expected
    outer = select(DocCard.id).select_from(DocCard, DocRelation).where(
        DocRelation.doc_id == DocCard.id, DocRelation.kind == "outer", DocCard.company_id == w.cid, acl,
        work_links.subject_clause(DocCard, w.cid, REF)).distinct()
    assert "FROM doc_relations" in str(outer.compile(dialect=dialect))
    assert set((await db.scalars(outer)).all()) == expected
    joined = select(DocCard.id).join(DocRelation, DocRelation.doc_id == DocCard.id).where(
        DocRelation.kind == "outer", DocCard.company_id == w.cid, acl,
        work_links.subject_clause(DocCard, w.cid, REF)).distinct()
    joined.compile(dialect=dialect)
    assert set((await db.scalars(joined)).all()) == expected
    # Default R2 profile remains auto-correlation, rather than silently acquiring
    # work-links' explicit/multi-level correlation construction profile.
    auto_outer = select(DocCard.id).select_from(DocCard, DocRelation).where(
        DocRelation.doc_id == DocCard.id, doc_subject_links.subject_documents_clause(w.cid, REF))
    with pytest.raises(InvalidRequestError, match="auto-correlation"):
        auto_outer.compile(dialect=dialect)
    nested = select(DocCard.id).where(DocCard.company_id == w.cid, acl,
        select(literal(1)).where(work_links.subject_clause(DocCard, w.cid, REF)).correlate(DocCard).exists())
    nested.compile(dialect=dialect)
    assert set((await db.scalars(nested)).all()) == expected


@pytest.mark.parametrize("task,role,status", [
    ("public", "author", 200), ("public", "assignee", 200), ("public", "stranger", 403),
    ("public", "admin", 200), ("public", "superadmin", 200), ("public", "manager", 200),
    ("private", "manager", 404), ("private", "author", 200), ("private", "admin", 200),
    ("watched", "manager", 200), ("watched", "watcher", 403), ("watched", "participant", 403),
    ("unassigned", "manager", 200), ("unassigned", "stranger", 403),
    ("personal", "author", 200), ("personal", "assignee", 404),
    ("personal", "admin", 404), ("personal", "superadmin", 404), ("personal", "manager", 404),
    ("foreign", "author", 404),
])
async def test_native_direct_actor_and_worklink_edit_outputs(world, db, task, role, status):
    w, row, user = world, world.tasks[task], world.users[role]
    before = await snapshot(db)
    assert await task_access.can_edit_task(db, w.cid, user, row) is (status == 200)
    assert await tasks_router._can_edit_task(db, w.cid, user, row) is (status == 200)
    for guard in (task_access.assert_actor, tasks_router._assert_actor):
        if status == 200:
            await guard(db, w.cid, user, row)
        else:
            with pytest.raises(HTTPException) as caught:
                await guard(db, w.cid, user, row)
            assert caught.value.status_code == status
            assert caught.value.detail == ("Задача не найдена" if status == 404 else "Задача не ваша")
    link_status = 404 if task == "personal" else status
    if link_status == 200:
        assert await work_links.readable_entity(db, w.cid, user, "task", row.id, edit=True) is row
    else:
        with pytest.raises(HTTPException) as caught:
            await work_links.readable_entity(db, w.cid, user, "task", row.id, edit=True)
        assert caught.value.status_code == link_status
        assert caught.value.detail == ("Работа не найдена" if link_status == 404 else "Задача не ваша")
    # An unchanged structural field still requires the native edit authority,
    # while causing no task/event/audit mutation and retaining caller commits.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{row.id}/action", headers=auth(w, role),
                                    json={"company_id": str(w.cid), "title": row.title})
    assert response.status_code == status, response.text
    assert await snapshot(db) == before


@pytest.mark.parametrize("revoke", ["membership", "modules"])
async def test_current_membership_oversight_and_caller_guards(world, db, revoke):
    w = world
    manager, row = w.users["manager"], w.tasks["public"]
    assert await task_access.can_edit_task(db, w.cid, manager, row)
    w.parent.head_user_id = None
    await db.commit()
    assert not await task_access.can_edit_task(db, w.cid, manager, row)
    w.parent.head_user_id = manager.id
    await db.commit()
    assert await task_access.can_edit_task(db, w.cid, manager, row)
    author = w.users["author"]
    member = await db.get(UserCompany, (author.id, w.cid))
    if revoke == "membership":
        await db.delete(member)
    else:
        member.modules = ["pulse"]
    await db.commit()
    before = await snapshot(db)
    # These are subordinate guards, not membership/product authorities.
    assert await task_access.can_edit_task(db, w.cid, author, row)
    assert await work_links.readable_entity(db, w.cid, author, "task", row.id, edit=True) is row
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{row.id}/action", headers=auth(w, "author"),
                                    json={"company_id": str(w.cid), "title": row.title})
    assert response.status_code == 403, response.text
    assert await snapshot(db) == before


async def test_direct_worklink_bindings_and_unknown_kind_stay_compatible(world, db, monkeypatch):
    w = world
    before = await snapshot(db)
    with monkeypatch.context() as patch:
        patch.setattr(tasks_router, "_assert_actor", AsyncMock(side_effect=AssertionError("obsolete actor binding")))
        patch.setattr(tasks_router, "_not_personal", Mock(side_effect=AssertionError("obsolete population binding")))
        assert await work_links.readable_entity(db, w.cid, w.users["author"], "unknown", TIDS["public"], edit=True) is w.tasks["public"]
        actual, _ = await union_rows(w, db, ref=REF)
        assert actual == {("doc", DIDS[k]) for k in ("direct", "graph", "dual")} | {("task", TIDS[k]) for k in ("public", "watched")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/work-contexts/work/unknown/{TIDS['public']}/origin",
                                    headers=auth(w, "author"), params={"company_id": str(w.cid)})
    assert response.status_code == 400 and response.json() == {"detail": "Неизвестный вид работы"}
    assert await snapshot(db) == before


async def test_document_link_does_not_add_read_or_edit_authority(world, db):
    w, user = world, world.users["watcher"]
    assert await work_links.readable_entity(db, w.cid, user, "doc", DIDS["direct"]) is w.docs["direct"]
    with pytest.raises(HTTPException) as caught:
        await work_links.readable_entity(db, w.cid, user, "doc", DIDS["direct"], edit=True)
    assert caught.value.status_code == 403
    db.add(DocAccessGrant(company_id=w.cid, scope_type="doc", scope_id=DIDS["direct"],
        subject_type="user", subject_id=user.id, permissions=[], denied_permissions=["read"]))
    await db.commit()
    before = await snapshot(db)
    actual, _ = await union_rows(w, db, ref=REF)
    assert actual == {("doc", DIDS[k]) for k in ("graph", "dual")} | {("task", TIDS[k]) for k in ("public", "watched")}
    with pytest.raises(HTTPException) as caught:
        await work_links.readable_entity(db, w.cid, user, "doc", DIDS["direct"])
    assert caught.value.status_code == 403 and caught.value.detail == "Документ закрыт"
    assert await snapshot(db) == before


async def test_helper_reads_do_not_flush_commit_audit_or_send(world, db, monkeypatch, pytestconfig):
    w = world
    before = await snapshot(db)
    boundary = pytestconfig._work_link_owners_boundary
    sent = len(boundary.capture)
    with monkeypatch.context() as patch:
        commit, flush = AsyncMock(side_effect=AssertionError("helper committed")), AsyncMock(side_effect=AssertionError("helper flushed"))
        patch.setattr(db, "commit", commit)
        patch.setattr(db, "flush", flush)
        await task_access.assert_actor(db, w.cid, w.users["author"], w.tasks["public"])
        await work_links.readable_entity(db, w.cid, w.users["author"], "task", TIDS["public"], edit=True)
        await union_rows(w, db, ref=REF)
        commit.assert_not_awaited()
        flush.assert_not_awaited()
    assert len(boundary.capture) == sent
    assert await snapshot(db) == before


@pytest.mark.parametrize("deny_view", [False, True])
async def test_native_actor_hooks_are_late_bound_falsey_and_view_first(monkeypatch, deny_view):
    db, cid, user, row = NS(), uuid.uuid4(), NS(id=uuid.uuid4()), NS()
    calls = []
    class View:
        def __bool__(self): return False
        async def __call__(self, *args):
            calls.append("view")
            if deny_view: raise HTTPException(404, "old view")
    class Edit:
        def __bool__(self): return False
        async def __call__(self, *args):
            calls.append("edit")
            return True
    monkeypatch.setattr(tasks_router, "_assert_view_task", View())
    monkeypatch.setattr(tasks_router, "_can_edit_task", Edit())
    if deny_view:
        with pytest.raises(HTTPException) as caught:
            await tasks_router._assert_actor(db, cid, user, row)
        assert caught.value.status_code == 404 and calls == ["view"]
    else:
        await tasks_router._assert_actor(db, cid, user, row)
        assert calls == ["view", "edit"]


async def test_native_view_admin_hooks_preserve_short_circuit_and_repeated_view(monkeypatch):
    cid = uuid.uuid4()
    user = NS(id=uuid.uuid4())
    row = NS(visibility="company", author_id=uuid.uuid4(), assignee_id=uuid.uuid4())
    view, admin = AsyncMock(return_value=False), AsyncMock(return_value=True)
    class Falsey:
        def __init__(self, call): self.call = call
        def __bool__(self): return False
        async def __call__(self, *args, **kwargs): return await self.call(*args, **kwargs)
    monkeypatch.setattr(tasks_router, "_can_view_task", Falsey(view))
    monkeypatch.setattr(tasks_router, "_is_admin", Falsey(admin))
    assert not await tasks_router._can_edit_task(NS(), cid, user, row)
    admin.assert_not_awaited()
    view.return_value = True
    assert await tasks_router._can_edit_task(NS(), cid, user, row)
    admin.assert_awaited_once()
    # Default assert_actor keeps its own view query and the can_edit view query.
    v, a = AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr(task_access, "can_view_task", v)
    monkeypatch.setattr(task_access, "is_admin", a)
    await task_access.assert_actor(NS(), cid, user, row)
    assert v.await_count == 2 and a.await_count == 1


@pytest.mark.parametrize("cutoff", [None, "before", "equal", "after"])
async def test_source_origin_history_and_scope_stay_caller_owned(world, db, cutoff):
    w, user = world, world.users["watcher"]
    at = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    since = None if cutoff is None else at + timedelta(seconds={"before": 1, "equal": 0, "after": -1}[cutoff])
    room = ChatRoom(company_id=w.cid, type="group", name="P6 synthetic origin", is_active=True)
    db.add(room)
    await db.flush()
    message = ChatMessage(room_id=room.id, user_id=user.id, user_name=user.name, content="P6 synthetic origin", created_at=at)
    db.add_all([message, ChatParticipant(room_id=room.id, user_id=user.id, history_from=since)])
    await db.flush()
    w.docs["direct"].source_ref = f"chat:{message.id}"
    db.add(TaskEvent(task_id=TIDS["watched"], kind="created", note=f"chat:{message.id}"))
    await db.commit()
    before = await snapshot(db)
    expected = None if cutoff == "before" else {"room_id": str(room.id), "message_id": str(message.id)}
    assert await work_links.origin(db, w.cid, user, "doc", DIDS["direct"]) == expected
    assert await work_links.origin(db, w.cid, user, "task", TIDS["watched"]) == expected
    assert await snapshot(db) == before
