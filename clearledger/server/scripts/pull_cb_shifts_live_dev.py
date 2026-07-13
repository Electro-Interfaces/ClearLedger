"""
DEV: снять СВЕЖИЕ смены 208 (продажи сопутка/общепит + приходы + ТТК) с БОЕВОЙ
ЦБ ЭЛСИ.АЗК `azs_centre` и залить в L2 (DataEntry). Перед заливкой удаляет старые
oneC-данные компании gig (апрельский снимок).

Коннект — из secrets.json `tsb_conn` (Srvr="SQL1";Ref="azs_centre";Usr="Elsy") —
прямой Python-COM через vpn-gw. Read-only к 1С.

Запуск (из server/):  py -3.13 scripts/pull_cb_shifts_live_dev.py [YYYY-MM-DD YYYY-MM-DD]
По умолчанию период = 2026-06-11 .. 2026-07-31, станция 208.
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
from app.services.cb_intake import ingest_packages  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
STATION = "208"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")


async def main() -> None:
    pf = sys.argv[1] if len(sys.argv) > 1 else "2026-06-11"
    pt = sys.argv[2] if len(sys.argv) > 2 else "2026-07-31"
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'
    live = "Srvr=" in conn
    print(f"Коннект: {'БОЕВАЯ ЦБ' if live else 'локальная копия'} | период {pf}..{pt} | станция {STATION}")

    # 1) снять смены с ЦБ
    async with OneCComClient(conn) as client:
        packages = await client.fetch_cb_shifts(pf, pt, station=STATION, limit=500)
    print(f"получено пакетов смен: {len(packages)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)

        # 2) удалить старые oneC-данные gig — ТОЛЬКО типы, что создаёт shift-пул
        # (retail/purchase/return). П2-фикс: раньше сносил ВСЕ oneC → одиночный
        # перезапуск уничтожал recipe/production/gain до прогона их пулов.
        SHIFT_KINDS = ["retail_sale_sidegoods", "purchase", "return_purchase"]
        old = (await db.execute(select(DataEntry.id).where(
            DataEntry.company_id == cid, DataEntry.source == "oneC",
            DataEntry.doc_type_id.in_(SHIFT_KINDS)))).scalars().all()
        if old:
            await db.execute(delete(DataEntry).where(
                DataEntry.company_id == cid, DataEntry.source == "oneC",
                DataEntry.doc_type_id.in_(SHIFT_KINDS)))
            await db.commit()
        print(f"удалено старых oneC DataEntry (retail/purchase/return): {len(old)}")

        # 3) залить свежие
        result = await ingest_packages(db, cid, packages)
        await db.commit()   # ingest_packages делает только flush — коммит на нас
        print(f"ingest: shifts={result.get('shifts')} created={result.get('created')} "
              f"updated={result.get('updated')} skipped={result.get('skipped_kinds')} "
              f"selfcheck_violations={(result.get('selfcheck') or {}).get('violations')}")

        # 4) сводка
        rows = (await db.execute(select(DataEntry.doc_type_id).where(
            DataEntry.company_id == cid, DataEntry.source == "oneC"))).scalars().all()
        from collections import Counter
        print("итог DataEntry(oneC):", dict(Counter(rows)))


if __name__ == "__main__":
    asyncio.run(main())
