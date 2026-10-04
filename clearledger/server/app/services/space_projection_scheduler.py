"""Догон проекции справочников пространства в приложения.

Объект уезжает в приложение сразу при изменении (`space_projection.project_object`
из `locations_router`), и для станций этого достаточно: их правят поштучно и
руками. Остальные справочники так не ведут: контрагенты приезжают загрузкой из
учёта тысячами, оборудование — пачкой, люди меняются реже, но тоже не по одному.
Точечная отправка на каждую строку такой загрузки означала бы тысячи запросов в
соседний контейнер вместо одной пачки.

Поэтому здесь — редкий общий проход: раз в полчаса отправить приложениям всё, что
им положено. Он же догоняет то, что не прошло точечно, пока приложение было
недоступно, — до него единственным средством была кнопка администратора, то есть
человек, который должен вспомнить.

Устройство повторяет соседние планировщики: цикл из lifespan, advisory-lock от
двойного прохода в кластере, ошибка одной пары «компания — приложение» не валит
тик остальных.
"""
from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import App, AppCompanyLink
from app.services import space_projection

log = logging.getLogger(__name__)

# Полчаса: справочники меняются медленно, а проход отправляет их целиком.
# Чаще — лишний шум в соседнем контейнере, реже — заметная задержка людей и
# оборудования, заведённых пачкой.
TICK_SECONDS = int(os.getenv("SPACE_PROJECTION_TICK_SECONDS", "1800"))

_LOCK_NS = 4711
_LOCK_KEY = 21


async def tick() -> int:
    """Один проход: все связанные пары «компания → приложение». Вернёт число пар."""
    done = 0
    async with async_session_factory() as db:
        got = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
            {"ns": _LOCK_NS, "key": _LOCK_KEY},
        )).scalar()
        if not got:
            return 0

        # Пара «наша компания → его компания» и есть условие проекции: без неё
        # неясно, в чьё пространство отправлять. Код приложения берём из реестра.
        pairs = (await db.execute(
            select(AppCompanyLink.company_id, App.code)
            .join(App, App.id == AppCompanyLink.app_id),
        )).all()

        for company_id, app_code in pairs:
            if not app_code:
                continue
            try:
                await space_projection.project_all(db, company_id, app_code)
                done += 1
            except space_projection.ProjectionError as e:
                # Не настроено или сосед недоступен — это состояние, а не поломка:
                # следующий проход через полчаса попробует снова.
                log.info("Проекция для компании %s не прошла: %s", company_id, e)
            except Exception:  # noqa: BLE001 — одна пара не валит остальные
                log.exception("Сбой проекции для компании %s", company_id)
    return done


async def run_forever() -> None:
    """Фоновый цикл — поднимается из lifespan приложения."""
    log.info("Догон проекции пространства запущен (тик %d с)", TICK_SECONDS)
    while True:
        try:
            n = await tick()
            if n:
                log.info("Проекция отправлена парам «компания — приложение»: %d", n)
        except asyncio.CancelledError:
            log.info("Догон проекции пространства остановлен")
            raise
        except Exception:  # noqa: BLE001 — цикл обязан пережить любую ошибку
            log.exception("Сбой тика проекции пространства")
        await asyncio.sleep(TICK_SECONDS)
