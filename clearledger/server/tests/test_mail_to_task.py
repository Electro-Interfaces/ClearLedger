"""Письмо, доехавшее до задачи: событие в ленте и вложения на месте.

Ловим то, из-за чего входящий документ пропадал молча: письмо дописывалось в
конец описания задачи, а вложение (в котором документ обычно и приезжает) не
переносилось никуда. Плюс проверяем, что общий вход в задачу не открыт
постороннему: плюс-адрес виден в письме и утекает пересылкой.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    MailAttachment, MailMessage, SourceFile, Task, TaskAttachment, TaskEvent,
    TaskParticipant, User,
)
from app.services import mail_routing
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _task_with_mail_participant(auth_client: AsyncClient, db: AsyncSession,
                                      email: str) -> tuple[str, Task, User]:
    """Задача с почтовым участником — так выглядит делегирование наружу."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Приёмка документов от подрядчика"})
    assert r.status_code == 201, r.text
    task = await db.get(Task, uuid.UUID(r.json()["id"]))

    person = User(id=uuid.uuid4(), email=email, name="Подрядчик",
                  password_hash="!", mail_only=True)
    db.add(person)
    await db.flush()
    db.add(TaskParticipant(task_id=task.id, user_id=person.id,
                           role="external", channel="mail", channel_ref=email))
    await db.commit()
    return cid, task, person


async def _letter(db: AsyncSession, cid: str, sender: str, *,
                  message_id: str, with_file: bool = True) -> MailMessage:
    row = MailMessage(
        id=uuid.uuid4(), company_id=uuid.UUID(cid), direction="in",
        message_id=message_id, subject="Акт выполненных работ",
        from_name="Подрядчик", from_email=sender,
        body_text="Направляем акт, просим подписать.",
        has_attachments=with_file)
    db.add(row)
    await db.flush()
    if with_file:
        db.add(MailAttachment(
            company_id=uuid.UUID(cid), message_id=row.id,
            file_name="акт-15.pdf", content_type="application/pdf",
            size=11, sha256="0" * 64, content=b"%PDF-1.4\n%%"))
    await db.commit()
    return row


async def test_письмо_доезжает_событием_и_приносит_вложение(
        auth_client: AsyncClient, db: AsyncSession):
    sender = f"podryad-{uuid.uuid4().hex[:8]}@example.org"
    cid, task, _ = await _task_with_mail_participant(auth_client, db, sender)
    letter = await _letter(db, cid, sender, message_id=f"<{uuid.uuid4()}@example.org>")

    assert await mail_routing.to_task(db, uuid.UUID(cid), letter, task.number) is True
    await db.commit()

    events = (await db.execute(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.kind == "mail"))).scalars().all()
    assert len(events) == 1, "письмо не легло событием в ленту"
    assert events[0].note.startswith("Направляем акт")
    assert events[0].from_value == letter.message_id, "нет ключа идемпотентности"

    # Описание задачи письмом не портится: раньше текст дописывался именно туда.
    await db.refresh(task)
    assert "Направляем акт" not in (task.description or "")
    assert task.waiting_for == "us", "мяч не вернулся к нам"

    # Вложение доехало файлом, а не потерялось.
    atts = (await db.execute(select(TaskAttachment).where(
        TaskAttachment.task_id == task.id))).scalars().all()
    assert len(atts) == 1, "вложение письма не стало файлом задачи"
    sf = await db.get(SourceFile, atts[0].file_id)
    assert sf.file_name == "акт-15.pdf"
    assert sf.size == 11 and sf.purpose == "attachment"


async def test_повторная_доставка_не_задваивает(
        auth_client: AsyncClient, db: AsyncSession):
    sender = f"podryad-{uuid.uuid4().hex[:8]}@example.org"
    cid, task, _ = await _task_with_mail_participant(auth_client, db, sender)
    letter = await _letter(db, cid, sender, message_id=f"<{uuid.uuid4()}@example.org>")

    for _ in range(2):
        assert await mail_routing.to_task(db, uuid.UUID(cid), letter, task.number) is True
        await db.commit()

    events = (await db.execute(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.kind == "mail"))).scalars().all()
    atts = (await db.execute(select(TaskAttachment).where(
        TaskAttachment.task_id == task.id))).scalars().all()
    assert len(events) == 1 and len(atts) == 1, "перечитанный ящик задвоил письмо"


async def test_посторонний_в_задачу_не_пишет(
        auth_client: AsyncClient, db: AsyncSession):
    sender = f"podryad-{uuid.uuid4().hex[:8]}@example.org"
    cid, task, _ = await _task_with_mail_participant(auth_client, db, sender)
    chuzhoy = await _letter(db, cid, "kto-to@example.net",
                            message_id=f"<{uuid.uuid4()}@example.net>")

    assert await mail_routing.to_task(db, uuid.UUID(cid), chuzhoy, task.number) is False
    events = (await db.execute(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.kind == "mail"))).scalars().all()
    assert events == [], "письмо постороннего попало в задачу"
