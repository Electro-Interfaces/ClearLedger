"""Уровень точки отпуска и коннектора — из состава разъёмов АСУиМ (СТО п. 2.5, 2.6).

Раньше наполнение откладывалось: `connectors_count` считает разъёмы, а точка
отпуска — это «не более одного ТС одновременно», и вывести одно из другого нельзя.
Но в снимке загрузки лежит состав с полем `evseId` — идентификатором точки отпуска
в витрине оператора. По нему уровень строится по факту, а не догадкой.

В данных АСУиМ на один `evseId` приходится один разъём (станция 574: четыре
точки отпуска, у каждой свой тип), поэтому коннектор заводится по каждой строке
состава, а точка отпуска — по каждому уникальному `evseId`.

Строки без `evseId` (их 22 из 1577) группируются по номеру разъёма: потерять
разъём хуже, чем приписать его точке отпуска с тем же номером.

`evseId` попадает и в реестр соответствий (`external:asuim_evse`) — это
идентификатор чужой системы, а не наш номер точки отпуска (п. 6.2).

Использование (без --apply ничего не пишет):
  COMPANY_SLUG=rushydro exec-py.sh rushydro backfill_evse.py
  python scripts/backfill_evse.py rushydro --apply
  python scripts/backfill_evse.py --selftest
"""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def group_by_evse(connectors: list[dict]) -> list[tuple[str | None, list[dict]]]:
    """Состав разъёмов → точки отпуска в порядке появления.

    Ключ группировки — `evseId`; где его нет, роль ключа играет номер разъёма.
    Порядок сохраняем: номера точек отпуска присваиваются по нему, и при повторном
    прогоне они должны совпасть, иначе внешний идентификатор уедет на другую точку.
    """
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for c in connectors or []:
        if not isinstance(c, dict):
            continue
        raw = c.get("evseId")
        key = str(raw).strip() if raw not in (None, "") else f"no:{c.get('no')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)
    return [(k if not k.startswith("no:") else None, groups[k]) for k in order]


def _selftest() -> None:
    rows = [
        {"evseId": 5954, "no": 1, "type": "CCS Combo 2", "powerKw": 120.0},
        {"evseId": 5955, "no": 2, "type": "CHAdeMO", "powerKw": 50.0},
        {"evseId": 5954, "no": 3, "type": "Type 2", "powerKw": 22.0},
    ]
    got = group_by_evse(rows)
    assert [k for k, _ in got] == ["5954", "5955"], got
    assert len(got[0][1]) == 2, "два разъёма на одной точке отпуска"

    # без evseId — группируем по номеру разъёма, ключ наружу не отдаём
    got2 = group_by_evse([{"no": 1, "type": "AC"}, {"no": 2, "type": "AC"}])
    assert [k for k, _ in got2] == [None, None]
    assert len(got2) == 2

    assert group_by_evse([]) == []
    assert group_by_evse(None) == []
    assert group_by_evse(["мусор"]) == []
    print("selftest ok")


if __name__ == "__main__" and "--selftest" in sys.argv:
    _selftest()
    raise SystemExit(0)

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import EzsConnector, EzsEvse, ObjectLink  # noqa: E402
from app.models import ServiceLocation as L  # noqa: E402
from app.services.station_passport import stations_by_location  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = os.environ.get("COMPANY_SLUG") or next(
    (a for a in sys.argv[1:] if not a.startswith("--")), "rushydro")
APPLY = "--apply" in sys.argv or os.environ.get("APPLY") == "1"
BASIS_NOTE = "Состав разъёмов из витрины АСУиМ (СТО п. 2.5, 2.6)"


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        locs = (await db.execute(
            select(L).where(L.company_id == cid, L.type == "ev_charging").order_by(L.code)
        )).scalars().all()
        stations = await stations_by_location(db, cid, [l.id for l in locs])

        have_evse = set((await db.execute(
            select(EzsEvse.unit_id).where(EzsEvse.company_id == cid)
        )).scalars().all())
        known_ext = {
            row for row in (await db.execute(
                select(ObjectLink.child_id).where(
                    ObjectLink.company_id == cid,
                    ObjectLink.relation == "external_id",
                    ObjectLink.child_type == "external:asuim_evse")
            )).scalars().all()
        }

        stats = {"evse": 0, "connectors": 0, "ext_ids": 0,
                 "skipped_no_station": 0, "skipped_no_composition": 0, "already": 0}

        for loc in locs:
            unit = stations.get(loc.id)
            if unit is None:
                stats["skipped_no_station"] += 1
                continue
            if unit.id in have_evse:
                stats["already"] += 1
                continue
            groups = group_by_evse((loc.extra_metadata or {}).get("connectors"))
            if not groups:
                stats["skipped_no_composition"] += 1
                continue

            for evse_no, (ext_id, rows) in enumerate(groups, start=1):
                powers = [p for p in (_num(r.get("powerKw")) for r in rows) if p]
                evse = EzsEvse(company_id=cid, unit_id=unit.id, number=evse_no,
                               power_kwt=max(powers) if powers else None)
                db.add(evse)
                await db.flush()
                stats["evse"] += 1

                for conn_no, row in enumerate(rows, start=1):
                    db.add(EzsConnector(
                        company_id=cid, evse_id=evse.id, number=conn_no,
                        connector_type=(str(row.get("type")).strip()[:40]
                                        if row.get("type") else None),
                        power_kwt=_num(row.get("powerKw")),
                    ))
                    stats["connectors"] += 1

                # Идентификатор точки отпуска в витрине оператора — в реестр
                # соответствий, а не в наш номер: чужие ключи своими не становятся.
                if ext_id and ext_id not in known_ext:
                    known_ext.add(ext_id)
                    db.add(ObjectLink(
                        company_id=cid,
                        parent_type="evse", parent_id=str(evse.id),
                        child_type="external:asuim_evse", child_id=ext_id,
                        relation="external_id",
                        valid_from=loc.created_at.date() if loc.created_at else date.today(),
                        basis_note=BASIS_NOTE,
                    ))
                    stats["ext_ids"] += 1

        if APPLY:
            await db.commit()
        else:
            await db.rollback()
            print("dry-run: изменения откачены")
        print("; ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    asyncio.run(main())
