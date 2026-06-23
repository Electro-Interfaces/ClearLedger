"""
Сид источников и каналов компании РусГидро (профиль energy).

В идеологии Источник → Канал → Разрез:
  Источник `manual_table` «Реестр договоров и оплат ЭЗС» (ручная загрузка xlsx)
  → Канал `reestr_contracts_payments` (fetch файла → нормализация L1→L2 → save)
  → разрезы `energy_suppliers` / `energy_rent` (reconcile_catalog).

Идемпотентно: повторный запуск обновляет записи, не плодит дубли.
НЕ удаляет источники/каналы вне списка (у РусГидро могут быть и другие energy-источники).

Запуск (из каталога server):
    py -3 scripts/seed_rushydro_connections.py [company_id|slug]
  dev:  py -3 scripts/seed_rushydro_connections.py 0a5cc6de-f890-419b-bea9-bd63aba31bd3
  прод: py -3 scripts/seed_rushydro_connections.py 174bbb4f-d22b-4fd8-bbdf-e0640fc6f951
"""
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Channel, ChannelStream, Source  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = sys.argv[1] if len(sys.argv) > 1 else "rushydro"

# (source_type, name, description, status, connection_config)
SOURCES = [
    ("manual_table", "Реестр договоров и оплат ЭЗС",
     "Ручная таблица (xlsx): по каждой ЭЗС энергоснабжение и аренда с контрагентом, "
     "договором/разрешением и статусом оплаты. Загрузка в канал → нормализация L1→L2.",
     "connected", {"sheet": "Общий свод"}),
]

# (template_id, name, description, status, anchor_source_type, anchor_doc_type, stream_name)
CHANNELS = [
    ("reestr_contracts_payments", "Реестр договоров и оплат ЭЗС",
     "Загрузка таблицы → L1 RAW → нормализация → L2 (контрагенты/договоры/платёжная "
     "дисциплина) → разрезы «Поставщики э/э» и «Аренда».",
     "active", "manual_table", "contracts_payments", "Реестр договоров и оплат"),
]


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        print(f"company '{COMPANY}' → {cid}")

        for st, name, descr, status, cfg in SOURCES:
            existing = (await db.execute(
                select(Source).where(Source.company_id == cid, Source.source_type == st)
            )).scalar_one_or_none()
            if existing:
                existing.name = name
                existing.description = descr
                existing.status = status
                existing.connection_config = cfg
                print(f"  source ~ {st:14} (обновлён)")
            else:
                db.add(Source(company_id=cid, source_type=st, name=name,
                              description=descr, status=status, connection_config=cfg))
                print(f"  source + {st:14} (создан)")
        await db.flush()
        src_id = {
            s.source_type: s.id
            for s in (await db.execute(select(Source).where(Source.company_id == cid))).scalars().all()
        }

        for tpl, name, descr, status, ast, adoc, sname in CHANNELS:
            ch = (await db.execute(
                select(Channel).where(Channel.company_id == cid, Channel.template_id == tpl)
            )).scalar_one_or_none()
            if ch:
                ch.name = name
                ch.description = descr
                ch.status = status
                print(f"  channel ~ {tpl} (обновлён)")
            else:
                ch = Channel(company_id=cid, name=name, description=descr,
                             status=status, template_id=tpl)
                db.add(ch)
                print(f"  channel + {tpl} (создан)")
            await db.flush()

            sid = src_id.get(ast)
            if sid:
                exists = (await db.execute(select(ChannelStream).where(
                    ChannelStream.channel_id == ch.id,
                    ChannelStream.source_id == sid,
                    ChannelStream.doc_type_id == adoc,
                ))).scalar_one_or_none()
                if not exists:
                    db.add(ChannelStream(channel_id=ch.id, source_id=sid,
                                         doc_type_id=adoc, name=sname))
                    print(f"      stream + {ast}:{adoc}")

        await db.commit()
        print("OK: источник+канал реестра РусГидро засеяны.")


if __name__ == "__main__":
    asyncio.run(main())
