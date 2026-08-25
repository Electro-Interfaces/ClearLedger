"""Личное напоминание приходит его хозяину — и никому больше.

Проверяется то, чего в интерфейсе не видно: планировщик берёт сработавшие
напоминания и пишет их в личную комнату чата. Ошибка здесь не выглядит
ошибкой — напоминание просто уходит не туда, и заметить это можно только у
чужого человека в ленте.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChatMessage, ChatParticipant, ChatRoom, Company, User, UserCompany)
from app.services import reminders
from app.services.task_scheduler import run_personal_reminders

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _пара(db: AsyncSession):
    """Компания и двое её людей: без второго проверять нечего."""
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    assert company is not None
    me = (await db.execute(select(User).where(
        User.email == "admin@clearledger.ru"))).scalars().first()
    assert me is not None
    другой = (await db.execute(
        select(User).join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == company.id,
               User.email != "admin@clearledger.ru").limit(1))).scalars().first()
    if другой is None:
        другой = User(email=f"other-{uuid.uuid4().hex[:8]}@test.local",
                      name="Второй сотрудник", role="user",
                      password_hash="!test", company_id=company.id)
        db.add(другой)
        await db.flush()
        db.add(UserCompany(user_id=другой.id, company_id=company.id, role="user"))
        await db.flush()
    return company, me, другой


async def test_напоминание_ставится_только_в_будущее(db: AsyncSession):
    company, me, _ = await _пара(db)
    прошлое = await reminders.put(db, company.id, me.id, f"task:{uuid.uuid4()}",
                                  datetime.now(timezone.utc) - timedelta(hours=1))
    assert прошлое is None, "о том, что уже прошло, не напоминаем"

    with pytest.raises(ValueError):
        await reminders.put(db, company.id, me.id, "чепуха",
                            datetime.now(timezone.utc) + timedelta(hours=1))


async def test_сработавшее_приходит_только_хозяину(db: AsyncSession):
    company, me, чужой = await _пара(db)
    текст = f"Позвонить в РусГидро {uuid.uuid4().hex[:6]}"
    row = await reminders.put(db, company.id, me.id, f"task:{uuid.uuid4()}",
                              datetime.now(timezone.utc) + timedelta(minutes=5),
                              note=текст)
    assert row is not None

    # Время наступило: планировщику передаём момент после срока, а не двигаем
    # строку — так проверяется ровно тот отбор, который работает в бою.
    assert await run_personal_reminders(db, row.remind_at + timedelta(minutes=1)) >= 1
    await db.refresh(row)
    assert row.fired_at is not None, "иначе то же напоминание придёт через тик снова"

    msg = (await db.execute(select(ChatMessage).where(
        ChatMessage.content == текст))).scalars().one()
    участники = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == msg.room_id))).scalars())
    assert me.id in участники
    assert чужой.id not in участники, "личное напоминание видит только хозяин"
    комната = await db.get(ChatRoom, msg.room_id)
    assert комната.type == "direct"

    # Повторно то же напоминание не доставляется.
    было = len((await db.execute(select(ChatMessage.id).where(
        ChatMessage.content == текст))).scalars().all())
    await run_personal_reminders(db, row.remind_at + timedelta(hours=1))
    стало = len((await db.execute(select(ChatMessage.id).where(
        ChatMessage.content == текст))).scalars().all())
    assert стало == было


async def test_отложенное_приходит_снова(db: AsyncSession):
    company, me, _ = await _пара(db)
    текст = f"Отчёт {uuid.uuid4().hex[:6]}"
    row = await reminders.put(db, company.id, me.id, f"task:{uuid.uuid4()}",
                              datetime.now(timezone.utc) + timedelta(minutes=5),
                              note=текст)
    await run_personal_reminders(db, row.remind_at + timedelta(minutes=1))

    await reminders.snooze(db, row, 30)
    assert row.fired_at is None and row.snooze_count == 1
    assert await reminders.due_count(db, company.id, me.id) >= 0

    await run_personal_reminders(db, row.remind_at + timedelta(minutes=1))
    сообщений = len((await db.execute(select(ChatMessage.id).where(
        ChatMessage.content == текст))).scalars().all())
    assert сообщений == 2, "отложенное обязано прийти второй раз"
