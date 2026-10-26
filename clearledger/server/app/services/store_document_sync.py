"""Фоновая сверка документов: выдача downlink не ждёт пересборки реестра.

Каждая компания обрабатывается в отдельной сессии. Занятый реестр пропускаем
до следующего такта; готовые снимки станции забирают обычным опросом очереди.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import EdgeAgent, StoreDocumentProjectionState
from app.services.store_document_snapshot import queue_onec_document_snapshot
from app.services.document_status_downlink import queue_document_status
from app.services.store_documents import (
    ProjectionRevisionConflict,
    rebuild_store_document_projection,
)

log = logging.getLogger("clearledger.document_sync")
СВЕЖЕСТЬ_МИНУТ = int(os.environ.get("DOCUMENT_SYNC_MINUTES", "10"))
TICK_SECONDS = max(1, СВЕЖЕСТЬ_МИНУТ * 60)
TRY_LOCK = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope_key, 0))")


async def сверить_документы(
    db: AsyncSession, company_id: uuid.UUID, station_id: int | list[int],
) -> dict:
    """Обновить общий реестр и поставить снимки всем станциям компании.

    Вызывается фоновым тактом под lock реестра. После rollback прекращаем
    обработку компании: транзакционный lock уже отпущен.
    """
    stations = station_id if isinstance(station_id, list) else [station_id]
    итог = {"rebuilt": False, "snapshot": False, "headers": 0, "detail": ""}
    порог = datetime.now(timezone.utc) - timedelta(minutes=СВЕЖЕСТЬ_МИНУТ)
    try:
        собран = (await db.execute(select(
            StoreDocumentProjectionState.last_successful_rebuild_at,
        ).where(StoreDocumentProjectionState.company_id == company_id))).scalar()
        if собран is not None and собран > порог:
            итог["detail"] = "реестр свежий"
        else:
            реестр = await rebuild_store_document_projection(db, company_id)
            итог["rebuilt"] = True
            итог["detail"] = f"реестр: {реестр['records']}"
    except ProjectionRevisionConflict as exc:
        await db.rollback()
        итог["detail"] = f"реестр требует полной пересборки: {exc}"
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        # Конфликт должен быть виден в состоянии станций, а не только в логе.
        try:
            for station in stations:
                await db.execute(text("""
                    UPDATE edge_agents
                       SET payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object(
                             'projection_conflict', jsonb_build_object(
                                 'at', now()::text, 'detail', :detail))
                     WHERE company_id = :cid AND station_id = :st
                """), {"cid": company_id, "st": station, "detail": итог["detail"]})
            await db.commit()
        except Exception:  # noqa: BLE001 — отметка не важнее обмена
            await db.rollback()
        return итог
    except Exception as exc:  # noqa: BLE001 — обмен важнее сверки
        await db.rollback()
        итог["detail"] = f"реестр не собран: {exc!r}"
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        return итог

    for station in stations:
        try:
            # Каждый вид доставки изолирован; успешный rebuild и его watermark
            # остаются в общей транзакции под lock даже при ошибке очереди.
            async with db.begin_nested():
                task, created = await queue_onec_document_snapshot(db, company_id, station)
            итог["snapshot"] |= bool(created)
            итог["headers"] += len((task.payload or {}).get("headers") or [])
        except Exception as exc:  # noqa: BLE001 — ошибка сверки не ломает обмен
            итог["detail"] += f", снимок станции {station} не поставлен: {exc!r}"
            log.warning("сверка документов компании %s: %s", company_id, итог["detail"])

        try:
            async with db.begin_nested():
                n = await queue_document_status(db, company_id, station)
            итог["statuses"] = итог.get("statuses", 0) + n
        except Exception as exc:  # noqa: BLE001 — ошибка сверки не ломает обмен
            итог["detail"] += f", статусы станции {station} не поставлены: {exc!r}"
            log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
    return итог


async def tick() -> int:
    """Один такт; сессия запроса станции здесь никогда не используется."""
    async with async_session_factory() as db:
        stations = (await db.execute(select(
            EdgeAgent.company_id, EdgeAgent.station_id,
        ).order_by(EdgeAgent.company_id, EdgeAgent.station_id))).all()
    companies: dict[uuid.UUID, list[int]] = {}
    for cid, station in stations:
        companies.setdefault(cid, []).append(station)
    processed = 0
    for cid, company_stations in companies.items():
        try:
            async with async_session_factory() as db:
                # Тот же ключ, что у ручной пересборки. Rebuild берёт его
                # повторно в этой же транзакции, поэтому ожидания там нет.
                got = (await db.execute(TRY_LOCK, {
                    "scope_key": f"store-documents:{cid}",
                })).scalar()
                if not got:
                    continue
                result = await сверить_документы(db, cid, company_stations)
                await db.commit()
                processed += 1
                log.info("сверка компании %s: %s", cid, result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — следующая компания продолжает обмен
            log.exception("сбой сверки документов компании %s", cid)
    return processed


async def run_forever() -> None:
    log.info("Сверка документов запущена (тик %d с)", TICK_SECONDS)
    try:
        while True:
            try:
                await tick()
            except Exception:  # noqa: BLE001 — временная ошибка не останавливает цикл
                log.exception("сбой такта сверки документов")
            await asyncio.sleep(TICK_SECONDS)
    except asyncio.CancelledError:
        # Отмена и во время SQL, и во время сна штатно завершает цикл.
        log.info("Сверка документов остановлена")
