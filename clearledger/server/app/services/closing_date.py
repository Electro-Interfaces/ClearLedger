"""Дата запрета изменения: граница закрытого бухгалтерией периода.

Одно значение на компанию — та же дата, что стоит в БП ГИГ. Она же уходит на
станции заданием и применяется там локально, в том числе без связи. Всё, что
относится к этой дате и раньше, не правится и не пересобирается: уточнение
оформляется документом открытой даты, как это делает бухгалтерия.

Почему одна дата, а не реестр периодов со статусами: это единственная граница,
которую бухгалтерия ведёт для себя, и она не требует от станции знать про
месяцы, кварталы и то, какой документ куда проведён.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ClosedPeriodError(Exception):
    """Факт относится к закрытому дню: менять его нельзя."""


async def get_closing_date(session: AsyncSession, company_id: uuid.UUID) -> date | None:
    """Действующая дата запрета. None — период не закрывали, ограничений нет."""
    row = (await session.execute(text("""
        SELECT closing_date FROM accounting_closing_date WHERE company_id = :c
    """), {"c": str(company_id)})).scalar_one_or_none()
    return row


async def set_closing_date(
    session: AsyncSession,
    company_id: uuid.UUID,
    closing_date: date | None,
    author: str,
    note: str = "",
) -> int:
    """Поставить дату и разослать её станциям.

    Пустая дата снимает запрет — так период открывают обратно. Возвращает число
    станций, которым ушло задание: правка в центре сама по себе ничего не меняет
    на АЗС, станция забирает задания своим тактом.
    """
    await session.execute(text("""
        INSERT INTO accounting_closing_date (company_id, closing_date, author, note, updated_at)
        VALUES (:c, :d, :a, :n, now())
        ON CONFLICT (company_id) DO UPDATE
           SET closing_date = EXCLUDED.closing_date,
               author = EXCLUDED.author,
               note = EXCLUDED.note,
               updated_at = now()
    """), {"c": str(company_id), "d": closing_date, "a": author or "", "n": note or ""})
    return await queue_closing_date(session, company_id, closing_date)


async def queue_closing_date(
    session: AsyncSession, company_id: uuid.UUID, closing_date: date | None
) -> int:
    """Положить дату в очередь заданий каждой станции компании.

    Задание идемпотентно: оно несёт саму дату, а не «сдвинь границу». Прежние
    невыданные задания того же вида снимаем — станции нужна последняя граница,
    а не их история.
    """
    from ..models import EdgeDownlink  # локальный импорт: модели тянут database

    stations = [r[0] for r in (await session.execute(text("""
        SELECT id FROM edge.station
        UNION
        SELECT station_id FROM edge_agents
         WHERE company_id = :c AND station_id IS NOT NULL
    """), {"c": str(company_id)})).all()]
    payload = {"date": closing_date.isoformat() if closing_date else ""}
    for station_id in stations:
        await session.execute(text("""
            DELETE FROM edge_downlink
             WHERE company_id = :c AND station_id = :s AND kind = 'accounting_closing_date'
               AND delivered_at IS NULL AND acked_at IS NULL AND cancelled_at IS NULL
        """), {"c": str(company_id), "s": station_id})
        session.add(EdgeDownlink(
            company_id=company_id, station_id=station_id,
            kind="accounting_closing_date", payload=payload,
        ))
    return len(stations)


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def assert_period_open(
    session: AsyncSession,
    company_id: uuid.UUID,
    fact_times,
    what: str = "документ",
) -> None:
    """Не дать тронуть факт закрытого дня.

    Проверка идёт по САМОЙ РАННЕЙ дате факта: если ею задет закрытый день,
    операция отклоняется целиком — частично проведённая группа хуже
    непроведённой. Отказ называет саму дату: «нельзя» без даты заставляет идти
    спрашивать.
    """
    closing = await get_closing_date(session, company_id)
    if closing is None:
        return
    dates = [d for d in (_as_date(value) for value in fact_times) if d is not None]
    if not dates:
        return
    earliest = min(dates)
    if earliest > closing:
        return
    raise ClosedPeriodError(
        f"{what} за {earliest.strftime('%d.%m.%Y')}: период закрыт бухгалтерией "
        f"по {closing.strftime('%d.%m.%Y')}. Проведите уточнение документом "
        f"открытой даты со ссылкой на исходный"
    )
