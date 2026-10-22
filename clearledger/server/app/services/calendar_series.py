"""Материализация одной серии встреч в транзакции вызывающего кода.

Сохранение встречи и регламент используют одну блокировку головы: после ожидания
читаются актуальные правило, участники и последняя назначенная дата. Поэтому
повторный или конкурентный запуск продолжает серию, не создавая дублей.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CalendarAttendee, CalendarEvent
from app.services import space_time

SERIES_HORIZON_DAYS = 60


async def lock_event(
    db: AsyncSession, company_id: uuid.UUID, event_id: uuid.UUID, *,
    skip_locked: bool = False,
) -> CalendarEvent | None:
    """Прочитать встречу под блокировкой до конца текущей транзакции.

    Вызывать ДО правки встречи или её участников. У экземпляра сначала запираем
    голову: перенос последнего экземпляра меняет точку продолжения серии.
    populate_existing обязателен: объект мог попасть в identity map до ожидания.
    """
    root_id = await db.scalar(select(CalendarEvent.series_id).where(
        CalendarEvent.id == event_id, CalendarEvent.company_id == company_id))
    if root_id is not None:
        locked_root = await db.scalar(select(CalendarEvent.id).where(
            CalendarEvent.id == root_id, CalendarEvent.company_id == company_id)
            .with_for_update(skip_locked=skip_locked))
        if locked_root is None:
            return None
    return await db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id, CalendarEvent.company_id == company_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True))


async def materialize_series(
    db: AsyncSession, company_id: uuid.UUID, head_id: uuid.UUID, now: datetime, *,
    limit: int | None = None, skip_locked: bool = False,
) -> int:
    """Дополнить одну голову до горизонта, не фиксируя транзакцию.

    Запрос сохраняет голову и весь горизонт вместе; регламент может ограничить
    число новых строк своим бюджетом. Уже назначенные встречи (включая отменённые
    и перенесённые отдельно) не перестраиваются при изменении правила.
    """
    if limit is not None and limit <= 0:
        return 0
    # Сначала сохраняем подготовленные вызывающим изменения и состав: повторное
    # чтение под блокировкой не должно затереть их, даже при autoflush=False.
    await db.flush()
    head = await lock_event(db, company_id, head_id, skip_locked=skip_locked)
    if head is None or head.series_id is not None or head.status != "planned":
        return 0
    rule = head.recurrence or {}
    if not isinstance(rule, dict) or not rule.get("mode"):
        return 0

    # Комната могла появиться после предыдущего построения горизонта.
    if head.conference_url:
        from app.services import jitsi
        await jitsi.share_series_url(db, head)
    zone = space_time.zone(head.tz)
    duration = head.ends_at - head.starts_at
    horizon = now + timedelta(days=SERIES_HORIZON_DAYS)
    until = (datetime.combine(head.recurrence_until, time.max, tzinfo=zone)
             if head.recurrence_until else None)
    last = await db.scalar(select(func.max(CalendarEvent.starts_at)).where(
        CalendarEvent.company_id == company_id,
        or_(CalendarEvent.series_id == head.id, CalendarEvent.id == head.id)))
    cursor = space_time.as_utc(last or head.starts_at)
    if cursor >= horizon:
        return 0
    # У старой головы нужны будущие встречи, а не восстановление пропущенной
    # истории. Дневные/недельные интервалы перескакиваем в местных датах, чтобы
    # даже давняя голова не сделала синхронный запрос многолетним backfill.
    if rule.get("mode") in {"daily", "weekly"}:
        days = max(1, int(rule.get("interval") or 1)) * (7 if rule["mode"] == "weekly" else 1)
        local = cursor.astimezone(zone)
        distance = (now.astimezone(zone).date() - local.date()).days
        jumps = max(0, distance // days - 1)
        cursor = (local + timedelta(days=jumps * days)).astimezone(timezone.utc)
    attendees = (await db.scalars(select(CalendarAttendee).where(
        CalendarAttendee.event_id == head.id)
        .execution_options(populate_existing=True))).all()

    made = 0
    while limit is None or made < limit:
        starts = next_occurrence(cursor, rule, zone)
        if starts is None or starts > horizon or (until is not None and starts > until):
            break
        cursor = starts
        if starts < now:
            continue
        event = CalendarEvent(
            company_id=head.company_id, organizer_id=head.organizer_id,
            title=head.title, description=head.description,
            starts_at=starts, ends_at=starts + duration,
            all_day=head.all_day, tz=head.tz, location=head.location,
            conference_url=head.conference_url, visibility=head.visibility,
            subject_ref=head.subject_ref, series_id=head.id)
        db.add(event)
        await db.flush()
        for attendee in attendees:
            # Текущий ответ головы наследуется в момент создания экземпляра.
            # Последующий ответ меняет одну встречу. Встречное предложение и
            # комментарий относятся к ней и в продолжение не переносятся.
            db.add(CalendarAttendee(
                event_id=event.id, user_id=attendee.user_id, role=attendee.role,
                response=attendee.response, is_host=attendee.is_host))
        made += 1
    await db.flush()
    return made


def next_occurrence(after: datetime, rule: dict, zone) -> datetime | None:
    """Следующее повторение после указанного момента, в поясе встречи."""
    step = max(1, int(rule.get("interval") or 1))
    mode = str(rule.get("mode") or "").lower()
    local = after.astimezone(zone)
    if mode == "daily":
        return (local + timedelta(days=step)).astimezone(timezone.utc)
    if mode == "weekly":
        return (local + timedelta(weeks=step)).astimezone(timezone.utc)
    if mode == "monthly":
        month = local.month - 1 + step
        year = local.year + month // 12
        month = month % 12 + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        return local.replace(year=year, month=month, day=day).astimezone(timezone.utc)
    return None
