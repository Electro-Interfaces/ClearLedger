"""
DEV: НСИ-реквизиты для эмиттера пакета БП (Фаза 1) — организации и склады из ЦБ
ЭЛСИ.АЗК → CbRef(kind='organization'/'warehouse', extra). Приёмник БП ищет
Организацию по ИНН, Склад — по UUID/номеру; эти реквизиты обязательны в НСИ-секции.

Коннект — s.get("tsb_conn") (боевая) или File= (локальная). Read-only.
Запуск (из server/):  py -3.13 scripts/pull_cb_orgs_wh_dev.py
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

from sqlalchemy import select, delete  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import CbRef  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    print(f"Коннект: {'БОЕВАЯ ЦБ' if 'Srvr=' in conn else 'локальная копия'}")

    async with OneCComClient(conn) as client:
        orgs = await client.fetch_orgs()
        whs = await client.fetch_warehouses()
    print(f"получено: организаций {len(orgs)}, складов {len(whs)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        await db.execute(delete(CbRef).where(CbRef.company_id == cid, CbRef.kind.in_(["organization", "warehouse"])))

        for o in orgs:
            ref = str(o.get("ref") or "")
            if not ref:
                continue
            db.add(CbRef(company_id=cid, kind="organization", external_ref=ref,
                         name=str(o.get("name") or ""), extra={
                             "full_name": o.get("full_name") or "", "inn": o.get("inn") or "",
                             "kpp": o.get("kpp") or "", "ogrn": o.get("ogrn") or "",
                             "okpo": o.get("okpo") or "", "jur_fiz": o.get("jur_fiz") or "ЮрЛицо",
                             "deleted": bool(o.get("deleted")),
                         }))
        for w in whs:
            ref = str(w.get("ref") or "")
            if not ref:
                continue
            db.add(CbRef(company_id=cid, kind="warehouse", external_ref=ref,
                         name=str(w.get("name") or ""), extra={
                             "code": w.get("code") or "", "kind_name": w.get("kind") or "",
                             "deleted": bool(w.get("deleted")),
                         }))
        await db.commit()

        no = (await db.execute(select(CbRef).where(CbRef.company_id == cid, CbRef.kind == "organization"))).scalars().all()
        nw = (await db.execute(select(CbRef).where(CbRef.company_id == cid, CbRef.kind == "warehouse"))).scalars().all()
        print(f"записано: организаций {len(no)}, складов {len(nw)}")
        for r in no:
            print(f"  орг {r.name} ИНН={(r.extra or {}).get('inn')}")


if __name__ == "__main__":
    asyncio.run(main())
