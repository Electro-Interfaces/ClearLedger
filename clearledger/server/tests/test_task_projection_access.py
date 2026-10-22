"""Обсуждение, ссылки на код и раскладка соблюдают текущий ACL поручения.

Настоящие JWT/HTTP/PostgreSQL; компании, люди и содержимое синтетические.
Сетевые отправители уведомлений заменены сборщиками, ACL и SQL настоящие.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.auth import create_access_token
from app.main import app
from app.models import (ChatMessage, ChatParticipant, ChatPushSubscription, ChatRoom,
                        Company, PersonalMark, Task, TaskCodeRef, TaskParticipant,
                        TaskProject, TaskWatcher, User, UserCompany)
from tests.helpers import drain_application_tasks

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def actors(db, monkeypatch):
    from app.services import chat_mail, web_push

    async def no_mail(*args, **kwargs):
        raise AssertionError("Тест не должен отправлять письма")

    def no_push(*args, **kwargs):
        raise AssertionError("Тест не должен отправлять Web Push")

    monkeypatch.setattr(chat_mail, "send_notice", no_mail)
    monkeypatch.setattr(web_push, "_send_one", no_push)
    companies = [Company(name="Тест · Проекции поручений", profile_id="energy",
                         slug=f"projection-{uuid.uuid4().hex}") for _ in range(2)]
    db.add_all(companies)
    await db.flush()
    roles = ("author", "assignee", "watcher", "participant", "stranger", "admin",
             "superadmin", "legacy", "denied", "outsider")
    users = {role: User(name=f"Тест · {role}", email=f"projection-{uuid.uuid4().hex}@example.test",
                       password_hash="!synthetic", role="user", task_notify=[],
                       company_id=companies[0].id, tz="Europe/Moscow",
                       is_superadmin=role == "superadmin") for role in roles}
    db.add_all(users.values())
    await db.flush()
    for role, user in users.items():
        if role == "outsider":
            continue
        db.add(UserCompany(user_id=user.id, company_id=companies[0].id,
                           role="admin" if role == "admin" else "user",
                           modules=["plan"] if role == "legacy" else
                                   ["pulse"] if role == "denied" else ["docs"]))
    project = TaskProject(company_id=companies[0].id, code="SYNTH", name="Тест · Проект")
    db.add(project)
    await db.commit()
    clients = {role: AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
               headers={"Authorization": f"Bearer {create_access_token(str(u.id), u.email)}",
                        "X-Company-Id": str(companies[0].id)}) for role, u in users.items()}
    yield companies, users, clients, project
    await drain_application_tasks()
    for client in clients.values():
        await client.aclose()


async def make(db, actors, visibility="private", *, code=True):
    companies, users, _, project = actors
    task = Task(company_id=companies[0].id, title="Тест · Скрытое поручение",
                visibility=visibility, author_id=users["author"].id,
                assignee_id=users["assignee"].id, project_id=project.id,
                project_number=1,
                due_at=datetime.now(timezone.utc) + timedelta(days=10))
    db.add(task)
    await db.flush()
    db.add_all([TaskWatcher(task_id=task.id, user_id=users["watcher"].id),
                TaskParticipant(task_id=task.id, user_id=users["participant"].id)])
    if code:
        db.add(TaskCodeRef(task_id=task.id, kind="pr", url="https://example.test/private/42",
                           title="Тест · Закрытая реализация", repo="synthetic",
                           added_by=users["author"].id))
    await db.commit()
    return task


async def ensure(actors, task, role="author"):
    return await actors[2][role].post(f"/api/chat/tasks/{task.id}/room")


async def room_snapshot(db, task):
    rooms = list((await db.scalars(select(ChatRoom.id).where(ChatRoom.scope_task_id == task.id))))
    parts = list((await db.execute(select(ChatParticipant.room_id, ChatParticipant.user_id,
                                         ChatParticipant.role).where(
        ChatParticipant.room_id.in_(rooms)).order_by(ChatParticipant.user_id))).all())
    return rooms, parts


@pytest.mark.parametrize("visibility,role", [
    ("private", "stranger"), ("personal", "stranger"), ("personal", "assignee"),
    ("personal", "watcher"), ("personal", "participant"),
    ("personal", "admin"), ("personal", "superadmin"),
])
@pytest.mark.parametrize("preexisting", [False, True])
async def test_denied_room_has_no_membership_side_effects(actors, db, visibility, role, preexisting):
    task = await make(db, actors, visibility)
    if preexisting:
        assert (await ensure(actors, task)).status_code == 200
    before = await room_snapshot(db, task)
    response = await ensure(actors, task, role)
    assert response.status_code == 404, response.text
    assert await room_snapshot(db, task) == before
    for rid in before[0]:
        for path in ("", "/messages"):
            response = await actors[2][role].get(f"/api/chat/rooms/{rid}{path}")
            assert response.status_code == 404, response.text
    assert (await actors[2][role].get(f"/api/tasks/{task.id}", params={
        "company_id": str(task.company_id)})).status_code == 404


@pytest.mark.parametrize("visibility,role", [
    ("company", "stranger"), ("company", "legacy"),
    ("private", "author"), ("private", "assignee"), ("private", "watcher"),
    ("private", "participant"), ("private", "admin"), ("private", "superadmin"),
    ("personal", "author"),
])
async def test_legitimate_task_chat_needs_no_extra_chat_product(actors, db, visibility, role):
    task = await make(db, actors, visibility)
    response = await ensure(actors, task, role)
    assert response.status_code == 200, response.text
    rid = response.json()["id"]
    client = actors[2][role]
    sent = await client.post(f"/api/chat/rooms/{rid}/messages", json={
        "type": "text", "content": "Тест · Разрешённая реплика"})
    assert sent.status_code == 201, sent.text
    messages = await client.get(f"/api/chat/rooms/{rid}/messages")
    assert messages.status_code == 200, messages.text
    assert "Разрешённая реплика" in messages.text


@pytest.mark.parametrize("role,status", [("denied", 403), ("outsider", 403)])
async def test_room_product_and_company_membership_still_required(actors, db, role, status):
    task = await make(db, actors, "company")
    assert (await ensure(actors, task, role)).status_code == status
    assert await room_snapshot(db, task) == ([], [])


class Socket:
    def __init__(self):
        self.messages = []

    async def accept(self):
        pass

    async def send_json(self, payload):
        self.messages.append(payload)


async def test_revoked_participant_receives_neither_push_nor_mail_preview(actors, db, monkeypatch):
    from types import SimpleNamespace
    from app.services import chat_mail, web_push
    from app.services.chat_ws import manager

    _, users, _, _ = actors
    task = await make(db, actors)
    opened = await ensure(actors, task, "participant")
    assert opened.status_code == 200, opened.text
    rid = uuid.UUID(opened.json()["id"])
    # Оба уже в комнате и получают сообщения до отзыва TaskWatcher.
    for name in ("watcher", "participant"):
        users[name].mail_only = True
        db.add(ChatPushSubscription(user_id=users[name].id,
            endpoint=f"https://example.test/push/{name}/{uuid.uuid4()}", p256dh="synthetic", auth="synthetic"))
    await db.commit()
    pushed, mailed = [], []

    async def keys(_db):
        return SimpleNamespace(private_pem="synthetic")

    async def offline():
        return set()

    def push(_key, info, payload, *_args):
        pushed.append((info["endpoint"], payload))

    async def mail(recipients, *_args, **_kwargs):
        mailed.extend(recipients)

    monkeypatch.setattr(web_push, "get_or_create_keys", keys)
    monkeypatch.setattr(web_push, "_send_one", push)
    monkeypatch.setattr(manager, "online_user_ids", offline)
    monkeypatch.setattr(chat_mail, "send_notice", mail)
    monkeypatch.setattr(chat_mail.settings, "smtp_host", "example.test")
    monkeypatch.setattr(chat_mail.settings, "chat_mail_inbox", "synthetic@example.test")

    async def send():
        web_push.push_room_async(rid, "Тест · Обсуждение", "Тест · Скрытый текст", users["author"].id)
        chat_mail.push_room_mail_async(rid, "Тест · Обсуждение", "Тест · Автор",
                                       "Тест · Скрытый текст", users["author"].id)
        await drain_application_tasks()

    await send()
    assert len(pushed) == 2
    assert set(mailed) == {users[n].email for n in ("watcher", "participant")}
    pushed.clear()
    mailed.clear()
    watcher = await db.scalar(select(TaskWatcher).where(TaskWatcher.task_id == task.id,
                                                       TaskWatcher.user_id == users["watcher"].id))
    await db.delete(watcher)
    await db.commit()
    await send()
    assert len(pushed) == 1 and "/participant/" in pushed[0][0]
    assert mailed == [users["participant"].email]


@pytest.mark.parametrize("revocation", ["watcher", "participant", "assignee", "personal"])
async def test_preexisting_room_rechecks_acl_for_rest_subscribe_delivery_and_search(actors, db, revocation):
    from app.routers.chat_router import _ws_can_subscribe
    from app.services.chat_ws import ChatConnectionManager
    from app.services.ticket_communications import delivery_allowed, recipient_allowed

    _, users, clients, _ = actors
    role = "watcher" if revocation == "personal" else revocation
    task = await make(db, actors)
    opened = await ensure(actors, task, role)
    assert opened.status_code == 200, opened.text
    rid = uuid.UUID(opened.json()["id"])
    room = await db.get(ChatRoom, rid)
    msg = ChatMessage(room_id=rid, user_id=users["author"].id, user_name="Тест · Автор",
                      content="syntheticneedle history", type="text")
    db.add(msg)
    await db.commit()
    channel = f"chat:{rid}"
    event = {"type": "chat:message", "id": str(msg.id), "content": "syntheticneedle live"}
    assert await _ws_can_subscribe(users[role], channel, db)
    assert await recipient_allowed(db, room, users[role].id)
    assert await delivery_allowed(channel, event, str(users[role].id))
    # Сокет подписан ДО отзыва: свежая подписка сама по себе этот случай не ловит.
    manager = ChatConnectionManager()
    sockets = {name: Socket() for name in (role, "author")}
    for name, sock in sockets.items():
        await manager.connect(sock, str(users[name].id), str(task.company_id))
        manager.subscribe(sock, channel)
        manager.subscribe(sock, f"user:{users[name].id}")
    if revocation in ("watcher", "participant"):
        model = TaskWatcher if revocation == "watcher" else TaskParticipant
        row = await db.scalar(select(model).where(model.task_id == task.id,
                                                  model.user_id == users[role].id))
        await db.delete(row)
    elif revocation == "assignee":
        task.assignee_id = users["author"].id
    else:
        task.visibility = "personal"
    await db.commit()
    assert await db.scalar(select(ChatParticipant.id).where(
        ChatParticipant.room_id == rid, ChatParticipant.user_id == users[role].id)) is not None
    before = await room_snapshot(db, task)
    for path in ("", "/messages", "/messages?q=syntheticneedle", "/media"):
        response = await clients[role].get(f"/api/chat/rooms/{rid}{path}")
        assert response.status_code == 404, (path, response.text)
    assert (await ensure(actors, task, role)).status_code == 404
    assert (await clients[role].post(f"/api/chat/rooms/{rid}/messages", json={
        "content": "Тест · Запрещённая запись"})).status_code == 404
    assert await room_snapshot(db, task) == before
    assert await db.scalar(select(func.count()).select_from(ChatMessage).where(
        ChatMessage.room_id == rid)) == 1
    assert not await _ws_can_subscribe(users[role], channel, db)
    assert not await recipient_allowed(db, room, users[role].id)
    assert not await delivery_allowed(channel, event, str(users[role].id))
    assert await delivery_allowed(channel, event, str(users["author"].id))
    for payload in (event, {"type": "room:updated", "name": "Скрытое имя"}):
        await manager._broadcast_local(channel, payload)
    mention = {"type": "chat:mention", "roomId": str(rid), "preview": "Скрытый текст"}
    for name in sockets:
        await manager._broadcast_local(f"user:{users[name].id}", mention)
    assert sockets[role].messages == []
    assert len(sockets["author"].messages) == 3
    for name in (role, "author"):
        # Поиск скрытого обсуждения остаётся внутри карточки даже у автора.
        search = await clients[name].get("/api/chat/search", params={"q": "syntheticneedle"})
        assert search.status_code == 200, search.text
        assert search.json() == []
        listed = await clients[name].get("/api/chat/rooms")
        assert listed.status_code == 200, listed.text
        assert str(rid) not in listed.text
    assert (await clients["author"].get(f"/api/chat/rooms/{rid}/messages")).status_code == 200
    for sock in sockets.values():
        await manager.disconnect(sock)


@pytest.mark.parametrize("visibility,role,allowed", [
    ("private", "stranger", False), ("private", "watcher", True),
    ("private", "admin", True), ("personal", "admin", False),
    ("personal", "superadmin", False), ("personal", "author", True),
    ("company", "stranger", True),
])
@pytest.mark.parametrize("code", [False, True])
async def test_code_refs_aliases_preserve_acl_and_empty_result(actors, db, visibility, role, allowed, code):
    task = await make(db, actors, visibility, code=code)
    for ref in (str(task.id), str(task.number), "SYNTH-1", "synth-1"):
        response = await actors[2][role].get(f"/api/tasks/{ref}/code", params={
            "company_id": str(task.company_id)})
        assert response.status_code == (200 if allowed else 404), (ref, response.text)
        if allowed:
            assert len(response.json()["code"]) == int(code)
        else:
            assert response.json() == {"detail": "Задача не найдена"}
    for ref in (str(uuid.uuid4()), "999999999", "ABSENT-99"):
        response = await actors[2][role].get(f"/api/tasks/{ref}/code", params={
            "company_id": str(task.company_id)})
        assert response.status_code == 404, response.text


@pytest.mark.parametrize("visibility,role,allowed", [
    ("private", "stranger", False), ("private", "watcher", True),
    ("private", "admin", True), ("personal", "stranger", False),
    ("personal", "admin", False), ("personal", "superadmin", False),
    ("personal", "author", True), ("company", "stranger", True),
])
async def test_code_creation_cannot_probe_or_modify_hidden_task(actors, db, visibility, role, allowed):
    from app.models import TaskEvent

    task = await make(db, actors, visibility)
    for ref in (str(task.id), str(task.number), "SYNTH-1", "synth-1"):
        before_refs = await db.scalar(select(func.count()).select_from(TaskCodeRef).where(
            TaskCodeRef.task_id == task.id))
        before_events = await db.scalar(select(func.count()).select_from(TaskEvent).where(
            TaskEvent.task_id == task.id))
        url = f"https://example.test/synthetic/{uuid.uuid4()}"
        response = await actors[2][role].post(f"/api/tasks/{ref}/code", json={
            "company_id": str(task.company_id), "url": url})
        assert response.status_code == (201 if allowed else 404), (ref, response.text)
        assert await db.scalar(select(func.count()).select_from(TaskCodeRef).where(
            TaskCodeRef.task_id == task.id)) == before_refs + int(allowed)
        assert await db.scalar(select(func.count()).select_from(TaskEvent).where(
            TaskEvent.task_id == task.id)) == before_events + int(allowed)
        if allowed:
            assert response.json()["url"] == url
        else:
            assert response.json() == {"detail": "Задача не найдена"}


@pytest.mark.parametrize("visibility,role,allowed", [
    ("private", "stranger", False), ("private", "watcher", True),
    ("private", "participant", True), ("private", "admin", True),
    ("personal", "stranger", False), ("personal", "admin", False),
    ("personal", "superadmin", False), ("personal", "author", True),
    ("company", "stranger", True),
])
@pytest.mark.parametrize("offset", [-1, 0, 5])
async def test_defer_has_no_hidden_due_or_mark_side_effects(actors, db, visibility, role, allowed, offset):
    from app.services.space_time import local_date

    task = await make(db, actors, visibility)
    target = f"task:{task.id}"
    due = local_date(task.due_at, "Europe/Moscow")
    response = await actors[2][role].post("/api/work/place", json={
        "company_id": str(task.company_id), "target_ref": target,
        "defer_until": (due + timedelta(days=offset)).isoformat()})
    assert response.status_code == (200 if allowed else 404), response.text
    mark = await db.scalar(select(PersonalMark).where(
        PersonalMark.user_id == actors[1][role].id, PersonalMark.target_ref == target))
    if allowed:
        assert response.json()["mark"]["deferred_until"] == min(
            due, due + timedelta(days=offset)).isoformat()
        assert mark is not None
    else:
        assert response.json() == {"detail": "Задача не найдена"}
        assert mark is None


@pytest.mark.parametrize("visibility", ["private", "personal"])
async def test_hidden_placement_rejects_changes_but_preserves_owner_cleanup(actors, db, visibility):
    task = await make(db, actors, visibility)
    user = actors[1]["stranger"]
    client = actors[2]["stranger"]
    target = f"task:{task.id}"
    # Раскладка могла остаться от времени до отзыва доступа.
    mark = PersonalMark(company_id=task.company_id, user_id=user.id, target_ref=target,
                        starred=True, deferred_until=task.due_at.date(), defer_count=3)
    author_mark = PersonalMark(company_id=task.company_id, user_id=actors[1]["author"].id,
                               target_ref=target, starred=True)
    db.add_all([mark, author_mark])
    await db.commit()
    for change in ({"starred": False}, {"position": 12},
                   {"defer_until": (task.due_at.date() + timedelta(days=20)).isoformat()}):
        response = await client.post("/api/work/place", json={
            "company_id": str(task.company_id), "target_ref": target, **change})
        assert response.status_code == 404, response.text
        await db.refresh(mark)
        assert mark.starred and mark.position == 0 and mark.defer_count == 3
        assert mark.deferred_until == task.due_at.date()
    response = await client.get("/api/work/placed", params={
        "company_id": str(task.company_id), "scope": "starred"})
    assert response.status_code == 200 and response.json() == {"items": []}, response.text
    author = await actors[2]["author"].get("/api/work/placed", params={
        "company_id": str(task.company_id), "scope": "starred"})
    assert author.status_code == 200 and len(author.json()["items"]) == 1, author.text
    cleared = await client.post("/api/work/place", json={
        "company_id": str(task.company_id), "target_ref": target, "clear": True})
    assert cleared.status_code == 200 and cleared.json()["mark"] is None, cleared.text
    assert await db.scalar(select(PersonalMark.id).where(PersonalMark.id == mark.id)) is None
    assert await db.scalar(select(PersonalMark.id).where(PersonalMark.id == author_mark.id)) is not None


async def test_missing_task_defer_and_plain_placement_have_same_404(actors, db):
    cid = actors[0][0].id
    for key in (str(uuid.uuid4()), "invalid"):
        for change in ({"starred": True}, {"defer_until": "2099-12-31"}):
            target = f"task:{key}"
            response = await actors[2]["stranger"].post("/api/work/place", json={
                "company_id": str(cid), "target_ref": target, **change})
            assert response.status_code == 404, response.text
            assert await db.scalar(select(PersonalMark.id).where(PersonalMark.target_ref == target)) is None


async def test_wrong_company_closes_all_three_projections(actors, db):
    task = await make(db, actors, "company")
    other_cid = actors[0][1].id
    user = actors[1]["stranger"]
    db.add(UserCompany(user_id=user.id, company_id=other_cid, modules=["docs"]))
    await db.commit()
    client = actors[2]["stranger"]
    for ref in (str(task.id), str(task.number), "SYNTH-1"):
        response = await client.get(f"/api/tasks/{ref}/code", params={"company_id": str(other_cid)})
        assert response.status_code == 404, response.text
    response = await client.post(f"/api/chat/tasks/{task.id}/room",
                                 headers={"X-Company-Id": str(other_cid)})
    assert response.status_code == 404, response.text
    assert await room_snapshot(db, task) == ([], [])
    target = f"task:{task.id}"
    response = await client.post("/api/work/place", json={
        "company_id": str(other_cid), "target_ref": target, "defer_until": "2099-12-31"})
    assert response.status_code == 404, response.text
    assert await db.scalar(select(PersonalMark.id).where(PersonalMark.target_ref == target)) is None
