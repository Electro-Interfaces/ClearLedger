"""Автозапуск каналов приёма по расписанию (`Channel.schedule`).

Поле `schedule` в модели было с самого начала, но его никто не исполнял: каналы
шли только по кнопке в кокпите. Так у ГИГ и накопился пробел в двенадцать дней —
сеть работала, смены закрывались, а система об этом не знала, пока человек не
нажмёт «Обновить». Этот модуль закрывает разрыв между «расписание настроено» и
«расписание работает».

Поддерживаются режимы:

* `{"mode": "daily", "at": "03:00", "tz": "Europe/Moscow"}` — раз в сутки в
  указанное местное время. Часовой пояс обязателен по смыслу: сервер живёт в UTC,
  а «в три ночи» бухгалтерия понимает по Москве.
* `{"mode": "interval", "interval_minutes": 60}` — раз в N минут.
* `{"mode": "manual"}` (и всё незнакомое) — не запускать.

Окно загрузки берётся с запасом назад (`lookback_days`, по умолчанию 3 дня):
смена может закрыться позже даты открытия, а ночной прогон должен подобрать и её.
Повторы безопасны — приём дедуплицирует по натуральному ключу смены/ТТН.

Защита от двойного запуска — Postgres advisory lock: даже если поднято несколько
воркеров или инстансов, прогон канала стартует ровно один раз.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Channel, ChannelSyncLog

log = logging.getLogger("clearledger.scheduler")

# Как часто просыпаемся сверить расписания.
TICK_SECONDS = 60
# Ключ пространства advisory-локов планировщика (произвольная константа).
LOCK_NAMESPACE = 0x1ED9E12
# Сколько дней назад перезапрашивать источник в каждом прогоне.
DEFAULT_LOOKBACK_DAYS = 3


def _tz(schedule: dict) -> ZoneInfo:
    try:
        return ZoneInfo(str(schedule.get("tz") or "Europe/Moscow"))
    except Exception:  # noqa: BLE001 — кривая зона не должна ронять планировщик
        return ZoneInfo("Europe/Moscow")


def _due(schedule: dict, last_run: datetime | None, now_utc: datetime) -> bool:
    """Пора ли запускать канал прямо сейчас."""
    mode = str(schedule.get("mode") or "manual").lower()

    if mode == "interval":
        minutes = int(schedule.get("interval_minutes") or 0)
        if minutes <= 0:
            return False
        return last_run is None or (now_utc - last_run) >= timedelta(minutes=minutes)

    if mode not in ("daily", "cron"):
        return False

    tz = _tz(schedule)
    at = str(schedule.get("at") or schedule.get("time") or "03:00")
    try:
        hh, mm = (int(x) for x in at.split(":")[:2])
    except ValueError:
        hh, mm = 3, 0

    local_now = now_utc.astimezone(tz)
    planned = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if local_now < planned:
        return False  # сегодняшнее время ещё не наступило
    if last_run is None:
        return True
    # Уже запускались после сегодняшней плановой точки — второй раз не идём.
    return last_run.astimezone(tz) < planned


async def _last_run(db, channel_id: uuid.UUID) -> datetime | None:
    """Последний старт прогона канала (любого — ручного или планового)."""
    return await db.scalar(
        select(ChannelSyncLog.started_at)
        .where(ChannelSyncLog.channel_id == channel_id)
        .order_by(ChannelSyncLog.started_at.desc())
        .limit(1)
    )


async def _has_running(db, channel_id: uuid.UUID) -> bool:
    return bool(await db.scalar(
        select(ChannelSyncLog.id)
        .where(ChannelSyncLog.channel_id == channel_id,
               ChannelSyncLog.status == "running")
        .limit(1)
    ))


async def _launch(db, ch: Channel, lookback_days: int) -> None:
    """Стартовать прогон канала тем же путём, что и кнопка в кокпите."""
    from app.routers.channels_router import _run_channel_background

    today = datetime.now(_tz(ch.schedule or {})).date()
    df = (today - timedelta(days=max(lookback_days, 0))).isoformat()
    dt = today.isoformat()

    entry = ChannelSyncLog(
        channel_id=ch.id, status="running", finished_at=None,
        date_from=df, date_to=dt,
        events=[{"level": "info", "event": "run",
                 "message": f"автозапуск по расписанию ({df}…{dt})"}],
    )
    db.add(entry)
    await db.flush()
    log_id = entry.id
    await db.commit()

    log.info("Автозапуск канала «%s» за %s…%s", ch.name, df, dt)
    asyncio.create_task(_run_channel_background(ch.id, df, dt, log_id))


async def tick() -> int:
    """Один проход по расписаниям. Возвращает число запущенных каналов."""
    started = 0
    now_utc = datetime.now(timezone.utc)

    async with async_session_factory() as db:
        channels = (await db.execute(
            select(Channel).where(Channel.status == "active")
        )).scalars().all()

        for ch in channels:
            schedule = ch.schedule or {}
            if str(schedule.get("mode") or "manual").lower() not in ("daily", "cron", "interval"):
                continue
            if await _has_running(db, ch.id):
                continue  # предыдущий прогон ещё идёт — не наслаиваем
            if not _due(schedule, await _last_run(db, ch.id), now_utc):
                continue

            # Один запуск на весь кластер: лок держится до конца транзакции,
            # а её мы завершаем сразу после создания лог-записи «running» —
            # дальше повторный старт отсекается проверкой _has_running.
            got = await db.scalar(
                text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                {"ns": LOCK_NAMESPACE, "key": ch.id.int % (2 ** 31)},
            )
            if not got:
                continue

            try:
                await _launch(db, ch, int(schedule.get("lookback_days")
                                          or DEFAULT_LOOKBACK_DAYS))
                started += 1
            except Exception:  # noqa: BLE001 — один канал не валит планировщик
                log.exception("Автозапуск канала «%s» не удался", ch.name)
                await db.rollback()

    return started


async def run_forever() -> None:
    """Фоновый цикл планировщика — поднимается из lifespan приложения."""
    log.info("Планировщик каналов запущен (тик %d с)", TICK_SECONDS)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            log.info("Планировщик каналов остановлен")
            raise
        except Exception:  # noqa: BLE001 — цикл обязан пережить любую ошибку
            log.exception("Сбой тика планировщика")
        await asyncio.sleep(TICK_SECONDS)
