"""Личные напоминания: поставить, отложить, погасить, доставить.

Отдельный сервис, потому что напоминание живёт дольше и самостоятельнее, чем
любой экран: его ставят из задачи, из встречи и из записной книжки, а гасят
через колокольчик. Собери эту логику в роутере — и три места начнут расходиться
в мелочах вроде «считается ли отложенное сработавшим».
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PersonalReminder

logger = logging.getLogger("clearledger.reminders")

# Предмет напоминания записывается тем же словарём `<вид>:<ключ>`, что у
# `Task.subject_ref`: один язык ссылок на всё пространство.
KINDS = ("task", "event", "doc")


def _valid_ref(target_ref: str) -> bool:
    kind, _, key = (target_ref or "").partition(":")
    return kind in KINDS and bool(key)


async def put(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID,
              target_ref: str, remind_at: datetime,
              note: str | None = None) -> PersonalReminder | None:
    """Поставить напоминание. Прошедшее время не ставим — молча, без ошибки:
    человек мог выбрать «сегодня в 9:00» после девяти, и отказ формой тут
    раздражал бы сильнее, чем отсутствие напоминания о том, что уже наступило."""
    if not _valid_ref(target_ref):
        raise ValueError(f"Неизвестный предмет напоминания: {target_ref}")
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    if remind_at <= datetime.now(timezone.utc):
        return None
    row = PersonalReminder(company_id=company_id, user_id=user_id,
                           target_ref=target_ref, remind_at=remind_at,
                           note=(note or None))
    db.add(row)
    await db.flush()
    return row


async def snooze(db: AsyncSession, row: PersonalReminder, minutes: int) -> PersonalReminder:
    """Отложить: срок вперёд, доставка снова впереди, счётчик растёт.

    Счётчик — не статистика, а разговор с человеком: напоминание, отложенное
    шестой раз, стоит не откладывать, а решить или выбросить.
    """
    row.remind_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, minutes))
    row.fired_at = None
    row.snooze_count += 1
    await db.flush()
    return row


async def reschedule(db: AsyncSession, row: PersonalReminder,
                     remind_at: datetime) -> PersonalReminder:
    """Перенести на конкретное время. Счётчик откладываний не растёт: назначить
    точное время — это решение, а не уклонение."""
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    row.remind_at = remind_at
    row.fired_at = None
    await db.flush()
    return row


async def drop_for(db: AsyncSession, target_ref: str,
                   user_id: uuid.UUID | None = None) -> int:
    """Снять напоминания о предмете: встречу отменили, задачу закрыли.

    Строки удаляются, а не помечаются: напоминание о том, чего больше нет, —
    это не история, а ложное срабатывание, которое человек будет гасить руками.
    """
    sel = select(PersonalReminder).where(
        PersonalReminder.target_ref == target_ref,
        PersonalReminder.done_at.is_(None))
    if user_id is not None:
        sel = sel.where(PersonalReminder.user_id == user_id)
    rows = list((await db.execute(sel)).scalars())
    for row in rows:
        await db.delete(row)
    return len(rows)


async def due_count(db: AsyncSession, company_id: uuid.UUID,
                    user_id: uuid.UUID) -> int:
    """Сколько напоминаний сработало и не погашено — число для колокольчика."""
    from sqlalchemy import func

    return int(await db.scalar(
        select(func.count(PersonalReminder.id)).where(
            PersonalReminder.company_id == company_id,
            PersonalReminder.user_id == user_id,
            PersonalReminder.fired_at.is_not(None),
            PersonalReminder.done_at.is_(None))) or 0)
