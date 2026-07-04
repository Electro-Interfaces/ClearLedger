"""Удаление старых ev_charging-объектов, НЕ представленных в справочнике станций.

Оставляет только объекты, сматченные строкой справочника (по stationId→serial→№,
логика повторяет ingest_stations) ИЛИ созданные под строку справочника. Старые
HubEx-объекты вне справочника v2 удаляются. Связь сессий (ChargeSession.location_id)
= ON DELETE SET NULL, поэтому удаление безопасно (сессии не теряются, только отвязка).

Использование (по умолчанию DRY-RUN; для удаления добавить --apply):
  python scripts/prune_stale_stations.py /tmp/stations.xlsx rushydro          # показать
  python scripts/prune_stale_stations.py /tmp/stations.xlsx rushydro --apply   # удалить
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import ServiceLocation  # noqa: E402
from app.services.stations_normalize import _loc_id, parse_stations_xlsx  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
XLSX = _args[0] if _args else "/tmp/stations.xlsx"
COMPANY = _args[1] if len(_args) > 1 else "rushydro"
APPLY = "--apply" in sys.argv


async def main() -> None:
    rows = parse_stations_xlsx(Path(XLSX).read_bytes())
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        existing = (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == cid, ServiceLocation.type == "ev_charging"))).scalars().all()

        # индексы резолва — как в ingest_stations
        by_sid: dict = {}
        by_serial: dict = {}
        by_num: dict = {}
        for loc in existing:
            md = loc.extra_metadata or {}
            sid = md.get("stationId") or md.get("ext_id")
            if sid:
                by_sid.setdefault(str(sid).strip(), loc)
            if loc.code:
                by_serial.setdefault(str(loc.code).strip(), loc)
            num = loc.station_number or md.get("number")
            if num is not None and str(num).strip():
                by_num.setdefault(str(num).strip(), loc)

        def resolve(r):
            ext_, serial, num = r.get("ext_id"), r.get("serial_number"), r.get("number")
            return ((by_sid.get(str(ext_).strip()) if ext_ else None)
                    or (by_serial.get(str(serial).strip()) if serial else None)
                    or (by_num.get(str(num).strip()) if num else None))

        keep: set = set()
        for r in rows:
            loc = resolve(r)
            keep.add(loc.id if loc else _loc_id(cid, r.get("ext_id")))

        stale = [o for o in existing if o.id not in keep]
        kept = len(existing) - len(stale)
        print(f"ev_charging: {len(existing)} | строк справочника: {len(rows)} | "
              f"оставить: {kept} | удалить (stale): {len(stale)}")
        for o in stale[:6]:
            print(f"  stale: {str(o.id)[:18]} {o.name!r}")

        if not APPLY:
            print("DRY-RUN — без --apply не удаляю.")
            return
        if stale:
            await db.execute(delete(ServiceLocation).where(
                ServiceLocation.id.in_([o.id for o in stale])))
            await db.commit()
        print(f"✓ удалено {len(stale)} | осталось ev_charging: {kept}")


if __name__ == "__main__":
    asyncio.run(main())
