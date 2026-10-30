"""Real PG/ASGI characterization for five local imports; run only via ROOT gate."""
import os

if os.environ.get("RUN_TASK_ACL_IMPORT_BOUNDARY_TESTS") != "1":
    raise RuntimeError("ROOT-approved task ACL runner required")

import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import (ChatMessage, ChatParticipant, ChatRoom, DocCard, DocKind,
                        DocRelation, Task, TaskEvent, TaskParticipant, TaskWatcher)
from app.routers import tasks_router
from app.services import management_local, task_access, work_links
from tests.test_management_api import headers, management_data  # noqa: F401
from tests.test_task_projection_access import actors, make  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def snapshot(db):
    """Full stored rows, including timestamps, not merely result lengths."""
    tables = (Task, TaskEvent, TaskParticipant, TaskWatcher, DocCard, DocRelation,
              ChatRoom, ChatParticipant, ChatMessage)
    return {model.__tablename__: sorted(
        [repr(tuple(row)) for row in (await db.execute(select(model.__table__))).all()])
        for model in tables}


@pytest.mark.parametrize("role", ["reader", "admin", "superadmin"])
async def test_management_native_acl_and_read_only(management_data, db, role):
    d = management_data
    if role == "superadmin":
        d[role] = d["admin"]
        d[role].is_superadmin = True
        await db.commit()
    expected = {"public", "private-author", "private-assignee",
                "private-watcher", "private-participant"}
    if role != "reader":
        expected.add("private-hidden")
    before = await snapshot(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/management/overview", headers=headers(d, user=role),
                                    params={"kind": "tasks"})
    assert response.status_code == 200, response.text
    assert response.json()["sources"][0]["state"] == "ok", response.text
    assert {item["title"] for item in response.json()["items"]} == expected
    assert response.headers["cache-control"] == "no-store"
    assert await snapshot(db) == before


@pytest.mark.parametrize("visibility,role,allowed", [
    ("company", "stranger", True),
    ("private", "author", True), ("private", "assignee", True),
    ("private", "watcher", True), ("private", "participant", True),
    ("private", "stranger", False), ("private", "admin", True),
    ("private", "superadmin", True),
    ("personal", "author", False), ("personal", "admin", False),
    ("personal", "superadmin", False),
])
async def test_work_union_and_single_read_preserve_task_doc_acl(actors, db, visibility, role, allowed):
    companies, users, _, _ = actors
    task = await make(db, actors, visibility, code=False)
    cid, other_cid = (company.id for company in companies)
    ref = f"boundary:{uuid.uuid4()}"
    task.subject_ref = ref
    foreign = Task(company_id=other_cid, title="Тест · Чужая компания",
                   author_id=users["author"].id, visibility="company", subject_ref=ref)
    kind = DocKind(company_id=cid, code="boundary-" + uuid.uuid4().hex[:20], name="Тест · Вид")
    db.add_all([kind, foreign])
    await db.flush()
    public = DocCard(company_id=cid, kind_id=kind.id, title="Тест · Открытый документ",
                     confidentiality="company", author_id=users["author"].id, subject_ref=ref)
    strict = DocCard(company_id=cid, kind_id=kind.id, title="Тест · Закрытый документ",
                     confidentiality="strict", author_id=users["author"].id, subject_ref=ref)
    db.add_all([public, strict])
    await db.commit()
    user = users[role]
    before = await snapshot(db)
    query = await work_links.visible_work(db, cid, user, ref=ref)
    result = {(row.kind, row.id) for row in (await db.execute(select(query))).all()}
    expected = {("doc", public.id)}
    if role == "author":
        expected.add(("doc", strict.id))
    if allowed:
        expected.add(("task", task.id))
    assert result == expected
    assert (await work_links.readable_entity(db, cid, user, "doc", public.id)).id == public.id
    for entity_kind, entity_id, permitted in [
        ("task", task.id, allowed), ("task", foreign.id, False),
        ("task", uuid.uuid4(), False), ("doc", strict.id, role == "author"),
    ]:
        if permitted:
            assert (await work_links.readable_entity(db, cid, user, entity_kind, entity_id)).id == entity_id
        else:
            with pytest.raises(HTTPException) as caught:
                await work_links.readable_entity(db, cid, user, entity_kind, entity_id)
            # Strict document policy retains its own 403; task misses stay 404.
            assert caught.value.status_code == (403 if entity_kind == "doc" else 404)
    assert await snapshot(db) == before


async def test_readable_task_retains_edit_actor_guard(actors, db):
    task = await make(db, actors, "private", code=False)
    user = actors[1]["watcher"]
    before = await snapshot(db)
    assert await work_links.readable_entity(db, task.company_id, user, "task", task.id) is task
    with pytest.raises(HTTPException) as caught:
        await work_links.readable_entity(db, task.company_id, user, "task", task.id, edit=True)
    assert caught.value.status_code == 403
    assert await work_links.readable_entity(
        db, task.company_id, actors[1]["author"], "task", task.id, edit=True) is task
    assert await snapshot(db) == before


async def test_owner_identity_old_reexports_and_live_lexical_bindings(management_data, db, monkeypatch):
    """Poison only the three old reexports; execute all five new local bindings."""
    d = management_data
    for name in ("is_admin", "visible_to", "can_view_task"):
        assert getattr(tasks_router, "_" + name) is getattr(task_access, name)
    seen = {"is_admin": 0, "visible_to": 0, "can_view_task": 0}
    original_admin, original_visible, original_can = (
        task_access.is_admin, task_access.visible_to, task_access.can_view_task)

    async def admin(*args, **kwargs):
        seen["is_admin"] += 1
        return await original_admin(*args, **kwargs)

    def visible(*args, **kwargs):
        seen["visible_to"] += 1
        return original_visible(*args, **kwargs)

    async def can(*args, **kwargs):
        seen["can_view_task"] += 1
        return await original_can(*args, **kwargs)

    def old_path(*args, **kwargs):
        raise AssertionError("service read used an obsolete task ACL reexport")

    monkeypatch.setattr(task_access, "is_admin", admin)
    monkeypatch.setattr(task_access, "visible_to", visible)
    monkeypatch.setattr(task_access, "can_view_task", can)
    for name in seen:
        monkeypatch.setattr(tasks_router, "_" + name, old_path)
    before = await snapshot(db)
    rows, truncated = await management_local.read_local(
        db, d["reader"], d["cid"], "tasks", query="", date_from=None, date_to=None, limit=100)
    assert not truncated and len(rows) == 5
    assert seen == {"is_admin": 1, "visible_to": 1, "can_view_task": 0}
    union = await work_links.visible_work(db, d["cid"], d["reader"])
    assert len((await db.execute(select(union))).all()) == 5
    assert seen == {"is_admin": 2, "visible_to": 2, "can_view_task": 0}
    task = d["tasks"]["public"]
    assert await work_links.readable_entity(db, d["cid"], d["reader"], "task", task.id) is task
    assert seen == {"is_admin": 3, "visible_to": 3, "can_view_task": 1}
    assert await snapshot(db) == before
