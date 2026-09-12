"""Приёмка «Развития»: режим присутствия по регионам и пять направлений роста.

Проверяем главное: раскладываются ли регионы по нашему положению, и считается ли
мера каждого направления по настоящим данным, а не по нулям.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_growth.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import growth_overview, growth_presence


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        presence = await growth_presence(company_id=cid, days=90, user=user, db=db)
        print("1. наше положение по регионам:")
        for g in presence["groups"]:
            print(f"   {g['label']:<22} регионов {g['regions']:>3}, наших точек "
                  f"{g['ourSites']:>4}, чужих {g['rivalSites']:>4}, "
                  f"сессий {g['ourSessions']:>7}")
        print("\n   крупнейшие регионы:")
        for r in presence["regions"][:10]:
            print(f"   {r['name'][:26]:<28}{r['presenceLabel']:<20}"
                  f"доля {r['sharePct']:>6}  наших {r['ourSites']:>4}  чужих {r['rivalSites']:>4}")

        overview = await growth_overview(company_id=cid, days=90, user=user, db=db)
        print("\n2. направления роста:")
        for t in overview["tracks"]:
            print(f"\n   {t['label']}")
            print(f"      {t['headline']}")
            print("      " + " · ".join(f"{m['label']}: {m['value']}" for m in t["metrics"]))


asyncio.run(main())
