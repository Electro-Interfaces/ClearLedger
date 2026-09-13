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
                                           ingest_operator_registry, ingest_players,
                                           ingest_region_stats, ingest_shops, parse_csv)


async def main() -> None:
    files = {
        "profiles": pathlib.Path("/tmp/ev-operator-profiles.csv"),
        "apps": pathlib.Path("/tmp/ev-apps.csv"),
        "legal": pathlib.Path("/tmp/ev-operators-legal.csv"),
        "regions": pathlib.Path("/tmp/ev-market-regions.csv"),
        "players": pathlib.Path("/tmp/ev-market-players.csv"),
        "oem": pathlib.Path("/tmp/ev-oem-players.csv"),
        "shops": pathlib.Path("/tmp/ev-shops.csv"),
        # Собрано исследованием, но прежде не доезжало до приложения: сводный
        # реестр на 182 компании, выписки ЕГРЮЛ, телефоны и сайты, операторы,
        # которых видит только OpenStreetMap, и публичные карточки организаций.
        "registry": pathlib.Path("/tmp/ev-operator-registry.csv"),
        "egrul": pathlib.Path("/tmp/ev-operators-egrul.csv"),
        "contacts": pathlib.Path("/tmp/ev-operators.csv"),
        "gap": pathlib.Path("/tmp/ev-operators-gap.csv"),
        "cards": pathlib.Path("/tmp/ev-yandex-cards.csv"),
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

        if data["players"] or data["oem"]:
            # Игроки ищутся через магазин приложений: агрегатора без своих станций
            # на карте зарядок не существует, хотя за водителя он борется наравне.
            found = await ingest_players(db, company.id, players=data["players"],
                                         oem=data["oem"])
            print(found["message"])

        if any(data[k] for k in ("registry", "egrul", "contacts", "gap", "cards")):
            reg = await ingest_operator_registry(
                db, company.id, registry=data["registry"], egrul=data["egrul"],
                contacts=data["contacts"], gap=data["gap"], cards=data["cards"])
            print(reg["message"])

        if data["shops"]:
            # «Нет витрины» — значение, а не пропуск: у чистых агрегаторов её нет,
            # и это отличает их от владельцев инфраструктуры.
            shops = await ingest_shops(db, company.id, data["shops"],
                                       checked_on="2026-09-13")
            print(shops["message"])


asyncio.run(main())
