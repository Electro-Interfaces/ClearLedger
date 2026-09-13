"""Приёмка: «Развитие» видит перспективные проекты «Проектов».

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_growth_pipeline.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import growth_pipeline, growth_presence, market_whitespots


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)

        p = await growth_pipeline(company_id=cid, user=user, db=db)
        print(f"площадок в работе: {p['projects']}")
        print("\nворонка:")
        for st in p["stages"]:
            plan = (f", план {st['plannedPoints']} станций по {st['withPlan']} проектам"
                    if st["plannedPoints"] else "")
            print(f"   {st['label']:<18}{st['projects']:>4}  город у {st['withCity']}, "
                  f"координаты у {st['withCoords']}{plan}")

        print(f"\nгородов с работой: {p['citiesTotal']}")
        print(f"   вход в новую территорию (нас там нет): {p['enteringTotal']}")
        print(f"   рынок в этих городах не наблюдали: {p['unseenTotal']}")
        print(f"регионов входа: {p['enteringRegions']}")
        plan = p["plan"]
        print(f"план: {plan['points']} станций по {plan['withPlan']} проектам "
              f"(заполнено {plan['coverage']}%), {plan['powerKwt']} кВт")

        print("\nтоп территорий входа:")
        for row in p["entering"][:8]:
            mark = "рынок не наблюдали" if not row["marketKnown"] else (
                f"рынок {row['marketSites']} точек, живых {row['marketAlive']}")
            stages = ", ".join(f"{k}×{v}" for k, v in row["stages"].items())
            print(f"   {row['city'][:22]:<24}{row['projects']} проектов ({stages}); {mark}")

        print("\n── белые пятна против начатой работы ──")
        w = await market_whitespots(company_id=cid, level="city", user=user, db=db)
        print(f"пятен {w['total']}, из них площадка уже заведена: {w['withProject']}")
        for row in [x for x in w["spots"] if x["projectsInWork"]][:6]:
            print(f"   {row['name'][:22]:<24}рынок {row['rivalSites']}, "
                  f"живых {row['rivalAlive']}, наши проекты: "
                  f"{', '.join(row['projectNumbers']) or row['projectsInWork']}")

        print("\n── присутствие: где мы входим ──")
        pr = await growth_presence(company_id=cid, days=90, user=user, db=db)
        print(f"регионов входа {pr['enteringRegions']}, "
              f"площадок в работе всего {pr['projectsInWork']}")
        for row in [r for r in pr["regions"] if r["entering"]][:8]:
            print(f"   {row['name'][:26]:<28}проектов {row['projectsInWork']}, "
                  f"рынок {row['rivalSites']} точек")


asyncio.run(main())
