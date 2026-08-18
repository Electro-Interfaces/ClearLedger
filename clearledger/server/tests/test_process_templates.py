import uuid

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _me(client: AsyncClient) -> dict:
    response = await client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={
        "email": email,
        "password": password,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _process_template(client: AsyncClient) -> tuple[str, dict]:
    me = await _me(client)
    cid = me["companies"][0]["id"]
    kind_response = await client.post("/api/docs/kinds", json={
        "company_id": cid,
        "code": f"chat_{uuid.uuid4().hex[:10]}",
        "name": "Процесс из чата",
        "number_template": "{prefix}-{yyyy}-{n:04d}",
        "number_scope": "kind_year",
        "requires_registration": False,
        "route": [{
            "code": "manager",
            "name": "Решение менеджера",
            "mode": "serial",
            "quorum": "all",
            "actors": [{"by": "user", "ref": me["id"]}],
        }],
    })
    assert kind_response.status_code == 201, kind_response.text
    kind = kind_response.json()
    template_response = await client.post("/api/tasks/templates", json={
        "company_id": cid,
        "name": "Разобрать обращение",
        "title": "Разобрать обращение из рабочего чата",
        "description": "Проверить основание и принять решение",
        "doc_kind_id": kind["id"],
        "assignee_id": me["id"],
        "due_days": 2,
    })
    assert template_response.status_code == 201, template_response.text
    return cid, template_response.json()


async def test_шаблон_документа_запускает_маршрут(auth_client: AsyncClient):
    cid, template = await _process_template(auth_client)

    listed = await auth_client.get(
        "/api/docs/process-templates", params={"company_id": cid})
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["templates"]
               if item["id"] == template["id"])
    assert row["kind"] == "document"
    assert row["steps"] == 1
    assert row["requiresPreparation"] is False

    started = await auth_client.post(
        f"/api/tasks/templates/{template['id']}/use",
        params={"company_id": cid},
    )
    assert started.status_code == 201, started.text
    result = started.json()
    assert result["kind"] == "document"
    assert result["started"] is True
    assert result["state"] == "approval"

    card_response = await auth_client.get(
        f"/api/docs/{result['docId']}", params={"company_id": cid})
    assert card_response.status_code == 200, card_response.text
    card = card_response.json()
    assert card["approval_status"] == "pending"
    assert card["responsible_id"]


async def test_сообщение_запускает_процесс_и_оставляет_ссылку(
    auth_client: AsyncClient,
):
    cid, template = await _process_template(auth_client)
    room_response = await auth_client.post("/api/chat/rooms", json={
        "type": "group",
        "name": "Рабочее обсуждение процесса",
    })
    assert room_response.status_code == 201, room_response.text
    room = room_response.json()
    message_response = await auth_client.post(
        f"/api/chat/rooms/{room['id']}/messages",
        json={"content": "Нужно согласовать изменение условий договора"},
    )
    assert message_response.status_code == 201, message_response.text
    message = message_response.json()

    old_action = await auth_client.post(
        f"/api/chat/messages/{message['id']}/task", json={})
    assert old_action.status_code == 404

    launched = await auth_client.post(
        f"/api/chat/messages/{message['id']}/process",
        json={"templateId": template["id"]},
    )
    assert launched.status_code == 201, launched.text
    result = launched.json()
    assert result["started"] is True
    assert f"doc={result['docId']}" in result["documentUrl"]

    duplicate = await auth_client.post(
        f"/api/chat/messages/{message['id']}/process",
        json={"templateId": template["id"]},
    )
    assert duplicate.status_code == 409

    messages = await auth_client.get(f"/api/chat/rooms/{room['id']}/messages")
    assert messages.status_code == 200, messages.text
    note = next(item for item in messages.json()
                if item.get("replyTo") == message["id"] and "Запущен процесс" in item["content"])
    assert result["documentUrl"] in note["content"]


async def test_стандартный_процесс_из_чата_создаёт_задачу(
    auth_client: AsyncClient,
):
    me = await _me(auth_client)
    cid = me["companies"][0]["id"]
    templates = (await auth_client.get(
        "/api/docs/process-templates", params={"company_id": cid})).json()["templates"]
    template = next(item for item in templates
                    if item["name"] == "Стандартное выполнение задачи")
    assert template["kind"] == "task"
    assert template["capabilities"] == ["assign", "transfer", "comments", "files"]

    room = (await auth_client.post("/api/chat/rooms", json={
        "type": "group",
        "name": "Обсуждение внутренней задачи",
    })).json()
    message = (await auth_client.post(
        f"/api/chat/rooms/{room['id']}/messages",
        json={"content": "Подготовить ответ сотрудникам до пятницы"},
    )).json()
    launched = await auth_client.post(
        f"/api/chat/messages/{message['id']}/process",
        json={"templateId": template["id"], "title": "Подготовить ответ сотрудникам"},
    )
    assert launched.status_code == 201, launched.text
    result = launched.json()
    assert result["kind"] == "task"
    assert result["state"] == "task"
    assert result["taskNumber"] > 0
    assert f"task={result['taskId']}" in result["taskUrl"]

    duplicate = await auth_client.post(
        f"/api/chat/messages/{message['id']}/process",
        json={"templateId": template["id"]},
    )
    assert duplicate.status_code == 409
    card = await auth_client.get(
        f"/api/tasks/{result['taskId']}", params={"company_id": cid})
    assert card.status_code == 200, card.text
    assert "Обсуждение внутренней задачи" in card.json()["description"]


async def test_сотрудники_запускают_передают_комментируют_и_прикладывают_файлы(
    auth_client: AsyncClient,
):
    from app.auth import hash_password
    from app.database import async_session_factory
    from app.models import User, UserCompany

    me = await _me(auth_client)
    cid = uuid.UUID(me["companies"][0]["id"])
    password = "process-test-123"
    people = [User(
        company_id=cid,
        email=f"process-{role}-{uuid.uuid4().hex[:8]}@test.ru",
        password_hash=hash_password(password),
        name=name,
        role="user",
    ) for role, name in (
        ("author", "Инициатор процесса"),
        ("first", "Первый исполнитель"),
        ("next", "Следующий исполнитель"),
    )]
    async with async_session_factory() as db:
        db.add_all(people)
        await db.flush()
        db.add_all([UserCompany(
            user_id=person.id,
            company_id=cid,
            role="user",
            modules=["docs"],
        ) for person in people])
        await db.commit()

    author_headers = await _login(auth_client, people[0].email, password)
    first_headers = await _login(auth_client, people[1].email, password)
    next_headers = await _login(auth_client, people[2].email, password)
    templates_response = await auth_client.get(
        "/api/docs/process-templates",
        params={"company_id": str(cid)},
        headers=author_headers,
    )
    assert templates_response.status_code == 200, templates_response.text
    template = next(item for item in templates_response.json()["templates"]
                    if item["name"] == "Стандартное выполнение задачи")

    launched = await auth_client.post(
        f"/api/docs/process-templates/{template['id']}/start",
        json={
            "company_id": str(cid),
            "responsible_id": str(people[1].id),
            "title": "Проверить внутренний документ",
        },
        headers=author_headers,
    )
    assert launched.status_code == 201, launched.text
    task = launched.json()
    assert task["kind"] == "task"

    comment = await auth_client.post(
        f"/api/tasks/{task['taskId']}/action",
        json={"company_id": str(cid), "note": "Добавляю материалы для работы"},
        headers=next_headers,
    )
    assert comment.status_code == 200, comment.text
    attached = await auth_client.post(
        f"/api/tasks/{task['taskId']}/attachments",
        params={"company_id": str(cid)},
        files={"file": ("материалы.txt", b"process evidence", "text/plain")},
        headers=next_headers,
    )
    assert attached.status_code == 201, attached.text

    handed_off = await auth_client.post(
        f"/api/tasks/{task['taskId']}/action",
        json={
            "company_id": str(cid),
            "stage_code": "in_progress",
            "assignee_id": str(people[2].id),
            "note": "Передаю следующий шаг",
        },
        headers=first_headers,
    )
    assert handed_off.status_code == 200, handed_off.text
    finished = await auth_client.post(
        f"/api/tasks/{task['taskId']}/action",
        json={
            "company_id": str(cid),
            "stage_code": "review",
            "status": "done",
            "note": "Работа выполнена",
        },
        headers=next_headers,
    )
    assert finished.status_code == 200, finished.text

    card = (await auth_client.get(
        f"/api/tasks/{task['taskId']}",
        params={"company_id": str(cid)},
        headers=author_headers,
    )).json()
    assert card["status"] == "done"
    assert card["assignee_id"] == str(people[2].id)
    assert [item["file_name"] for item in card["attachments"]] == ["материалы.txt"]
    assert {event["kind"] for event in card["events"]} >= {
        "created", "assign", "comment", "stage", "status",
    }


async def test_менеджер_видит_шаблон_только_в_пределах_прав(
    auth_client: AsyncClient,
):
    from app.database import async_session_factory
    from app.models import DocAccessGrant, TaskTemplate, User, UserCompany
    from app.services.process_templates import can_launch_kind

    cid, template = await _process_template(auth_client)
    manager = User(
        company_id=uuid.UUID(cid),
        email=f"manager-{uuid.uuid4().hex[:10]}@example.test",
        password_hash="not-used",
        name="Менеджер процесса",
        role="user",
    )
    async with async_session_factory() as db:
        db.add(manager)
        await db.flush()
        db.add(UserCompany(
            user_id=manager.id,
            company_id=uuid.UUID(cid),
            role="user",
        ))
        await db.flush()
        tpl = await db.get(TaskTemplate, uuid.UUID(template["id"]))
        assert tpl is not None and tpl.doc_kind_id is not None

        assert await can_launch_kind(db, uuid.UUID(cid), tpl.doc_kind_id, manager) is True

        db.add(DocAccessGrant(
            company_id=uuid.UUID(cid),
            scope_type="kind",
            scope_id=tpl.doc_kind_id,
            subject_type="user",
            subject_id=uuid.uuid4(),
            permissions=["edit"],
            denied_permissions=[],
        ))
        await db.flush()
        assert await can_launch_kind(db, uuid.UUID(cid), tpl.doc_kind_id, manager) is False

        manager_grant = DocAccessGrant(
            company_id=uuid.UUID(cid),
            scope_type="kind",
            scope_id=tpl.doc_kind_id,
            subject_type="user",
            subject_id=manager.id,
            permissions=["edit"],
            denied_permissions=[],
        )
        db.add(manager_grant)
        await db.flush()
        assert await can_launch_kind(db, uuid.UUID(cid), tpl.doc_kind_id, manager) is True

        manager_grant.denied_permissions = ["read"]
        await db.flush()
        assert await can_launch_kind(db, uuid.UUID(cid), tpl.doc_kind_id, manager) is False
