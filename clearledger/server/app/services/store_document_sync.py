"""Сверка документов центра со станциями — своим тактом.

Раздел «Документы» показывал в центре сорок три накладные, а на станции три.
Это не расхождение данных: обе стороны их видели, просто реестр центра
собирался по кнопке, а заголовки уезжали на станцию отдельной командой. Пока
человек не нажмёт — история в двух местах разная.

Сначала сверку повесили на выдачу заданий станции: «станция и так стучится
каждую минуту». Не стучится — агент ходит за заданиями, только когда центр
сказал, что они есть (так с 01.08.2026). Отсюда две беды разом:

* без заданий реестр стоял сутками — 16.10.2026 в нём не было ничего новее
  вечера 14.10, хотя смены, приёмки и оприходования станций уже пришли;
* с заданиями каждая выдача ждала полную пересборку реестра всей компании —
  10.10 НСИ не доезжала до 208 (агент ждёт ответ 90 с), 14.10 пачка карточек
  Верево положила центр: каждая рассылка вниз запускала пересборку.

Поэтому сверка — свой такт, как автопризнание заявок: раз в
DOCUMENT_SYNC_MINUTES реестр компании пересобирается, и каждой её станции
кладётся снимок заголовков и бух-статусы. Задания ложатся в ту же очередь, где
живут все прочие; станция узнаёт о них из heartbeat и забирает обычным
порядком. Выдача заданий от реестра больше не зависит.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine
from app.models import EdgeAgent
from app.services.store_document_snapshot import queue_onec_document_snapshot
from app.services.document_status_downlink import queue_document_status
from app.services.store_documents import (
    ProjectionRevisionConflict,
    rebuild_store_document_projection,
)

log = logging.getLogger("clearledger.document_sync")

# Реестр собирается на всю компанию, поэтому не чаще этого: документы станции
# всё равно приходят пакетами.
ТАКТ_МИНУТ = int(os.environ.get("DOCUMENT_SYNC_MINUTES", "10"))
ЛОК = 0x0D0C5EC1             # свой ключ: чужие регламенты не блокируем


async def сверить_станцию(
    db: AsyncSession, company_id: uuid.UUID, station_id: int,
) -> dict:
    """Положить станции свежий снимок заголовков и бух-статусы её документов.

    Вызывается после пересборки реестра. Ошибки не поднимаются наверх: одна
    станция не должна оставить без сверки остальные.
    """
    итог = {"snapshot": False, "headers": 0, "detail": ""}
    try:
        task, created = await queue_onec_document_snapshot(db, company_id, station_id)
        payload = task.payload or {}
        итог["snapshot"] = bool(created)
        итог["headers"] = len(payload.get("headers") or [])
        итог["detail"] = f"заголовков станции: {итог['headers']}"
    except ValueError as exc:
        итог["detail"] = f"снимок не поставлен: {exc}"
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        итог["detail"] = f"снимок не поставлен: {exc!r}"
        log.warning("снимок документов станции %s: %s", station_id, итог["detail"])

    # Этап B: бух-статус собственных документов станции — обратно на станцию.
    try:
        n = await queue_document_status(db, company_id, station_id)
        итог["statuses"] = n
        итог["detail"] += f", статусов вниз: {n}"
    except Exception as exc:  # noqa: BLE001 — статус не важнее остального
        await db.rollback()
        итог["detail"] += f", статусы не поставлены: {exc!r}"
        log.warning("статусы документов станции %s: %s", station_id, итог["detail"])
    await db.commit()
    return итог


async def сверить_компанию(db: AsyncSession, company_id: uuid.UUID) -> dict:
    """Пересобрать реестр компании и разослать её станциям заголовки и статусы."""
    итог: dict = {"rebuilt": False, "detail": "", "stations": {}}
    станции = (await db.execute(select(EdgeAgent.station_id).where(
        EdgeAgent.company_id == company_id).distinct())).scalars().all()
    try:
        реестр = await rebuild_store_document_projection(db, company_id)
        await db.commit()
        итог["rebuilt"] = True
        итог["detail"] = f"реестр: {реестр['records']}"
    except ProjectionRevisionConflict as exc:
        # Правила разбора изменились: собрать начисто — отдельное решение
        # человека, молча переписывать историю сверка не должна.
        #
        # Но молчать об этом тоже нельзя. Один конфликт останавливает пересборку
        # ВСЕГО реестра, и 22.08.2026 так вышло: приёмку поправили, ревизия не
        # выросла, и девять дней документы станции не попадали в центр — а знал
        # об этом только лог. Записываем отказ в состояние станций, чтобы он был
        # виден там же, где остальная их работа.
        await db.rollback()
        итог["detail"] = f"реестр требует полной пересборки: {exc}"
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        try:
            await db.execute(text("""
                UPDATE edge_agents
                   SET payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object(
                         'projection_conflict', jsonb_build_object(
                             'at', now()::text, 'detail', :detail))
                 WHERE company_id = :cid
            """), {"cid": company_id, "detail": итог["detail"]})
            await db.commit()
        except Exception:  # noqa: BLE001 — отметка не важнее сверки
            await db.rollback()
        return итог
    except Exception as exc:  # noqa: BLE001 — такт не должен умирать
        await db.rollback()
        итог["detail"] = f"реестр не собран: {exc!r}"
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        return итог

    for station_id in станции:
        итог["stations"][station_id] = await сверить_станцию(db, company_id, station_id)
    return итог


async def tick() -> int:
    """Один проход по компаниям со станциями. Возвращает число компаний."""
    # Замок держим на отдельном соединении: сверка коммитит по ходу, а сессия
    # после commit отдаёт соединение в пул — сессионный замок, взятый через неё,
    # остался бы висеть на чужом соединении, и следующие такты не шли бы вовсе.
    async with engine.connect() as замок:
        # Оба воркера будятся на одной границе такта, сверяет один.
        if not (await замок.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                    {"k": ЛОК})).scalar():
            return 0
        await замок.commit()
        try:
            async with async_session_factory() as db:
                компании = (await db.execute(
                    select(EdgeAgent.company_id).distinct())).scalars().all()
                for cid in компании:
                    начало = time.monotonic()
                    итог = await сверить_компанию(db, cid)
                    # Длительность — в лог каждый раз: пересборка идёт по всей
                    # компании, и её цену надо видеть, а не угадывать.
                    log.info("сверка документов %s за %.1f с: %s",
                             cid, time.monotonic() - начало, итог["detail"])
                return len(компании)
        finally:
            await замок.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ЛОК})
            await замок.commit()


async def run_forever() -> None:
    """Фоновый цикл — поднимается из lifespan приложения."""
    шаг = ТАКТ_МИНУТ * 60
    log.info("Сверка документов со станциями запущена (такт %d мин)", ТАКТ_МИНУТ)
    while True:
        # Будимся на границе такта, а не через «шаг» от своего старта: граница у
        # обоих воркеров общая, замок достаётся одному, второй такт пропускает.
        await asyncio.sleep(шаг - time.time() % шаг)
        try:
            await tick()
        except Exception:  # noqa: BLE001 — сверка не критична для API
            log.exception("Сбой такта сверки документов")
