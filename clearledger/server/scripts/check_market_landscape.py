"""Приёмка раздела «Рынок»: расклад сил, платформы, роуминг, сервис."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_landscape


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        data = await market_landscape(company_id=str(company.id), user=user, db=db)
        t = data["totals"]
        print(f"сетей с точками: {t['networks']}, их точек: {t['networkSites']}")
        print(f"профиль есть у {t['withProfile']}, своя платформа у {t['ownPlatform']}")
        print(f"в роуминге {t['roamingNetworks']} сетей ({t['roamingSites']} точек), "
              f"работают только в своём приложении {t['closedNetworks']} ({t['closedSites']})")
        print(f"приложение с оценкой у {t['withApp']}, реквизиты подтверждены у {t['legalTrusted']}\n")

        print("расклад сил:")
        print(f"{'сеть':<20}{'точек':>7}{'доля':>7}{'городов':>8}{'связь':>7}"
              f"{'цена':>7}{'прилож':>8}  платформа / роуминг")
        for r in data["networks"][:12]:
            print(f"{r['name'][:19]:<20}{r['sites']:>7}{r['sharePct']:>7}{(r['cities'] or 0):>8}"
                  f"{('—' if r['quality'] is None else r['quality']):>7}"
                  f"{('—' if r['medianPricePerKwh'] is None else r['medianPricePerKwh']):>7}"
                  f"{('—' if r['appRating'] is None else r['appRating']):>8}  "
                  f"{r['platformOwner'] or '—'}"
                  f"{' · роуминг' if r['roaming'] else ' · своё приложение' if r['roaming'] is False else ''}")

        print("\nплатформы рынка (по числу чужих точек):")
        for p in data["platforms"][:6]:
            clients = ", ".join(f"{c['name']} ({c['sites']})" for c in p["clients"][:4])
            print(f"   {p['owner'][:18]:<20} своих {p['ownSites']:>4}, чужих {p['clientSites']:>4} "
                  f"в {len(p['clients'])} сетях: {clients}")

        ours = next((r for r in data["networks"] if r["isOurs"]), None)
        if ours:
            print(f"\nмы: {ours['sites']} точек ({ours['sharePct']} %), {ours['cities']} городов, "
                  f"связь {ours['quality']}, приложение {ours['appRating']}, "
                  f"роуминг {'да' if ours['roaming'] else 'нет'}, "
                  f"молчат больше полугода {ours['silentHalfYear']}")


asyncio.run(main())
