"""
Приём пакетов смен ЦБ в L2: нормализация + идемпотентная запись DataEntry.

ingest_packages(db, company_id, packages):
  пакет смены → normalize_shift_package → upsert DataEntry по натуральному
  ключу (company_id, source='oneC', source_id={ОСЭ_Номер}:{kind}:{UUID}).
  Идемпотентно: повторный приём той же смены обновляет, не дублирует.

Это стадии normalize+save канала сопутки/общепита. Стадию fetch (pull смен
из ЦБ) даёт onec_operational через com_worker.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry
from app.services.cb_normalize import normalize_shift_package


async def ingest_packages(
    db: AsyncSession,
    company_id: uuid.UUID,
    packages: list[dict],
) -> dict:
    """Нормализовать пакеты смен и идемпотентно записать в L2 (DataEntry)."""
    created = 0
    updated = 0
    shifts = 0
    skipped: list[str] = []

    for pkg in packages:
        res = normalize_shift_package(pkg)
        shifts += 1
        skipped.extend(res.get("skipped", []))

        for draft in res["entries"]:
            sid = draft["source_id"]
            existing = (
                await db.execute(
                    select(DataEntry).where(
                        DataEntry.company_id == company_id,
                        DataEntry.source == "oneC",
                        DataEntry.source_id == sid,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                existing.title = draft["title"]
                existing.category_id = draft["category_id"]
                existing.subcategory_id = draft["subcategory_id"]
                existing.doc_type_id = draft["doc_type_id"]
                existing.status = draft["status"]
                existing.layer = draft["layer"]
                existing.meta = draft["meta"]
                updated += 1
            else:
                db.add(
                    DataEntry(
                        company_id=company_id,
                        title=draft["title"],
                        category_id=draft["category_id"],
                        subcategory_id=draft["subcategory_id"],
                        doc_type_id=draft["doc_type_id"],
                        status=draft["status"],
                        source=draft["source"],
                        source_label=draft["source_label"],
                        source_id=sid,
                        layer=draft["layer"],
                        meta=draft["meta"],
                    )
                )
                created += 1
        await db.flush()

    return {
        "shifts": shifts,
        "created": created,
        "updated": updated,
        "skipped_kinds": sorted(set(skipped)),
    }
