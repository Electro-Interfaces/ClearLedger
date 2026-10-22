"""Регрессии границы поручений на синтетических компаниях и настоящих JWT."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.auth import create_access_token
from app.main import app
from app.models import (Company, SourceFile, Task, TaskAttachment, TaskEvent, TaskLink,
                        TaskParticipant, TaskWatcher, User, UserCompany)
from tests.helpers import drain_application_tasks

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def actors(db, monkeypatch):
    from app.services import notify, task_mail

    async def quiet(*args, **kwargs):
        pass
    monkeypatch.setattr(notify, "tell", quiet)
    monkeypatch.setattr(task_mail, "send_notice_async", lambda *args: None)
    companies = [Company(name="Тест · Граница поручений", profile_id="energy",
                         slug=f"track-boundary-{uuid.uuid4().hex}") for _ in range(2)]
    db.add_all(companies)
    await db.flush()
    roles = ("author", "assignee", "watcher", "participant", "stranger", "admin", "superadmin")
    users = {role: User(name=f"Тест · {role}", email=f"track-{uuid.uuid4().hex}@example.test",
                       password_hash="!synthetic", role="user", task_notify=[],
                       is_superadmin=role == "superadmin") for role in roles}
    db.add_all(users.values())
    await db.flush()
    for role, user in users.items():
        db.add(UserCompany(user_id=user.id, company_id=companies[0].id,
                           role="admin" if role == "admin" else "user"))
    await db.commit()
    clients = {role: AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
               headers={"Authorization": f"Bearer {create_access_token(str(u.id), u.email)}"})
               for role, u in users.items()}
    yield companies, users, clients
    await drain_application_tasks()
    for client in clients.values():
        await client.aclose()


async def make(actors, **fields):
    companies, _, clients = actors
    response = await clients["author"].post("/api/tasks", json={
        "company_id": str(companies[0].id), "title": "Тест · Доступная работа", **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def card(actors, task, role="stranger"):
    companies, _, clients = actors
    return await clients[role].get(f"/api/tasks/{task['id']}",
                                   params={"company_id": str(companies[0].id)})


async def test_links_both_directions_and_every_kind(actors, db):
    companies, _, _ = actors
    visible = await make(actors)
    secret = await make(actors, title="Скрытое поручение с особым заголовком", visibility="private")
    links = [TaskLink(task_id=uuid.UUID(a["id"]), related_task_id=uuid.UUID(b["id"]), kind=kind)
             for kind in ("subtask", "blocks", "relates", "duplicates")
             for a, b in ((visible, secret), (secret, visible))]
    db.add_all(links)
    await db.commit()
    assert (await card(actors, secret)).status_code == 404
    response = await card(actors, visible)
    assert response.status_code == 200, response.text
    assert response.json()["links"] == []
    assert response.json()["subtasks"] == {"total": 0, "open": 0}
    assert secret["id"] not in response.text
    control = await card(actors, visible, "author")
    assert {link["kind"] for link in control.json()["links"]} == {
        "subtask", "parent", "blocks", "blocked_by", "relates", "duplicates", "duplicated_by"}
    assert len(control.json()["links"]) == 8


async def test_selfwatch_cannot_create_access(actors, db):
    companies, users, clients = actors
    secret = await make(actors, visibility="private")
    cid = str(companies[0].id)
    for body in ({"company_id": cid}, {"company_id": cid, "user_id": str(users["stranger"].id)}):
        response = await clients["stranger"].post(f"/api/tasks/{secret['id']}/watchers", json=body)
        assert response.status_code == 404, response.text
        assert await db.get(TaskWatcher, (uuid.UUID(secret["id"]), users["stranger"].id)) is None
    assert (await card(actors, secret)).status_code == 404
    # Управляющий добавляет ещё не причастного человека, затем отзыв закрывает чтение.
    response = await clients["admin"].post(f"/api/tasks/{secret['id']}/watchers", json={
        "company_id": cid, "user_id": str(users["stranger"].id)})
    assert response.status_code == 201, response.text
    assert (await card(actors, secret)).status_code == 200
    response = await clients["admin"].delete(
        f"/api/tasks/{secret['id']}/watchers/{users['stranger'].id}", params={"company_id": cid})
    assert response.status_code == 200
    assert (await card(actors, secret)).status_code == 404
    response = await clients["stranger"].post(f"/api/tasks/{secret['id']}/watchers", json={"company_id": cid})
    assert response.status_code == 404


async def test_postlink_aliases_denied_before_insert_or_existing_branch(actors, db):
    companies, users, clients = actors
    cid = str(companies[0].id)
    visible = await make(actors)
    secret = await make(actors, visibility="private")
    from app.models import TaskProject
    project = TaskProject(company_id=companies[0].id, name="Тест · Ключ", code="BOUND")
    db.add(project)
    await db.flush()
    task = await db.get(Task, uuid.UUID(secret["id"]))
    task.project_id, task.project_number = project.id, 7
    # Stranger owns the visible side but has no read on secret; known keys must not disclose it.
    owner = await db.get(Task, uuid.UUID(visible["id"]))
    owner.assignee_id = users["stranger"].id
    await db.commit()
    for ref in (secret["id"], str(secret["number"]), " bound-7 "):
        response = await clients["stranger"].post(f"/api/tasks/{visible['id']}/links", json={
            "company_id": cid, "related_task_id": ref, "kind": "subtask"})
        assert response.status_code == 404, response.text
        assert await db.scalar(select(func.count()).select_from(TaskLink).where(
            TaskLink.task_id == owner.id)) == 0
    hidden_link = TaskLink(task_id=owner.id, related_task_id=task.id, kind="subtask")
    reverse = TaskLink(task_id=task.id, related_task_id=owner.id, kind="subtask")
    db.add_all([hidden_link, reverse])
    await db.commit()
    response = await clients["stranger"].post(f"/api/tasks/{visible['id']}/links", json={
        "company_id": cid, "related_task_id": secret["id"], "kind": "subtask"})
    assert response.status_code == 404  # before duplicate/cycle return
    # Readable target need not be editable by caller.
    other = await make(actors)
    response = await clients["stranger"].post(f"/api/tasks/{visible['id']}/links", json={
        "company_id": cid, "related_task_id": other["id"], "kind": "relates"})
    assert response.status_code == 201, response.text
    response = await clients["author"].delete(f"/api/tasks/{other['id']}/links/{response.json()['id']}",
                                               params={"company_id": cid})
    assert response.status_code == 200


async def test_private_roles_personal_admin_and_tenant(actors, db):
    companies, users, clients = actors
    visible = await make(actors)
    private = await make(actors, visibility="private", assignee_id=str(users["assignee"].id))
    personal = await make(actors, visibility="personal")
    pid = uuid.UUID(private["id"])
    db.add_all([TaskWatcher(task_id=pid, user_id=users["watcher"].id),
                TaskParticipant(task_id=pid, user_id=users["participant"].id),
                TaskLink(task_id=uuid.UUID(visible["id"]), related_task_id=pid, kind="relates"),
                TaskLink(task_id=uuid.UUID(visible["id"]), related_task_id=uuid.UUID(personal["id"]), kind="relates")])
    foreign = Task(company_id=companies[1].id, title="Другая компания", visibility="company")
    db.add(foreign)
    await db.flush()
    db.add_all([TaskLink(task_id=uuid.UUID(visible["id"]), related_task_id=foreign.id, kind="subtask"),
                TaskLink(task_id=foreign.id, related_task_id=uuid.UUID(visible["id"]), kind="blocks")])
    await db.commit()
    for role in users:
        response = await card(actors, private, role)
        assert response.status_code == (404 if role == "stranger" else 200), (role, response.text)
        response = await card(actors, visible, role)
        ids = {link["task_id"] for link in response.json()["links"]}
        assert (private["id"] in ids) == (role != "stranger")
        assert (personal["id"] in ids) == (role == "author")
        assert str(foreign.id) not in response.text
        assert response.json()["subtasks"] == {"total": 0, "open": 0}
        assert (await card(actors, personal, role)).status_code == (200 if role == "author" else 404)
    # No company-membership shortcut through the other task's author/assignee.
    response = await clients["author"].get(f"/api/tasks/{foreign.id}", params={"company_id": str(companies[0].id)})
    assert response.status_code == 404
    # Predicate singleton and list must fail closed on unknown visibility.
    task = await db.get(Task, pid)
    task.visibility = "invalid-legacy"
    await db.commit()
    for role in ("stranger", "admin", "superadmin"):
        assert (await card(actors, private, role)).status_code == 404


async def test_visible_subtask_aggregates_every_response_and_search(actors, db):
    companies, users, clients = actors
    cid = str(companies[0].id)
    parent = await make(actors, assignee_id=str(users["stranger"].id))
    visible = await make(actors)
    hidden = await make(actors, visibility="private", title="Секретное название для поиска")
    db.add_all([TaskLink(task_id=uuid.UUID(parent["id"]), related_task_id=uuid.UUID(child["id"]), kind="subtask")
                for child in (visible, hidden)])
    await db.commit()
    for params in ({"q": parent["title"]}, {"query": parent["title"]}, {}):
        response = await clients["stranger"].get("/api/tasks", params={"company_id": cid, **params})
        assert response.status_code == 200, response.text
        row = next(t for t in response.json()["tasks"] if t["id"] == parent["id"])
        assert row["subtasks"] == {"total": 1, "open": 1}
        assert hidden["id"] not in response.text
    for params in ({"q": hidden["title"]}, {"query": hidden["title"]}, {"q": str(hidden["number"])}):
        response = await clients["stranger"].get("/api/tasks", params={"company_id": cid, **params})
        assert response.json()["total"] == 0
    assert (await card(actors, parent)).json()["subtasks"] == {"total": 1, "open": 1}
    response = await clients["stranger"].post(f"/api/tasks/{parent['id']}/action", json={"company_id": cid, "status": "done"})
    assert response.status_code == 200, response.text
    assert response.json()["subtasks"] == {"total": 1, "open": 1}
    assert "1" in response.json()["warning"]
    # Summary activity is a projection too; secret task metadata must not leak there.
    response = await clients["stranger"].get("/api/tasks/summary", params={"company_id": cid})
    assert hidden["id"] not in response.text
    assert hidden["title"] not in response.text


async def test_attachment_both_sinks_revoke_multibinding_and_generic(actors, db, tmp_path):
    companies, users, clients = actors
    cid = str(companies[0].id)
    private = await make(actors, visibility="private")
    personal = await make(actors, visibility="personal")
    visible = await make(actors)
    payload = b"synthetic task attachment bytes"
    local = tmp_path / "synthetic.txt"
    local.write_bytes(payload)
    source = SourceFile(company_id=companies[0].id, file_name="synthetic.txt", mime_type="text/plain",
                        size=len(payload), fingerprint="a" * 64, storage_path=str(local), purpose="data")
    db.add(source)
    await db.flush()
    attachment = TaskAttachment(task_id=uuid.UUID(private["id"]), file_id=source.id,
                                uploaded_by=users["author"].id)
    db.add(attachment)
    watcher = TaskWatcher(task_id=uuid.UUID(private["id"]), user_id=users["watcher"].id)
    db.add(watcher)
    await db.commit()

    async def download(role, generic=False):
        return await clients[role].get(f"/api/files/{source.id}" if generic else f"/api/tasks/attachments/{attachment.id}",
                                      params={} if generic else {"company_id": cid})

    for generic in (False, True):
        assert (await download("stranger", generic)).status_code == 404
        response = await download("watcher", generic)
        assert response.status_code == 200 and response.content == payload
        assert response.headers["cache-control"] == "private, no-store"
    await db.delete(watcher)
    await db.commit()
    for generic in (False, True):
        assert (await download("watcher", generic)).status_code == 404
    # personal remains author-only even for company admins/superadmins.
    attachment.task_id = uuid.UUID(personal["id"])
    await db.commit()
    for role in ("admin", "superadmin", "stranger"):
        for generic in (False, True):
            assert (await download(role, generic)).status_code == 404
    assert (await download("author", True)).content == payload
    # Another same-company binding provides legitimate generic-file access,
    # but does not authorize reading a hidden task's specific attachment.
    second = TaskAttachment(task_id=uuid.UUID(visible["id"]), file_id=source.id)
    db.add(second)
    await db.commit()
    assert (await download("stranger", True)).content == payload
    assert (await download("stranger", False)).status_code == 404
    await db.delete(second)
    await db.commit()
    assert (await download("stranger", True)).status_code == 404
    # Foreign task binding must not provide a same-company allowance, even for superadmin.
    foreign = Task(company_id=companies[1].id, title="Файл другой компании", visibility="company")
    db.add(foreign)
    await db.flush()
    second = TaskAttachment(task_id=foreign.id, file_id=source.id)
    db.add(second)
    await db.commit()
    assert (await download("superadmin", True)).status_code == 404
    await db.delete(second)
    await db.delete(attachment)
    await db.commit()
    # File without task bindings retains its existing generic contract.
    assert (await download("stranger", True)).content == payload


@pytest.mark.parametrize("invalid", ["-1ч", "-30м", "−1ч", "минус 1ч", "мусор 2ч", "2ч мусор", "1ч -30м", "1e3", "0"])
async def test_invalid_duration_work_and_estimate_no_side_effects(actors, invalid):
    companies, _, clients = actors
    task = await make(actors)
    cid = str(companies[0].id)
    before = (await card(actors, task, "author")).json()
    for path, fields in (("work", {"duration": invalid}), ("action", {"estimate": invalid})):
        response = await clients["author"].post(f"/api/tasks/{task['id']}/{path}", json={"company_id": cid, **fields})
        assert response.status_code == 400, response.text
    after = (await card(actors, task, "author")).json()
    assert after["time"] == before["time"]
    assert after["events"] == before["events"]


async def test_duration_legitimate_capabilities_and_readonly_comments(actors):
    companies, _, clients = actors
    task = await make(actors)
    cid = str(companies[0].id)
    for duration, minutes in (("1,5ч", 90), ("2ч 30м", 150), ("90м", 90), ("45", 2700), ("2 часа 30 минут", 150)):
        response = await clients["author"].post(f"/api/tasks/{task['id']}/work", json={"company_id": cid, "duration": duration})
        assert response.status_code == 201 and response.json()["minutes"] == minutes, response.text
        response = await clients["author"].post(f"/api/tasks/{task['id']}/action", json={"company_id": cid, "estimate": duration})
        assert response.status_code == 200 and response.json()["time"]["estimate"] == minutes, response.text
    assert (await card(actors, task, "author")).json()["can_edit"] is True
    readonly = (await card(actors, task)).json()
    assert readonly["can_edit"] is False
    assert not any(w["can_delete"] for w in readonly["work_items"])
    response = await clients["stranger"].post(f"/api/tasks/{task['id']}/action", json={"company_id": cid, "note": "Помог с проверкой"})
    assert response.status_code == 200
    response = await clients["stranger"].post(f"/api/tasks/{task['id']}/work", json={"company_id": cid, "duration": "30м"})
    assert response.status_code == 201, response.text
    own_id = response.json()["id"]
    readonly = (await card(actors, task)).json()
    assert next(w for w in readonly["work_items"] if w["id"] == own_id)["can_delete"] is True
    assert readonly["can_edit"] is False
    response = await clients["stranger"].delete(f"/api/tasks/{task['id']}/work/{own_id}", params={"company_id": cid})
    assert response.status_code == 200
    response = await clients["stranger"].post(f"/api/tasks/{task['id']}/action", json={"company_id": cid, "priority": "high"})
    assert response.status_code == 403


async def test_unknown_stage_bulk_is_refused_and_explicit_note_works(actors):
    companies, _, clients = actors
    task = await make(actors)
    cid = str(companies[0].id)
    before = (await card(actors, task, "author")).json()
    for command in ("стадия Несуществующая", "срочная стадия Несуществующая"):
        response = await clients["author"].post("/api/tasks/command", json={
            "company_id": cid, "task_ids": [task["id"]], "command": command})
        assert response.status_code == 400 and "стади" in response.text.lower()
        after = (await card(actors, task, "author")).json()
        assert after["events"] == before["events"]
        assert after["priority"] == before["priority"]
    response = await clients["author"].post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [task["id"]], "command": "Проверю после встречи"})
    assert response.status_code == 200 and response.json()["changed"] == 1
    after = (await card(actors, task, "author")).json()
    assert after["events"][-1]["note"] == "Проверю после встречи"


async def test_closed_report_cohort_and_mine_drill_agree(actors, db):
    companies, users, clients = actors
    cid = str(companies[0].id)
    # Moscow date 22 Oct starts 21 Oct 21:00Z, includes 22 Oct 20:59Z.
    times = ["2026-10-21T20:59:59+00:00", "2026-10-21T21:00:00+00:00",
             "2026-10-22T20:59:59.999999+00:00", "2026-10-22T21:00:00+00:00"]
    tasks = []
    for i, at in enumerate(times):
        task = await make(actors)
        row = await db.get(Task, uuid.UUID(task["id"]))
        row.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        row.closed_at = datetime.fromisoformat(at)
        row.status = "cancelled" if i == 2 else "done"
        tasks.append(task)
    open_task = await make(actors, assignee_id=str(users["author"].id), due_at="2020-01-01T00:00:00Z")
    await make(actors, assignee_id=str(users["stranger"].id))
    external = await make(actors, assignee_id=str(users["author"].id))
    (await db.get(Task, uuid.UUID(external["id"]))).waiting_for = "external"
    personal = await make(actors, visibility="personal")
    row = await db.get(Task, uuid.UUID(personal["id"]))
    row.closed_at, row.status = datetime.fromisoformat(times[1]), "done"
    await db.commit()
    report = await clients["admin"].get("/api/tasks/reports/discipline", params={"company_id": cid, "date_from": "2026-10-22", "date_to": "2026-10-22"})
    assert report.status_code == 200, report.text
    assert report.json()["closed"] == 2
    response = await clients["admin"].get("/api/tasks", params={"company_id": cid, "scope": "closed", "closed_from": "2026-10-22", "closed_to": "2026-10-22"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == report.json()["closed"]
    assert {t["id"] for t in response.json()["tasks"]} == {tasks[1]["id"], tasks[2]["id"]}
    summary = (await clients["author"].get("/api/tasks/summary", params={"company_id": cid})).json()
    mine = (await clients["author"].get("/api/tasks", params={"company_id": cid, "scope": "mine"})).json()
    assert summary["totals"]["mine"] == mine["total"] == 1
    assert mine["tasks"][0]["id"] == open_task["id"]
    # Current backlog remains independent of the report's historical period.
    assert report.json()["backlog"]["open"] == 3
    response = await clients["admin"].get("/api/tasks", params={"company_id": cid, "scope": "open"})
    assert response.json()["total"] == report.json()["backlog"]["open"]


async def test_monthly_create_validates_and_legacy_invalid_never_spawns(actors, db):
    from app.models import TaskRecurrence, TaskTemplate
    from app.services import task_scheduler
    companies, users, clients = actors
    cid = str(companies[0].id)
    template = TaskTemplate(company_id=companies[0].id, name="Тест · Расписание", title="Тест · Порождённое",
                            assignee_id=users["author"].id)
    db.add(template)
    await db.commit()
    for rule in ({"mode": "monthly", "day": 32}, {"mode": "monthly", "day": 0},
                 {"mode": "monthly", "day": 1.5}, {"mode": "monthly", "day": "31"},
                 {"mode": "monthly", "day": True}, {"mode": "daily", "at": "25:00"},
                 {"mode": "daily", "at": "09:60"}, {"mode": "whatever"}, {"tz": "Invalid/Zone"}):
        response = await clients["author"].post("/api/tasks/recurrences", json={
            "company_id": cid, "template_id": str(template.id), "rule": rule})
        assert response.status_code == 400, response.text
        assert await db.scalar(select(func.count()).select_from(TaskRecurrence).where(
            TaskRecurrence.company_id == companies[0].id)) == 0
    response = await clients["author"].post("/api/tasks/recurrences", json={
        "company_id": cid, "template_id": str(template.id),
        "rule": {"mode": "monthly", "day": 31, "at": "09:00", "tz": "Europe/Moscow"}})
    assert response.status_code == 201, response.text
    rule = response.json()["rule"]
    assert rule["day"] == 31
    # Old invalid row with a due next_run is rejected before spawn (not after).
    bad = TaskRecurrence(company_id=companies[0].id, template_id=template.id, created_by=users["author"].id,
                         enabled=True, rule={"mode": "monthly", "day": 32},
                         next_run_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    db.add(bad)
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(Task).where(Task.company_id == companies[0].id))
    await task_scheduler.run_recurrences(db, datetime(2026, 10, 22, tzinfo=timezone.utc))
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.company_id == companies[0].id)) == before
    assert bad.last_run_at is None and bad.next_run_at.year == 2000


async def test_capability_matches_actor_oversight_and_work_creator(actors, db):
    from app.models import Department, TaskWorkItem
    companies, users, clients = actors
    cid = str(companies[0].id)
    task = await make(actors, assignee_id=str(users["assignee"].id))
    department = Department(company_id=companies[0].id, name="Тест · Надзор",
                            head_user_id=users["stranger"].id)
    db.add(department)
    await db.flush()
    member = await db.get(UserCompany, (users["assignee"].id, companies[0].id))
    member.department_id = department.id
    work = TaskWorkItem(task_id=uuid.UUID(task["id"]), user_id=users["participant"].id,
                        created_by=users["watcher"].id, minutes=30, work_date=date(2026, 10, 22))
    db.add(work)
    await db.commit()
    for role in ("author", "assignee", "admin", "superadmin", "stranger"):
        response = await card(actors, task, role)
        assert response.json()["can_edit"] is True, (role, response.text)
        assert response.json()["work_items"][0]["can_delete"] is True
        response = await clients[role].post(f"/api/tasks/{task['id']}/action", json={"company_id": cid, "priority": "high"})
        assert response.status_code == 200, (role, response.text)
    for role in ("watcher", "participant"):
        response = await card(actors, task, role)
        assert response.json()["can_edit"] is False
        assert response.json()["work_items"][0]["can_delete"] is True
    response = await clients["watcher"].delete(f"/api/tasks/{task['id']}/work/{work.id}", params={"company_id": cid})
    assert response.status_code == 200
    # Oversight alone still cannot read a private task or link it by a known ref.
    private = await make(actors, visibility="private", assignee_id=str(users["assignee"].id))
    assert (await card(actors, private)).status_code == 404
    response = await clients["stranger"].post(f"/api/tasks/{private['id']}/links", json={
        "company_id": cid, "related_task_id": task["id"], "kind": "relates"})
    assert response.status_code == 404


async def test_place_passes_actor_timezone_for_all_task_deadlines(actors, db, monkeypatch):
    from app.routers import work_router
    companies, users, clients = actors
    cid = str(companies[0].id)
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 22, 19, tzinfo=timezone.utc).astimezone(tz or timezone.utc)
    monkeypatch.setattr(work_router, "datetime", FixedDatetime)
    users["author"].tz = "Europe/Moscow"
    await db.commit()
    for due in ("2026-10-22T21:00:00Z", "2026-10-23T20:59:00Z"):
        task = await make(actors, due_at=due)
        response = await clients["author"].post("/api/work/place", json={
            "company_id": cid, "target_ref": f"task:{task['id']}", "defer_until": "2026-10-30"})
        assert response.status_code == 200, response.text
        assert response.json()["mark"]["deferred_until"] == "2026-10-23"
    users["author"].tz = "Asia/Vladivostok"
    await db.commit()
    task = await make(actors, due_at="2026-10-23T12:00:00Z")  # local today, no hiding
    response = await clients["author"].post("/api/work/place", json={
        "company_id": cid, "target_ref": f"task:{task['id']}", "defer_until": "2026-10-30"})
    assert response.status_code == 400, response.text


async def test_task_file_allowance_does_not_override_chat_guard(actors, db, tmp_path):
    from app.models import ChatMessage, ChatParticipant, ChatRoom
    companies, users, clients = actors
    visible = await make(actors)
    local = tmp_path / "shared.txt"
    local.write_bytes(b"synthetic shared task and chat file")
    source = SourceFile(company_id=companies[0].id, file_name=local.name,
                        storage_path=str(local), mime_type="text/plain", size=local.stat().st_size)
    room = ChatRoom(company_id=companies[0].id, type="group", name="Тест · Закрытый чат")
    db.add_all([source, room])
    await db.flush()
    db.add_all([TaskAttachment(task_id=uuid.UUID(visible["id"]), file_id=source.id),
                ChatMessage(room_id=room.id, user_id=users["author"].id,
                            file_url=f"/api/files/{source.id}", type="file")])
    await db.commit()
    response = await clients["stranger"].get(f"/api/files/{source.id}")
    assert response.status_code == 404
    # Both task and chat authorization are necessary, then both grant succeeds.
    participant = ChatParticipant(room_id=room.id, user_id=users["stranger"].id)
    db.add(participant)
    await db.commit()
    response = await clients["stranger"].get(f"/api/files/{source.id}")
    assert response.status_code == 200 and response.content == local.read_bytes(), response.text
    await db.delete(participant)
    await db.commit()
    assert (await clients["stranger"].get(f"/api/files/{source.id}")).status_code == 404


async def test_task_counts_in_projects_versions_and_sprints_obey_same_acl(actors, db):
    from app.models import TaskProject, TaskSprint, TaskVersion
    companies, _, clients = actors
    project = TaskProject(company_id=companies[0].id, code="COUNTS", name="Тест · Счётчики")
    db.add(project)
    await db.flush()
    version = TaskVersion(company_id=companies[0].id, project_id=project.id, name="test-version")
    sprint = TaskSprint(company_id=companies[0].id, project_id=project.id, name="test-sprint")
    db.add_all([version, sprint])
    await db.flush()
    for i, visibility in enumerate(("company", "private", "personal"), 1):
        task = await make(actors, visibility=visibility)
        row = await db.get(Task, uuid.UUID(task["id"]))
        row.project_id, row.project_number = project.id, i
        row.fix_version_id, row.sprint_id = version.id, sprint.id
    await db.commit()
    for role, expected in (("stranger", 1), ("author", 3), ("admin", 2), ("superadmin", 2)):
        for endpoint, item_id, count_key in (("projects", project.id, "tasks"),
                                             ("versions", version.id, "open"),
                                             ("sprints", sprint.id, "left")):
            response = await clients[role].get(f"/api/tasks/{endpoint}", params={"company_id": str(companies[0].id)})
            assert response.status_code == 200, response.text
            row = next(row for row in response.json()[endpoint] if row["id"] == str(item_id))
            assert row[count_key] == expected, (role, endpoint, row)
