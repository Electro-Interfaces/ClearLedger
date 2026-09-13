"""Приёмка карты: слои, фильтры и полнота выдачи."""
import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import list_sites, our_map_points


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)

        async def sites(**kw):
            base = dict(company_id=cid, kind=None, city=None, bbox=None, site_class=None,
                        current_type=None, operator_id=None, min_power=None, alive=None,
                        limit=5000, offset=0, user=user, db=db)
            base.update(kw)
            return await list_sites(**base)

        whole = await sites()
        print(f"всего точек рынка: {whole['total']}")
        for label, kw in (
            ("сети операторов", dict(site_class="network")),
            ("независимые", dict(site_class="independent")),
            ("домашние розетки", dict(site_class="home")),
            ("только DC", dict(current_type="DC")),
            ("от 150 кВт", dict(min_power=150)),
            ("заряжали за 90 дней", dict(alive=True)),
            ("молчат", dict(alive=False)),
            ("Москва (область карты)", dict(bbox="55.5,37.3,56.0,37.9")),
        ):
            r = await sites(**kw)
            print(f"   {label:<26}{r['total']:>6}  (отдано {r['returned']})")

        ours = await our_map_points(company_id=cid, days=90, user=user, db=db)
        pts = ours["points"]
        print(f"\nнаших станций на карте: {ours['total']}")
        print(f"   производителей: {len(ours['brands'])}, состояний: {len(ours['statuses'])}")
        for label, cond in (
            ("работают", lambda p: p["status"] == "working"),
            ("нет связи", lambda p: p["status"] == "no_link"),
            ("выведены", lambda p: p["status"] == "decommissioned"),
            ("быстрые", lambda p: p["speedClass"] == "fast"),
            ("простаивают (<0,3 сессии на порт)",
             lambda p: (p["sessionsPerPortDay"] or 0) < 0.3 and p["sessionsPerPortDay"] is not None),
            ("загружены (от 2)", lambda p: (p["sessionsPerPortDay"] or 0) >= 2),
            ("срывов больше 30 %", lambda p: (p["errorPct"] or 0) > 30),
        ):
            print(f"   {label:<36}{sum(1 for p in pts if cond(p)):>5}")


asyncio.run(main())
