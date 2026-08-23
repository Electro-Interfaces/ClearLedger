"""Следующая очередь «Трека»: поиск, права и письмо в документ."""
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Company, Counterparty, Department, DocAccessGrant, DocAcquaint, DocApproval,
    DocCard, DocCase, DocEvent, DocInboxItem, DocKind, DocSignatureEvidence,
    DocVersion, MailAttachment, MailMessage, Organization, User, UserCompany,
)
from app.routers import docs_router
from app.services import mail_routing, task_scheduler
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _context(client: AsyncClient) -> tuple[dict, str, dict]:
    me = (await client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
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


async def test_мои_документы_не_подменяются_общим_реестром(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    mine = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-мой-{uuid.uuid4().hex}",
    })).json()
    company = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-чужой-{uuid.uuid4().hex}",
    })).json()
    other = User(
        company_id=cid, email=f"other-{uuid.uuid4().hex}@example.org",
        name="Другой автор", password_hash="!",
    )
    db.add(other)
    await db.flush()
    company_doc = await db.get(DocCard, uuid.UUID(company["id"]))
    company_doc.author_id = other.id
    company_doc.responsible_id = None
    await db.commit()

    result = await auth_client.get("/api/docs", params={
        "company_id": cid_raw, "mine": "true",
    })
    assert result.status_code == 200, result.text
    ids = {item["id"] for item in result.json()["docs"]}
    assert mine["id"] in ids
    assert company["id"] not in ids
    assert me["id"] != str(other.id)


async def test_мои_документы_можно_листать(auth_client: AsyncClient):
    _, cid, kind = await _context(auth_client)
    marker = f"ПРОВЕРКА-листание-{uuid.uuid4().hex}"
    for index in range(3):
        created = await auth_client.post("/api/docs", json={
            "company_id": cid, "kind_id": kind["id"],
            "title": f"{marker}-{index}",
        })
        assert created.status_code == 201, created.text

    first = (await auth_client.get("/api/docs", params={
        "company_id": cid, "mine": "true", "q": marker, "limit": 1,
    })).json()["docs"]
    second = (await auth_client.get("/api/docs", params={
        "company_id": cid, "mine": "true", "q": marker, "limit": 1, "offset": 1,
    })).json()["docs"]
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]


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


async def test_допуск_к_визе_и_подписанию_не_подменяет_назначение(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    principal = User(
        company_id=cid, email=f"principal-{uuid.uuid4().hex}@example.org",
        name="Назначенный участник", password_hash="!",
    )
    outsider = User(
        company_id=cid, email=f"outsider-{uuid.uuid4().hex}@example.org",
        name="Посторонний участник", password_hash="!",
    )
    db.add_all([principal, outsider])
    await db.flush()
    db.add_all([
        UserCompany(user_id=principal.id, company_id=cid, role="user", modules=["docs"]),
        UserCompany(user_id=outsider.id, company_id=cid, role="user", modules=["docs"]),
    ])
    doc = DocCard(
        company_id=cid, kind_id=uuid.UUID(kind["id"]), kind_code=kind["code"],
        family=kind["family"], direction=kind["direction"], title="Закрытый маршрут",
        confidentiality="private", author_id=uuid.UUID(me["id"]),
        signatory_id=principal.id, approval_status="pending", approval_round=1,
    )
    db.add(doc)
    await db.flush()
    approval = DocApproval(
        company_id=cid, doc_id=doc.id, round=1, step_no=1,
        step_code="legal", step_name="Юристы", mode="serial", quorum="all",
        assignee_id=principal.id, status="pending",
    )
    db.add(approval)
    await db.commit()

    assert await docs_router._can_doc(db, cid, doc, principal, "approve") is True
    assert await docs_router._can_doc(db, cid, doc, principal, "sign") is True

    policy = DocAccessGrant(
        company_id=cid, scope_type="doc", scope_id=doc.id,
        subject_type="user", subject_id=outsider.id,
        permissions=["approve", "sign"], created_by=uuid.UUID(me["id"]),
    )
    db.add(policy)
    await db.commit()

    assert await docs_router._can_doc(db, cid, doc, outsider, "read") is False
    assert await docs_router._can_doc(db, cid, doc, principal, "approve") is False
    assert await docs_router._can_doc(db, cid, doc, principal, "sign") is False
    assert await docs_router._can_doc(db, cid, doc, outsider, "approve") is False
    assert await docs_router._can_doc(db, cid, doc, outsider, "sign") is False

    policy.subject_id = principal.id
    await db.commit()
    assert await docs_router._can_doc(db, cid, doc, principal, "approve") is True
    assert await docs_router._can_doc(db, cid, doc, principal, "sign") is True


async def test_администратор_управляет_acl_но_не_читает_закрытую_карточку(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    admin = User(
        company_id=cid, email=f"acl-admin-{uuid.uuid4().hex}@example.org",
        name="Администратор доступа", password_hash="!",
    )
    editor = User(
        company_id=cid, email=f"acl-editor-{uuid.uuid4().hex}@example.org",
        name="Редактор", password_hash="!",
    )
    db.add_all([admin, editor])
    await db.flush()
    db.add_all([
        UserCompany(user_id=admin.id, company_id=cid, role="admin"),
        UserCompany(user_id=editor.id, company_id=cid, role="user", modules=["docs"]),
    ])
    doc = DocCard(
        company_id=cid, kind_id=uuid.UUID(kind["id"]), kind_code=kind["code"],
        family=kind["family"], direction=kind["direction"], title="Кадровый приказ",
        confidentiality="private", author_id=uuid.UUID(me["id"]),
    )
    db.add(doc)
    await db.flush()
    db.add(DocAccessGrant(
        company_id=cid, scope_type="doc", scope_id=doc.id,
        subject_type="user", subject_id=editor.id, permissions=["edit"],
        created_by=uuid.UUID(me["id"]),
    ))
    await db.commit()

    assert await docs_router._can_manage_doc_access(db, cid, doc, admin) is True
    assert await docs_router._can_doc(db, cid, doc, admin, "read") is False
    assert await docs_router._can_doc(db, cid, doc, admin, "edit") is False
    assert await docs_router._can_doc(db, cid, doc, editor, "edit") is True
    assert await docs_router._can_manage_doc_access(db, cid, doc, editor) is False
    for field in ("responsible_id", "signatory_id"):
        with pytest.raises(HTTPException) as denied:
            await docs_router.doc_action(
                str(doc.id),
                docs_router.ActionIn(
                    company_id=cid_raw, **{field: str(editor.id)}),
                db, editor,
            )
        assert denied.value.status_code == 403

async def test_сырой_файл_сэд_доступен_только_делопроизводителю(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    member = User(
        company_id=cid, email=f"inbox-{uuid.uuid4().hex}@example.org",
        name="Обычный участник", password_hash="!",
    )
    db.add(member)
    await db.flush()
    db.add(UserCompany(
        user_id=member.id, company_id=cid, role="user", modules=["docs"],
    ))
    file_id = uuid.uuid4()
    item = DocInboxItem(
        company_id=cid, file_name="входящий.pdf", source_path="/tmp/incoming.pdf",
        size_bytes=10, sha256=uuid.uuid4().hex * 2, file_id=file_id,
        parsed={"title": "Сырые данные"}, status="new",
    )
    db.add(item)
    await db.commit()

    assert await docs_router._can_process_inbox(db, cid, member) is False
    with pytest.raises(HTTPException) as denied:
        await docs_router.authorize_docs_file_download(db, member, file_id)
    assert denied.value.status_code == 404

    db.add(DocAccessGrant(
        company_id=cid, scope_type="kind", scope_id=uuid.UUID(kind["id"]),
        subject_type="user", subject_id=member.id, permissions=["edit"],
        created_by=uuid.UUID(me["id"]),
    ))
    await db.commit()
    assert await docs_router._can_process_inbox(db, cid, member) is True
    await docs_router.authorize_docs_file_download(db, member, file_id)

    kinds = (await auth_client.get(
        "/api/docs/kinds", params={"company_id": cid_raw})).json()["kinds"]
    non_incoming = next(value for value in kinds if value["family"] != "incoming")
    bad_item = DocInboxItem(
        company_id=cid, file_name="неверный-вид.pdf", source_path="/tmp/wrong.pdf",
        size_bytes=10, sha256=uuid.uuid4().hex * 2,
        parsed={"title": "Не входящий"}, status="new",
    )
    db.add(bad_item)
    await db.commit()
    rejected_kind = await auth_client.post(
        f"/api/docs/exchange/inbox/{bad_item.id}",
        json={
            "company_id": cid_raw, "accept": True,
            "kind_id": non_incoming["id"],
        },
    )
    assert rejected_kind.status_code == 400, rejected_kind.text


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

    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    report = await auth_client.get("/api/docs/reports/discipline", params={
        "company_id": cid, "date_from": today, "date_to": today,
    })
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["summary"]["completed"] >= 1
    assert any(row["user_id"] == me["id"] and row["decisions"] >= 1
               for row in data["people"])


async def test_подписание_отличается_от_визы_и_фиксирует_точный_пакет(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid, kind = await _context(auth_client)
    created = await auth_client.post("/api/docs", json={
        "company_id": cid,
        "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-подпись-{uuid.uuid4().hex}",
        "signatory_id": me["id"],
    })
    assert created.status_code == 201, created.text
    doc = created.json()
    registered = await auth_client.post(
        f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    assert registered.status_code == 200, registered.text
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid,
        "route": [{
            "code": "sign", "name": "Подписание", "step_kind": "sign",
            "mode": "serial", "quorum": "all",
            "actors": [{"by": "user", "ref": me["id"]}],
        }],
    })
    assert started.status_code == 201, started.text

    mine = (await auth_client.get(
        "/api/docs/approvals/mine", params={"company_id": cid})).json()["approvals"]
    approval = next(item for item in mine if item["doc_id"] == doc["id"])
    assert approval["step_kind"] == "sign"
    decided = await auth_client.post(f"/api/docs/approvals/{approval['id']}", json={
        "company_id": cid, "approved": True,
    })
    assert decided.status_code == 200, decided.text

    card = (await auth_client.get(
        f"/api/docs/{doc['id']}", params={"company_id": cid})).json()
    row = next(item for item in card["approval"]["rows"]
               if item["id"] == approval["id"])
    assert row["step_kind"] == "sign"
    route_evidence = next(item for item in card["signatures"]
                          if item["method"] == "internal_approval")
    assert route_evidence["approval_id"] == approval["id"]
    assert route_evidence["snapshot_sha256"] == card["approval"]["snapshot_sha256"]
    assert route_evidence["verification_status"] == "verified"

    enacted = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
        "company_id": cid, "status": "in_force",
    })
    assert enacted.status_code == 200, enacted.text
    evidence = (await db.execute(select(DocSignatureEvidence).where(
        DocSignatureEvidence.doc_id == uuid.UUID(doc["id"]),
    ))).scalars().all()
    assert {item.method for item in evidence} == {
        "internal_approval", "internal_direct",
    }
    assert all(item.signer_id == uuid.UUID(me["id"]) for item in evidence)
    assert all(item.document_snapshot.get("card", {}).get("id") == doc["id"]
               for item in evidence)


async def test_отчёт_различает_круги_активацию_и_текущую_просрочку(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid_raw, _ = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    user_id = uuid.UUID(me["id"])
    cohort_day = datetime.now(timezone.utc).date() - timedelta(days=200)
    started = datetime.combine(cohort_day, datetime.min.time(), tzinfo=timezone.utc)
    deputy = User(
        company_id=cid, email=f"deputy-{uuid.uuid4().hex}@example.org",
        name="Заместитель", password_hash="!",
    )
    outsider = User(
        email=f"outsider-{uuid.uuid4().hex}@example.org",
        name="Чужой пользователь", password_hash="!",
    )
    kind = DocKind(
        company_id=cid, code=f"report_{uuid.uuid4().hex[:10]}",
        name=f"Проверка отчёта {uuid.uuid4().hex[:10]}", family="internal",
        direction="none", fields=[], route=[],
    )
    db.add_all([kind, deputy, outsider])
    await db.flush()
    db.add(UserCompany(
        user_id=deputy.id, company_id=cid, role="user", modules=["docs"],
    ))
    approved = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Первый круг", status="archived",
        approval_status="approved", approval_round=1,
    )
    repeated = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Повторный круг", status="registered",
        approval_status="approved", approval_round=2,
    )
    waiting = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Старая текущая просрочка", status="registered",
        approval_status="pending", approval_round=1,
    )
    outside = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Просрочка вне когорты", status="registered",
        approval_status="pending", approval_round=1,
    )
    cancelled = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Отменённый круг", status="registered",
        approval_status="none", approval_round=1,
    )
    db.add_all([approved, repeated, waiting, outside, cancelled])
    await db.flush()

    def approval(doc: DocCard, round_no: int, state: str, activated: datetime,
                 decided: datetime | None = None, due: datetime | None = None,
                 decided_by: uuid.UUID | None = None):
        return DocApproval(
            company_id=cid, doc_id=doc.id, round=round_no, step_no=1,
            step_code="test", step_name="Проверка", mode="serial", quorum="all",
            actor_kind="user", assignee_id=user_id, required=True, status=state,
            created_at=activated, activated_at=activated, decided_at=decided,
            decided_by=(decided_by or user_id) if decided else None, due_at=due,
        )

    db.add_all([
        approval(approved, 1, "approved", started, started + timedelta(hours=2),
                 started + timedelta(hours=1), deputy.id),
        approval(repeated, 1, "rejected", started, started + timedelta(hours=1)),
        approval(repeated, 2, "approved", started + timedelta(days=2),
                 started + timedelta(days=2, hours=3)),
        approval(waiting, 1, "pending", started,
                 due=datetime.now(timezone.utc) - timedelta(hours=1)),
        approval(outside, 1, "pending", started - timedelta(days=10),
                 due=datetime.now(timezone.utc) - timedelta(hours=2)),
        approval(cancelled, 1, "skipped", started),
    ])
    await db.commit()

    report = await auth_client.get("/api/docs/reports/discipline", params={
        "company_id": cid_raw,
        "date_from": cohort_day.isoformat(),
        "date_to": cohort_day.isoformat(),
    })
    assert report.status_code == 200, report.text
    data = report.json()
    kind_row = next(row for row in data["by_kind"] if row["kind_id"] == str(kind.id))
    assert kind_row["documents"] == 2
    assert kind_row["average_hours"] == 26.5
    assert data["summary"]["first_pass_sample"] == 2
    assert data["summary"]["first_pass_rate"] == 50
    assert data["summary"]["documents"] == 4
    assert data["backlog"]["pending"] >= 2
    assert data["backlog"]["overdue"] >= 2
    deputy_row = next(row for row in data["people"] if row["user_id"] == str(deputy.id))
    assert deputy_row["decisions"] == 1
    assert deputy_row["documents"] == 1
    assert deputy_row["late_documents"] == 1
    assert deputy_row["late_decisions"] == 1
    assert deputy_row["delegated_decisions"] == 1

    detail = await auth_client.get("/api/docs/board", params={
        "company_id": cid_raw, "kind_id": str(kind.id),
        "cohort_from": cohort_day.isoformat(), "cohort_to": cohort_day.isoformat(),
        "report_metric": "late_decisions", "decision_by": str(deputy.id),
    })
    assert detail.status_code == 200, detail.text
    assert detail.json()["total"] == 1
    assert detail.json()["columns"][0]["docs"][0]["id"] == str(approved.id)

    completed_detail = await auth_client.get("/api/docs/board", params={
        "company_id": cid_raw, "kind_id": str(kind.id),
        "cohort_from": cohort_day.isoformat(), "cohort_to": cohort_day.isoformat(),
        "report_metric": "completed",
    })
    assert completed_detail.status_code == 200, completed_detail.text
    completed_ids = {
        item["id"] for column in completed_detail.json()["columns"]
        for item in column["docs"]
    }
    assert completed_ids == {str(approved.id), str(repeated.id)}

    cancelled_detail = await auth_client.get("/api/docs/board", params={
        "company_id": cid_raw, "kind_id": str(kind.id),
        "cohort_from": cohort_day.isoformat(), "cohort_to": cohort_day.isoformat(),
        "report_metric": "cancelled",
    })
    assert cancelled_detail.status_code == 200, cancelled_detail.text
    assert cancelled_detail.json()["total"] == 1
    assert cancelled_detail.json()["columns"][0]["key"] == "cancelled"

    foreign_filter = await auth_client.get("/api/docs/board", params={
        "company_id": cid_raw, "assignee_id": str(outsider.id),
    })
    assert foreign_filter.status_code == 200, foreign_filter.text
    assert foreign_filter.json()["filter"]["assignee_name"] is None

    backlog = await auth_client.get("/api/docs/board", params={
        "company_id": cid_raw, "kind_id": str(kind.id),
        "assignee_id": str(user_id), "overdue_only": "true",
    })
    assert backlog.status_code == 200, backlog.text
    backlog_docs = [item for column in backlog.json()["columns"] for item in column["docs"]]
    outside_row = next(item for item in backlog_docs if item["id"] == str(outside.id))
    assert outside_row["approval_overdue"] is True
    assert outside_row["waiting_people"][0]["user_id"] == str(user_id)


async def test_последовательный_шаг_получает_свой_момент_активации(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid, kind = await _context(auth_client)
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-активация-{uuid.uuid4().hex}",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    route = [
        {"code": "first", "name": "Первый", "mode": "serial", "quorum": "all",
         "actors": [{"by": "user", "ref": me["id"]}]},
        {"code": "second", "name": "Второй", "mode": "serial", "quorum": "all",
         "actors": [{"by": "user", "ref": me["id"]}]},
    ]
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid, "route": route,
    })
    assert started.status_code == 201, started.text
    db.expunge_all()
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == uuid.UUID(doc["id"])).order_by(DocApproval.step_no)
    )).scalars().all()
    assert rows[0].status == "pending" and rows[0].activated_at is not None
    assert rows[1].status == "waiting" and rows[1].activated_at is None
    # Идентификаторы забираем до `expire_all`: после него доступ к атрибуту
    # тянет подгрузку, а синхронное обращение к async-сессии падает.
    first_id, second_id = rows[0].id, rows[1].id

    decided = await auth_client.post(f"/api/docs/approvals/{first_id}", json={
        "company_id": cid, "approved": True,
    })
    assert decided.status_code == 200, decided.text
    db.expunge_all()
    second = await db.get(DocApproval, second_id)
    assert second.status == "pending" and second.activated_at is not None
    assert second.activated_at >= rows[0].activated_at


async def test_отчёт_и_детализация_одинаково_скрывают_закрытый_документ(
        auth_client: AsyncClient, db: AsyncSession):
    _, cid_raw, _ = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    cohort_day = datetime.now(timezone.utc).date() - timedelta(days=250)
    started = datetime.combine(cohort_day, datetime.min.time(), tzinfo=timezone.utc)
    admin = User(
        company_id=cid, email=f"report-admin-{uuid.uuid4().hex}@example.org",
        name="Администратор отчёта", password_hash="!",
    )
    assignee = User(
        company_id=cid, email=f"private-assignee-{uuid.uuid4().hex}@example.org",
        name="Согласующий закрытого документа", password_hash="!",
    )
    kind = DocKind(
        company_id=cid, code=f"private_{uuid.uuid4().hex[:10]}",
        name="Закрытый вид", family="internal", direction="none", fields=[], route=[],
    )
    db.add_all([admin, assignee, kind])
    await db.flush()
    db.add_all([
        UserCompany(user_id=admin.id, company_id=cid, role="admin", modules=["docs"]),
        UserCompany(user_id=assignee.id, company_id=cid, role="user", modules=["docs"]),
    ])
    doc = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title="Закрытая аналитика", status="registered",
        confidentiality="private", author_id=assignee.id,
        approval_status="approved", approval_round=1,
    )
    db.add(doc)
    await db.flush()
    db.add(DocApproval(
        company_id=cid, doc_id=doc.id, round=1, step_no=1,
        step_code="private", step_name="Закрытая виза", mode="serial", quorum="all",
        actor_kind="user", assignee_id=assignee.id, required=True, status="approved",
        created_at=started, activated_at=started, decided_at=started + timedelta(hours=1),
        decided_by=assignee.id,
    ))
    await db.commit()

    report = await docs_router.approval_discipline(
        company_id=cid_raw, date_from=cohort_day, date_to=cohort_day,
        db=db, current_user=admin,
    )
    assert report["summary"]["documents"] == 0
    detail = await docs_router.docs_board(
        company_id=cid_raw, family=None, kind_id=str(kind.id), assignee_id=None,
        pending_only=False, overdue_only=False, cohort_from=cohort_day,
        cohort_to=cohort_day, report_metric="completed", decision_by=None,
        page=1, page_size=50, label_id=None, db=db, current_user=admin,
    )
    assert detail["total"] == 0


async def test_поимённый_отчёт_не_отдаётся_обычному_участнику(
        auth_client: AsyncClient, db: AsyncSession):
    _, cid_raw, _ = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    reader = User(
        company_id=cid, email=f"discipline-{uuid.uuid4().hex}@example.org",
        name="Обычный участник", password_hash="!",
    )
    db.add(reader)
    await db.flush()
    db.add(UserCompany(
        user_id=reader.id, company_id=cid, role="user", modules=["docs"],
    ))
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await docs_router.approval_discipline(
            company_id=cid_raw, date_from=None, date_to=None,
            db=db, current_user=reader,
        )
    assert error.value.status_code == 403


async def test_период_отчёта_использует_московские_сутки():
    selected_from, selected_to, start_at, end_at = docs_router._discipline_bounds(
        datetime(2026, 8, 17).date(), datetime(2026, 8, 17).date(),
    )
    assert selected_from == selected_to == datetime(2026, 8, 17).date()
    assert start_at == datetime(2026, 8, 16, 21, tzinfo=timezone.utc)
    assert end_at == datetime(2026, 8, 17, 21, tzinfo=timezone.utc)


async def test_подразделение_получает_ознакомление_и_напоминание(
        auth_client: AsyncClient, db: AsyncSession, monkeypatch):
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    department = Department(company_id=cid, name=f"Проверка {uuid.uuid4().hex[:8]}")
    person = User(
        company_id=cid, email=f"acquaint-{uuid.uuid4().hex}@example.org",
        name="Получатель ознакомления", password_hash="!",
    )
    excluded = User(
        company_id=cid, email=f"no-docs-{uuid.uuid4().hex}@example.org",
        name="Без доступа к Треку", password_hash="!",
    )
    db.add_all([department, person, excluded])
    await db.flush()
    db.add(UserCompany(
        user_id=person.id, company_id=cid, role="user", modules=["docs"],
        department_id=department.id,
    ))
    db.add(UserCompany(
        user_id=excluded.id, company_id=cid, role="user", modules=["tasks"],
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
    assert added.json()["skipped"] == 1

    notices: list[tuple[list[str], str, str]] = []
    async def send_ok(emails, subject, text):
        notices.append((emails, subject, text))
        return True, None

    monkeypatch.setattr(
        task_scheduler.task_mail, "send_notice_checked", send_ok,
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

    async def send_fail(emails, subject, text):
        notices.append((emails, subject, text))
        return False, "SMTP временно недоступен"

    row.reminded_at = None
    row.reminder_attempted_at = None
    monkeypatch.setattr(task_scheduler.task_mail, "send_notice_checked", send_fail)
    await db.commit()
    sent = await task_scheduler.run_acquaint_reminders(db, now)
    assert sent == 0
    await db.refresh(row)
    assert row.reminded_at is None
    assert row.reminder_error == "SMTP временно недоступен"

    membership = await db.get(UserCompany, (person.id, cid))
    await db.delete(membership)
    row.reminder_attempted_at = None
    notices.clear()
    await db.commit()
    sent = await task_scheduler.run_acquaint_reminders(db, now)
    assert sent == 0 and notices == []


async def test_новая_редакция_требует_нового_ознакомления(
        auth_client: AsyncClient, db: AsyncSession):
    _, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    person = User(
        company_id=cid, email=f"revision-{uuid.uuid4().hex}@example.org",
        name="Читатель новой редакции", password_hash="!",
    )
    db.add(person)
    await db.flush()
    db.add(UserCompany(
        user_id=person.id, company_id=cid, role="user", modules=["docs"],
    ))
    await db.commit()
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-редакция-{uuid.uuid4().hex}",
    })).json()
    uploaded = await auth_client.post(
        f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid_raw, "role": "body"},
        files={"file": ("редакция-1.txt", b"version one", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    first = await auth_client.post(f"/api/docs/{doc['id']}/acquaint", json={
        "company_id": cid_raw, "user_ids": [str(person.id)],
    })
    assert first.status_code == 201 and first.json()["added"] == 1, first.text

    uploaded = await auth_client.post(
        f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid_raw, "role": "body"},
        files={"file": ("редакция-2.txt", b"version two", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    rows = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == uuid.UUID(doc["id"]),
        DocAcquaint.user_id == person.id,
    ))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "superseded"

    second = await auth_client.post(f"/api/docs/{doc['id']}/acquaint", json={
        "company_id": cid_raw, "user_ids": [str(person.id)],
    })
    assert second.status_code == 201 and second.json()["added"] == 1, second.text
    rows = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == uuid.UUID(doc["id"]),
        DocAcquaint.user_id == person.id,
    ))).scalars().all()
    assert len(rows) == 2
    assert {row.status for row in rows} == {"pending", "superseded"}
    assert len({row.snapshot_sha256 for row in rows}) == 2

    changed = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
        "company_id": cid_raw, "title": f"Изменено-{uuid.uuid4().hex}",
    })
    assert changed.status_code == 200, changed.text
    rows = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == uuid.UUID(doc["id"]),
        DocAcquaint.user_id == person.id,
    ))).scalars().all()
    assert all(row.status == "superseded" for row in rows)


async def test_расписание_сэд_включается_только_после_ручной_проверки(
        auth_client: AsyncClient, tmp_path, monkeypatch):
    from app.services import doc_exchange
    monkeypatch.setattr(doc_exchange.settings, "doc_exchange_roots", str(tmp_path))
    monkeypatch.setattr(doc_exchange, "MIN_STABLE_AGE_SECONDS", 0)
    monkeypatch.setattr(doc_exchange, "MAX_INBOX_FILES", 2)
    _, cid, _ = await _context(auth_client)
    inbox = tmp_path / cid
    inbox.mkdir()
    for index in range(3):
        (inbox / f"{index}.txt").write_text(f"file-{index}", encoding="utf-8")
    code = f"test-{uuid.uuid4().hex[:8]}"
    created = await auth_client.post("/api/docs/exchange/targets", json={
        "company_id": cid, "code": code, "name": "Проверка папки",
        "system": "other", "inbox_path": str(inbox), "outbox_path": "",
    })
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    before = await auth_client.put(f"/api/docs/exchange/targets/{target_id}/schedule", json={
        "company_id": cid, "enabled": True, "interval_min": 15,
    })
    assert before.status_code == 409
    scanned = await auth_client.post(
        "/api/docs/exchange/scan", params={"company_id": cid, "target_id": target_id})
    assert scanned.status_code == 200 and scanned.json()["added"] == 2, scanned.text
    scanned = await auth_client.post(
        "/api/docs/exchange/scan", params={"company_id": cid, "target_id": target_id})
    assert scanned.status_code == 200 and scanned.json()["added"] == 1, scanned.text
    after = await auth_client.put(f"/api/docs/exchange/targets/{target_id}/schedule", json={
        "company_id": cid, "enabled": True, "interval_min": 15,
    })
    assert after.status_code == 200 and after.json()["enabled"] is True


async def test_дела_проверяют_тенант_юрлицо_и_ручную_подшивку(
        auth_client: AsyncClient, db: AsyncSession):
    _, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    other_cid = await db.scalar(select(Company.id).where(Company.id != cid).limit(1))
    assert other_cid is not None
    foreign_org = Organization(
        company_id=other_cid, inn=str(uuid.uuid4().int)[:12], name="Чужое юрлицо",
    )
    foreign_department = Department(company_id=other_cid, name="Чужой отдел")
    foreign_case = DocCase(
        company_id=other_cid, year=datetime.now(ZoneInfo("Europe/Moscow")).year,
        index=f"X-{uuid.uuid4().hex[:6]}", title="Чужое дело",
    )
    db.add_all([foreign_org, foreign_department, foreign_case])
    await db.commit()

    rejected_org = await auth_client.post("/api/docs/cases", json={
        "company_id": cid_raw, "year": foreign_case.year, "index": "01-01",
        "title": "Дело с чужим юрлицом", "organization_id": str(foreign_org.id),
    })
    assert rejected_org.status_code == 400, rejected_org.text
    rejected_department = await auth_client.post("/api/docs/cases", json={
        "company_id": cid_raw, "year": foreign_case.year, "index": "01-02",
        "title": "Дело с чужим отделом", "department_id": str(foreign_department.id),
    })
    assert rejected_department.status_code == 400, rejected_department.text
    foreign_default = await auth_client.put(f"/api/docs/kinds/{kind['id']}", json={
        **kind, "company_id": cid_raw, "default_case_id": str(foreign_case.id),
    })
    assert foreign_default.status_code == 404, foreign_default.text

    suffix = uuid.uuid4().hex[:6]
    first = await auth_client.post("/api/docs/cases", json={
        "company_id": cid_raw, "year": foreign_case.year, "index": f"01-{suffix}",
        "title": "Переписка", "storage_term": "5 лет", "storage_years": 5,
    })
    assert first.status_code == 201, first.text
    duplicate = await auth_client.post("/api/docs/cases", json={
        "company_id": cid_raw, "year": foreign_case.year, "index": f"01-{suffix}",
        "title": "Дубликат", "storage_term": "5 лет", "storage_years": 5,
    })
    assert duplicate.status_code == 409, duplicate.text
    second = await auth_client.post("/api/docs/cases", json={
        "company_id": cid_raw, "year": foreign_case.year, "index": f"02-{suffix}",
        "title": "Договоры", "storage_term": "10 лет", "storage_years": 10,
    })
    assert second.status_code == 201, second.text

    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"], "title": "Ручная подшивка",
    })).json()
    rejected_foreign_case = await auth_client.put(f"/api/docs/{doc['id']}/case", json={
        "company_id": cid_raw, "case_id": str(foreign_case.id),
    })
    assert rejected_foreign_case.status_code == 404, rejected_foreign_case.text
    filed = await auth_client.put(f"/api/docs/{doc['id']}/case", json={
        "company_id": cid_raw, "case_id": first.json()["id"],
    })
    assert filed.status_code == 200 and filed.json()["case_id"] == first.json()["id"]
    registered = await auth_client.post(f"/api/docs/{doc['id']}/register", json={
        "company_id": cid_raw,
    })
    assert registered.status_code == 200, registered.text
    assert registered.json()["storage_until"] == f"{foreign_case.year + 5}-12-31"
    moved = await auth_client.put(f"/api/docs/{doc['id']}/case", json={
        "company_id": cid_raw, "case_id": second.json()["id"],
    })
    assert moved.status_code == 200 and moved.json()["case_id"] == second.json()["id"]
    assert moved.json()["storage_until"] == registered.json()["storage_until"]

    closed = await auth_client.post(f"/api/docs/cases/{second.json()['id']}/close", json={
        "company_id": cid_raw, "note": "Год завершён",
    })
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    other_doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"], "title": "После закрытия",
    })).json()
    rejected_closed = await auth_client.put(f"/api/docs/{other_doc['id']}/case", json={
        "company_id": cid_raw, "case_id": second.json()["id"],
    })
    assert rejected_closed.status_code == 409, rejected_closed.text


async def test_дефолтное_дело_проверяется_и_подставляется_при_регистрации(
        auth_client: AsyncClient):
    _, cid, _ = await _context(auth_client)
    year = datetime.now(ZoneInfo("Europe/Moscow")).year
    case_row = await auth_client.post("/api/docs/cases", json={
        "company_id": cid, "year": year, "index": f"D-{uuid.uuid4().hex[:6]}",
        "title": "Дело по умолчанию", "storage_term": "3 года", "storage_years": 3,
    })
    assert case_row.status_code == 201, case_row.text
    kind = await auth_client.post("/api/docs/kinds", json={
        "company_id": cid, "code": f"default_{uuid.uuid4().hex[:8]}",
        "name": "Вид с делом", "default_case_id": case_row.json()["id"],
    })
    assert kind.status_code == 201, kind.text
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind.json()["id"], "title": "Автоподшивка",
    })).json()
    registered = await auth_client.post(f"/api/docs/{doc['id']}/register", json={
        "company_id": cid,
    })
    assert registered.status_code == 200, registered.text
    assert registered.json()["case_id"] == case_row.json()["id"]
    assert registered.json()["storage_until"] == f"{year + 3}-12-31"


async def test_конкурентный_дубль_общего_дела_останавливает_индекс(
        auth_client: AsyncClient):
    _, cid, _ = await _context(auth_client)
    year = datetime.now(ZoneInfo("Europe/Moscow")).year
    case_index = f"C-{uuid.uuid4().hex[:8]}"
    payload = {
        "company_id": cid,
        "year": year,
        "index": case_index,
        "title": "Общее дело при конкурентном создании",
        "storage_term": "5 лет",
        "storage_years": 5,
        "organization_id": None,
    }
    responses = await asyncio.gather(*[
        auth_client.post("/api/docs/cases", json=payload) for _ in range(2)
    ])
    assert sorted(item.status_code for item in responses) == [201, 409]


async def test_конкурентные_запуск_и_решение_согласования_дают_одного_победителя(
        auth_client: AsyncClient, db: AsyncSession):
    me, cid, kind = await _context(auth_client)
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-конкуренция-{uuid.uuid4().hex}",
    })).json()
    registered = await auth_client.post(f"/api/docs/{doc['id']}/register", json={
        "company_id": cid,
    })
    assert registered.status_code == 200, registered.text
    route = [{
        "code": "one", "name": "Один согласующий", "mode": "serial", "quorum": "all",
        "actors": [{"by": "user", "ref": me["id"]}],
    }]

    starts = await asyncio.gather(*[
        auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
            "company_id": cid, "route": route,
        }) for _ in range(2)
    ])
    assert sorted(item.status_code for item in starts) == [201, 409]
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == uuid.UUID(doc["id"]),
    ))).scalars().all()
    assert len(rows) == 1 and rows[0].status == "pending"
    # Идентификатор забираем до `expire_all`: после него обращение к атрибуту
    # тянет подгрузку, а синхронный доступ к async-сессии падает MissingGreenlet.
    approval_id = rows[0].id

    decisions = await asyncio.gather(*[
        auth_client.post(f"/api/docs/approvals/{approval_id}", json={
            "company_id": cid, "approved": True,
        }) for _ in range(2)
    ])
    assert sorted(item.status_code for item in decisions) == [200, 409]
    db.expunge_all()
    approval = await db.get(DocApproval, approval_id)
    assert approval.status == "approved"
    events = (await db.execute(select(DocEvent).where(
        DocEvent.doc_id == uuid.UUID(doc["id"]),
        DocEvent.kind == "approval",
        DocEvent.from_value == "Один согласующий",
        DocEvent.to_value == "согласовано",
    ))).scalars().all()
    assert len(events) == 1

    cancel_doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-конкуренция-отмена-{uuid.uuid4().hex}",
    })).json()
    await auth_client.post(f"/api/docs/{cancel_doc['id']}/register", json={
        "company_id": cid,
    })
    started = await auth_client.post(
        f"/api/docs/{cancel_doc['id']}/approval/start",
        json={"company_id": cid, "route": route},
    )
    assert started.status_code == 201, started.text
    cancelled = await asyncio.gather(*[
        auth_client.post(f"/api/docs/{cancel_doc['id']}/approval/cancel", json={
            "company_id": cid, "reason": "Проверка гонки",
        }) for _ in range(2)
    ])
    assert sorted(item.status_code for item in cancelled) == [200, 409]
    cancel_events = (await db.execute(select(DocEvent).where(
        DocEvent.doc_id == uuid.UUID(cancel_doc["id"]),
        DocEvent.kind == "approval",
        DocEvent.to_value == "круг отменён",
    ))).scalars().all()
    assert len(cancel_events) == 1
