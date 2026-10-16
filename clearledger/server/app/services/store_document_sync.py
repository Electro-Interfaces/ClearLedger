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
DOCUMENT_SYNC_MINUTES центр смотрит, пришло ли в источники реестра что-то новое,
и если да — пересобирает реестр компании и кладёт каждой её станции снимок
заголовков и бух-статусы. Задания ложатся в ту же очередь, где живут все
прочие; станция узнаёт о них из heartbeat и забирает обычным порядком. Выдача
заданий от реестра больше не зависит.

Пересборка не дешёвая: она читает все пакеты станций компании, на gig
16.10.2026 — около минуты. Поэтому без новых данных её не запускаем: источники
меняются несколько раз в сутки (смены ночью, приёмки днём, чтение БП утром), а
не каждые десять минут.
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
# Даже без видимых изменений реестр пересобирается не реже этого: у части
# источников нет отметки времени, их правку на месте отпечаток не заметит.
НЕ_РЕЖЕ_ЧАСОВ = 6
# Пакеты станций, которые документов реестра не порождают (проверено по живой
# базе gig 16.10.2026: в них только stock_snapshot, stock_moves, cash_state,
# item_draft, price_change, catalog_digest, mrc_fact). Первые четыре станции шлют
# ежечасно — по ним пересборка шла бы почти каждый такт.
БЕЗ_ДОКУМЕНТОВ = ("stock", "stock-moves", "chain", "cash_state",
                  "station-nsi", "station-catalog", "station-mrc")

# Что видел такт этого воркера: компания → (отпечаток источников, когда собирал).
_прошлый: dict[uuid.UUID, tuple[tuple, float]] = {}


async def отпечаток_источников(db: AsyncSession, company_id: uuid.UUID) -> tuple:
    """Число строк и последняя отметка времени в каждом источнике реестра.

    Источники — те, что читают адаптеры реестра (store_documents.ADAPTER_REGISTRY).
    Изменился отпечаток — пора пересобирать; нет — реестр и так верен.
    """
    строка = (await db.execute(text("""
        SELECT
          (SELECT count(*) || '/' || coalesce(max(received_at)::text, '')
             FROM edge_packets WHERE company_id = :c AND kind <> ALL(:без_документов)),
          (SELECT count(*) || '/' || coalesce(max(r.received_at)::text, '')
             FROM edge_packet_revisions r JOIN edge_packets p ON p.id = r.edge_packet_id
            WHERE r.company_id = :c AND p.kind <> ALL(:без_документов)),
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM data_entries WHERE company_id = :c),
          (SELECT count(*) || '/' || coalesce(max(received_at)::text, '')
             FROM store_cheques WHERE company_id = :c),
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM store_receipts WHERE company_id = :c),
          (SELECT count(*) || '/' || coalesce(max(created_at)::text, '')
             FROM store_receipt_stock_movements WHERE company_id = :c),
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM accounting_docs WHERE company_id = :c),
          (SELECT count(*) FROM accounting_source_links WHERE company_id = :c),
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM export_packets WHERE company_id = :c),
          -- не адаптер, но та же сверка: бух-надстройку везёт статус станции
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM store_doc_meta WHERE company_id = :c),
          -- каталог: по нему чеки и смены получают НДС и карантин
          (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '')
             FROM edge.item WHERE company_id = :c)
    """), {"c": company_id, "без_документов": list(БЕЗ_ДОКУМЕНТОВ)})).one()
    return tuple(строка)


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
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — одна станция не валит остальные
        await db.rollback()
        итог["detail"] += f", не записано: {exc!r}"
        log.warning("сверка документов станции %s: %s", station_id, итог["detail"])
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
        # Но молчать об этом нельзя: один конфликт останавливает пересборку
        # ВСЕГО реестра, и 22.08.2026 так вышло — девять дней документы станции
        # не попадали в центр. Прежняя отметка в edge_agents.payload не жила и
        # минуты (heartbeat переписывает payload целиком), поэтому — в лог.
        await db.rollback()
        итог["detail"] = f"реестр требует полной пересборки: {exc}"
        итог["conflict"] = True
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        return итог
    except Exception as exc:  # noqa: BLE001 — такт не должен умирать
        await db.rollback()
        итог["detail"] = f"реестр не собран: {exc!r}"
        log.warning("сверка документов компании %s: %s", company_id, итог["detail"])
        return итог

    for station_id in станции:
        итог["stations"][station_id] = await сверить_станцию(db, company_id, station_id)
    return итог


async def пора_сверять(db: AsyncSession, company_id: uuid.UUID) -> tuple | None:
    """Отпечаток источников, если реестр пора пересобрать; None — не пора."""
    отпечаток = await отпечаток_источников(db, company_id)
    прошлый = _прошлый.get(company_id)
    if прошлый and прошлый[0] == отпечаток and \
            time.monotonic() - прошлый[1] < НЕ_РЕЖЕ_ЧАСОВ * 3600:
        return None
    return отпечаток


async def tick() -> int:
    """Один проход по компаниям со станциями. Возвращает число сверенных."""
    сверено = 0
    async with async_session_factory() as db:
        компании = (await db.execute(
            select(EdgeAgent.company_id).distinct())).scalars().all()
    for cid in компании:
        # Своя сессия на компанию: сбой одной не отравляет сверку других.
        async with async_session_factory() as db:
            try:
                отпечаток = await пора_сверять(db, cid)
                if отпечаток is None:
                    continue
                начало = time.monotonic()
                итог = await сверить_компанию(db, cid)
                # Конфликт ревизий запоминаем как сверку: повторять его
                # каждые десять минут — минута работы впустую, он ждёт
                # человека или новых данных. Временный сбой (таймаут,
                # обрыв) не запоминаем — повторится на следующем такте.
                if итог["rebuilt"] or итог.get("conflict"):
                    _прошлый[cid] = (отпечаток, time.monotonic())
                сверено += 1
                # Длительность — в лог каждый раз: пересборка идёт по
                # всей компании, её цену надо видеть, а не угадывать.
                log.info("сверка документов %s за %.1f с: %s",
                         cid, time.monotonic() - начало, итог["detail"])
            except Exception:  # noqa: BLE001 — одна компания не валит такт
                await db.rollback()
                log.exception("сверка документов компании %s не удалась", cid)
    return сверено


async def run_forever() -> None:
    """Фоновый цикл — поднимается из lifespan приложения.

    Сверяет один воркер — ведущий: он берёт замок на отдельном соединении и
    держит, пока жив. Второй каждую границу такта пробует его взять и сверяет,
    только если ведущий умер. Память о прошлых сверках (_прошлый) у каждого
    воркера своя; при сверке по очереди каждое изменение пересобиралось бы
    дважды. Замок не через сессию: сессия после commit отдаёт соединение в пул,
    и сессионный замок оставался бы висеть на чужом соединении.
    """
    шаг = ТАКТ_МИНУТ * 60
    log.info("Сверка документов со станциями запущена (такт %d мин)", ТАКТ_МИНУТ)
    while True:
        try:
            async with engine.connect() as замок:
                ведущий = False
                while True:
                    await asyncio.sleep(шаг - time.time() % шаг)
                    if not ведущий:
                        ведущий = bool((await замок.execute(
                            text("SELECT pg_try_advisory_lock(:k)"), {"k": ЛОК})).scalar())
                        if ведущий:
                            log.info("Сверка документов: этот воркер ведущий")
                    else:
                        # Соединение живо — замок по-прежнему наш. Умерло —
                        # исключение, переподключаемся и пробуем заново.
                        await замок.execute(text("SELECT 1"))
                    await замок.commit()
                    if not ведущий:
                        continue
                    try:
                        await tick()
                    except Exception:  # noqa: BLE001 — сверка не критична для API
                        log.exception("Сбой такта сверки документов")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — соединение замка оборвалось
            log.exception("Сверка документов: соединение замка потеряно")
            await asyncio.sleep(60)
