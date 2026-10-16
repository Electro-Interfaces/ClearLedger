"""Уведомление о поручении приходит туда, куда человек попросил в личных настройках.

Ошибка здесь не видна в интерфейсе: поручение просто не доходит, и назначенный
узнаёт о нём по просрочке (РусГидро, 16.10.2026).
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatParticipant, ChatRoom, Company, User, UserCompany
from app.services import notify, task_mail

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _человек(db: AsyncSession, **kw) -> tuple[Company, User]:
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    assert company is not None
    u = User(email=f"tn-{uuid.uuid4().hex[:8]}@example.test", name="Тест · Исполнитель",
             role="user", password_hash="!test", company_id=company.id, **kw)
    db.add(u)
    await db.flush()
    db.add(UserCompany(user_id=u.id, company_id=company.id, role="user"))
    await db.flush()
    return company, u


async def _комнаты(db: AsyncSession, текст: str) -> list[ChatRoom]:
    ids = (await db.execute(select(ChatMessage.room_id).where(
        ChatMessage.content.like(f"{текст}%")))).scalars().all()
    return [await db.get(ChatRoom, i) for i in ids]


async def test_каналы_по_умолчанию_и_почтовый_участник():
    assert notify.task_channels(User(task_notify=None, mail_only=False)) == {"secretary", "email"}
    assert notify.task_channels(User(task_notify=["notices"], mail_only=False)) == {"notices"}
    # Почтовый участник чата не видит — только письмо, что бы ни стояло.
    assert notify.task_channels(User(task_notify=["secretary"], mail_only=True)) == {"email"}


async def test_по_умолчанию_секретарь_и_почта(db: AsyncSession, monkeypatch):
    письма: list = []
    monkeypatch.setattr(task_mail, "send_notice_async", lambda e, s, t: письма.append(e))
    company, u = await _человек(db)
    тема = f"Вам поручена задача {uuid.uuid4().hex[:6]}"
    await notify.tell(db, company.id, [u], тема, "Поручил: Тест")

    комнаты = await _комнаты(db, тема)
    assert [r.type for r in комнаты] == ["direct"], "одно сообщение — в беседе с Секретарём"
    assert письма == [[u.email]]


async def test_отдельный_канал_уведомлений(db: AsyncSession, monkeypatch):
    письма: list = []
    monkeypatch.setattr(task_mail, "send_notice_async", lambda e, s, t: письма.append(e))
    company, u = await _человек(db, task_notify=["notices"])
    тема = f"Вам поручена задача {uuid.uuid4().hex[:6]}"
    await notify.tell(db, company.id, [u], тема, "Поручил: Тест")
    await notify.tell(db, company.id, [u], тема + " вторая", "Поручил: Тест")

    комнаты = await _комнаты(db, тема)
    assert len(комнаты) == 2 and комнаты[0].id == комнаты[1].id, "канал у человека один"
    r = комнаты[0]
    assert (r.type, r.kind, r.name) == ("channel", notify.NOTICES_ROOM_KIND, "Уведомления")
    роли = dict((await db.execute(select(ChatParticipant.user_id, ChatParticipant.role)
                                 .where(ChatParticipant.room_id == r.id))).all())
    assert роли.get(u.id) == "member", "писать в канал уведомлений человеку незачем"
    assert len(роли) == 2, "канал личный: человек и Секретарь"
    assert письма == [[], []], "почту человек не выбирал"


async def test_поручение_через_api_доходит_в_выбранный_чат(auth_client, db: AsyncSession,
                                                          monkeypatch):
    """Сквозной путь «Проектов»: поставили задачу на человека — он видит её в чате."""
    from tests.helpers import seed_company_id

    monkeypatch.setattr(task_mail, "send_notice_async", lambda *a: None)
    me = (await auth_client.get("/api/auth/me")).json()
    assert me["task_notify"] == ["email", "secretary"], "умолчание: Секретарь и почта"
    cid = seed_company_id(me)

    # Пустой выбор отбивается: поручение не должно оставаться без канала.
    r = await auth_client.patch("/api/chat/me", json={"taskNotify": []})
    assert r.status_code == 400, r.text
    r = await auth_client.patch("/api/chat/me", json={"taskNotify": ["notices", "мусор"]})
    assert r.status_code == 200, r.text
    assert (await auth_client.get("/api/auth/me")).json()["task_notify"] == ["notices"]
    await auth_client.patch("/api/chat/me", json={"taskNotify": ["secretary", "email"]})

    company = await db.get(Company, uuid.UUID(cid))
    _, u = await _человек(db, task_notify=["notices"])
    if u.company_id != company.id:
        db.add(UserCompany(user_id=u.id, company_id=company.id, role="user"))
    await db.commit()
    название = f"Проверка поручения {uuid.uuid4().hex[:6]}"
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": название, "assignee_id": str(u.id)})
    assert r.status_code == 201, r.text

    db.expire_all()
    комнаты = await _комнаты(db, f"Вам поручена задача №{r.json()['number']}: {название}")
    assert [(x.type, x.kind) for x in комнаты] == [("channel", notify.NOTICES_ROOM_KIND)]
