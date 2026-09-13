"""Загрузить профили операторов, приложения, реквизиты и парк машин по регионам.

Файлы ожидаются в контейнере: /tmp/ev-operator-profiles.csv, /tmp/ev-apps.csv,
/tmp/ev-operators-legal.csv, /tmp/ev-market-regions.csv

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro seed_operator_profiles.py
"""
import asyncio
import pathlib

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company
from app.services.market_operators import (ingest_operator_profiles,
                                           ingest_region_stats, parse_csv)


async def main() -> None:
    files = {
        "profiles": pathlib.Path("/tmp/ev-operator-profiles.csv"),
        "apps": pathlib.Path("/tmp/ev-apps.csv"),
        "legal": pathlib.Path("/tmp/ev-operators-legal.csv"),
        "regions": pathlib.Path("/tmp/ev-market-regions.csv"),
    }
    data: dict[str, list] = {}
    for key, path in files.items():
        if not path.exists():
            print(f"нет файла {path} — раздел пропущен")
            data[key] = []
            continue
        data[key] = parse_csv(path.read_bytes())
        print(f"{path.name}: {len(data[key])} строк")

    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        result = await ingest_operator_profiles(
            db, company.id, profiles=data["profiles"], apps=data["apps"],
            legal=data["legal"])
        print("\n" + result["message"])

        if data["regions"]:
            # Дата парка фиксируется вместе с числами: он обновляется вручную
            # несколько раз в год, и через полгода никто не вспомнит, к какому
            # моменту относятся эти 80 тысяч машин.
            stats = await ingest_region_stats(
                db, company.id, data["regions"],
                source="АВТОСТАТ «Парк ТС в РФ» + наш обход", as_of="2026-01-01")
            print(stats["message"])


asyncio.run(main())
