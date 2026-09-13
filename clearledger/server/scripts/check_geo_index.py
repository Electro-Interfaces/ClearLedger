"""Приёмка: пространственный индекс находит ровно тех же соседей, что полный перебор.

Ускорение бессмысленно, если оно теряет точки. Скрипт сверяет два способа на всех
наших объектах: индекс против перебора всей страны.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_geo_index.py
"""
import asyncio
import time

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, MarketSite, ServiceLocation
from app.routers.market_router import _distance_km, _geo_around, _geo_index


async def main() -> None:
    radius_km = 3.0
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        market = (await db.execute(select(MarketSite).where(
            MarketSite.company_id == company.id, MarketSite.status != "closed",
            MarketSite.latitude.is_not(None),
            MarketSite.longitude.is_not(None)))).scalars().all()
        ours = (await db.execute(select(ServiceLocation).where(
            ServiceLocation.company_id == company.id,
            ServiceLocation.is_test.is_(False),
            ServiceLocation.latitude.is_not(None)))).scalars().all()

        index = _geo_index(market, radius_km)
        print(f"точек рынка {len(market)}, наших объектов {len(ours)}, "
              f"клеток в индексе {len(index)}")

        def around_full(lat: float, lon: float) -> set[str]:
            return {str(m.id) for m in market
                    if _distance_km(lat, lon, float(m.latitude), float(m.longitude))
                    <= radius_km}

        def around_index(lat: float, lon: float) -> set[str]:
            return {str(m.id) for m in _geo_around(index, lat, lon, radius_km)
                    if _distance_km(lat, lon, float(m.latitude), float(m.longitude))
                    <= radius_km}

        t = time.perf_counter()
        by_index = [around_index(float(o.latitude), float(o.longitude)) for o in ours]
        t_index = time.perf_counter() - t

        t = time.perf_counter()
        by_full = [around_full(float(o.latitude), float(o.longitude)) for o in ours]
        t_full = time.perf_counter() - t

        lost = 0
        extra = 0
        worst = None
        for o, a, b in zip(ours, by_index, by_full):
            if a != b:
                lost += len(b - a)
                extra += len(a - b)
                if worst is None:
                    worst = (o.name, sorted(b - a)[:3])
        print(f"перебор {t_full:.2f} с, индекс {t_index:.2f} с "
              f"(быстрее в {t_full / max(t_index, 1e-6):.0f} раз)")
        print(f"соседей потеряно {lost}, лишних {extra}")
        if worst:
            print(f"   пример расхождения: {worst[0]} — {worst[1]}")
        assert lost == 0 and extra == 0, "индекс расходится с полным перебором"
        print("индекс сходится с перебором на всех объектах")


asyncio.run(main())
