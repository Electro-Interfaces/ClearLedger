"""
Демо-сид источников и каналов компании ГИГ.

Модель ГИГ (14.06.2026):
  Источники: STS (нефтепродукты), ЦБ ЭЛСИ.АЗК (сопутка/общепит), 1С:Бухгалтерия (эталон).
  Каналы (2 операционных источника → 4 канала):
    STS              → «сменный отчёт (продажи)» + «приём (ТТН)»  (отдельные каналы — свои разрезы)
    ЦБ ЭЛСИ.АЗК       → «сопутка» + «общепит»
    1С:Бухгалтерия = эталон, каналов не порождает (используется как опорная сверка).

Идемпотентно: повторный запуск обновляет записи и не плодит дубли; источники/каналы
вне актуального списка удаляются.

Запуск (из каталога server):
    py -3 scripts/seed_gig_connections.py
"""
import asyncio
import sys
from pathlib import Path

# консоль Windows = cp1251; принудительно UTF-8 для вывода с кириллицей/стрелками
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# чтобы `import app...` работал при запуске из server/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Channel, ChannelStream, Source  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"

# (source_type, name, description, status, connection_config)
SOURCES = [
    ("sts", "STS API ГИГ (система 15)",
     "Сменные отчёты по нефтепродуктам: продажи, ТРК, резервуары, оплаты + ТТН приёма (pos.autooplata.ru/tms, система 15)",
     "connected", {"base_url": "https://pos.autooplata.ru/tms", "default_system_ids": "15", "system_id": "15"}),
    ("onec_operational", "ЦБ ЭЛСИ.АЗК (сопутка и общепит)",
     "Сменные отчёты по сопутке и общепиту (магазин + кухня) из центральной базы ЭЛСИ.АЗК",
     "connected", {}),
    ("onec_accounting", "1С:Бухгалтерия ГИГ (эталон)",
     "Эталон учёта — боевая БП 3.0 ГИГ (COM-агент 1c-dev-01). Сверка и приёмник проводок. Важнейший источник.",
     "connected", {"base": "GIG"}),
]

# (template_id, name, description, status, anchor_source_type, anchor_doc_type, stream_name)
# status: active = работает. Каждый канал привязан к опорному (anchor) источнику.
CHANNELS = [
    ("fuel_shift", "Топливо: сменный отчёт (продажи)",
     "Сменные отчёты по нефтепродуктам — продажи, ТРК, оплаты. Опорный канал, к нему сходятся сверки каналов.",
     "active", "sts", "shift_report", "Сменные отчёты (STS)"),
    ("fuel_delivery", "Топливо: приём (ТТН)",
     "Приём нефтепродуктов по товарно-транспортным накладным. Отдельный канал — свои разрезы сверки.",
     "active", "sts", "receipt", "Поступления / ТТН (STS)"),
    ("sidegoods", "Сопутка (магазин)",
     "Сменные отчёты по сопутке из центральной базы ЭЛСИ.АЗК.",
     "active", "onec_operational", "orp_sidegoods", "ОРП сопутки (ЦБ)"),
    ("food", "Общепит",
     "Сменные отчёты по общепиту (кухня) из центральной базы ЭЛСИ.АЗК.",
     "active", "onec_operational", "food_sale", "Продажи общепита (ЦБ)"),
]


async def main() -> None:
    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)
        print(f"company '{COMPANY}' → {cid}")

        # ─── Источники ───────────────────────────────────────────────
        for st, name, descr, status, cfg in SOURCES:
            existing = (await db.execute(
                select(Source).where(Source.company_id == cid, Source.source_type == st)
            )).scalar_one_or_none()
            if existing:
                existing.name = name
                existing.description = descr
                existing.status = status
                existing.connection_config = cfg
                print(f"  source ~ {st:18} status={status} (обновлён)")
            else:
                db.add(Source(
                    company_id=cid, source_type=st, name=name,
                    description=descr, status=status, connection_config=cfg,
                ))
                print(f"  source + {st:18} status={status} (создан)")

        keep_src = {st for st, *_ in SOURCES}
        for s in (await db.execute(select(Source).where(Source.company_id == cid))).scalars().all():
            if s.source_type not in keep_src:
                await db.delete(s)
                print(f"  source - {s.source_type:18} (удалён, не в списке)")

        await db.flush()
        src_id = {
            s.source_type: s.id
            for s in (await db.execute(select(Source).where(Source.company_id == cid))).scalars().all()
        }

        # ─── Каналы (+ привязка к опорному источнику) ─────────────────
        keep_tpl = {c[0] for c in CHANNELS}
        for tpl, name, descr, status, ast, adoc, sname in CHANNELS:
            ch = (await db.execute(
                select(Channel).where(Channel.company_id == cid, Channel.template_id == tpl)
            )).scalar_one_or_none()
            if ch:
                ch.name = name
                ch.description = descr
                ch.status = status
                print(f"  channel ~ {tpl:14} status={status} (обновлён)")
            else:
                ch = Channel(company_id=cid, name=name, description=descr,
                             status=status, template_id=tpl)
                db.add(ch)
                print(f"  channel + {tpl:14} status={status} (создан)")
            await db.flush()  # ch.id

            sid = src_id.get(ast)
            if sid:
                exists = (await db.execute(select(ChannelStream).where(
                    ChannelStream.channel_id == ch.id,
                    ChannelStream.source_id == sid,
                    ChannelStream.doc_type_id == adoc,
                ))).scalar_one_or_none()
                if not exists:
                    db.add(ChannelStream(
                        channel_id=ch.id, source_id=sid, doc_type_id=adoc, name=sname,
                    ))
                    print(f"      stream + {ast}:{adoc}")

        for ch in (await db.execute(select(Channel).where(Channel.company_id == cid))).scalars().all():
            if ch.template_id not in keep_tpl:
                await db.delete(ch)
                print(f"  channel - {ch.template_id} (удалён, не в списке)")

        await db.commit()
        print("OK: источники и каналы ГИГ засеяны.")


if __name__ == "__main__":
    asyncio.run(main())
