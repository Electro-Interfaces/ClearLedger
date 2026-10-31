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

ПОЧЕМУ ПЕРЕСБОРКА УШЛА С ПУТИ ЗАПРОСА (26.10.2026). Пересборка реестра на всю
компанию — это 18 467 проекций из 8 152 ревизий пакетов, и на gig она не
укладывалась в 90 секунд. Агент станции ждал её внутри `GET /api/edge/downlink`,
уходил по своему таймауту, корутина отменялась, `rebuilt_at` не обновлялся — и
следующий стук через минуту начинал всё заново. Самоподдерживающийся цикл: за
сутки 1302 обрыва 499, из них 785 с временем ответа ≥ 89 с, успешных downlink
около 5 %. Станции просто не получали задания.

Заявленная выше гарантия «ошибки не поднимаются наверх, сверка не имеет права
уронить обмен» этого не покрывала: отмена клиента приходит как `CancelledError`,
а он не `Exception` — ни один `except` здесь его не ловит.

Поэтому пересборка идёт ОТДЕЛЬНОЙ задачей со своей сессией, под неблокирующим
advisory-замком на компанию: разрыв соединения со станцией её не рвёт,
параллельные стуки не плодят копии, а запрос станции получает задания сразу.
Быстрые шаги (снимок заголовков, статусы) остаются на пути запроса — они
работают с уже собранным реестром и занимают доли секунды.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreDocumentProjection, StoreDocumentProjectionState
from app.services.store_document_snapshot import queue_onec_document_snapshot
from app.services.document_status_downlink import queue_document_status
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
    """Поставить станции свежий снимок заголовков; реестр освежить отдельно.

    Возвращает, что сделано, — чтобы это было видно в состоянии станции, а не
    только в логе. Ошибки не поднимаются наверх: сверка не имеет права
    уронить обмен, из-за которого станция теряет задания и пакеты. Долгая
    пересборка реестра здесь НЕ выполняется — см. заголовок модуля.
    """
    итог = {"rebuilt": False, "snapshot": False, "headers": 0, "detail": ""}
    порог = datetime.now(timezone.utc) - timedelta(minutes=СВЕЖЕСТЬ_МИНУТ)
    собран = (await db.execute(select(
        StoreDocumentProjectionState.last_successful_rebuild_at,
    ).where(StoreDocumentProjectionState.company_id == company_id))).scalar()
    if собран is None:  # первый запуск после добавления метки
        собран = (await db.execute(select(func.max(StoreDocumentProjection.rebuilt_at)).where(
            StoreDocumentProjection.company_id == company_id))).scalar()
    if собран is None or собран <= порог:
        # Реестр устарел — пересборку ведёт отдельная задача, запрос станции её
        # не ждёт. Снимок и статусы ниже пойдут по тому реестру, что есть:
        # отдать станции прошлый снимок на минуту раньше лучше, чем не отдать
        # ничего, потому что она ушла по таймауту.
        запустить_пересборку(company_id, station_id)
        итог["detail"] = "пересборка реестра запущена отдельно"
    else:
        итог["detail"] = "реестр свежий"

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

    # Этап B: бух-статус собственных документов станции — обратно на станцию.
    try:
        n = await queue_document_status(db, company_id, station_id)
        итог["statuses"] = n
        итог["detail"] += f", статусов вниз: {n}"
    except Exception as exc:  # noqa: BLE001 — статус не важнее обмена
        await db.rollback()
        итог["detail"] += f", статусы не поставлены: {exc!r}"
        log.warning("статусы документов станции %s: %s", station_id, итог["detail"])
    return итог


# Ссылки на живые задачи: без них сборщик мусора вправе выбросить задачу,
# на которую никто не смотрит, и пересборка оборвётся на середине.
_живые: set[asyncio.Task] = set()


def запустить_пересборку(company_id: uuid.UUID, station_id: int) -> None:
    """Отправить пересборку реестра в отдельную задачу и сразу вернуться."""
    задача = asyncio.create_task(_пересобрать(company_id, station_id))
    _живые.add(задача)
    задача.add_done_callback(_живые.discard)


async def _пересобрать(company_id: uuid.UUID, station_id: int) -> None:
    """Пересобрать реестр компании в своей сессии, один раз на компанию.

    Транзакционный try-lock совпадает с lock ручной пересборки. Занятую
    компанию пропускаем без очереди. Сборка только flush-ит; commit делается
    здесь после полного успеха. При отказе транзакция и lock откатываются.
    """
    from app.database import async_session_factory

    # Тот же ключ и транзакция, что у ручной пересборки. Commit/rollback
    # освобождает lock до возврата соединения в пул, в том числе при ошибке.
    scope_key = f"store-documents:{company_id}"
    async with async_session_factory() as db:
        взят = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope_key, 0))"),
            {"scope_key": scope_key})).scalar()
        if not взят:
            log.info("пересборка реестра компании %s уже идёт — пропускаю", company_id)
            return
        try:
            реестр = await rebuild_store_document_projection(db, company_id)
            await db.commit()
            log.info("реестр документов компании %s пересобран: %s",
                     company_id, реестр.get("records"))
        except ProjectionRevisionConflict as exc:
            # Правила разбора изменились: собрать начисто — отдельное решение
            # человека, молча переписывать историю обмен не должен.
            #
            # Но молчать об этом тоже нельзя. Один конфликт останавливает
            # пересборку ВСЕГО реестра, и 22.08.2026 так вышло: приёмку
            # поправили, ревизия не выросла, и девять дней документы станции не
            # попадали в центр — а знал об этом только лог. Записываем отказ в
            # состояние станции, чтобы он был виден там же, где её работа.
            await db.rollback()
            detail = f"реестр требует полной пересборки: {exc}"
            log.warning("сверка документов станции %s: %s", station_id, detail)
            try:
                await db.execute(text("""
                    UPDATE edge_agents
                       SET payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object(
                             'projection_conflict', jsonb_build_object(
                                 'at', now()::text, 'detail', :detail))
                     WHERE company_id = :cid AND station_id = :st
                """), {"cid": company_id, "st": station_id, "detail": detail})
                await db.commit()
            except Exception:  # noqa: BLE001 — отметка не важнее обмена
                await db.rollback()
        except Exception as exc:  # noqa: BLE001 — обмен важнее сверки
            await db.rollback()
            log.warning("реестр документов компании %s не собран: %r", company_id, exc)
        except asyncio.CancelledError:
            await db.rollback()
            raise
