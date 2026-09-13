"""Приёмка этапа 1б: как нас видит рынок и сходится ли это с нашими данными."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_self_view


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        data = await market_self_view(company_id=str(company.id), match_km=0.3,
                                      days=90, user=user, db=db)
        t = data["totals"]
        print(f"пространство: {company.name}\n")
        print(f"наших точек в публичном реестре: {t['inMarket']}, "
              f"сопоставлено с нашим реестром: {t['matchedToRegistry']}")
        print(f"как нас видит клиент: связь {t['quality']} %, успешных зарядок "
              f"{t['success']} %, оценка {t['rating']} по {t['reviews']} отзывам")
        print(f"рынок считает живыми: {t['aliveByMarket']} из {t['inMarket']}")
        print(f"⚠ рынок молчит, а сессии идут: {t['silentButWorking']} точек — "
              "клиент видит станцию мёртвой")
        print("\nс кем сравниваемся (сети от 30 точек):")
        print(f"{'сеть':<22}{'точек':>7}{'связь':>8}{'успех':>8}{'оценка':>8}")
        for p in data["peers"]:
            print(f"{p['name'][:21]:<22}{p['sites']:>7}"
                  f"{('—' if p['quality'] is None else p['quality']):>8}"
                  f"{('—' if p['success'] is None else p['success']):>8}"
                  f"{('—' if p['rating'] is None else p['rating']):>8}")
        print("\nнаши худшие точки по успешности зарядок:")
        for r in data["sites"][:8]:
            if r["successPct"] is None:
                continue
            print(f"   {(r['marketName'] or '')[:30]:<32} успех {r['successPct']:>5} %, "
                  f"связь {r['quality']}, оценка {r['rating']}, "
                  f"наших сессий {r['ourSessions']}")


asyncio.run(main())
