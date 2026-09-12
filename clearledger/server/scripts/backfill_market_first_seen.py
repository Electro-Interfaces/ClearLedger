"""Дата появления точки — из источника, а не из даты нашей загрузки.

Точки, заехавшие первой выгрузкой, получили `first_seen_at` = момент загрузки, и
разрез «как рос конкурент» сводился к одному столбику в сентябре 2026. В самой
выгрузке есть `created_at` записи источника (у части точек — 2022 год), он и есть
честный ответ на «когда точка появилась».

Разовый проход: дальше приём ставит дату сам.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro backfill_market_first_seen.py
"""
import asyncio
import collections

from sqlalchemy import select

from app.database import async_session_factory
from app.models import MarketSite
from app.services.market_registry import SOURCE_CODE, _dt


async def main() -> None:
    async with async_session_factory() as db:
        sites = (await db.execute(select(MarketSite).where(
            MarketSite.source == SOURCE_CODE))).scalars().all()
        fixed = 0
        years: collections.Counter = collections.Counter()
        for site in sites:
            created = _dt((site.raw or {}).get("created_at"))
            if created is None:
                continue
            years[created.year] += 1
            if site.first_seen_at is None or site.first_seen_at.date() != created.date():
                site.first_seen_at = created
                fixed += 1
        await db.commit()
        print(f"точек источника: {len(sites)}, дата появления уточнена у {fixed}")
        print("по годам появления:", ", ".join(
            f"{year}: {count}" for year, count in sorted(years.items())))


asyncio.run(main())
