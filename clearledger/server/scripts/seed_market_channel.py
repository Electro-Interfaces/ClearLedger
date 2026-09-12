"""Завести канал «Реестр ЭЗС страны» и прогнать через него выгрузку.

Делает ровно то, что делает человек в «Данные → Коннекторы»: подключение,
канал из шаблона, загруженный файл, запуск обработки. Вызывается тот же
`run_channel`, что дёргает API, — проверяется весь конвейер, а не парсер.

Файл ожидается в контейнере по пути `/tmp/market-ru.csv`.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro seed_market_channel.py
"""
import asyncio
import os
import pathlib

from sqlalchemy import select

from app.channel_catalog import get_channel_template
from app.database import async_session_factory
from app.models import Channel, ChannelStage, ChannelStream, Company, Source
from app.services import file_store
from app.services.channel_orchestrator import run_channel

SRC_TYPE = "market_registry_file"
TEMPLATE = "market_registry"
# Путь можно переопределить: приёмка частичного среза грузит обрезанный файл.
FILE = pathlib.Path(os.getenv("MARKET_FILE", "/tmp/market-ru.csv"))


async def main() -> None:
    if not FILE.exists():
        print(f"файла {FILE} нет — сначала docker cp выгрузку в контейнер")
        return
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        cid = company.id
        print(f"пространство: {company.name}")

        source = (await db.execute(select(Source).where(
            Source.company_id == cid, Source.source_type == SRC_TYPE))).scalars().first()
        if source is None:
            source = Source(company_id=cid, source_type=SRC_TYPE,
                            name="Реестр ЭЗС страны", status="active",
                            connection_config={})
            db.add(source)
            await db.flush()
            print("подключение заведено")

        channel = (await db.execute(select(Channel).where(
            Channel.company_id == cid, Channel.template_id == TEMPLATE))).scalars().first()
        if channel is None:
            tpl = get_channel_template(TEMPLATE)
            channel = Channel(company_id=cid, name=tpl.label, description=tpl.description,
                              status="active", template_id=TEMPLATE,
                              schedule=tpl.schedule, config={})
            db.add(channel)
            await db.flush()
            for s in tpl.streams:
                db.add(ChannelStream(channel_id=channel.id, source_id=source.id,
                                     doc_type_id=s.doc_type, name=s.label,
                                     role=s.role, enabled=True))
            for i, st in enumerate(tpl.stages):
                db.add(ChannelStage(channel_id=channel.id, stage_type=st.stage_type,
                                    name=st.name, order_index=i))
            await db.flush()
            print("канал заведён из шаблона")

        data = FILE.read_bytes()
        stored = file_store.put(db, cid, data, file_name="ev-russia-full.csv",
                                mime="text/csv", purpose="data")
        await db.flush()
        channel.config = {**(channel.config or {}), "uploadFileId": str(stored.id)}
        await db.commit()
        print(f"файл загружен: {len(data):,} байт".replace(",", " "))

        result = await run_channel(db, channel)
        await db.commit()
        print("\nрезультат прогона:")
        for key, value in result.items():
            print(f"   {key}: {value}")


asyncio.run(main())
