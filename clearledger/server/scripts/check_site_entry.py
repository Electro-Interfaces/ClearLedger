"""Приёмка: экономика входа в место (мощность, присоединение, окупаемость)."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, MarketSite, User
from app.routers.market_router import market_site_score


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        probes = (await db.execute(select(MarketSite).where(
            MarketSite.company_id == company.id,
            MarketSite.latitude.is_not(None),
            MarketSite.site_class == "network").limit(3))).scalars().all()
        for probe in probes:
            score = await market_site_score(
                company_id=str(company.id), lat=float(probe.latitude),
                lon=float(probe.longitude), radius_km=5.0, days=90,
                place="auto", speed_class="auto", user=user, db=db)
            e, f = score["entry"], score["forecast"]
            print(f"\n«{probe.name[:34]}» ({probe.city or 'город неизвестен'})")
            print(f"   рынок: чужих {score['rivals']['total']}, живых {score['rivals']['alive']}")
            print(f"   прогноз: {f['sessionsPerPeriod']} сессий / {f['revenuePerPeriod']} ₽ "
                  f"за {f['days']} дн; аналогов {f['analogues']}, из них молчат {f['zeroDemand']}")
            print(f"   вход: площадок рядом {e['projectsNearby']}, присоединение "
                  f"{e['tpCostMedian']}, срок {e['tpTermMonthsMedian']} мес, "
                  f"свободная мощность {e['freePowerKwtMedian']} кВт")
            print(f"   капитал {e['capexEstimate']}, периодов выручки {e['paybackPeriods']}")


asyncio.run(main())
