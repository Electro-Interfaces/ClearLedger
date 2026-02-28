"""Background scheduler для автоматической синхронизации с 1С.

Каждые 60 секунд проверяет active-подключения, запускает sync если пора.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.models import OneCConnection
from app.services.onec.sync_service import sync_full
from app.services.onec.file_exchange import check_feedback
from app.services.onec.odata_client import ODataConnectionError

logger = logging.getLogger("onec.scheduler")

CHECK_INTERVAL = 60  # секунды между проверками


async def onec_sync_loop() -> None:
    """Основной цикл: проверяет active connections, запускает sync по расписанию."""
    logger.info("1С scheduler запущен (интервал проверки: %ds)", CHECK_INTERVAL)

    while True:
        try:
            await _check_and_sync()
        except Exception as e:
            logger.error("Ошибка scheduler: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)


async def _check_and_sync() -> None:
    """Проверяет все активные подключения."""
    async with async_session() as db:
        result = await db.execute(
            select(OneCConnection).where(OneCConnection.status == "active")
        )
        connections = list(result.scalars().all())

    if not connections:
        return

    now = datetime.now(timezone.utc)

    for conn in connections:
        try:
            # Проверяем интервал
            if conn.last_sync_at:
                elapsed = (now - conn.last_sync_at).total_seconds()
                if elapsed < conn.sync_interval_sec:
                    continue

            logger.info("Автосинхронизация: %s (company=%s)", conn.name, conn.company_id)
            await sync_full(conn.id)

            # Проверяем feedback от файлового обмена
            if conn.exchange_path:
                await check_feedback(conn)

        except ODataConnectionError as e:
            logger.warning("1С недоступна (%s): %s. Пропускаем до следующего цикла.", conn.name, e)
        except Exception as e:
            logger.error("Ошибка автосинхронизации %s: %s", conn.name, e)
