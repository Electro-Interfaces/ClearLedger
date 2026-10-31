"""Регулярный опрос почтовых ящиков (docs/MAIL.md).

Пока почту забирают кнопкой, коннектор — не канал, а инструмент: письма приходят
тогда, когда о них вспомнили. Здесь один цикл на весь контейнер: раз в минуту
смотрит, каким ящикам пора по их собственному интервалу, и опрашивает только их.

Один цикл, а не задача на ящик: ящиков десятки, интервалы у них разные, а работа
короткая — плодить задачи ради ожидания незачем.
"""
from __future__ import annotations

import asyncio
import logging

from app.database import async_session_factory
from app.services import calendar_replies
from app.services.mail_intake import poll_due

logger = logging.getLogger("clearledger.mail")

# Как часто смотрим, кому пора. Минимальный интервал ящика — минута, чаще проверять
# нечего: почтовые серверы этого и не любят.
TICK_SECONDS = 60


async def run_forever() -> None:
    # Небольшая пауза на старте: при развёртывании база ещё может доезжать
    # миграциями, а опрос ей не поможет.
    await asyncio.sleep(30)
    while True:
        try:
            async with async_session_factory() as db:
                res = await poll_due(db)
                if res.get("polled"):
                    logger.info("почта: опрошено ящиков %s", res["polled"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — цикл не должен умирать от одной ошибки
            logger.warning("опрос почты не выполнен: %s", e)
        # Ответы на приглашения — свой ящик и своя ошибка: сбой одного опроса
        # не должен останавливать другой.
        try:
            async with async_session_factory() as db:
                n = await calendar_replies.poll(db)
                if n:
                    logger.info("почта: ответов на приглашения %s", n)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("ящик ответов на приглашения не опрошен: %s", e)
        await asyncio.sleep(TICK_SECONDS)
