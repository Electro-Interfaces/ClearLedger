"""Приёмка исправлений аудита 13.09.2026: А01–А09 на живых данных.

Печатает ровно те числа, которые аудит назвал неверными, чтобы разницу было видно
без пересказа: доля Владивостока и Приморья, выручка территорий, наша цена,
максимум недельной цены в эластичности, состав окружения в оценке площадки.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_audit_fixes.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import (growth_presence, market_elasticity,
                                       market_price_landscape, market_territories,
                                       market_site_score, territory_profile)


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)

        print("── А03/А05: территории ──")
        terr = await market_territories(company_id=cid, level="city", days=90,
                                        user=user, db=db)
        vl = next((r for r in terr["territories"] if r["name"] == "Владивосток"), None)
        if vl:
            print(f"Владивосток: наших {vl['ourSites']}, рынка {vl['rivalSites']}, "
                  f"доля {vl['sharePct']}%")
        revenue = sum(r["ourRevenue"] for r in terr["territories"])
        print(f"выручка всех территорий за 90 дней: {revenue:,.2f} ₽".replace(",", " "))

        print("\n── А04: профиль территории ──")
        prof = await territory_profile(company_id=cid, level="region", name="Приморский край",
                                       days=90, user=user, db=db)
        m = prof["market"]
        print(f"Приморский край: наших {prof['ours']['objects']}, сетевых {m['rivalSites']}, "
              f"независимых {m['independentSites']}, доля {m['sharePct']}%")

        print("\n── А01: покрытие географии ──")
        pres = await growth_presence(company_id=cid, days=90, user=user, db=db)
        print(f"покрытие {pres['geoCoverage']}%, без региона {pres['sitesWithoutRegion']} точек")
        for g in pres["groups"]:
            print(f"   {g['label'][:28]:<30}{g['regions']:>3} регионов")

        print("\n── А06: наша цена ──")
        price = await market_price_landscape(company_id=cid, days=90, user=user, db=db)
        print(f"розничная цена {price['ourPricePerKwh']} ₽/кВт·ч "
              f"по {price['retailSessions']} сессиям из {price['allSessions']}")
        print(f"учётная реализация {price['ourRealizationPerKwh']} ₽/кВт·ч на всю энергию")
        print(f"медиана рынка {price['marketMedianPerKwh']}")

        print("\n── А07: эластичность ──")
        el = await market_elasticity(company_id=cid, weeks=52, min_change_pct=5,
                                     min_sessions=20, user=user, db=db)
        cases = el.get("cases", [])
        if cases:
            worst = max(cases, key=lambda c: abs(c["pricePct"]))
            print(f"случаев {len(cases)}, медиана {el.get('medianElasticity')}")
            print(f"крайний случай: {worst['name'][:30]} — цена {worst['priceWas']} → "
                  f"{worst['priceNow']} ({worst['pricePct']:+}%)")
        else:
            print(el.get("message", "случаев нет"))

        print("\n── А08: оценка площадки, Владивосток ──")
        score = await market_site_score(company_id=cid, lat=43.1155, lon=131.8855,
                                 radius_km=5.0, days=90, place="auto", speed_class="auto",
                                 user=user, db=db)
        r = score["rivals"]
        print(f"конкурентов {r['total']}, живых {r['alive']}")
        print(f"наших рядом {score['cannibalization']['ourNearby']}")
        f = score.get("forecast") or {}
        print(f"аналогов {f.get('analogues')}, работают {f.get('working')}, "
              f"молчат {f.get('zeroDemand')}")
        print(f"прогноз выручки {f.get('revenuePerPeriod')} ₽ за 90 дней "
              f"(разброс {f.get('revenueLow')}–{f.get('revenueHigh')})")


asyncio.run(main())
