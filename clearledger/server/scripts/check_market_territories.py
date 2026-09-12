"""Приёмка этапа 3: территории, белые пятна, оценка площадки.

Зовём те же функции, что отдают API. Проверяем три вещи, на которых экран может
врать незаметно: сходится ли число наших объектов по территориям с реестром, не
попали ли домашние розетки в конкуренты и собирается ли прогноз по аналогам из
настоящих объектов, а не из воздуха.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_territories.py
"""
import asyncio

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models import Company, MarketSite, ServiceLocation, User
from app.routers.market_router import (market_site_score, market_territories,
                                       market_whitespots)


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        reply = await market_territories(company_id=cid, level="city", days=90,
                                         user=user, db=db)
        rows = reply["territories"]
        with_us = [r for r in rows if r["ourSites"] > 0]
        print(f"1. территорий (города): {len(rows)}, где стоим мы: {len(with_us)}")
        print(f"{'территория':<26}{'наших':>7}{'сессий':>8}{'чужих':>7}"
              f"{'живых':>7}{'доля %':>8}{'рынок ₽':>9}")
        for r in sorted(rows, key=lambda x: -x["ourSessions"])[:10]:
            print(f"{r['name'][:25]:<26}{r['ourSites']:>7}{r['ourSessions']:>8}"
                  f"{r['rivalSites']:>7}{r['rivalAlive']:>7}"
                  f"{('—' if r['sharePct'] is None else r['sharePct']):>8}"
                  f"{('—' if r['marketPricePerKwh'] is None else r['marketPricePerKwh']):>9}")

        # Сходимость: сумма наших объектов по территориям = объектам в реестре.
        ours_total = int((await db.execute(
            select(func.count()).select_from(ServiceLocation)
            .where(ServiceLocation.company_id == company.id))).scalar() or 0)
        by_terr = sum(r["ourSites"] for r in rows)
        print(f"\n   сходимость: объектов в реестре {ours_total}, "
              f"разложено по территориям {by_terr}"
              + ("  ← совпало" if by_terr == ours_total else "  ← РАСХОЖДЕНИЕ"))

        # Домашние розетки не должны попасть в конкурентов.
        homes = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .where(MarketSite.company_id == company.id,
                   MarketSite.site_class == "home"))).scalar() or 0)
        by_home = sum(r["homeSockets"] for r in rows)
        print(f"   домашних розеток в базе {homes}, в колонке розеток {by_home}"
              + ("  ← не в конкурентах" if by_home == homes else "  ← РАСХОЖДЕНИЕ"))

        spots = await market_whitespots(company_id=cid, level="city", user=user, db=db)
        print(f"\n2. белых пятен: {spots['total']}")
        for r in spots["spots"][:8]:
            print(f"   {r['name'][:28]:<30} чужих {r['rivalSites']:>3}, "
                  f"живых {r['rivalAlive']:>3}, портов {r['rivalPorts']:>3}")

        # Оценка площадки в месте, где рынок точно есть: берём самое плотное белое пятно
        # или первую точку рынка с координатами.
        probe = (await db.execute(select(MarketSite).where(
            MarketSite.company_id == company.id,
            MarketSite.latitude.is_not(None),
            MarketSite.site_class == "network").limit(1))).scalar_one_or_none()
        if probe is None:
            print("\n3. точек рынка с координатами нет — оценку проверять негде")
            return
        score = await market_site_score(
            company_id=cid, lat=float(probe.latitude), lon=float(probe.longitude),
            radius_km=5.0, days=90, user=user, db=db)
        f = score["forecast"]
        print(f"\n3. оценка площадки рядом с «{probe.name}»:")
        print(f"   чужих в радиусе {score['rivals']['total']}, живых {score['rivals']['alive']}, "
              f"портов {score['rivals']['ports']}, цена рынка {score['rivals']['marketPricePerKwh']}")
        print(f"   наших рядом {score['cannibalization']['ourNearby']}")
        print(f"   аналогов {f['analogues']}, прогноз: {f['sessionsPerPeriod']} сессий / "
              f"{f['revenuePerPeriod']} ₽ за {f['days']} дней")
        if f["sample"]:
            print("   собран из:", ", ".join(
                f"{a['name']} ({a['sessions']})" for a in f["sample"][:4]))


asyncio.run(main())
