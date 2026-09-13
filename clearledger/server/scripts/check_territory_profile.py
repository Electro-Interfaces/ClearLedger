"""Приёмка: профиль территории — наша сеть во всей полноте рядом с рынком."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import market_territories, territory_profile


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        terr = await market_territories(company_id=cid, level="region", days=90,
                                        user=user, db=db)
        top = [t for t in terr["territories"] if t["ourSites"] > 0][:2]
        for t in top:
            p = await territory_profile(company_id=cid, name=t["name"], level="region",
                                        days=90, user=user, db=db)
            o, m = p["ours"], p["market"]
            print(f"\n══ {p['name']} ══")
            print(f"наша сеть: {o['objects']} объектов, {o['ports']} портов, "
                  f"суммарная мощность {o['powerKwtTotal']} кВт (максимум {o['powerKwtMax']})")
            print(f"   по скорости: {o['bySpeed']}")
            print(f"   по производителю: {dict(list(o['byBrand'].items())[:4])}")
            print(f"   состояние: {o['byStatus']}")
            print(f"реализация за 90 дн: {o['sessions']} сессий, {round(o['energyKwh'])} кВт·ч, "
                  f"{round(o['revenue'])} ₽, средний чек {o['avgCheck']} ₽, "
                  f"наша цена {o['pricePerKwh']} ₽/кВт·ч")
            print(f"   клиентов {o['clients']}, средняя зарядка {o['avgDurationMin']} мин")
            print(f"   загрузка: {o['sessionsPerPortDay']} сессий и {o['kwhPerPortDay']} кВт·ч "
                  f"на порт в сутки")
            print(f"   кто заряжается: "
                  + ", ".join(f"{k}: {v['sessions']}" for k, v in o['byUserType'].items()))
            print(f"   чем: {dict(list(o['byConnector'].items())[:4])}")
            print(f"   результат: {dict(list(o['byResult'].items())[:3])}")
            peak = max(o['hours'], key=lambda h: h['sessions']) if o['hours'] else None
            print(f"   час пик: {peak['hour']}:00 — {peak['sessions']} сессий" if peak else "")
            tr = o['trend']
            print(f"   динамика: сессии {tr['sessionsPct']} %, выручка {tr['revenuePct']} % "
                  f"к прошлым 90 дням")
            print(f"рынок рядом: сетевых {m['rivalSites']} (живых {m['aliveRivals']}), "
                  f"независимых {m['independentSites']}, розеток {m['homeSockets']}, "
                  f"цена {m['marketPricePerKwh']}, наша доля {m['sharePct']} %")


asyncio.run(main())
