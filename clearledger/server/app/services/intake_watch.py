"""Сторож свежести выгрузки: данные не пришли — надо сказать, а не ждать.

ЗАЧЕМ. Витрина ЭЗС приезжает ежедневным файлом, который кладёт человек: канал
«Витрина АСУиМ ЭЗС» работает в ручном режиме, расписания у него нет. 18 сентября
файл пришёл, 19 и 20 — нет, и об этом никто не узнал: экраны продолжали честно
считать «по последним данным», а люди читали позавчерашнюю картину как сегодняшнюю
(проверка 20.09.2026).

Расписание тут не поможет — файл не забирается, а приносится. Помогает обратная
проверка: раз в час смотрим, когда в последний раз приходили данные, и если тишина
дольше порога — оповещаем тех, кто подписан на категорию «данные».

Порог — полтора суток, а не сутки. Выгрузка приходит утром и накрывает позавчера,
поэтому сутки без файла — обычное дело в выходной; тревога на каждый выходной
приучает не читать оповещения вовсе.

Молчим, пока тревога не снята: повторное письмо каждый час про одно и то же
раздражает и теряется. Второй раз скажем, когда данные пойдут снова (и то один
раз), или когда отставание перевалит за неделю — это уже другой разговор.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import ChargePayment, ChargeSession, Company
from app.services import notify

log = logging.getLogger(__name__)

# Раз в час: чаще незачем — файл приходит раз в сутки, а тревога всё равно одна.
TICK_SECONDS = int(os.getenv("INTAKE_WATCH_TICK_SECONDS", "3600"))

# Сколько часов тишины считаем нормой. 36 = утренняя выгрузка за позавчера плюс
# запас на выходной.
ПОРОГ_ЧАСОВ = int(os.getenv("INTAKE_WATCH_HOURS", "36"))

# Вторая ступень: неделя без данных — это уже не «забыли положить файл».
ТРЕВОГА_ЧАСОВ = 24 * 7

_LOCK_NS = 4711
_LOCK_KEY = 23

# Что уже сказали по компании, чтобы не повторяться каждый час.
_сказано: dict[str, str] = {}


async def состояние(db: AsyncSession, company_id) -> dict[str, Any]:
    """Когда последний раз приходили данные и сколько прошло."""
    последняя = (await db.execute(
        select(func.max(ChargeSession.created_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    данные_по = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    сейчас = datetime.now(timezone.utc)
    if последняя is None:
        return {"everLoaded": False, "hours": None, "level": "unknown",
                "lastLoadAt": None, "dataThrough": None}
    if последняя.tzinfo is None:
        последняя = последняя.replace(tzinfo=timezone.utc)
    часов = (сейчас - последняя).total_seconds() / 3600
    уровень = ("ok" if часов < ПОРОГ_ЧАСОВ
               else "alarm" if часов >= ТРЕВОГА_ЧАСОВ else "late")
    return {
        "everLoaded": True,
        "hours": round(часов, 1),
        "level": уровень,
        "lastLoadAt": последняя.isoformat(),
        "dataThrough": данные_по.isoformat() if данные_по else None,
        "thresholdHours": ПОРОГ_ЧАСОВ,
    }


async def здоровье(db: AsyncSession, company_id) -> dict[str, Any]:
    """Состояние выгрузки для экрана: свежесть, пропавшие поля, потери.

    Три вопроса, на которые человек иначе отвечает запросом в базу: приходит ли
    файл, всё ли в нём осталось и всё ли доехало. Последние две проверки —
    по факту августа 2026: из выгрузки пропали название станции, адрес и номер
    поста, а платежей без сессии стало в двадцать раз больше.
    """
    s = await состояние(db, company_id)

    # Поля, которые перестали приходить: сравниваем последние 30 дней данных с
    # предыдущими 30. Пустое поле само по себе не беда — беда, когда оно БЫЛО.
    граница = (await db.execute(
        select(func.max(ChargeSession.started_at))
        .where(ChargeSession.company_id == company_id))).scalar()
    поля: list[dict[str, Any]] = []
    if граница is not None:
        было_с = граница - timedelta(days=60)
        было_по = граница - timedelta(days=30)
        проверяем = {
            "station_name": ("название станции", ChargeSession.station_name),
            "address": ("адрес", ChargeSession.address),
            "connector_no": ("номер поста", ChargeSession.connector_no),
            "connector_type": ("тип коннектора", ChargeSession.connector_type),
            "rfid": ("карта клиента", ChargeSession.rfid),
        }
        for код, (имя, колонка) in проверяем.items():
            было, стало = (await db.execute(select(
                func.count().filter(
                    (ChargeSession.started_at >= было_с)
                    & (ChargeSession.started_at < было_по)
                    & колонка.is_not(None)),
                func.count().filter(
                    (ChargeSession.started_at >= было_по) & колонка.is_not(None)),
            ).where(ChargeSession.company_id == company_id))).one()
            if (было or 0) > 100 and (стало or 0) == 0:
                # Когда именно перестало приходить — по последней непустой строке.
                последняя = (await db.execute(
                    select(func.max(ChargeSession.started_at))
                    .where(ChargeSession.company_id == company_id,
                           колонка.is_not(None)))).scalar()
                нет_у = (await db.execute(
                    select(func.count()).where(
                        ChargeSession.company_id == company_id,
                        колонка.is_(None),
                        ChargeSession.started_at > (последняя or было_по)))).scalar()
                поля.append({
                    "field": код, "label": имя,
                    "lastSeen": последняя.date().isoformat() if последняя else None,
                    "rowsWithout": int(нет_у or 0),
                })

    # Платежи, у которых нет своей сессии: деньги пришли, а сессия не доехала.
    #
    # Анти-джойном, а не коррелированным NOT EXISTS: на 179 тыс. платежей против
    # 190 тыс. сессий второй вариант не завершался за пять минут — Postgres
    # проверял каждую строку отдельным поиском.
    сирот, сумма = (await db.execute(text("""
        select count(*), coalesce(sum(p.amount), 0)
          from charge_payments p
          left join charge_sessions s on s.session_ext_id = p.session_ext_id
         where p.company_id = :cid and s.id is null
    """), {"cid": str(company_id)})).one()
    всего_пл = (await db.execute(
        select(func.count()).where(ChargePayment.company_id == company_id))).scalar()

    # Сессии без станции: связка по коду не нашла объект.
    без_станции = (await db.execute(
        select(func.count()).where(
            ChargeSession.company_id == company_id,
            ChargeSession.location_id.is_(None)))).scalar()

    return {
        **s,
        "lostFields": поля,
        "payments": {
            "total": int(всего_пл or 0),
            "orphans": int(сирот or 0),
            "orphanAmount": round(float(сумма or 0), 2),
        },
        "sessionsWithoutStation": int(без_станции or 0),
        "note": ("данные приходят файлом витрины: канал ведётся вручную, поэтому "
                 "тишину проверяем сами, а не ждём расписания"),
    }


def _текст(имя_компании: str, s: dict[str, Any]) -> str:
    дней = (s["hours"] or 0) / 24
    когда = (s["lastLoadAt"] or "")[:16].replace("T", " ")
    по = (s["dataThrough"] or "")[:10]
    хвост = f" Последние данные — по {по}." if по else ""
    if s["level"] == "alarm":
        return (f"{имя_компании}: выгрузка не приходит {дней:.0f} суток. "
                f"Последняя загрузка {когда}.{хвост} "
                "Экраны эксплуатации и продаж считают по старым данным.")
    return (f"{имя_компании}: выгрузка не приходила {s['hours']:.0f} ч "
            f"(последняя загрузка {когда}).{хвост} "
            "Пока файла нет, «сегодня» на экранах — это последний загруженный день.")


async def tick() -> int:
    """Один проход по компаниям. Возвращает число разосланных оповещений."""
    послано = 0
    async with async_session_factory() as db:
        # Замок: в кластере тик не должен идти дважды — люди получат два письма.
        взят = (await db.execute(
            text("SELECT pg_try_advisory_lock(:ns, :k)"),
            {"ns": _LOCK_NS, "k": _LOCK_KEY})).scalar()
        if not взят:
            return 0
        try:
            компании = (await db.execute(select(Company))).scalars().all()
            for c in компании:
                s = await состояние(db, c.id)
                if not s["everLoaded"]:
                    continue
                ключ = str(c.id)
                было = _сказано.get(ключ)
                if s["level"] == "ok":
                    # Данные пошли — снимаем тревогу и говорим об этом один раз.
                    if было:
                        _сказано.pop(ключ, None)
                        notify.dispatch_async(
                            c.id, "intake.resumed", who=None,
                            details=f"{c.name}: выгрузка снова приходит.")
                        послано += 1
                    continue
                if было == s["level"]:
                    continue
                _сказано[ключ] = s["level"]
                notify.dispatch_async(
                    c.id, "intake.stale", who=None, details=_текст(c.name, s))
                послано += 1
                log.warning("выгрузка отстаёт: %s — %s ч", c.name, s["hours"])
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:ns, :k)"),
                             {"ns": _LOCK_NS, "k": _LOCK_KEY})
    return послано


async def run_forever() -> None:
    """Цикл сторожа: запускается из lifespan рядом с прочими планировщиками."""
    # Первый проход — не сразу: при старте контейнера база может быть ещё занята
    # миграциями, а тревога «данных нет» в этот момент была бы ложной.
    await asyncio.sleep(120)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — тик не должен ронять приложение
            log.exception("сторож свежести: тик упал")
        await asyncio.sleep(TICK_SECONDS)
