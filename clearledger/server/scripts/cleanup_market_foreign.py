"""Убрать из рынка точки, стоящие не в России.

Первая загрузка прошла до того, как выяснилось, что треть выгрузки — Финляндия,
Эстония и Латвия (`country` в источнике пуст, координаты не различают). Точки уже
в базе, и «рынок России» с ними показывает чужую плотность и чужую цену.

Удаляем, а не помечаем: это не наблюдение, которое стоит хранить ради истории, а
строки, попавшие по ошибке разбора. Вместе с точкой уходят её срезы и наблюдения
(каскадом), а операторы, оставшиеся без точек, остаются — их заведение ничего не
стоит и они могут ещё встретиться.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro cleanup_market_foreign.py
"""
import asyncio

from sqlalchemy import delete, select

from app.database import async_session_factory
from app.models import MarketSite
from app.services.market_registry import RU_TIMEZONES, SOURCE_CODE


async def main() -> None:
    async with async_session_factory() as db:
        sites = (await db.execute(select(MarketSite).where(
            MarketSite.source == SOURCE_CODE))).scalars().all()
        foreign = [s for s in sites
                   if (s.raw or {}).get("time_zone")
                   and (s.raw or {}).get("time_zone") not in RU_TIMEZONES]
        print(f"точек источника {SOURCE_CODE}: {len(sites)}, из них не в России: {len(foreign)}")
        zones: dict[str, int] = {}
        for s in foreign:
            tz = (s.raw or {}).get("time_zone")
            zones[tz] = zones.get(tz, 0) + 1
        for tz, count in sorted(zones.items(), key=lambda r: -r[1]):
            print(f"   {tz}: {count}")
        if not foreign:
            print("чистить нечего")
            return
        await db.execute(delete(MarketSite).where(
            MarketSite.id.in_([s.id for s in foreign])))
        await db.commit()
        print(f"\nудалено {len(foreign)} точек; осталось {len(sites) - len(foreign)}")


asyncio.run(main())
