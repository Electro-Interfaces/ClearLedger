"""Паспорт станции, стоящей в точке обслуживания.

После разделения уровней (СТО, `docs/OBJECTS.md`) заводской номер, модель,
мощность, инвентарный номер и прочие графы железа принадлежат **станции**, а не
точке обслуживания. Прежние колонки `service_locations` при этом остались на
месте: снимать их до перевода всех читателей нельзя.

Отсюда правило: **графу спрашиваем у того, кто её пишет, с фолбэком на второго**.
Конвейеры загрузки переведены на запись владельцу (`write_value`), поэтому
владелец всех граф — станция; пока связь не заведена, и чтение, и запись идут в
точку, как до разделения. Никакой даты переключения не требуется, и откат не
ломает витрины.

Станция ищется по связи с периодом действия, а не по скалярной ссылке: в точке
за годы стоят разные станции, и «какая стоит сейчас» — это вопрос с датой.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsEquipmentUnit, ObjectLink

# Графа паспорта → откуда её брать: (поле станции, поле точки).
# Пусто в поле станции означает «станция не знает» — тогда работает вторая колонка.
PASSPORT_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("serialNumber", "serial_number", "serial_number"),
    ("powerKwt", "power_kwt", "power_kwt"),
    ("connectorsCount", "connectors_count", "connectors_count"),
    ("connectorTypes", "connector_types", "connector_types"),
    ("brand", "brand", "brand"),
    ("model", "model", "model"),
    ("owner", "owner_name", "owner"),
    ("ocppProtocol", "ocpp_protocol", "ocpp_protocol"),
    ("firmware", "firmware", "firmware"),
    ("speedClass", "speed_class", "speed_class"),
    ("installedOn", "commissioned_on", "installed_on"),
    ("decommissionedOn", "decommissioned_on", "decommissioned_on"),
    ("inventoryNumber", "inventory_number", "inventory_number"),
    ("hubexAssetId", "hubex_asset_id", "hubex_asset_id"),
)


# Раздвоения владельцев больше нет: конвейеры загрузки пишут паспорт владельцу
# графы (`write_value`), а не в колонки точки — переведены нормализация разъёмов
# (`asuim_normalize`), нормализация станций (`stations_normalize`) и реестр
# РусГидро (`reestr_rushydro`). Поэтому спрашиваем станцию первой у ВСЕХ граф.
#
# Множество оставлено пустым намеренно: если запись какой-то графы вернётся в
# точку (новый конвейер, чужая интеграция), её имя добавляется сюда — и читатель
# сразу перестаёт показывать застывшее значение станции.
FEED_OWNED: frozenset[str] = frozenset()


def passport_value(key: str, loc, unit) -> object | None:
    """Значение одной графы у того, кто ею владеет, с фолбэком на второго.

    Владелец — станция, кроме граф из `FEED_OWNED`: их до сих пор пишет загрузка
    в колонки точки, и спрашивать станцию первой значило бы показывать устаревшее.
    """
    for out_key, unit_field, loc_field in PASSPORT_SOURCES:
        if out_key != key:
            continue
        loc_value = getattr(loc, loc_field, None)
        unit_value = getattr(unit, unit_field, None) if unit is not None else None
        first, second = ((loc_value, unit_value) if out_key in FEED_OWNED
                         else (unit_value, loc_value))
        return first if first not in (None, "") else second
    return getattr(loc, key, None)


def write_value(key: str, loc, unit, value) -> bool:
    """Записать графу её владельцу: станции, если она заведена, иначе точке.

    Пишем в одно место, а не в оба: двойная запись рождает вопрос «чья правда»
    ровно там, где мы его только что убрали. Пока связь не заведена (новая точка,
    объект без станции), запись идёт в точку — как до разделения, и читатель
    возьмёт её оттуда фолбэком.

    Возвращает True, если значение изменилось: конвейеры считают по этому признаку
    «обновлено N станций», и терять счётчик нельзя.
    """
    for out_key, unit_field, loc_field in PASSPORT_SOURCES:
        if out_key != key:
            continue
        target, field = ((unit, unit_field) if unit is not None else (loc, loc_field))
        if getattr(target, field, None) == value:
            return False
        setattr(target, field, value)
        return True
    if getattr(loc, key, None) == value:
        return False
    setattr(loc, key, value)
    return True


async def stations_by_location(
    db: AsyncSession,
    company_id,
    location_ids: list[str] | None,
    on: date | None = None,
) -> dict[str, EzsEquipmentUnit]:
    """Карта «точка обслуживания → станция, стоящая в ней на дату».

    Один запрос на весь список: карточка объекта открывается из реестра сети, где
    объектов шестьсот, и запрос на каждую строку превратил бы список в N+1.

    `location_ids=None` — все точки компании: конвейерам загрузки список заранее
    неизвестен, объекты резолвятся по ходу разбора файла.
    """
    if location_ids is not None and not location_ids:
        return {}
    on = on or date.today()
    # Два запроса вместо join'а: `child_id` — текст (там бывает и nanoid точки, и
    # значение внешнего идентификатора), а `id` станции — uuid. Приведение типа в
    # join'е ради одного похода в базу не стоит хрупкости.
    links = (await db.execute(
        select(ObjectLink.parent_id, ObjectLink.child_id).where(
            ObjectLink.company_id == company_id,
            ObjectLink.relation == "placed_at",
            ObjectLink.parent_type == "point_of_service",
            ObjectLink.child_type == "station",
            *([ObjectLink.parent_id.in_(location_ids)] if location_ids is not None else []),
            ObjectLink.valid_from <= on,
            or_(ObjectLink.valid_to.is_(None), ObjectLink.valid_to > on),
        )
    )).all()
    if not links:
        return {}

    by_unit: dict[str, str] = {}
    unit_ids: list[uuid.UUID] = []
    for loc_id, child_id in links:
        try:
            unit_uuid = uuid.UUID(child_id)
        except ValueError:
            continue
        by_unit[child_id] = loc_id
        unit_ids.append(unit_uuid)

    units = (await db.execute(
        select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.company_id == company_id,
            EzsEquipmentUnit.id.in_(unit_ids),
        )
    )).scalars().all()
    return {by_unit[str(u.id)]: u for u in units if str(u.id) in by_unit}
