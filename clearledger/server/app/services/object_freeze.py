"""Заморозка номера объекта (СТО п. 7.5, 7.6).

После наступления замораживающего события номер объекта не подлежит изменению, и
запрет обязан быть программным, а не устным. Смысл нормы прикладной: по номеру
объект уже нашли снаружи — в договоре, в проводке, в чужой системе, — и правка
номера рвёт эти ссылки молча.

Замораживающих событий четыре (п. 7.6):

1. привязка объекта к договору;
2. принятие станции к бухгалтерскому учёту (у станции появился инвентарный номер);
3. регистрация первой зарядной сессии;
4. передача сведений об объекте во внешнюю систему по журналу выгрузок.

**Обмен между информационными системами организации замораживающим событием не
является** — это оговорено в норме прямо. Проекция из Ядра в Поддержку и выгрузка
по внутреннему ключу заморозку не вызывают, поэтому четвёртое событие считается
только по записям журнала, помеченным как внешние.
"""
from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChargeSession, ContractLocation, EzsEquipmentUnit, ObjectExportLog, ObjectLink,
    ServiceLocation,
)

# Человекочитаемые причины: их видит тот, кому отказали в правке номера, и по ним
# должно быть понятно, что делать дальше.
REASON_CONTRACT = "объект привязан к договору"
REASON_ACCOUNTED = "станция принята к бухгалтерскому учёту"
REASON_SESSION = "по объекту зарегистрирована зарядная сессия"
REASON_EXPORTED = "сведения об объекте переданы во внешнюю систему"


async def freeze_reasons(db: AsyncSession, company_id, location_id: str) -> list[str]:
    """Все наступившие замораживающие события. Пустой список — номер менять можно.

    Возвращаем именно список, а не флаг: человеку важно знать, ЧТО заморозило
    номер. «Нельзя» без причины провоцирует правку в обход системы.
    """
    reasons: list[str] = []

    has_contract = await db.scalar(select(exists().where(
        ContractLocation.location_id == location_id)))
    if has_contract:
        reasons.append(REASON_CONTRACT)

    # Станции этой точки за всю историю: инвентарный номер мог получить и та,
    # что уже снята, — принятие к учёту не отменяется демонтажом.
    station_ids = list((await db.execute(
        select(ObjectLink.child_id).where(
            ObjectLink.company_id == company_id,
            ObjectLink.relation == "placed_at",
            ObjectLink.parent_id == location_id,
            ObjectLink.child_type == "station",
        )
    )).scalars().all())

    if station_ids:
        accounted = await db.scalar(select(exists().where(
            EzsEquipmentUnit.company_id == company_id,
            EzsEquipmentUnit.id.in_([_uuid(x) for x in station_ids if _uuid(x)]),
            EzsEquipmentUnit.inventory_number.is_not(None),
        )))
        if accounted:
            reasons.append(REASON_ACCOUNTED)

    has_session = await db.scalar(select(exists().where(
        ChargeSession.company_id == company_id,
        ChargeSession.location_id == location_id)))
    if has_session:
        reasons.append(REASON_SESSION)

    # Четвёртое событие — передача во ВНЕШНЮЮ систему. Обмен между системами
    # организации (проекция Ядро → Поддержка) сюда не относится по п. 7.6, поэтому
    # признаком служит запись реестра соответствий: идентификатор в чужой системе
    # означает, что объект туда уже уехал. Смотрим и на точку, и на её станции —
    # идентификатор мог быть записан на любом уровне.
    exported = await db.scalar(select(exists().where(
        ObjectLink.company_id == company_id,
        ObjectLink.relation == "external_id",
        ObjectLink.parent_id.in_([location_id, *station_ids]),
    )))
    if not exported:
        # Второй признак — запись журнала выгрузок, помеченная как внешняя
        # (п. 12.3). Реестр соответствий свидетельствует о состоявшейся передаче
        # адресно, журнал — о передаче как таковой; для заморозки годится любое.
        exported = await db.scalar(select(exists().where(
            ObjectExportLog.company_id == company_id,
            ObjectExportLog.is_external.is_(True),
        )))
    if exported:
        reasons.append(REASON_EXPORTED)

    return reasons


def _uuid(value: str):
    """Идентификатор станции из связи; не-uuid значит «не станция» — пропускаем."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def number_changed(loc: ServiceLocation, new_code: str | None,
                   new_number: str | None) -> bool:
    """Меняется ли номер объекта. Номер — это `code` и «Номер станции».

    Заводской, инвентарный и внешний идентификаторы номерами объекта не являются
    (п. 2.9) и под заморозку не подпадают: их ведут изготовитель, учётная система
    и чужие системы соответственно.
    """
    if new_code is not None and str(new_code).strip() != (loc.code or ""):
        return True
    if new_number is not None and str(new_number).strip() != (loc.station_number or ""):
        return True
    return False
