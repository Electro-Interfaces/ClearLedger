import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, MarketOperator

async def main():
    async with async_session_factory() as db:
        c = (await db.execute(select(Company).limit(1))).scalar_one()
        for name in ("Россети", "Sitronics Electro", "Sitronics", "РусГидро", "TOUCH", "Touch"):
            op = (await db.execute(select(MarketOperator).where(
                MarketOperator.company_id == c.id,
                MarketOperator.name == name))).scalars().first()
            if op is None:
                print(f"{name:<20} — оператора с таким именем нет")
                continue
            print(f"{name:<20} платформа={op.platform_owner!r} своя={op.own_platform} "
                  f"роуминг={op.ocpi_roaming} городов={op.cities} приложение={op.app_rating}")
asyncio.run(main())
