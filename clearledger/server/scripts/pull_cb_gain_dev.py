"""
DEV: снять ОприходованиеТоваров (gain) 208 с ЦБ ЭЛСИ.АЗК →
DataEntry(source='oneC', doc_type_id='gain'). Для эмиттера пакета БП.
Коннект — s.get("tsb_conn") (боевая) или File=. Read-only.
Запуск (из server/):  py -3.13 scripts/pull_cb_gain_dev.py [YYYY-MM-DD YYYY-MM-DD]
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import DataEntry  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
STATION = "208"
DOC_TYPE = "gain"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


async def main() -> None:
    pf = sys.argv[1] if len(sys.argv) > 1 else "2026-06-11"
    pt = sys.argv[2] if len(sys.argv) > 2 else "2026-07-31"
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    print(f"Коннект: {'БОЕВАЯ ЦБ' if 'Srvr=' in conn else 'локальная копия'} | {pf}..{pt} | ст.{STATION}")

    async with OneCComClient(conn) as client:
        items = await client.fetch_gain(pf, pt, station=STATION)
    print(f"получено Оприходование: {len(items)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        await db.execute(delete(DataEntry).where(
            DataEntry.company_id == cid, DataEntry.source == "oneC", DataEntry.doc_type_id == DOC_TYPE))
        for it in items:
            uid = str(it.get("ИсточникUUID") or "")
            if not uid:
                continue
            meta = {"kind": DOC_TYPE, "Документ": it,
                    "Смена": {"КодАЗС": it.get("_station") or STATION, "Открытие": it.get("Дата") or ""}}
            db.add(DataEntry(
                company_id=cid, category_id="retail", subcategory_id="gain", doc_type_id=DOC_TYPE,
                source="oneC", source_id=f"{it.get('Номер') or ''}:{DOC_TYPE}:{uid}",
                source_label="ЦБ ЭЛСИ.АЗК", layer="clean", status="new",
                title=f"Оприходование {it.get('Номер') or ''}", meta=meta,
            ))
        await db.commit()
        cnt = (await db.execute(select(DataEntry).where(
            DataEntry.company_id == cid, DataEntry.source == "oneC", DataEntry.doc_type_id == DOC_TYPE))).scalars().all()
        lines = sum(len((e.meta or {}).get("Документ", {}).get("Товары", [])) for e in cnt)
        print(f"записано gain: {len(cnt)} (строк {lines})")


if __name__ == "__main__":
    asyncio.run(main())
