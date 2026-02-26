"""Sync-сервис: staging → облако → promote to public.

Background worker забирает raw_entries с status='parsed',
отправляет batch в облако, получает результаты, промоутит в public.entries.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.models import RawEntry, AiResult, Entry, Company

logger = logging.getLogger("sync")

BATCH_SIZE = 20
RETRY_DELAYS = [5, 15, 60, 300, 900]  # секунды между попытками


async def sync_loop():
    """Основной цикл: проверяет staging каждые 30 секунд."""
    logger.info("Sync worker запущен")
    while True:
        try:
            await process_pending_batch()
        except Exception as e:
            logger.error(f"Ошибка sync: {e}")
        await asyncio.sleep(30)


async def process_pending_batch():
    """Берёт пачку parsed записей и обрабатывает."""
    if not settings.cloud_api_url:
        # Нет облака — работаем в offline-режиме, ничего не отправляем
        return

    async with async_session() as db:
        # Забираем batch
        result = await db.execute(
            select(RawEntry)
            .where(RawEntry.processing_status == "parsed")
            .order_by(RawEntry.created_at)
            .limit(BATCH_SIZE)
        )
        raw_entries = list(result.scalars().all())
        if not raw_entries:
            return

        logger.info(f"Отправляем batch: {len(raw_entries)} записей")

        # Помечаем как 'sent'
        ids = [e.id for e in raw_entries]
        await db.execute(
            update(RawEntry)
            .where(RawEntry.id.in_(ids))
            .values(processing_status="sent", updated_at=datetime.now(timezone.utc))
        )
        await db.commit()

    # Отправляем в облако
    try:
        results = await send_to_cloud(raw_entries)
    except Exception as e:
        logger.error(f"Облако недоступно: {e}")
        # Возвращаем status обратно в parsed
        async with async_session() as db:
            await db.execute(
                update(RawEntry)
                .where(RawEntry.id.in_(ids))
                .values(processing_status="parsed")
            )
            await db.commit()
        return

    # Обрабатываем результаты
    async with async_session() as db:
        for r in results:
            await handle_ai_result(db, r)
        await db.commit()


async def send_to_cloud(raw_entries: list[RawEntry]) -> list[dict]:
    """Отправляет batch в облачный API."""
    # Подгружаем profile_id компаний для контекстной классификации
    company_ids = list({e.company_id for e in raw_entries})
    company_profiles: dict[str, str] = {}
    async with async_session() as db:
        result = await db.execute(
            select(Company.id, Company.profile_id).where(Company.id.in_(company_ids))
        )
        for row in result.all():
            company_profiles[row.id] = row.profile_id

    batch = []
    for e in raw_entries:
        batch.append({
            "raw_entry_id": str(e.id),
            "file_name": e.file_name,
            "mime_type": e.mime_type,
            "extracted_text": e.extracted_text[:50000],  # лимит
            "extracted_fields": e.extracted_fields,
            "company_id": e.company_id,
            "company_profile": company_profiles.get(e.company_id, "general"),
        })

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.cloud_api_url}/api/process",
            json={
                "instance_id": settings.instance_id,
                "batch": batch,
            },
            headers={"Authorization": f"Bearer {settings.cloud_api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["results"]


async def handle_ai_result(db: AsyncSession, result: dict):
    """Обрабатывает один результат от облака."""
    raw_entry_id = UUID(result["raw_entry_id"])
    decision = result.get("decision", "pending")

    # Сохраняем AI result
    ai_result = AiResult(
        raw_entry_id=raw_entry_id,
        category_id=result.get("classification", {}).get("category_id"),
        subcategory_id=result.get("classification", {}).get("subcategory_id"),
        doc_type_id=result.get("classification", {}).get("doc_type_id"),
        confidence=result.get("classification", {}).get("confidence", 0),
        normalized_metadata=result.get("normalized_metadata", {}),
        decision=decision,
        rejection_reason=result.get("rejection_reason"),
        model_version=result.get("model_version"),
    )
    db.add(ai_result)

    # Если accepted — промоутим в public.entries
    if decision == "accepted":
        await promote_to_public(db, raw_entry_id, result)

    # Обновляем статус raw_entry
    status = "promoted" if decision == "accepted" else (
        "rejected" if decision == "rejected" else "processed"
    )
    await db.execute(
        update(RawEntry)
        .where(RawEntry.id == raw_entry_id)
        .values(processing_status=status, updated_at=datetime.now(timezone.utc))
    )


async def promote_to_public(db: AsyncSession, raw_entry_id: UUID, result: dict):
    """Перемещает запись из staging в public.entries."""
    # Получаем raw_entry
    raw = (await db.execute(
        select(RawEntry).where(RawEntry.id == raw_entry_id)
    )).scalar_one()

    classification = result.get("classification", {})
    metadata = result.get("normalized_metadata", {})

    # Определяем source_type из extracted_fields (email, 1c, etc.) или fallback upload
    extracted = raw.extracted_fields or {}
    source_type = "email" if extracted.get("_email_sender") else "upload"

    entry = Entry(
        company_id=raw.company_id,
        source_id=raw.source_id,
        title=metadata.get("title", raw.file_name),
        category_id=classification.get("category_id", "uncategorized"),
        subcategory_id=classification.get("subcategory_id", "other"),
        doc_type_id=classification.get("doc_type_id"),
        status="new",
        source_type=source_type,
        source_label=raw.file_name,
        metadata_=metadata,
    )
    db.add(entry)
    logger.info(f"Promoted: {raw.file_name} → {entry.title}")
