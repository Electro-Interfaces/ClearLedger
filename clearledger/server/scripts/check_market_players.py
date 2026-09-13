"""Приёмка: игроки рынка — модели бизнеса, классы, качество."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_players


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        data = await market_players(company_id=str(company.id), user=user, db=db)
        if not data.get("players"):
            print(data.get("message"))
            return
        t = data["totals"]
        print(f"игроков: {data['total']} | со станциями {t['withStations']}, "
              f"без станций {t['assetLight']}, смежных {t['adjacent']}")
        print(f"медиана оценки приложения {t['medianRating']} по {t['withRating']} "
              f"приложениям, класс не проверен у {t['unchecked']}\n")

        for q in data["quadrants"]:
            print(f"{q['label']}: {q['count']} игроков"
                  + (f", {q['stations']} станций" if q['stations'] else ""))
            print("   " + ", ".join(p["app"] for p in q["players"][:8]))

        print("\nоткуда приходят:")
        for c in data["classes"]:
            mark = " (смежные)" if c["adjacent"] else ""
            print(f"   {c['class'][:30]:<32}{c['players']:>4} игроков, без станций "
                  f"{c['assetLight']:>4}, станций {c['stations']:>5}, оценка "
                  f"{c['medianRating']}{mark}")

        print("\nкачество против размера (по числу отзывов):")
        for p in data["quality"][:8]:
            print(f"   {p['app'][:24]:<26} станций {(p['ownStations'] or 0):>5}, "
                  f"оценка {p['rating']}, отзывов {p['reviews']}")


asyncio.run(main())
