"""Сверка документов при обмене со станцией.

Раздел «Документы» показывал в центре сорок три накладные, а на станции три.
Это не расхождение данных: обе стороны их видели, просто реестр центра
собирался по кнопке, а заголовки уезжали на станцию отдельной командой. Пока
человек не нажмёт — история в двух местах разная.

Отдельного планировщика для этого не нужно: станция и так стучится за
заданиями каждую минуту, и это готовый момент сверки. При обращении центр
проверяет, не устарел ли реестр, и если да — пересобирает его и кладёт свежий
снимок заголовков в ту же очередь заданий, где живут все прочие задания
станции. Ничего нового человеку осваивать не приходится: снимок виден в
«Заданиях станциям», применение — в состоянии станции.

Сверка идёт только когда связь есть — она и есть признак связи. Нет связи —
нет и сверки, документы дождутся следующего обращения.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreDocumentProjection
from app.services.store_document_snapshot import queue_onec_document_snapshot
from app.services.store_documents import (
    ProjectionRevisionConflict,
    rebuild_store_document_projection,
)

log = logging.getLogger("clearledger.document_sync")

# Реестр собирается на всю компанию, поэтому не на каждый стук: раз в столько
# минут его достаточно освежить, документы станции всё равно приходят пакетами.
СВЕЖЕСТЬ_МИНУТ = int(os.environ.get("DOCUMENT_SYNC_MINUTES", "10"))


async def сверить_документы(
    db: AsyncSession, company_id: uuid.UUID, station_id: int,
) -> dict:
    """Обновить реестр и поставить станции свежий снимок заголовков.

    Возвращает, что сделано, — чтобы это было видно в состоянии станции, а не
    только в логе. Ошибки не поднимаются наверх: сверка не имеет права
    уронить обмен, из-за которого станция теряет задания и пакеты.
    """
    итог = {"rebuilt": False, "snapshot": False, "headers": 0, "detail": ""}
    порог = datetime.now(timezone.utc) - timedelta(minutes=СВЕЖЕСТЬ_МИНУТ)
    собран = (await db.execute(select(func.max(StoreDocumentProjection.rebuilt_at)).where(
        StoreDocumentProjection.company_id == company_id))).scalar()
    if собран is not None and собран > порог:
        итог["detail"] = "реестр свежий"
        return итог
    try:
        реестр = await rebuild_store_document_projection(db, company_id)
        итог["rebuilt"] = True
        итог["detail"] = f"реестр: {реестр['records']}"
    except ProjectionRevisionConflict as exc:
        # Правила разбора изменились: собрать начисто — отдельное решение
        # человека, молча переписывать историю обмен не должен.
        await db.rollback()
        итог["detail"] = f"реестр требует полной пересборки: {exc}"
        log.warning("сверка документов станции %s: %s", station_id, итог["detail"])
        return итог
    except Exception as exc:  # noqa: BLE001 — обмен важнее сверки
        await db.rollback()
        итог["detail"] = f"реестр не собран: {exc!r}"
        log.warning("сверка документов станции %s: %s", station_id, итог["detail"])
        return итог

    try:
        task, created = await queue_onec_document_snapshot(db, company_id, station_id)
        payload = task.payload or {}
        итог["snapshot"] = bool(created)
        итог["headers"] = len(payload.get("headers") or [])
        итог["detail"] += f", заголовков станции: {итог['headers']}"
    except ValueError as exc:
        итог["detail"] += f", снимок не поставлен: {exc}"
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        итог["detail"] += f", снимок не поставлен: {exc!r}"
        log.warning("снимок документов станции %s: %s", station_id, итог["detail"])
    return итог
