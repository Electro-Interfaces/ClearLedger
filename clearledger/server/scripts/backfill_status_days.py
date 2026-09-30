"""Ряд статусов станций по дням — из сохранённых книг витрины АСУиМ.

Книги лежат в `source_files` с 11.09.2026, а ряд `station_status_days` заводится
только с выпуска 30.09. Скрипт проходит книги по порядку загрузки, пишет срез
каждой (повторный прогон перезаписывает те же дни) и восстанавливает журнал
переходов статуса (`location_op_status`, автор «Восстановлено из книг витрины»):
до 30.09 книга перезаписывала статус молча, и в истории станции было пусто.

Использование (без --apply ничего не пишет):
  python scripts/backfill_status_days.py rushydro
  python scripts/backfill_status_days.py rushydro --apply
"""
import asyncio
import io
import json
import os
import re
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402
from sqlalchemy import delete, select, text  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import AuditEvent, Company, SourceFile  # noqa: E402
from app.services.asuim_normalize import _read_sheet, detect_sheets  # noqa: E402
from app.services.station_status_days import record_book_day  # noqa: E402

КНИГА = re.compile(r"^\d\d\.\d\d(\.\d{4})?\.xlsx$")
АВТОР = "vitrina_backfill"
МСК = timezone(timedelta(hours=3))


async def main(slug: str, apply: bool) -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()
        files = (await db.execute(select(SourceFile).where(SourceFile.company_id == company.id)
                                  .order_by(SourceFile.created_at))).scalars().all()
        seen: set[str] = set()
        for sf in files:
            if not КНИГА.match(sf.file_name or "") or sf.storage_path in seen:
                continue
            seen.add(sf.storage_path)
            path = sf.storage_path if os.path.isabs(sf.storage_path) else os.path.join("/app", sf.storage_path)
            if not os.path.exists(path):
                print(f"{sf.file_name}: файла нет ({path})")
                continue
            with open(path, "rb") as fh:
                wb = openpyxl.load_workbook(io.BytesIO(fh.read()), read_only=True, data_only=True)
            try:
                sheets = detect_sheets(wb)
                if "stations" not in sheets:
                    print(f"{sf.file_name}: не книга витрины")
                    continue
                st = _read_sheet(wb[sheets["stations"]])
                cn = _read_sheet(wb[sheets["connectors"]]) if "connectors" in sheets else []
            finally:
                wb.close()
            res = await record_book_day(db, company.id, st, cn)
            print(f"{sf.file_name}: срез {res['day']}, станций {res['stations']}, разъёмов {len(cn)}")

        # Журнал переходов — по восстановленному ряду: смена статуса между
        # соседними срезами = событие на день более позднего среза.
        rows = (await db.execute(text(
            "select location_id, day, operational_status, status_dev from station_status_days "
            "where company_id = :cid order by location_id, day"), {"cid": str(company.id)})).all()
        await db.execute(delete(AuditEvent).where(AuditEvent.company_id == company.id,
                                                  AuditEvent.user_id == АВТОР))
        events, prev = 0, {}
        for r in rows:
            p = prev.get(r.location_id)
            if p is not None and p != r.operational_status:
                db.add(AuditEvent(
                    company_id=company.id, user_id=АВТОР,
                    user_name="Восстановлено из книг витрины", action="location_op_status",
                    timestamp=datetime.combine(r.day, time(1, 0), МСК),
                    details=json.dumps({"location_id": r.location_id, "from": p,
                                        "to": r.operational_status,
                                        "reason": r.status_dev or "выгрузка витрины"},
                                       ensure_ascii=False, separators=(",", ":"))))
                events += 1
            prev[r.location_id] = r.operational_status
        days = sorted({r.day for r in rows})
        print(f"ряд: дней {len(days)} ({days[0] if days else '-'} … {days[-1] if days else '-'}), "
              f"строк {len(rows)}, переходов статуса {events}")
        if apply:
            await db.commit()
            print("записано")
        else:
            await db.rollback()
            print("пробный прогон: ничего не записано (--apply — записать)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(args[0] if args else os.environ.get("COMPANY_SLUG", "rushydro"),
                     "--apply" in sys.argv))
