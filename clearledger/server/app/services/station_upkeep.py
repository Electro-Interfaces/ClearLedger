"""Метрология и обслуживание станции: поверка счётчика и срок следующего ТО.

ЗАЧЕМ ОТДЕЛЬНО ОТ ОСМОТРА. Чек-лист (`station_check.py`) отвечает на вопрос
«что инженер увидел глазами», и пункт «поверка не истекла» там тоже есть. Но
отметка осмотра — это текст: чтобы узнать, у скольких станций сети поверка
кончается в этом квартале, пришлось бы перечитывать примечания. Дата поверки и
периодичность ТО — данные, а не наблюдение, и потому живут полями единицы
оборудования (`EzsEquipmentUnit`), где уже лежит серийный номер и гарантия.

ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ КАЖЕТСЯ. Показания счётчика с истёкшей поверкой
недействительны для расчётов (ФЗ-102 «Об обеспечении единства измерений»): по
такой станции нечем возразить ни клиенту, ни поставщику энергии. Беда тихая —
станция работает, ток идёт, а юридическая сила учёта уже кончилась.

ПЕРИОДИЧНОСТЬ ТО — СВОЙСТВО МОДЕЛИ. Быструю DC-станцию обходят чаще медленной
AC: у неё жидкостное охлаждение, вентиляторы и силовые модули под нагрузкой.
Конкретный интервал ставится у единицы (`service_interval_days`); пусто —
работает норматив по типу, а не «обслуживать не надо».

ЧЕГО ЗДЕСЬ НЕТ. Учёта работ и актов ТО: наряд ведёт «Поддержка», и заводить
второй журнал работ значит развести две правды. Здесь только дата последнего
обслуживания — ровно то, из чего считается «пора ехать».
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsEquipmentUnit, ServiceLocation
from app.services.ops_monitor_context import MSK

#: Норматив обслуживания по типу станции, дней. Применяется, когда у единицы
#: свой интервал не задан.
ТО_ПО_ТИПУ: dict[str, int] = {"DC": 180, "AC": 365}
ТО_ПО_УМОЛЧАНИЮ = 365

#: За сколько дней до конца поверки это уже работа, а не напоминание. Месяц —
#: реальный срок: заявку в метрологию подают, счётчик везут, станция стоит.
ПРЕДУПРЕДИТЬ_ЗА = 30

СОСТОЯНИЯ = {
    "ok": "в порядке",
    "soon": "скоро",
    "overdue": "просрочено",
    "unknown": "не заполнено",
}


def _дата(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def интервал_то(unit: EzsEquipmentUnit) -> int:
    """Периодичность обслуживания: своя у единицы либо норматив по типу."""
    if unit.service_interval_days and unit.service_interval_days > 0:
        return int(unit.service_interval_days)
    return ТО_ПО_ТИПУ.get((unit.station_type or "").upper(), ТО_ПО_УМОЛЧАНИЮ)


def _срок(до: date | None, сегодня: date) -> tuple[str, int | None]:
    """Состояние срока и сколько дней осталось (отрицательное — просрочено)."""
    if до is None:
        return "unknown", None
    осталось = (до - сегодня).days
    if осталось < 0:
        return "overdue", осталось
    return ("soon" if осталось <= ПРЕДУПРЕДИТЬ_ЗА else "ok"), осталось


def разбор(unit: EzsEquipmentUnit, сегодня: date | None = None) -> dict[str, Any]:
    """Метрология и ТО одной единицы — общий расчёт для карточки и для сети."""
    сегодня = сегодня or datetime.now(timezone.utc).date()

    поверка_до = _дата(unit.meter_verify_until)
    м_состояние, м_осталось = _срок(поверка_до, сегодня)

    интервал = интервал_то(unit)
    последнее = _дата(unit.last_service_on)
    следующее = (последнее + timedelta(days=интервал)) if последнее else None
    т_состояние, т_осталось = _срок(следующее, сегодня)

    return {
        "unitId": str(unit.id),
        "serial": unit.serial_number,
        "vendor": unit.vendor,
        "model": unit.model,
        "stationType": unit.station_type,
        "meter": {
            "serial": unit.meter_serial,
            "verifiedOn": unit.meter_verified_on,
            "verifyUntil": unit.meter_verify_until,
            "state": м_состояние,
            "stateLabel": СОСТОЯНИЯ[м_состояние],
            "daysLeft": м_осталось,
        },
        "service": {
            "intervalDays": интервал,
            # Интервал взят из норматива типа, а не задан человеком: показываем
            # честно, иначе «раз в 365 дней» читается как решение, которого не было.
            "intervalDefault": not (unit.service_interval_days and unit.service_interval_days > 0),
            "lastOn": unit.last_service_on,
            "nextOn": следующее.isoformat() if следующее else None,
            "state": т_состояние,
            "stateLabel": СОСТОЯНИЯ[т_состояние],
            "daysLeft": т_осталось,
        },
        "warrantyUntil": unit.warranty_until,
    }


async def _единица(db: AsyncSession, company_id: uuid.UUID,
                   location_id: str) -> EzsEquipmentUnit | None:
    return (await db.execute(
        select(EzsEquipmentUnit)
        .where(EzsEquipmentUnit.company_id == company_id,
               EzsEquipmentUnit.current_location_id == location_id)
        .order_by(EzsEquipmentUnit.created_at)
        .limit(1))).scalar_one_or_none()


async def station_upkeep(db: AsyncSession, company_id: uuid.UUID,
                         location_id: str) -> dict[str, Any]:
    """Метрология и обслуживание станции на точке."""
    loc = (await db.execute(select(ServiceLocation.id).where(
        ServiceLocation.id == location_id,
        ServiceLocation.company_id == company_id))).scalar_one_or_none()
    if loc is None:
        raise ValueError("Станция не найдена")

    unit = await _единица(db, company_id, location_id)
    if unit is None:
        # Точка есть, железка за ней не закреплена — писать поверку некуда.
        # Молча показать пустые поля значило бы предложить завести метрологию
        # у места, а не у прибора: при замене станции она уехала бы за точкой.
        return {"hasUnit": False, "note": (
            "за точкой не закреплена единица оборудования: метрология и график "
            "обслуживания ведутся у станции-железки, а не у места")}

    return {"hasUnit": True, **разбор(unit),
            "note": ("поверка — ФЗ-102: показания счётчика с истёкшей поверкой "
                     "недействительны для расчётов")}


async def set_upkeep(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    meter_serial: str | None = None,
    meter_verified_on: str | None = None,
    meter_verify_until: str | None = None,
    service_interval_days: int | None = None,
    last_service_on: str | None = None,
) -> dict[str, Any]:
    """Записать метрологию и обслуживание. Переданы только изменяемые поля."""
    unit = await _единица(db, company_id, location_id)
    if unit is None:
        raise ValueError("За точкой не закреплена единица оборудования")

    поля = {
        "meter_serial": meter_serial,
        "meter_verified_on": meter_verified_on,
        "meter_verify_until": meter_verify_until,
        "service_interval_days": service_interval_days,
        "last_service_on": last_service_on,
    }
    for k, v in поля.items():
        if v is None:
            continue
        # Пустая строка — осознанное «стереть»: иначе ошибочно введённую дату
        # поверки нечем убрать, и станция навсегда остаётся просроченной.
        if isinstance(v, str):
            v = v.strip()
            if k.endswith("_on") or k.endswith("_until"):
                if v and _дата(v) is None:
                    raise ValueError(f"Неверная дата: {v}")
            v = v or None
        setattr(unit, k, v)
    await db.flush()
    return разбор(unit)


async def network_upkeep(db: AsyncSession, company_id: uuid.UUID, *, as_of: date | None = None) -> dict[str, Any]:
    """Сроки по всей сети: у кого кончается поверка и кого пора обслуживать.

    Считается по станциям В ЭКСПЛУАТАЦИИ: у склада и списанных единиц поверка
    тоже истекает, но это не работа сегодняшнего дня.
    """
    units = (await db.execute(
        select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.company_id == company_id,
            EzsEquipmentUnit.state == "in_operation",
            EzsEquipmentUnit.current_location_id.isnot(None)))).scalars().all()

    сегодня = as_of or datetime.now(MSK).date()
    строки = []
    for u in units:
        р = разбор(u, сегодня)
        строки.append({"locationId": u.current_location_id, **р})

    def счёт(раздел: str, состояние: str) -> int:
        return sum(1 for r in строки if r[раздел]["state"] == состояние)

    return {
        "totals": {
            "units": len(строки),
            "meterOverdue": счёт("meter", "overdue"),
            "meterSoon": счёт("meter", "soon"),
            "meterUnknown": счёт("meter", "unknown"),
            "serviceOverdue": счёт("service", "overdue"),
            "serviceSoon": счёт("service", "soon"),
            "serviceUnknown": счёт("service", "unknown"),
        },
        "rows": строки,
        "note": (f"поверка предупреждает за {ПРЕДУПРЕДИТЬ_ЗА} дн.; интервал ТО — "
                 f"свой у станции либо норматив типа (DC {ТО_ПО_ТИПУ['DC']} дн., "
                 f"AC {ТО_ПО_ТИПУ['AC']} дн.)"),
    }


def demo() -> None:
    """Самопроверка расчёта сроков без базы."""
    class У:  # минимальная заглушка единицы
        id = uuid.uuid4(); serial_number = "X1"; vendor = "Setec"; model = None
        station_type = "DC"; warranty_until = None
        meter_serial = "M-1"; meter_verified_on = "2024-01-10"
        meter_verify_until = None; service_interval_days = None
        last_service_on = None

    сегодня = date(2026, 9, 20)
    u = У()

    # ничего не заполнено — «не заполнено», а не «в порядке»
    р = разбор(u, сегодня)
    assert р["meter"]["state"] == "unknown", р
    assert р["service"]["state"] == "unknown", р
    assert р["service"]["intervalDays"] == 180 and р["service"]["intervalDefault"]

    # поверка кончилась вчера
    u.meter_verify_until = "2026-09-19"
    assert разбор(u, сегодня)["meter"]["state"] == "overdue"
    # кончается через две недели — уже работа
    u.meter_verify_until = "2026-10-04"
    assert разбор(u, сегодня)["meter"]["state"] == "soon"
    # через год — спокойно
    u.meter_verify_until = "2027-09-19"
    assert разбор(u, сегодня)["meter"]["state"] == "ok"

    # ТО: DC раз в 180 дней, последнее было год назад
    u.last_service_on = "2025-09-20"
    р = разбор(u, сегодня)
    assert р["service"]["state"] == "overdue" and р["service"]["nextOn"] == "2026-03-19", р
    # свой интервал перебивает норматив типа
    u.service_interval_days = 400
    р = разбор(u, сегодня)
    assert р["service"]["state"] == "ok" and not р["service"]["intervalDefault"], р
    print("station_upkeep: расчёт сроков сходится")


if __name__ == "__main__":
    demo()
