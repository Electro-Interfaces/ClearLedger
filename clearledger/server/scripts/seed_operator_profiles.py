"""Загрузить профили операторов, приложения и реквизиты.

Файлы ожидаются в контейнере: /tmp/ev-operator-profiles.csv, /tmp/ev-apps.csv,
/tmp/ev-operators-legal.csv

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro seed_operator_profiles.py
"""
import asyncio
import pathlib

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company
from app.services.market_operators import ingest_operator_profiles, parse_csv


async def main() -> None:
    files = {
        "profiles": pathlib.Path("/tmp/ev-operator-profiles.csv"),
        "apps": pathlib.Path("/tmp/ev-apps.csv"),
        "legal": pathlib.Path("/tmp/ev-operators-legal.csv"),
    }
    data = {}
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


asyncio.run(main())
