from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from app.models import (ChatMessage, ChatParticipant, DocCard, DocKind, DocRelation,
    DocSignatureEvidence, DocVersion, EzsSite, EzsSiteDoc, SourceFile, Task, TaskAttachment,
    User, UserCompany, WorkContextResult)
from app.services import project_work, track_files, work_contexts
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def identity(client):
    me = (await client.get("/api/auth/me")).json()
    return uuid.UUID(seed_company_id(me)), uuid.UUID(me["id"])


async def site(db, cid, kind="new_build"):
    row = EzsSite(company_id=cid, title="Тест интеграции", city="Тестовый город", kind=kind, stage="decision")
    db.add(row)
    await db.commit()
    return row


@pytest.mark.parametrize("kind", ["new_build", "procurement", "warehouse", "corporate_client", "retrofit"])
async def test_сообщение_работа_принятие_возврат_в_пять_сценариев(auth_client, db, kind):
    cid, uid = await identity(auth_client)
    project = await site(db, cid, kind)
    room = await auth_client.post("/api/chat/rooms", json={"type": "group", "name": "Общий разговор", "participantIds": []})
    assert room.status_code == 201, room.text
    msg = await auth_client.post(f"/api/chat/rooms/{room.json()['id']}/messages", json={"content": "Подготовить результат проекта"})
    assert msg.status_code == 201, msg.text
    message_id = msg.json()["id"]
    made = await auth_client.post(f"/api/chat/messages/{message_id}/task", json={
        "title": "Подготовить результат", "subjectRef": f"site:{project.id}", "assigneeId": str(uid)})
    assert made.status_code == 201, made.text
    tid = made.json()["taskId"]
    listed = await auth_client.get(f"/api/sites/{project.id}/track", params={"company_id": str(cid)})
    assert listed.status_code == 200, listed.text
    assert tid in {r["id"] for r in listed.json()["items"]}
    assert listed.json()["waiting"] == 0
    origin = await auth_client.get(f"/api/work-contexts/work/task/{tid}/origin", params={"company_id": str(cid)})
    assert origin.json()["origin"]["message_id"] == message_id
    closed = await auth_client.post(f"/api/tasks/{tid}/action", json={"company_id": str(cid), "status": "done", "note": "Результат проверен и принят"})
    assert closed.status_code == 200, closed.text
    queued = await db.scalar(select(WorkContextResult).where(WorkContextResult.entity_id == uuid.UUID(tid)))
    assert queued is not None and queued.delivered_at is None
    pending = await auth_client.get(f"/api/project-workspace/{project.id}", params={"company_id": str(cid)})
    assert tid in {r["id"] for r in pending.json()["pending_results"]["items"]}
    await work_contexts.deliver_pending(db)
    await db.commit()
    result = await auth_client.get(f"/api/project-workspace/{project.id}", params={"company_id": str(cid)})
    assert result.status_code == 200, result.text
    assert any(e["kind"] == "result" for e in result.json()["events"])
    await db.refresh(project)
    assert project.stage == "decision"


async def test_права_в_проекте_и_пагинация(auth_client, db):
    cid, uid = await identity(auth_client)
    project = await site(db, cid)
    other = User(email=f"reader-{uuid.uuid4().hex}@example.test", name="Читатель", company_id=cid,
                 password_hash="test-only", role="user")
    db.add(other)
    await db.flush()
    db.add(UserCompany(user_id=other.id, company_id=cid, role="member"))
    for i in range(105):
        db.add(Task(company_id=cid, title=f"Открытая {i}", subject_ref=f"site:{project.id}",
                    author_id=uid, status="open", visibility="company"))
    db.add(Task(company_id=cid, title="Тайное поручение", subject_ref=f"site:{project.id}",
                author_id=uid, status="open", visibility="private"))
    kind_id = await db.scalar(select(DocKind.id).where(DocKind.company_id == cid).limit(1))
    db.add(DocCard(company_id=cid, kind_id=kind_id, title="Закрытый документ", subject_ref=f"site:{project.id}",
                   author_id=uid, confidentiality="strict"))
    await db.commit()
    page = await project_work.listing(db, cid, other, site=project, offset=100, limit=40)
    assert page["total"] == 105 and len(page["items"]) == 5
    assert all(r["title"].startswith("Открытая") for r in page["items"])


async def test_основной_чат_идемпотентен_и_контракт_не_зависит_от_проектов(auth_client, db):
    cid, _ = await identity(auth_client)
    project = await site(db, cid)
    body = {"ref": f"site:{project.id}", "purpose": "main", "audience": "internal"}
    one = await auth_client.post("/api/work-contexts/room", params={"company_id": str(cid)}, json=body)
    two = await auth_client.post("/api/work-contexts/room", params={"company_id": str(cid)}, json=body)
    assert one.status_code == two.status_code == 200, (one.text, two.text)
    assert one.json()["room_id"] == two.json()["room_id"]
    providers = (await auth_client.get("/api/work-contexts", params={"company_id": str(cid)})).json()["providers"]
    assert {p["prefix"] for p in providers} >= {"site", "object"}


async def test_новая_редакция_не_сохраняет_подпись(auth_client, db, tmp_path):
    from app.services.doc_approvals import _document_snapshot
    cid, uid = await identity(auth_client)
    actor = await db.get(User, uid)
    source_path = tmp_path / "result.txt"
    source_path.write_text("Принятый результат", encoding="utf-8")
    source = SourceFile(company_id=cid, file_name="result.txt", mime_type="text/plain",
                        size=source_path.stat().st_size, storage_path=str(source_path), purpose="attachment")
    kind_id = await db.scalar(select(DocKind.id).where(DocKind.company_id == cid).limit(1))
    doc = DocCard(company_id=cid, kind_id=kind_id, title="Подписанный документ", author_id=uid, status="registered")
    db.add_all([source, doc])
    await db.flush()
    await track_files.initial_version(db, cid, doc, source, actor)
    snapshot, digest = await _document_snapshot(db, doc)
    db.add(DocSignatureEvidence(company_id=cid, doc_id=doc.id, method="internal_direct", signer_id=uid,
        signer_name=actor.name, document_snapshot=snapshot, snapshot_sha256=digest, verification_status="verified"))
    await db.flush()
    assert await track_files.signed_current(db, doc)
    doc.title = "Изменённый документ"
    await db.flush()
    assert not await track_files.signed_current(db, doc)


async def test_следующий_шаг_использует_срок_работы(auth_client, db):
    from app.services import ezs_sites, ezs_project
    cid, uid = await identity(auth_client)
    project = await site(db, cid)
    task = Task(company_id=cid, title="Следующий результат", author_id=uid, subject_ref=f"site:{project.id}",
                due_at=datetime.now(timezone.utc) + timedelta(days=4))
    db.add(task)
    await db.commit()
    r = await auth_client.put(f"/api/project-workspace/{project.id}/next", params={"company_id": str(cid)},
                             json={"work": {"kind": "task", "id": str(task.id)}})
    assert r.status_code == 200, r.text
    task.due_at += timedelta(days=3)
    await db.commit()
    overview = await auth_client.get(f"/api/project-workspace/{project.id}", params={"company_id": str(cid)})
    assert datetime.fromisoformat(overview.json()["next_work"]["due_at"]) == task.due_at
    task.due_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()
    late = await db.scalars(select(EzsSite.id).where(EzsSite.company_id == cid, *ezs_sites._risk_conditions("step_overdue")))
    late_ids = set(late.all())
    assert project.id in late_ids
    no_next = set((await db.scalars(select(EzsSite.id).where(EzsSite.company_id == cid, *ezs_sites._risk_conditions("no_next")))).all())
    assert project.id not in no_next
    portfolio = await ezs_project.portfolio_overview(db, cid)
    attention = portfolio["attention"]
    assert next(item["count"] for item in attention if item["key"] == "step_overdue") == len(late_ids)
    task.status = "done"
    await db.commit()
    assert project.id not in set((await db.scalars(select(EzsSite.id).where(*ezs_sites._risk_conditions("step_overdue")))).all())


async def test_ошибка_приложения_не_отменяет_результат_трека(auth_client, db, monkeypatch):
    cid, uid = await identity(auth_client)
    project = await site(db, cid)
    task = Task(company_id=cid, title="Принятая работа", author_id=uid, subject_ref=f"site:{project.id}")
    db.add(task)
    await db.commit()
    provider, _ = work_contexts.provider_for(f"site:{project.id}")
    original_result = provider.result
    async def unavailable(*args):
        raise RuntimeError("Приложение недоступно")
    monkeypatch.setattr(provider, "result", unavailable)
    r = await auth_client.post(f"/api/tasks/{task.id}/action", json={"company_id": str(cid), "status": "done"})
    assert r.status_code == 200, r.text
    await work_contexts.deliver_pending(db)
    await db.commit()
    row = await db.scalar(select(WorkContextResult).where(WorkContextResult.entity_id == task.id))
    assert row.last_error and row.attempts == 1 and row.delivered_at is None
    await db.refresh(task)
    assert task.status == "done"
    result_view = await auth_client.get(f"/api/work-contexts/work/task/{task.id}/results", params={"company_id": str(cid)})
    assert result_view.json()["items"][0]["error"] is True
    retry = await auth_client.post(f"/api/work-contexts/results/{row.id}/retry", params={"company_id": str(cid)})
    assert retry.status_code == 200, retry.text
    await db.refresh(row)
    assert row.attempts == 0 and row.last_error is None
    monkeypatch.setattr(provider, "result", original_result)
    await work_contexts.deliver_pending(db)
    await db.commit()
    await db.refresh(row)
    assert row.delivered_at is not None


async def test_файл_из_чата_входит_в_согласуемую_редакцию_и_повторно_не_загружается(auth_client, db, tmp_path):
    from app.models import DocApproval, TaskTemplate
    from tests.test_process_templates import _process_template
    cid, uid = await identity(auth_client)
    project = await site(db, cid, "procurement")
    _, template = await _process_template(auth_client)
    path = tmp_path / "offer.txt"
    path.write_text("Предложение поставщика", encoding="utf-8")
    source = SourceFile(company_id=cid, file_name="offer.txt", mime_type="text/plain", purpose="attachment",
                        size=path.stat().st_size, storage_path=str(path))
    db.add(source)
    await db.commit()
    room = (await auth_client.post("/api/chat/rooms", json={"type": "group", "name": "Вложения", "participantIds": []})).json()
    msg = await auth_client.post(f"/api/chat/rooms/{room['id']}/messages", json={
        "type": "file", "content": "Согласовать предложение", "fileUrl": f"/api/files/{source.id}", "fileName": source.file_name})
    assert msg.status_code == 201, msg.text
    mid = msg.json()["id"]
    made = await auth_client.post(f"/api/chat/messages/{mid}/process", json={"templateId": template["id"], "subjectRef": f"site:{project.id}"})
    assert made.status_code == 201, made.text
    did = uuid.UUID(made.json()["docId"])
    version = await db.scalar(select(DocVersion).where(DocVersion.doc_id == did))
    assert version.file_id == source.id
    approval = await db.scalar(select(DocApproval).where(DocApproval.doc_id == did).limit(1))
    assert str(source.id) in {f["file_id"] for f in approval.document_snapshot["files"]}
    added = await auth_client.post("/api/work-contexts/action", params={"company_id": str(cid)}, json={
        "ref": f"site:{project.id}", "action": "file", "message_id": mid})
    assert added.status_code == 200, added.text
    file_link = await db.scalar(select(EzsSiteDoc).where(EzsSiteDoc.site_id == project.id))
    assert file_link.file_id == source.id
    tpl = await db.get(TaskTemplate, uuid.UUID(template["id"]))
    promoted = await auth_client.post(f"/api/project-workspace/{project.id}/promote", params={"company_id": str(cid)},
        json={"file_id": str(file_link.id), "kind_id": str(tpl.doc_kind_id), "title": "Предложение из файла"})
    assert promoted.status_code == 201, promoted.text
    attached = await db.scalar(select(DocVersion).where(DocVersion.doc_id == uuid.UUID(promoted.json()["doc_id"])))
    assert attached.file_id == source.id


async def test_сценарий_требует_реальный_результат_и_защищён_от_повтора(auth_client, db):
    cid, uid = await identity(auth_client)
    project = await site(db, cid, "procurement")
    task = Task(company_id=cid, author_id=uid, title="Потребность подтверждена", subject_ref=f"site:{project.id}", status="open")
    db.add(task)
    await db.commit()
    payload = {"fields": {"need": "Пять устройств", "budget": "1000"}, "advance": True,
               "expected_stage": "need", "evidence": {"kind": "task", "id": str(task.id)}}
    url = f"/api/project-workspace/{project.id}/scenario"
    response = await auth_client.put(url, params={"company_id": str(cid)}, json=payload)
    assert response.status_code == 409, response.text
    task.status = "done"
    await db.commit()
    response = await auth_client.put(url, params={"company_id": str(cid)}, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["scenario"]["stage"] == "approval"
    repeated = await auth_client.put(url, params={"company_id": str(cid)}, json=payload)
    assert repeated.status_code == 409


async def test_переход_к_старому_сообщению_и_граница_истории(auth_client, db):
    cid, uid = await identity(auth_client)
    room = (await auth_client.post("/api/chat/rooms", json={"type": "group", "name": "Давний разговор", "participantIds": []})).json()
    rid = uuid.UUID(room["id"])
    before = datetime.now(timezone.utc) - timedelta(days=5)
    old = ChatMessage(room_id=rid, user_id=uid, user_name="Тест", type="text", content="Исходное сообщение", created_at=before)
    db.add(old)
    for i in range(105):
        db.add(ChatMessage(room_id=rid, user_id=uid, user_name="Тест", type="text", content=f"Сообщение {i}"))
    await db.commit()
    response = await auth_client.get(f"/api/chat/rooms/{rid}/messages", params={"around": str(old.id)})
    assert response.status_code == 200 and response.json()[-1]["id"] == str(old.id)
    participant = await db.scalar(select(ChatParticipant).where(ChatParticipant.room_id == rid, ChatParticipant.user_id == uid))
    participant.history_from = before + timedelta(hours=1)
    await db.commit()
    denied = await auth_client.get(f"/api/chat/rooms/{rid}/messages", params={"around": str(old.id)})
    assert denied.status_code == 404


async def test_новое_приложение_подключает_работу_без_изменений_ядра(auth_client, db, monkeypatch):
    from fastapi import HTTPException
    cid, uid = await identity(auth_client)
    received = []
    class Adapter:
        prefix = "qa_contract"
        application = "qa"
        label = "Проверочное приложение"
        async def resolve(self, db, company, user, key):
            if company != cid or key != "allowed":
                raise HTTPException(404, "Нет доступа к предмету")
            return {"ref": "qa_contract:allowed", "application": "qa", "title": "Заявка приложения",
                    "url": "/qa/allowed", "object_id": None, "defaults": {}, "actions": []}
        async def result(self, db, company, key, work_ref, outcome, result_key):
            received.append((company, key, work_ref, outcome))
    monkeypatch.setitem(work_contexts._providers, "qa_contract", Adapter())
    invalid = await auth_client.post("/api/tasks", json={"company_id": str(cid), "title": "Чужая заявка", "subject_ref": "qa_contract:denied"})
    assert invalid.status_code == 404
    made = await auth_client.post("/api/tasks", json={"company_id": str(cid), "title": "Работа нового приложения", "subject_ref": "qa_contract:allowed", "assignee_id": str(uid)})
    assert made.status_code == 201, made.text
    tid = made.json()["id"]
    refs = await auth_client.get("/api/docs/refs/resolve", params={"company_id": str(cid), "refs": "qa_contract:allowed"})
    assert "Заявка приложения" in refs.text
    done = await auth_client.post(f"/api/tasks/{tid}/action", json={"company_id": str(cid), "status": "done"})
    assert done.status_code == 200, done.text
    await work_contexts.deliver_pending(db)
    await db.commit()
    assert received == [(cid, "allowed", f"task:{tid}", "done")]
    await work_contexts.deliver_pending(db)
    assert len(received) == 1


async def test_наблюдатели_создаются_атомарно_и_не_пересекают_пространства(auth_client, db):
    from app.models import TaskWatcher
    cid, uid = await identity(auth_client)
    project = await site(db, cid)
    before = set((await db.scalars(select(Task.id).where(Task.company_id == cid))).all())
    invalid = await auth_client.post("/api/tasks", json={"company_id": str(cid), "title": "Работа с неверным наблюдателем",
        "subject_ref": f"site:{project.id}", "watcher_ids": [str(uuid.uuid4())]})
    assert invalid.status_code == 400, invalid.text
    assert set((await db.scalars(select(Task.id).where(Task.company_id == cid))).all()) == before
    made = await auth_client.post("/api/tasks", json={"company_id": str(cid), "title": "Работа с наблюдателем",
        "subject_ref": f"site:{project.id}", "watcher_ids": [str(uid), str(uid)]})
    assert made.status_code == 201, made.text
    tid = uuid.UUID(made.json()["id"])
    assert len((await db.scalars(select(TaskWatcher).where(TaskWatcher.task_id == tid))).all()) == 1


async def test_шаблон_этапа_и_команда_становятся_настройками_общих_функций(auth_client, db):
    from tests.test_process_templates import _process_template
    cid, uid = await identity(auth_client)
    project = await site(db, cid, "procurement")
    _, template = await _process_template(auth_client)
    project.owner_user_id = uid
    await db.commit()
    response = await auth_client.put(f"/api/project-workspace/{project.id}/scenario", params={"company_id": str(cid)},
        json={"fields": {}, "templates": {"need": template["id"]}})
    assert response.status_code == 200, response.text
    context = await auth_client.get("/api/work-contexts/resolve", params={"company_id": str(cid), "ref": f"site:{project.id}"})
    assert context.status_code == 200, context.text
    assert context.json()["defaults"]["template_ids"] == [template["id"]]
    assert context.json()["defaults"]["responsible_id"] == str(uid)


async def test_завершённый_сценарий_не_остаётся_активным_или_просроченным(auth_client, db):
    from app.services import ezs_sites, ezs_project
    cid, _ = await identity(auth_client)
    project = await site(db, cid, "warehouse")
    project.workspace_data = {"scenario": {"stage": "done"}}
    project.next_action_due = "2020-01-01"
    await db.commit()
    active = await ezs_sites.list_sites(db, cid, stage="active", search="Тест интеграции", page_size=1000)
    assert str(project.id) not in {row["id"] for row in active["items"]}
    overdue = await ezs_sites.list_sites(db, cid, overdue=True, page_size=1000)
    assert str(project.id) not in {row["id"] for row in overdue["items"]}
    summary = await ezs_sites.sites_overview(db, cid)
    portfolio = await ezs_project.portfolio_overview(db, cid)
    assert summary["active"] == portfolio["active"]
    assert ezs_sites._site_out(project)["stageLabel"] == "Завершено"


async def test_пропавшее_вложение_не_создаёт_поручение_с_битым_файлом(auth_client, db, tmp_path):
    cid, uid = await identity(auth_client)
    source = SourceFile(company_id=cid, file_name="missing.txt", mime_type="text/plain", purpose="attachment",
        size=5, storage_path=str(tmp_path / "absent.txt"))
    db.add(source)
    await db.commit()
    room = (await auth_client.post("/api/chat/rooms", json={"type": "group", "name": "Пропавший файл", "participantIds": []})).json()
    msg = await auth_client.post(f"/api/chat/rooms/{room['id']}/messages", json={"type": "file", "content": "Проверить файл",
        "fileUrl": f"/api/files/{source.id}", "fileName": source.file_name})
    response = await auth_client.post(f"/api/chat/messages/{msg.json()['id']}/task", json={"assigneeId": str(uid)})
    assert response.status_code == 409, response.text


async def test_исполнение_документа_возвращает_результат_приложению(auth_client, db):
    cid, uid = await identity(auth_client)
    project = await site(db, cid)
    kind_id = await db.scalar(select(DocKind.id).where(DocKind.company_id == cid).limit(1))
    doc = DocCard(company_id=cid, kind_id=kind_id, title="Документ исполнен", author_id=uid,
        status="in_force", approval_status="approved", subject_ref=f"site:{project.id}")
    db.add(doc)
    await db.commit()
    response = await auth_client.post(f"/api/docs/{doc.id}/action", json={"company_id": str(cid), "status": "executed"})
    assert response.status_code == 200, response.text
    row = await db.scalar(select(WorkContextResult).where(WorkContextResult.entity_id == doc.id))
    assert row is not None and row.outcome == "done"
