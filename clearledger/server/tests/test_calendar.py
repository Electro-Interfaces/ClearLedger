"""Встреча: кто её меняет и что происходит с согласиями при переносе.

Проверяется не вёрстка календаря, а два правила, поломка которых выглядит как
работающая программа. Первое: менять встречу может только тот, кто её собрал —
иначе приглашённый молча переносит чужую планёрку. Второе: перенос обнуляет
ответы участников, потому что «буду в 10» не равно «буду в 18», а сохранённое
согласие показывает организатору кворум, которого нет.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CalendarAttendee, CalendarEvent, Company, User, UserCompany
from app.routers.work_router import EventAction, EventIn, calendar_action, calendar_create

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _пара(db: AsyncSession):
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    assert company is not None
    я = (await db.execute(select(User).where(
        User.email == "admin@clearledger.ru"))).scalars().first()
    assert я is not None
    другой = (await db.execute(
        select(User).join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == company.id,
               User.email != "admin@clearledger.ru").limit(1))).scalars().first()
    if другой is None:
        другой = User(email=f"guest-{uuid.uuid4().hex[:8]}@test.local",
                      name="Приглашённый", role="user",
                      password_hash="!test", company_id=company.id)
        db.add(другой)
        await db.flush()
        db.add(UserCompany(user_id=другой.id, company_id=company.id, role="user"))
        await db.flush()
    return company, я, другой


async def _встреча(db, company, я, другой, через_часов=24):
    начало = datetime.now(timezone.utc) + timedelta(hours=через_часов)
    return await calendar_create(
        EventIn(company_id=str(company.id), title="Планёрка по 208",
                starts_at=начало, ends_at=начало + timedelta(hours=1),
                attendee_ids=[str(другой.id)]),
        db=db, current_user=я)


async def test_конец_раньше_начала_не_проходит(db: AsyncSession):
    company, я, другой = await _пара(db)
    начало = datetime.now(timezone.utc) + timedelta(days=1)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ошибка:
        await calendar_create(
            EventIn(company_id=str(company.id), title="Задом наперёд",
                    starts_at=начало, ends_at=начало - timedelta(hours=1)),
            db=db, current_user=я)
    assert ошибка.value.status_code == 400


async def test_организатор_всегда_участник(db: AsyncSession):
    company, я, другой = await _пара(db)
    ev = await _встреча(db, company, я, другой)
    участники = {a["user_id"]: a["response"] for a in ev["attendees"]}
    assert str(я.id) in участники, "иначе своей встречи в календаре не видно"
    assert участники[str(я.id)] == "accepted"
    assert участники[str(другой.id)] == "pending"


async def test_чужую_встречу_не_подвинуть(db: AsyncSession):
    from fastapi import HTTPException

    company, я, другой = await _пара(db)
    ev = await _встреча(db, company, я, другой)
    новое = datetime.now(timezone.utc) + timedelta(days=3)
    with pytest.raises(HTTPException) as ошибка:
        await calendar_action(
            ev["id"], EventAction(company_id=str(company.id), starts_at=новое,
                                  ends_at=новое + timedelta(hours=1)),
            db=db, current_user=другой)
    assert ошибка.value.status_code == 403


async def test_перенос_обнуляет_согласия(db: AsyncSession):
    company, я, другой = await _пара(db)
    ev = await _встреча(db, company, я, другой)

    ответ = await calendar_action(
        ev["id"], EventAction(company_id=str(company.id), response="accepted"),
        db=db, current_user=другой)
    assert ответ["my_response"] == "accepted"

    новое = datetime.now(timezone.utc) + timedelta(days=2)
    после = await calendar_action(
        ev["id"], EventAction(company_id=str(company.id), starts_at=новое,
                              ends_at=новое + timedelta(hours=1)),
        db=db, current_user=я)
    гость = next(a for a in после["attendees"] if a["user_id"] == str(другой.id))
    assert гость["response"] == "pending", "согласие на другое время не переносится"
    мой = next(a for a in после["attendees"] if a["user_id"] == str(я.id))
    assert мой["response"] == "accepted", "организатор в своей встрече не сомневается"


async def test_отмена_не_удаляет(db: AsyncSession):
    company, я, другой = await _пара(db)
    ev = await _встреча(db, company, я, другой)
    после = await calendar_action(
        ev["id"], EventAction(company_id=str(company.id), cancel=True,
                              cancel_reason="перенесли на следующую неделю"),
        db=db, current_user=я)
    assert после["status"] == "cancelled"
    assert после["cancel_reason"] == "перенесли на следующую неделю"

    # Строка остаётся: встреча уже стоит в чужих календарях, и молча исчезнувшая
    # означает, что кто-то придёт в пустую переговорную.
    строка = await db.get(CalendarEvent, uuid.UUID(ev["id"]))
    assert строка is not None
    остались = list((await db.execute(select(CalendarAttendee).where(
        CalendarAttendee.event_id == строка.id))).scalars())
    assert len(остались) == 2
