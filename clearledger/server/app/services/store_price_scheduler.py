"""Исполнитель запланированных цен: применяет корзину, когда приходит её время.

Отложенное применение существует ради одной фразы товароведа — «пусть сменится к
открытию смены, а не сейчас». Если бы его исполнял открытый экран, обещание
держалось бы ровно до закрытия вкладки, и цена уехала бы на кассу когда угодно
или не уехала вовсе.

Устройство то же, что у планировщика каналов (`channel_scheduler`): фоновый цикл
из lifespan, advisory-lock от двойного применения в кластере, ошибка одной
компании не валит тик. Тик минутный: у цены значение имеет минута, к которой её
обещали сменить, — «через час» не должно превращаться в «через час и десять».
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.database import async_session_factory
from app.services import store_price_plans

log = logging.getLogger("clearledger.store.prices")

TICK_SECONDS = 60
LOCK_NAMESPACE = 0x9C1CE5


async def tick() -> int:
    """Применить всё, чьё время пришло. Возвращает число записанных цен."""
    применено = 0
    async with async_session_factory() as db:
        по_компаниям = await store_price_plans.созревшие(db)
        for cid, строки in по_компаниям.items():
            # Один исполнитель на компанию во всём кластере: иначе две реплики
            # запишут одну цену дважды и станция получит два одинаковых задания.
            got = await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                {"ns": LOCK_NAMESPACE, "key": cid.int % (2 ** 31)},
            )
            if not got:
                continue
            try:
                итог = await store_price_plans.исполнить(db, строки, cid, автор="")
                применено += итог["ok"]
                if итог["failed"]:
                    log.warning("Запланированные цены: %d не записаны (компания %s)",
                                итог["failed"], cid)
            except Exception:  # noqa: BLE001 — одна компания не валит тик
                log.exception("Сбой применения запланированных цен, компания %s", cid)
                await db.rollback()
    return применено


async def run_forever() -> None:
    """Фоновый цикл — поднимается из lifespan приложения."""
    log.info("Исполнитель запланированных цен запущен (тик %d с)", TICK_SECONDS)
    while True:
        try:
            n = await tick()
            if n:
                log.info("Применено запланированных цен: %d", n)
        except asyncio.CancelledError:
            log.info("Исполнитель запланированных цен остановлен")
            raise
        except Exception:  # noqa: BLE001 — цикл обязан пережить любую ошибку
            log.exception("Сбой тика запланированных цен")
        await asyncio.sleep(TICK_SECONDS)
