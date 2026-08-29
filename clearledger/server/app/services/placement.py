"""Личная раскладка работы: как человек разложил у себя чужие и свои предметы.

Раскладка — надстройка над работой, а не её часть. Она отвечает на три вопроса
об одном предмете: в какой моей подборке он лежит, когда я им занимаюсь и важен ли
он мне. Ничего в самом предмете при этом не меняется: срок остаётся общим,
состояние — объективным, а видит отметку только хозяин.

Два правила живут здесь, а не в роутере, потому что раскладку трогают из строки
очереди, с доски и из карточки, и разойтись они не должны.

1. **Отложить у себя — не отложить срок.** Личное сокрытие прячет предмет из
   раскладки, но просрочка идёт по расписанию компании. Поэтому отложить дальше
   срока нельзя — дата обрезается днём срока, — а просроченное не прячется
   вовсе. Без этого «не сегодня» становится способом обнулить обязательство.
2. **Откладывание считается.** `defer_count` показывается хозяину и меняет
   ПРЕДЛОЖЕНИЕ, а не текст: на измеренных данных отклонивший первое напоминание
   серии отклоняет следующие в 88% случаев, так что повторять то же самое
   бессмысленно. Наверх этот счётчик не уходит никогда: как только его видит
   руководитель, люди перестают откладывать и начинают закрывать формально.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PersonalMark


class DeferRefused(ValueError):
    """Отложить нельзя, и причина называется вслух."""


def out(row: PersonalMark | None) -> dict | None:
    """Отметка для клиента. `None` — предмет не разложен, и это нормальное
    состояние, а не пустые поля."""
    if row is None:
        return None
    return {
        "list_id": str(row.list_id) if row.list_id else None,
        "taken_for": row.taken_for.isoformat() if row.taken_for else None,
        "deferred_until": (row.deferred_until.isoformat()
                           if row.deferred_until else None),
        "starred": row.starred,
        "defer_count": row.defer_count or 0,
        "position": row.position,
    }


async def marks_for(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID,
                    refs: list[str]) -> dict[str, PersonalMark]:
    """Отметки на перечисленные предметы одним запросом.

    Одним, а не по строке на предмет: очередь показывает две сотни строк, и
    отдельный запрос на каждую превратил бы открытие «Сегодня» в две сотни
    обращений к базе.
    """
    if not refs:
        return {}
    rows = (await db.execute(select(PersonalMark).where(
        PersonalMark.company_id == company_id,
        PersonalMark.user_id == user_id,
        PersonalMark.target_ref.in_(set(refs))))).scalars().all()
    return {r.target_ref: r for r in rows}


def _day(value: datetime | str | None) -> date | None:
    """Срок предмета как календарный день. Строку принимаем потому, что очередь
    отдаёт срок в ISO, а не объектом."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date()


def clamp_defer(until: date, due: datetime | str | None,
                today: date | None = None) -> date:
    """До какого дня отложение допустимо.

    Чистая функция, поэтому проверяется без базы. Просроченное не прячется
    вовсе; отложенное дальше срока возвращается в день срока.
    """
    today = today or datetime.now(timezone.utc).date()
    if until <= today:
        raise DeferRefused("Отложить можно только на будущий день")
    day = _day(due)
    if day is None:
        return until
    if day <= today:
        raise DeferRefused(
            "Срок уже прошёл: просроченное не прячется — его закрывают, "
            "передают или переносят срок")
    return min(until, day)


async def put(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID,
              target_ref: str, *, list_id: uuid.UUID | None = None,
              taken_for: date | None = None, deferred_until: date | None = None,
              starred: bool | None = None, position: int | None = None,
              due_at: datetime | str | None = None, today: date | None = None,
              drop_day: bool = False, undefer: bool = False,
              clear: bool = False) -> PersonalMark | None:
    """Поставить или изменить отметку. Переданное меняется, остальное стоит.

    Право на предмет здесь не проверяется намеренно, тем же соображением, что у
    напоминания: отметка ничего не открывает — она хранит ссылку. Проверка
    случится там, где человек по ссылке пойдёт, а раскладка чужого документа без
    доступа просто не покажет строку.
    """
    row = (await db.execute(select(PersonalMark).where(
        PersonalMark.company_id == company_id,
        PersonalMark.user_id == user_id,
        PersonalMark.target_ref == target_ref))).scalar_one_or_none()

    if clear:
        if row is not None:
            await db.delete(row)
        return None

    if row is None:
        row = PersonalMark(company_id=company_id, user_id=user_id,
                           target_ref=target_ref)
        db.add(row)

    if list_id is not None:
        # Подборка эксклюзивна: назначение новой вытесняет прежнюю, а не добавляет
        # вторую. Пустой UUID сюда не приходит — «убрать из подборки» это `clear`
        # или явный `list_id=None` в роутере.
        row.list_id = list_id
    if drop_day:
        # Снятие с дня — отдельный флаг, а не пустое значение: `None` здесь
        # значит «не трогать», и без флага кнопка «убрать из дня» молча ничего
        # бы не делала.
        row.taken_for = None
    if undefer:
        # Возврат из отложенного не увеличивает счётчик: человек передумал
        # прятать, а не отложил ещё раз.
        row.deferred_until = None
    if taken_for is not None:
        row.taken_for = taken_for
        # Взял в день — значит уже не отложено: два ответа на вопрос «когда»
        # одновременно означали бы, что предмет и в дне, и спрятан.
        row.deferred_until = None
    if deferred_until is not None:
        # `today` — местный день ЧЕЛОВЕКА: он прячет предмет у себя, и «завтра»
        # у него наступает по его часам, а не по серверным.
        row.deferred_until = clamp_defer(deferred_until, due_at, today)
        row.taken_for = None
        # `default=0` у колонки применяется при ВСТАВКЕ, а не при создании
        # объекта: у только что заведённой отметки счётчик ещё None, и
        # первое же «не сегодня» по неразложенному предмету падало с 500.
        row.defer_count = (row.defer_count or 0) + 1
    if starred is not None:
        row.starred = starred
    if position is not None:
        row.position = position
    await db.flush()
    return row


def hidden(mark: PersonalMark | None, today: date | None = None) -> bool:
    """Спрятано ли сейчас: отложено до будущего дня."""
    if mark is None or mark.deferred_until is None:
        return False
    return mark.deferred_until > (today or datetime.now(timezone.utc).date())
