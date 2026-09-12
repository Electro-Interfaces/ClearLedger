"""Приёмка этапа 6: кто дополняет нашу сеть, а кто дублирует."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_partners


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        reply = await market_partners(company_id=str(company.id), min_sites=2,
                                      user=user, db=db)
        print(f"мы стоим в {reply['ourCities']} городах; сетей в разборе {reply['total']}\n")
        print(f"{'сеть':<22}{'точек':>7}{'живых':>7}{'дополняет':>11}{'дублирует':>11}  города без нас")
        for r in reply["partners"][:12]:
            print(f"{r['name'][:21]:<22}{r['sites']:>7}{r['alive']:>7}"
                  f"{r['complementSites']:>11}{r['overlapSites']:>11}  "
                  + (", ".join(r["newCities"][:3]) or "—"))
        # Сходимость: дополнение + дублирование не больше общего числа точек.
        bad = [r for r in reply["partners"]
               if r["complementSites"] + r["overlapSites"] > r["sites"]]
        print(f"\nсходимость: сетей с расхождением {len(bad)}"
              + ("  ← совпало" if not bad else "  ← ОШИБКА"))


asyncio.run(main())
