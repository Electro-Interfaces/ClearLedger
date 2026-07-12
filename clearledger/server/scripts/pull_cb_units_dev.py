"""
DEV: подтянуть единицы измерения (ЕдиницаИзмерения) в CbNomenclature из ЦБ
ЭЛСИ.АЗК через enrich_nomenclature (ПРЕДСТАВЛЕНИЕ единицы), батчами по GUID.
Коннект — s.get("tsb_conn") (боевая) или File= (локальная копия). Read-only.

Запуск (из server/):  py -3.13 scripts/pull_cb_units_dev.py
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

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import CbNomenclature  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
BATCH = 800


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    print(f"Коннект: {'БОЕВАЯ ЦБ' if 'Srvr=' in conn else 'локальная копия'}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        refs = (await db.execute(select(CbNomenclature.external_ref).where(
            CbNomenclature.company_id == cid))).scalars().all()
        print(f"номенклатуры к обогащению: {len(refs)}")

        units: dict[str, str] = {}
        async with OneCComClient(conn) as client:
            for i in range(0, len(refs), BATCH):
                chunk = refs[i:i + BATCH]
                res = await client.enrich_nomenclature(chunk)
                for ref, d in (res or {}).items():
                    u = (d or {}).get("unit")
                    if u:
                        units[str(ref)] = str(u).strip()
                print(f"  батч {i // BATCH + 1}: +{len(res or {})} (единиц накоплено {len(units)})")

        # апдейт unit пакетно
        n = 0
        rows = (await db.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == cid))).scalars().all()
        for r in rows:
            u = units.get(r.external_ref)
            if u and u != r.unit:
                r.unit = u
                n += 1
        await db.commit()
        # распределение единиц
        from collections import Counter
        dist = Counter(units.values())
        print(f"обновлено unit: {n}; распределение топ-10: {dict(sorted(dist.items(), key=lambda x: -x[1])[:10])}")


if __name__ == "__main__":
    asyncio.run(main())
