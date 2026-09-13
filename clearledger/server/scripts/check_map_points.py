"""Сколько точек рынка реально доезжает до карты."""
import asyncio
from sqlalchemy import func, select
from app.database import async_session_factory
from app.models import Company, MarketSite, ServiceLocation, User
from app.routers.market_router import list_sites


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)

        in_db = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .where(MarketSite.company_id == company.id))).scalar() or 0)
        with_geo = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .where(MarketSite.company_id == company.id,
                   MarketSite.latitude.is_not(None)))).scalar() or 0)
        ours = int((await db.execute(
            select(func.count()).select_from(ServiceLocation)
            .where(ServiceLocation.company_id == company.id,
                   ServiceLocation.is_test.is_(False),
                   ServiceLocation.latitude.is_not(None)))).scalar() or 0)
        print(f"точек рынка в базе: {in_db}, из них с координатами: {with_geo}")
        print(f"наших объектов с координатами: {ours}")

        # Как сейчас просит карта — без пагинации.
        reply = await list_sites(company_id=cid, kind=None, city=None, bbox=None,
                                 limit=2000, offset=0, user=user, db=db)
        print(f"\nкарта по умолчанию (limit=2000): отдано {reply['returned']} "
              f"из {reply['total']} — не видно {reply['total'] - reply['returned']}")

        reply = await list_sites(company_id=cid, kind=None, city=None, bbox=None,
                                 limit=5000, offset=0, user=user, db=db)
        print(f"максимальная страница (limit=5000): отдано {reply['returned']} "
              f"из {reply['total']}")

        # Область Москвы — проверка отбора по видимой части карты.
        reply = await list_sites(company_id=cid, kind=None, city=None,
                                 bbox="55.5,37.3,56.0,37.9", limit=5000, offset=0,
                                 user=user, db=db)
        print(f"\nобласть Москвы (bbox): {reply['total']} точек, отдано {reply['returned']}")


asyncio.run(main())
