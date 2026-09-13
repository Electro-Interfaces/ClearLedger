"""Восстановить географию точек рынка: регион из города и единое написание субъекта.

Аудит 13.09.2026 (А01): региона нет у 79% точек, потому что источник пишет адрес
как «г Тюмень, ул Советская» — субъекта в строке нет вовсе. Город при этом известен
почти всегда. Там же, где регион есть, он написан четырьмя способами, и один субъект
дробится на несколько территорий.

Приём реестра теперь делает это сам; скрипт лечит то, что уже загружено.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro backfill_market_geo.py
"""
import asyncio
from collections import Counter

from sqlalchemy import select

from app.database import async_session_factory
from app.models import MarketSite
from app.services import ru_geo


async def main() -> None:
    async with async_session_factory() as db:
        sites = (await db.execute(select(MarketSite))).scalars().all()
        by_source = Counter()
        changed = 0
        for site in sites:
            region, how = ru_geo.resolve(site.region, site.city)
            by_source[how] += 1
            if region and region != site.region:
                site.region = region
                changed += 1
        await db.commit()

        print(f"точек {len(sites)}: регион записан заново у {changed}")
        print(f"  из адреса источника  {by_source['source']}")
        print(f"  выведен из города    {by_source['city']}")
        print(f"  остался неизвестным  {by_source['unknown']}")

        # Что осталось без региона — по городам, чтобы видеть, чего не хватает
        # справочнику, а не считать пропуск безликой массой.
        rest = Counter((s.city or "— город не указан") for s in sites if not s.region)
        if rest:
            print("\nбез региона, топ городов:")
            for city, n in rest.most_common(15):
                print(f"   {city[:32]:<34}{n}")


asyncio.run(main())
