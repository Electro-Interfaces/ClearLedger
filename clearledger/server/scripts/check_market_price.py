"""Приёмка этапа 4: ценовой ландшафт, давление конкурента, эластичность.

Три вопроса: считается ли цена по классам мощности (а не одной кашей), видно ли
появление соседа рядом с нашими объектами, и находит ли расчёт отклика настоящие
изменения нашей цены.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_price.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import (market_elasticity, market_pressure,
                                       market_price_landscape)


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        land = await market_price_landscape(company_id=cid, days=90, user=user, db=db)
        print(f"1. ценовой ландшафт (цена известна у {land['pricedSites']} точек, "
              f"без мощности {land['unknownPower']}):")
        for b in land["buckets"]:
            print(f"   {b['bucket']:<12} точек {b['sites']:>4}  "
                  f"четверть {b['low']}  медиана {b['median']}  четверть {b['high']}")
        print(f"   наша цена {land['ourPricePerKwh']} ₽/кВт·ч, медиана рынка "
              f"{land['marketMedianPerKwh']}, разрыв {land['gapPct']} %")

        pressure = await market_pressure(company_id=cid, months=24, radius_km=5.0,
                                         user=user, db=db)
        print(f"\n2. давление конкурента: наших объектов с новым соседом {pressure['total']}")
        for r in pressure["rows"][:8]:
            print(f"   {r['name'][:26]:<28} сосед {r['rivalName'][:20]:<22} "
                  f"{r['appearedOn']}  {r['sessionsBefore']:>4} → {r['sessionsAfter']:>4}  "
                  f"{r['changePct']} %")

        elast = await market_elasticity(company_id=cid, weeks=52, min_change_pct=5.0,
                                        min_sessions=20, user=user, db=db)
        print(f"\n3. изменений цены за год: {elast['total']}, "
              f"медианный отклик {elast['medianElasticity']}")
        for c in elast["cases"][:8]:
            print(f"   {c['name'][:24]:<26} {c['week']}  цена {c['priceWas']} → {c['priceNow']} "
                  f"({c['pricePct']:+} %), сессии {c['sessionsWas']} → {c['sessionsNow']} "
                  f"({c['sessionsPct']:+} %), отклик {c['elasticity']}")


asyncio.run(main())
