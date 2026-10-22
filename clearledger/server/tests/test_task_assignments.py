"""Входящие поручения: версия передачи, личный просмотр и отдельная просрочка."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.auth import create_access_token
from app.main import app
from app.models import Company, PersonalMark, TaskAssignmentRead, Task, User, UserCompany
from app.services import task_assignments

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def people(db, monkeypatch):
    from app.services import notify, task_mail

    async def quiet(*args, **kwargs):
        pass
    monkeypatch.setattr(notify, "tell", quiet)
    monkeypatch.setattr(task_mail, "send_notice_async", lambda *args: None)
    companies = [Company(name="Тест · Входящие", profile_id="energy", slug=f"assignment-{uuid.uuid4().hex}")
                 for _ in range(2)]
    db.add_all(companies)
    await db.flush()
    users = [User(name=f"Тест · Исполнитель {i}", email=f"badge-{uuid.uuid4().hex}@example.test",
                  password_hash="!synthetic", role="user", task_notify=[])
             for i in range(4)]
    db.add_all(users)
    await db.flush()
    for u in users:
        db.add(UserCompany(user_id=u.id, company_id=companies[0].id, role="user"))
    db.add(UserCompany(user_id=users[1].id, company_id=companies[1].id, role="user"))
    await db.commit()
    clients = [AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={
        "Authorization": f"Bearer {create_access_token(str(u.id), u.email)}",
    }) for u in users]
    yield companies, users, clients
    for client in clients:
        await client.aclose()


async def count(client, cid):
    r = await client.get("/api/tasks/assignment-counts", params={"company_id": str(cid)})
    assert r.status_code == 200, r.text
    return r.json()


async def create(client, cid, assignee, **kwargs):
    r = await client.post("/api/tasks", json={
        "company_id": str(cid), "title": "Тест · Назначение",
        "assignee_id": str(assignee), **kwargs,
    })
    assert r.status_code == 201, r.text
    return r.json()


async def action(client, cid, tid, **kwargs):
    r = await client.post(f"/api/tasks/{tid}/action", json={"company_id": str(cid), **kwargs})
    assert r.status_code == 200, r.text
    return r.json()


async def ack(client, cid, task):
    r = await client.post(f"/api/tasks/{task['id']}/assignment-view", json={
        "company_id": str(cid), "assignment_revision": task["assignment_revision"],
    })
    assert r.status_code == 200, r.text
    return r.json()["acknowledged"]


async def test_new_ack_reassign_self_and_stale_card(people, db):
    companies, users, (author, recipient, other, _) = people
    cid = companies[0].id
    task = await create(author, cid, users[1].id)
    assert await count(recipient, cid) == {"new": 1, "overdue": 0}
    # Открытие очереди и GET автором не погашают чужое входящее.
    await recipient.get("/api/tasks", params={"company_id": str(cid), "scope": "mine"})
    for client in (author, other):
        r = await client.get(f"/api/tasks/{task['id']}", params={"company_id": str(cid)})
        assert r.status_code == 200
        assert not await ack(client, cid, r.json())
    assert (await count(recipient, cid))["new"] == 1
    assert await ack(recipient, cid, task)
    assert await ack(recipient, cid, task)
    assert (await count(recipient, cid))["new"] == 0
    # Просмотр переживает новый клиент и очистку личной раскладки.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers=dict(recipient.headers)) as second_device:
        assert (await count(second_device, cid))["new"] == 0
    from app.services import placement
    await placement.put(db, cid, users[1].id, f"task:{task['id']}", starred=True)
    await db.commit()
    await placement.put(db, cid, users[1].id, f"task:{task['id']}", clear=True)
    await db.commit()
    assert (await count(recipient, cid))["new"] == 0
    assert (await db.execute(select(func.count()).select_from(PersonalMark).where(
        PersonalMark.user_id == users[1].id,
        PersonalMark.target_ref == f"task:{task['id']}",
    ))).scalar_one() == 0, "ACK не создаёт личную раскладку"
    assert (await db.execute(select(func.count()).select_from(TaskAssignmentRead).where(
        TaskAssignmentRead.user_id == users[1].id,
        TaskAssignmentRead.task_id == uuid.UUID(task["id"]),
    ))).scalar_one() == 1
    changed = await action(author, cid, task["id"], title="Тест · Уточнение", note="Дополнено")
    assert changed["assignment_revision"] == task["assignment_revision"]
    await action(author, cid, task["id"], assignee_id=str(users[2].id))
    reassigned = await action(author, cid, task["id"], assignee_id=str(users[1].id))
    assert reassigned["assignment_revision"] != task["assignment_revision"]
    assert not await ack(recipient, cid, task), "старое поколение не подтверждает новое"
    assert (await count(recipient, cid))["new"] == 1
    assert (await count(other, cid))["new"] == 0
    # Назначение автору другим человеком — полноценное новое входящее.
    await action(recipient, cid, task["id"], assignee_id=str(users[0].id))
    assert (await count(author, cid))["new"] == 1
    await action(author, cid, task["id"], assignee_id=str(users[1].id))
    # Взять себе собственным действием — без нового входящего.
    await action(author, cid, task["id"], assignee_id=str(users[0].id))
    assert (await count(author, cid))["new"] == 0
    await create(author, cid, users[0].id)
    assert (await count(author, cid))["new"] == 0


async def test_counts_all_rows_and_overdue_is_separate(people, db):
    companies, users, (_, recipient, _, _) = people
    cid = companies[0].id
    now = datetime.now(timezone.utc)
    tasks = [Task(company_id=cid, title=f"Тест · Поручение {i}",
                  author_id=users[0].id, assignee_id=users[1].id,
                  due_at=now - timedelta(days=1) if i < 3 else now + timedelta(days=1))
             for i in range(125)]
    tasks += [Task(company_id=cid, title="Тест · Неактивное", author_id=users[0].id,
                   assignee_id=users[1].id, status=status, waiting_for=waiting)
              for status, waiting in (("done", None), ("cancelled", None), ("open", "external"))]
    db.add_all(tasks)
    await db.commit()
    assert await count(recipient, cid) == {"new": 125, "overdue": 3}
    detail = (await recipient.get(f"/api/tasks/{tasks[0].id}", params={"company_id": str(cid)})).json()
    assert await ack(recipient, cid, detail)
    assert await count(recipient, cid) == {"new": 124, "overdue": 3}
    await action(recipient, cid, str(tasks[1].id), status="done")
    assert await count(recipient, cid) == {"new": 123, "overdue": 2}


async def test_company_private_and_product_permissions(people, db):
    companies, users, (author, recipient, other, denied) = people
    cid, other_cid = (c.id for c in companies)
    task = await create(author, cid, users[1].id, visibility="private")
    assert (await other.get(f"/api/tasks/{task['id']}", params={"company_id": str(cid)})).status_code == 404
    assert (await other.post(f"/api/tasks/{task['id']}/assignment-view", json={
        "company_id": str(cid), "assignment_revision": task["assignment_revision"],
    })).status_code == 404
    wrong = await recipient.post(f"/api/tasks/{task['id']}/assignment-view", json={
        "company_id": str(other_cid), "assignment_revision": task["assignment_revision"],
    })
    assert wrong.status_code == 404
    assert await count(recipient, other_cid) == {"new": 0, "overdue": 0}
    assert (await count(recipient, cid))["new"] == 1
    # Отсутствие членства не разрешает считать даже метаданные чужой компании.
    assert (await other.get("/api/tasks/assignment-counts", params={"company_id": str(other_cid)})).status_code == 403
    member = await db.get(UserCompany, (users[3].id, cid))
    member.modules = []
    await db.commit()
    assert (await denied.get("/api/tasks/assignment-counts", params={"company_id": str(cid)})).status_code == 403


async def test_bulk_command_and_orm_generation(people, db):
    companies, users, (author, recipient, _, _) = people
    cid = companies[0].id
    task = await create(author, cid, users[0].id)
    r = await author.post("/api/tasks/bulk", json={
        "company_id": str(cid), "task_ids": [task["id"]], "assignee_id": str(users[1].id),
    })
    # Канонический путь массового назначения.
    assert r.status_code == 200, r.text
    assert (await count(recipient, cid))["new"] == 1
    command = await author.post("/api/tasks/command", json={
        "company_id": str(cid), "task_ids": [task["id"]], "command": "на меня",
    })
    assert command.status_code == 200, command.text
    assert (await count(author, cid))["new"] == 0
    # Конструктор Task вне tasks_router — как у docs/process/chat/scheduler.
    direct = Task(company_id=cid, title="Тест · Из процесса", author_id=users[0].id,
                  assignee_id=users[1].id)
    db.add(direct)
    await db.flush()
    first = direct.assignment_revision
    task_assignments.assign(direct, users[2].id, users[0].id)
    await db.flush()
    assert direct.assignment_revision != first
    task_assignments.assign(direct, users[1].id, users[0].id)
    await db.commit()
    assert (await count(recipient, cid))["new"] == 1
    command = await recipient.post("/api/tasks/command", json={
        "company_id": str(cid), "task_ids": [str(direct.id)], "command": "на меня",
    })
    assert command.status_code == 200, command.text
    assert (await count(recipient, cid))["new"] == 1, "повтор тому же исполнителю не новая передача"


async def test_refresh_only_after_commit_and_not_rollback(people, db, monkeypatch):
    from app.services.chat_ws import manager
    companies, users, _ = people
    await asyncio.gather(*task_assignments._pending_deliveries)
    calls = []
    async def broadcast(channel, payload):
        calls.append((channel, payload))
    monkeypatch.setattr(manager, "broadcast", broadcast)
    task = Task(company_id=companies[0].id, title="Тест · Коммит", author_id=users[0].id,
                assignee_id=users[1].id)
    db.add(task)
    await db.flush()
    await asyncio.sleep(0)
    assert not calls
    await db.commit()
    await asyncio.gather(*task_assignments._pending_deliveries)
    assert calls == [(f"user:{users[1].id}", {
        "type": "task:assignments-changed", "companyId": str(companies[0].id),
    })]
    calls.clear()
    task_assignments.assign(task, users[2].id, users[0].id)
    await db.commit()
    await asyncio.gather(*task_assignments._pending_deliveries)
    assert {channel for channel, _ in calls} == {f"user:{users[1].id}", f"user:{users[2].id}"}
    calls.clear()
    assert await task_assignments.acknowledge(db, companies[0].id, users[2].id,
                                            task.id, task.assignment_revision)
    await db.commit()
    await asyncio.gather(*task_assignments._pending_deliveries)
    assert [channel for channel, _ in calls] == [f"user:{users[2].id}"]
    calls.clear()
    nested = await db.begin_nested()
    task_assignments.assign(task, users[1].id, users[0].id)
    await db.flush()
    await nested.commit()
    await asyncio.sleep(0)
    assert not calls, "RELEASE SAVEPOINT не должен уведомлять до внешнего коммита"
    await db.rollback()
    await asyncio.sleep(0)
    assert not calls


async def test_existing_schema_upgrade_baselines_without_false_incoming(people, db):
    from app.database import create_all

    companies, users, (_, recipient, _, _) = people
    cid = companies[0].id
    task = Task(company_id=cid, title="Тест · Старая задача", author_id=users[0].id,
                assignee_id=users[1].id)
    db.add(task)
    await db.flush()
    tid = task.id
    db.add(PersonalMark(company_id=cid, user_id=users[1].id, target_ref=f"task:{tid}", starred=True))
    await db.commit()
    # Существующая схема до обновления; отдельная тестовая БД этого прогона.
    for ddl in (
        "ALTER TABLE tasks DROP COLUMN assignment_revision",
        "ALTER TABLE tasks DROP COLUMN assignment_by_id",
        "DROP TABLE task_assignment_reads",
    ):
        await db.execute(text(ddl))
    await db.commit()
    await create_all()
    assert await count(recipient, cid) == {"new": 0, "overdue": 0}
    assert (await db.execute(select(PersonalMark.starred).where(
        PersonalMark.target_ref == f"task:{tid}", PersonalMark.user_id == users[1].id,
    ))).scalar_one() is True
    new_task = Task(company_id=cid, title="Тест · После обновления", author_id=users[0].id,
                    assignee_id=users[1].id)
    db.add(new_task)
    await db.commit()
    await db.commit()
    await create_all()
    assert (await count(recipient, cid))["new"] == 1, "повтор миграции не подтверждает новые назначения"
