"""Следующая очередь «Трека»: поиск, права и письмо в документ."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Counterparty, Department, DocAccessGrant, DocAcquaint, DocCard, DocVersion,
    MailAttachment, MailMessage, User, UserCompany,
)
from app.routers import docs_router
from app.services import mail_routing, task_scheduler

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _context(client: AsyncClient) -> tuple[dict, str, dict]:
    me = (await client.get("/api/auth/me")).json()
    cid = me["companies"][0]["id"]
    starter = await client.post(f"/api/docs/kinds/starter?company_id={cid}")
    assert starter.status_code in (200, 201), starter.text
    kinds = (await client.get("/api/docs/kinds", params={"company_id": cid})).json()["kinds"]
    return me, cid, next(item for item in kinds if item["code"] == "doc_in")


async def test_реестр_ищет_по_тексту_файла(auth_client: AsyncClient):
    _, cid, kind = await _context(auth_client)
    marker = f"телемеханика-{uuid.uuid4().hex}"
    created = await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Без маркера в заголовке",
    })
    assert created.status_code == 201, created.text
    doc = created.json()
    uploaded = await auth_client.post(
        f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("письмо.txt", f"Сведения: {marker}".encode(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text

    found = await auth_client.get("/api/docs", params={"company_id": cid, "q": marker})
    assert found.status_code == 200, found.text
    assert doc["id"] in {item["id"] for item in found.json()["docs"]}


async def test_право_на_документ_и_вид_открывает_закрытую_карточку(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    created = await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"], "title": "Закрытый приказ",
        "confidentiality": "private",
    })
    assert created.status_code == 201, created.text
    doc = await db.get(DocCard, uuid.UUID(created.json()["id"]))

    user = User(
        company_id=cid, email=f"doc-{uuid.uuid4().hex}@example.org",
        name="Сотрудник делопроизводства", password_hash="!",
    )
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid, role="user", modules=["docs"]))
    await db.commit()

    assert await docs_router._can_doc(db, cid, doc, user, "read") is False
    acquaint = DocAcquaint(
        company_id=cid, doc_id=doc.id, user_id=user.id, created_by=uuid.UUID(me["id"]),
    )
    db.add(acquaint)
    await db.commit()
    assert await docs_router._can_doc(db, cid, doc, user, "read") is True
    await db.delete(acquaint)
    await db.commit()
    assert await docs_router._can_doc(db, cid, doc, user, "read") is False

    db.add(DocAccessGrant(
        company_id=cid, scope_type="doc", scope_id=doc.id,
        subject_type="user", subject_id=user.id, permissions=["read"],
        created_by=uuid.UUID(me["id"]),
    ))
    db.add(DocAccessGrant(
        company_id=cid, scope_type="kind", scope_id=doc.kind_id,
        subject_type="user", subject_id=user.id, permissions=["edit"],
        created_by=uuid.UUID(me["id"]),
    ))
    await db.commit()

    assert await docs_router._can_doc(db, cid, doc, user, "read") is True
    assert await docs_router._can_doc(db, cid, doc, user, "edit") is True


async def test_письмо_известного_контрагента_становится_одним_черновиком(
        auth_client: AsyncClient, db: AsyncSession):
    _, cid_raw, _ = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    counterparty = Counterparty(
        company_id=cid, inn=str(uuid.uuid4().int)[:12], name="ООО Входящий тест",
    )
    db.add(counterparty)
    await db.flush()
    message = MailMessage(
        company_id=cid, direction="in", message_id=f"<{uuid.uuid4()}@example.org>",
        subject="Акт сверки", from_name="Контрагент", from_email="docs@example.org",
        body_text="Вложение содержит контрольную фразу.", has_attachments=True,
        counterparty_id=counterparty.id,
    )
    db.add(message)
    await db.flush()
    content = "Контрольная фраза входящего документа".encode()
    db.add(MailAttachment(
        company_id=cid, message_id=message.id, file_name="акт.txt",
        content_type="text/plain", size=len(content),
        sha256=hashlib.sha256(content).hexdigest(), content=content,
    ))
    await db.commit()

    for _ in range(2):
        assert await mail_routing.to_doc(db, cid, message) is True
        await db.commit()

    docs = (await db.execute(select(DocCard).where(
        DocCard.company_id == cid, DocCard.source == "mail",
        DocCard.source_ref == f"mail:{message.message_id}",
    ))).scalars().all()
    assert len(docs) == 1
    assert docs[0].status == "draft" and docs[0].counterparty_id == counterparty.id
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == docs[0].id,
    ))).scalars().all()
    assert len(versions) == 1
    assert "Контрольная фраза" in (versions[0].content_text or "")


async def test_отчёт_считает_завершённое_согласование(
        auth_client: AsyncClient):
    me, cid, kind = await _context(auth_client)
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-отчёт-{uuid.uuid4().hex}",
    })).json()
    registered = await auth_client.post(
        f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    assert registered.status_code == 200, registered.text
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid,
        "route": [{
            "code": "test", "name": "Проверка", "mode": "serial", "quorum": "all",
            "actors": [{"by": "user", "ref": me["id"]}],
        }],
    })
    assert started.status_code == 201, started.text
    mine = (await auth_client.get(
        "/api/docs/approvals/mine", params={"company_id": cid})).json()["approvals"]
    approval = next(item for item in mine if item["doc_id"] == doc["id"])
    decided = await auth_client.post(f"/api/docs/approvals/{approval['id']}", json={
        "company_id": cid, "approved": True,
    })
    assert decided.status_code == 200, decided.text

    today = datetime.now(timezone.utc).date().isoformat()
    report = await auth_client.get("/api/docs/reports/discipline", params={
        "company_id": cid, "date_from": today, "date_to": today,
    })
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["summary"]["completed"] >= 1
    assert any(row["user_id"] == me["id"] and row["decisions"] >= 1
               for row in data["people"])


async def test_подразделение_получает_ознакомление_и_напоминание(
        auth_client: AsyncClient, db: AsyncSession, monkeypatch):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    department = Department(company_id=cid, name=f"Проверка {uuid.uuid4().hex[:8]}")
    person = User(
        company_id=cid, email=f"acquaint-{uuid.uuid4().hex}@example.org",
        name="Получатель ознакомления", password_hash="!",
    )
    db.add_all([department, person])
    await db.flush()
    db.add(UserCompany(
        user_id=person.id, company_id=cid, role="user", modules=["docs"],
        department_id=department.id,
    ))
    await db.commit()
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-ознакомление-{uuid.uuid4().hex}",
    })).json()
    now = datetime.now(timezone.utc)
    added = await auth_client.post(f"/api/docs/{doc['id']}/acquaint", json={
        "company_id": cid_raw, "user_ids": [], "department_id": str(department.id),
        "due_at": (now + timedelta(hours=12)).isoformat(),
    })
    assert added.status_code == 201 and added.json()["added"] == 1, added.text

    notices: list[tuple[list[str], str, str]] = []
    monkeypatch.setattr(
        task_scheduler.task_mail, "send_notice_async",
        lambda emails, subject, text: notices.append((emails, subject, text)),
    )
    sent = await task_scheduler.run_acquaint_reminders(db, now)
    assert sent >= 1
    assert any(person.email in emails and doc["title"] in subject
               for emails, subject, _ in notices)
    row = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == uuid.UUID(doc["id"]),
        DocAcquaint.user_id == person.id,
    ))).scalar_one()
    assert row.reason == "department" and row.reminded_at is not None
    assert row.created_by == uuid.UUID(me["id"])
    await db.commit()


async def test_расписание_сэд_включается_только_после_ручной_проверки(
        auth_client: AsyncClient, tmp_path):
    _, cid, _ = await _context(auth_client)
    code = f"test-{uuid.uuid4().hex[:8]}"
    created = await auth_client.post("/api/docs/exchange/targets", json={
        "company_id": cid, "code": code, "name": "Проверка папки",
        "system": "other", "inbox_path": str(tmp_path), "outbox_path": "",
    })
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    before = await auth_client.put(f"/api/docs/exchange/targets/{target_id}/schedule", json={
        "company_id": cid, "enabled": True, "interval_min": 15,
    })
    assert before.status_code == 409
    scanned = await auth_client.post(
        "/api/docs/exchange/scan", params={"company_id": cid, "target_id": target_id})
    assert scanned.status_code == 200 and scanned.json()["errors"] == [], scanned.text
    after = await auth_client.put(f"/api/docs/exchange/targets/{target_id}/schedule", json={
        "company_id": cid, "enabled": True, "interval_min": 15,
    })
    assert after.status_code == 200 and after.json()["enabled"] is True
