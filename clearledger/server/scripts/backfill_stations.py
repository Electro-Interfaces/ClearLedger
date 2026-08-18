"""Разделение точки обслуживания и станции: бэкфилл станций и связей.

Что делает (идемпотентно, повторный запуск ничего не дублирует):
  1) для каждого объекта `ev_charging` находит или заводит единицу оборудования —
     она и есть станция («станция-железка складского контура»);
  2) дозаполняет паспорт станции из прежних граф объекта, НЕ перетирая непустое;
  3) открывает связь «станция размещена в точке обслуживания» с периодом действия.

Что НЕ делает: не трогает читателей и не снимает старые колонки `service_locations`.
Прежние экраны продолжают работать на старом месте — снятие дублей отдельным шагом
после перевода витрин.

Уровень точки отпуска наполняется только по флагу `--evse` и только одной точкой
на станцию: сколько их физически, из имеющихся данных не следует (`connectors_count`
считает разъёмы, а точка отпуска — это «не более одного ТС одновременно»).
СТО п. 15.8 разрешает вести внешний идентификатор на станции, пока уровень не
введён достоверно, поэтому выдумывать структуру ради заполненности не нужно.

Использование:
  docker compose exec ledger-backend python scripts/backfill_stations.py rushydro
  docker compose exec ledger-backend python scripts/backfill_stations.py rushydro --dry-run
  docker compose exec ledger-backend python scripts/backfill_stations.py rushydro --evse
  python scripts/backfill_stations.py --selftest      # без БД

Основание: СТО «Идентификация и учёт объектов зарядной инфраструктуры»,
docs/OBJECTS.md в ecosystem-deploy.
"""
import asyncio
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Паспортные графы: куда в станции переезжает какая графа объекта.
PASSPORT_MAP = (
    ("serial_number", "serial_number"),
    ("model", "model"),
    ("power_kwt", "power_kwt"),
    ("connectors_count", "connectors_count"),
    ("connector_types", "connector_types"),
    ("inventory_number", "inventory_number"),
    ("brand", "brand"),
    ("owner_name", "owner"),
    ("ocpp_protocol", "ocpp_protocol"),
    ("firmware", "firmware"),
    ("speed_class", "speed_class"),
    ("commissioned_on", "installed_on"),
    ("decommissioned_on", "decommissioned_on"),
    ("hubex_asset_id", "hubex_asset_id"),
)


def parse_connector_types(raw: str | None, count: int | None = None) -> list[str | None]:
    """Разбирает состав разъёмов «CCS2, CHAdeMO» в список типов.

    Типов может быть меньше, чем разъёмов (в выгрузке пишут уникальные), поэтому
    список добивается до `count` пустыми: разъём есть, тип неизвестен — это
    честнее, чем повторить последний известный.
    """
    # Разделители — только запятая и точка с запятой: слэш входит в само название
    # разъёма («GB/T»), и резать по нему значит разломать реальный тип надвое.
    types: list[str | None] = [t.strip() for t in re.split(r"[,;]", raw or "") if t.strip()]
    if count and len(types) < count:
        types += [None] * (count - len(types))
    if not types and count:
        return [None] * count
    return types


def _selftest() -> None:
    assert parse_connector_types("CCS2, CHAdeMO") == ["CCS2", "CHAdeMO"]
    assert parse_connector_types("CCS2; GB/T DC") == ["CCS2", "GB/T DC"]  # слэш — часть названия
    assert parse_connector_types("CCS2", 3) == ["CCS2", None, None]
    assert parse_connector_types(None, 2) == [None, None]
    assert parse_connector_types(None) == []
    assert parse_connector_types("  ", 1) == [None]
    print("selftest ok")


if "--selftest" in sys.argv:
    _selftest()
    raise SystemExit(0)

from sqlalchemy import func, select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import EzsConnector, EzsEvse, EzsEquipmentUnit, ObjectLink  # noqa: E402
from app.models import ServiceLocation as L  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = next((a for a in sys.argv[1:] if not a.startswith("--")), "rushydro")
DRY_RUN = "--dry-run" in sys.argv
WITH_EVSE = "--evse" in sys.argv
BASIS_NOTE = "Бэкфилл разделения уровней (СТО, docs/OBJECTS.md)"


async def _open_link(db, cid, loc_id: str) -> ObjectLink | None:
    """Действующая связь станции с этой точкой обслуживания, если она уже есть."""
    return (await db.execute(
        select(ObjectLink).where(
            ObjectLink.company_id == cid,
            ObjectLink.relation == "placed_at",
            ObjectLink.parent_type == "point_of_service",
            ObjectLink.parent_id == loc_id,
            ObjectLink.valid_to.is_(None),
        ).limit(1)
    )).scalar_one_or_none()


async def _find_unit(db, cid, loc: L) -> EzsEquipmentUnit | None:
    """Станция этого объекта: по серийнику, затем по прежней скалярной привязке."""
    serial = (loc.serial_number or "").strip()
    if serial:
        unit = (await db.execute(
            select(EzsEquipmentUnit).where(
                EzsEquipmentUnit.company_id == cid,
                func.lower(EzsEquipmentUnit.serial_number) == serial.lower(),
            ).limit(1)
        )).scalar_one_or_none()
        if unit is not None:
            return unit
    return (await db.execute(
        select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.company_id == cid,
            EzsEquipmentUnit.current_location_id == loc.id,
            EzsEquipmentUnit.state == "in_operation",
        ).limit(1)
    )).scalar_one_or_none()


def _fill_passport(unit: EzsEquipmentUnit, loc: L) -> list[str]:
    """Дозаполняет пустые графы станции. Заполненное не трогает: у склада могли
    поправить серийник руками, и бэкфилл не вправе это отменять."""
    filled = []
    for unit_field, loc_field in PASSPORT_MAP:
        if getattr(unit, unit_field, None) in (None, ""):
            value = getattr(loc, loc_field, None)
            if value not in (None, ""):
                setattr(unit, unit_field, value)
                filled.append(unit_field)
    return filled


def _valid_from(loc: L) -> date:
    """Дата, с которой станция стоит в точке: ввод в эксплуатацию, иначе появление
    записи. Сегодняшнюю дату не берём — это ровно та ошибка, из-за которой дата
    ввода равнялась дню просмотра карточки."""
    raw = (loc.installed_on or "").strip()
    if len(raw) == 10:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return loc.created_at.date() if loc.created_at else date.today()


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        locs = (await db.execute(
            select(L).where(L.company_id == cid, L.type == "ev_charging").order_by(L.code)
        )).scalars().all()
        print(f"company '{COMPANY}' → {cid}; объектов ev_charging: {len(locs)}")

        stats = {"units_created": 0, "units_filled": 0, "links_created": 0,
                 "links_exist": 0, "evse_created": 0, "connectors_created": 0}

        for loc in locs:
            unit = await _find_unit(db, cid, loc)
            if unit is None:
                unit = EzsEquipmentUnit(
                    company_id=cid, kind="station", state="in_operation", is_used=True,
                    current_location_id=loc.id, custodian="site", origin_location_id=loc.id,
                    notes=BASIS_NOTE,
                )
                db.add(unit)
                await db.flush()
                stats["units_created"] += 1

            if _fill_passport(unit, loc):
                stats["units_filled"] += 1

            if await _open_link(db, cid, loc.id) is None:
                db.add(ObjectLink(
                    company_id=cid,
                    parent_type="point_of_service", parent_id=loc.id,
                    child_type="station", child_id=str(unit.id),
                    relation="placed_at",
                    valid_from=_valid_from(loc),
                    basis_note=BASIS_NOTE,
                ))
                stats["links_created"] += 1
            else:
                stats["links_exist"] += 1

            if WITH_EVSE:
                has_evse = (await db.execute(
                    select(EzsEvse.id).where(EzsEvse.unit_id == unit.id).limit(1)
                )).scalar_one_or_none()
                if has_evse is None:
                    evse = EzsEvse(company_id=cid, unit_id=unit.id, number=1,
                                   power_kwt=unit.power_kwt)
                    db.add(evse)
                    await db.flush()
                    stats["evse_created"] += 1
                    types = parse_connector_types(unit.connector_types, unit.connectors_count)
                    for no, ctype in enumerate(types, start=1):
                        db.add(EzsConnector(company_id=cid, evse_id=evse.id,
                                            number=no, connector_type=ctype))
                        stats["connectors_created"] += 1

        if DRY_RUN:
            await db.rollback()
            print("dry-run: изменения откачены")
        else:
            await db.commit()
        print("; ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    asyncio.run(main())
