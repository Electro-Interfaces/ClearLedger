"""Реестр соответствий: идентификаторы внешних систем — в связи с периодом.

СТО раздел 8 требует вести соответствия объектов организации идентификаторам
внешних систем одним реестром: уровень объекта, система, значение, даты начала и
окончания действия, источник. Сегодня они разбросаны по снимку загрузки
(`extra_metadata`) и колонке `hubex_asset_id`, и ответить на вопрос «кому
принадлежит этот идентификатор» можно только перебором JSONB.

Механика та же, что у размещения станции: `object_links` с `relation='external_id'`.
Отдельной таблицы не заводим — правила совпадают дословно (закрытие датой вместо
удаления, запрет двух объектов на одно значение в один период), а EXCLUDE по
(компания, тип, значение, отношение, период) даёт норму п. 8.4 бесплатно.

Уровень: идентификаторы чужих систем описывают ЖЕЛЕЗО (актив в FSM, станция в
витрине оператора, адрес в OCPP), поэтому вешаются на станцию. Если станции нет
(тестовый объект, выведенная станция со снятой связью) — на точку обслуживания:
потерять соответствие хуже, чем записать его уровнем выше.

Снимок загрузки остаётся на месте: он сырьё конвейера, а реестр — нормализованное
представление. Читателей у реестра пока нет, и это осознанно — сначала данные.

Использование (без --apply ничего не пишет):
  COMPANY_SLUG=rushydro exec-py.sh rushydro backfill_external_ids.py
  python scripts/backfill_external_ids.py rushydro --apply
  python scripts/backfill_external_ids.py --selftest
"""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Система → откуда брать значение. Порядок важен только для читаемости отчёта.
#   asuim — витрина АСУиМ (в снимке лежит дважды: ext_id дублирует asuimStationId);
#   hubex — актив в FSM подрядчика (колонка паспорта, в снимке — hubexAssetId);
#   ocpp  — адрес станции в протоколе управления зарядкой;
#   cpo   — идентификатор станции в системе оператора.
SYSTEMS: tuple[tuple[str, str, str | None], ...] = (
    ("asuim", "asuimStationId", None),
    ("hubex", "hubexAssetId", "hubex_asset_id"),
    ("ocpp", "ocppId", None),
    ("cpo", "stationId", None),
)


def external_values(loc) -> list[tuple[str, str]]:
    """Пары (система, значение) для одного объекта — без пустых и дублей.

    Значение колонки паспорта главнее снимка: снимок переживает правки руками,
    а колонку ведёт связка с внешней системой.
    """
    out: list[tuple[str, str]] = []
    meta = getattr(loc, "extra_metadata", None) or {}
    for system, meta_key, column in SYSTEMS:
        raw = None
        if column:
            raw = getattr(loc, column, None)
        if raw in (None, ""):
            raw = meta.get(meta_key)
        value = str(raw).strip() if raw not in (None, "") else ""
        if value:
            out.append((system, value))
    return out


def _selftest() -> None:
    from types import SimpleNamespace

    loc = SimpleNamespace(hubex_asset_id="H-1", extra_metadata={
        "asuimStationId": "A-1", "ocppId": " O-1 ", "stationId": "", "hubexAssetId": "H-OLD"})
    assert external_values(loc) == [("asuim", "A-1"), ("hubex", "H-1"), ("ocpp", "O-1")], \
        external_values(loc)

    # колонка пуста — берём снимок
    loc2 = SimpleNamespace(hubex_asset_id=None, extra_metadata={"hubexAssetId": "H-2"})
    assert external_values(loc2) == [("hubex", "H-2")]

    # нет ничего — нет и записей
    assert external_values(SimpleNamespace(hubex_asset_id=None, extra_metadata=None)) == []
    print("selftest ok")


if __name__ == "__main__" and "--selftest" in sys.argv:
    _selftest()
    raise SystemExit(0)

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import ObjectLink  # noqa: E402
from app.models import ServiceLocation as L  # noqa: E402
from app.services.station_passport import stations_by_location  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = os.environ.get("COMPANY_SLUG") or next(
    (a for a in sys.argv[1:] if not a.startswith("--")), "rushydro")
APPLY = "--apply" in sys.argv or os.environ.get("APPLY") == "1"
BASIS_NOTE = "Реестр соответствий из снимка загрузки (СТО раздел 8)"


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        locs = (await db.execute(
            select(L).where(L.company_id == cid, L.type == "ev_charging").order_by(L.code)
        )).scalars().all()
        stations = await stations_by_location(db, cid, [l.id for l in locs])

        existing = {
            (row.child_type, row.child_id)
            for row in (await db.execute(
                select(ObjectLink).where(ObjectLink.company_id == cid,
                                         ObjectLink.relation == "external_id")
            )).scalars().all()
        }

        stats = {"created": 0, "exists": 0, "on_station": 0, "on_point": 0}
        conflicts: list[str] = []
        seen: dict[tuple[str, str], str] = {}

        for loc in locs:
            unit = stations.get(loc.id)
            parent_type, parent_id = (("station", str(unit.id)) if unit is not None
                                      else ("point_of_service", loc.id))
            # Дата, с которой соответствие известно: раньше появления записи об
            # объекте его быть не могло, а точной даты выдачи нам никто не сообщал.
            start = loc.created_at.date() if loc.created_at else date.today()

            for system, value in external_values(loc):
                child_type = f"external:{system}"
                key = (child_type, value)
                if key in existing:
                    stats["exists"] += 1
                    continue
                if key in seen and seen[key] != parent_id:
                    # Норма п. 8.4: одно значение — один объект в один период.
                    conflicts.append(f"{system} «{value}»: {seen[key]} и {loc.code}")
                    continue
                seen[key] = parent_id
                db.add(ObjectLink(
                    company_id=cid,
                    parent_type=parent_type, parent_id=parent_id,
                    child_type=child_type, child_id=value,
                    relation="external_id",
                    valid_from=start,
                    basis_note=BASIS_NOTE,
                ))
                stats["created"] += 1
                stats["on_station" if unit is not None else "on_point"] += 1

        if APPLY:
            await db.commit()
        else:
            await db.rollback()
            print("dry-run: изменения откачены")
        print("; ".join(f"{k}={v}" for k, v in stats.items()))
        if conflicts:
            print(f"\nОдно значение у разных объектов ({len(conflicts)}):")
            for line in conflicts[:20]:
                print(f"  · {line}")


if __name__ == "__main__":
    asyncio.run(main())
