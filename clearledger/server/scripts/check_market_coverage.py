"""Приёмка: обеспеченность регионов зарядками."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_coverage


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        data = await market_coverage(company_id=str(company.id), user=user, db=db)
        if not data["regions"]:
            print(data.get("message"))
            return
        print(f"регионов с известным парком: {data['total']}\n")
        print(f"{'регион':<24}{'машин':>7}{'точек':>7}{'живых':>7}"
              f"{'на точку':>10}{'на живую':>10}{'разрыв':>8}{'наших':>7}")
        for r in data["regions"]:
            print(f"{r['region'][:23]:<24}{(r['evCars'] or 0):>7}{(r['stations'] or 0):>7}"
                  f"{(r['stationsAlive'] or 0):>7}{(r['carsPerStation'] or 0):>10}"
                  f"{(r['carsPerAlive'] or 0):>10}"
                  f"{('—' if r['deadGapRatio'] is None else 'x' + str(r['deadGapRatio'])):>8}"
                  f"{r['ourSites']:>7}")
        print(f"\n{data['note']}")


asyncio.run(main())
