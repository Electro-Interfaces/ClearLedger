"""Пост-деплой накат данных ЭЗС (РусГидро) на прод.

Запуск в контейнере backend ПОСЛЕ:
  1) деплоя кода (миграции применяются на старте — create_all + ALTER-список);
  2) загрузки справочника станций через коннектор «Справочник станций ЭЗС» (UI:
     Коннекторы → создать/открыть → загрузить xlsx → запустить) — это наполняет
     объекты типизированным паспортом L2 (мощность/коннекторы/бренд/регион-канон).

Делает (идемпотентно):
  1) бэкфилл ChargeSession.location_id — материализует связь сессия→объект по № станции;
  2) скидка каршеринга 25% (CorporateClient.discount_pct) — розница−25% в регионах матрицы;
  3) переприменение обогащения ЮЛ из реестра (client_name/tariff/amount с учётом скидки).

Использование:
  docker compose exec ledger-backend python scripts/postdeploy_ezs_nakat.py rushydro
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select, update  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import ChargeSession as S  # noqa: E402
from app.models import CorporateClient as C  # noqa: E402
from app.models import ServiceLocation as L  # noqa: E402
from app.services.charge_sessions_normalize import enrich_from_registry  # noqa: E402
from app.services.stations_normalize import backfill_session_locations  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = sys.argv[1] if len(sys.argv) > 1 else "rushydro"


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        print(f"company '{COMPANY}' → {cid}")

        objs = int((await db.execute(select(func.count()).select_from(L).where(
            L.company_id == cid, L.type == "ev_charging", L.station_number.is_not(None)))).scalar() or 0)
        print(f"объектов ЭЗС с № (паспорт L2): {objs}")
        if not objs:
            print("⚠ станции без паспорта — сначала загрузите справочник через коннектор "
                  "«Справочник станций ЭЗС» (UI), затем перезапустите скрипт.")

        # 1) связь сессий с объектами (по № станции)
        bf = await backfill_session_locations(db, cid)
        await db.commit()
        print("1) backfill location_id:", bf["message"])

        # 2) скидка каршеринга 25% (розница−25% в регионах матрицы)
        r = await db.execute(update(C).where(
            C.company_id == cid, C.name.ilike("%аршеринг%")).values(discount_pct=25))
        await db.commit()
        print(f"2) каршеринг discount=25%: обновлено {int(r.rowcount or 0)} клиент(ов)")

        # 3) переприменение обогащения ЮЛ из реестра (с учётом скидки)
        res = await enrich_from_registry(db, cid)
        await db.commit()
        print("3) re-enrich:", res["message"])
        print("✓ накат ЭЗС завершён")


if __name__ == "__main__":
    asyncio.run(main())
