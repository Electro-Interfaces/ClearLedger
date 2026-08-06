"""Утренний дайджест «Пульса»: эскалации приходят к человеку, а не ждут его.

«Пульс» устроен так, что руководитель должен зайти. Между «система знает» и
«человек узнал» — целый день: alert-карточка живёт до конца суток и умирает
непрочитанной, если в этот день было не до экрана.

Раз в сутки, в час, заданный компанией (`pulse_targets.digest_hour`, по умолчанию
9 утра по Москве), карточки экрана дня уходят письмом тем, у кого есть доступ к
продукту. Молчание — тоже результат: если вмешательства не требуется, письма нет.
Пустая рассылка «сегодня всё спокойно» приучает не открывать письма вообще.

Повтор в тот же день исключён отметкой в журнале (`pulse.digest`), а гонка
нескольких воркеров — тем же advisory-локом, что у планировщика каналов.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.database import async_session_factory
from app.services.email_service import send_notice

log = logging.getLogger("clearledger.pulse.digest")

TICK_SECONDS = 300           # проверяем раз в пять минут: час — грубая единица
DEFAULT_HOUR = 9             # утро по Москве, до начала разбора
TZ = ZoneInfo("Europe/Moscow")
LOCK_KEY = 0x50554C53        # 'PULS' — свой лок, чужие прогоны не блокируем


async def _companies_due(db) -> list[tuple[str, str]]:
    """Компании, которым сейчас пора: час совпал и сегодня ещё не отправляли."""
    hour_now = datetime.now(TZ).hour
    rows = (await db.execute(text("""
        select c.id::text as cid, c.name,
               coalesce((select value from pulse_targets t
                         where t.company_id = c.id and t.key = 'digest_hour'), :def) as hour
        from companies c
        where not exists (
            select 1 from audit_events a
            where a.company_id = c.id and a.action = 'pulse.digest'
              and a.timestamp >= date_trunc('day', now())
        )
    """), {"def": DEFAULT_HOUR})).all()
    # Час -1 — доставка выключена компанией.
    return [(r.cid, r.name) for r in rows
            if int(r.hour) >= 0 and int(r.hour) == hour_now]


async def _recipients(db, cid: str) -> list[str]:
    """Кому слать: у кого есть доступ к «Пульсу».

    Набор модулей разбирает `auth.resolve_member_modules` — та же функция, что
    решает доступ на входе в продукт. Свой SQL здесь означал бы второй ответ на
    вопрос «кому можно», и однажды они разошлись бы.

    Спящие учётки исключены: письмо в мёртвый ящик — это не доставка.
    """
    from sqlalchemy import select

    from app.auth import resolve_member_modules
    from app.models import User, UserCompany

    rows = (await db.execute(
        select(UserCompany, User)
        .join(User, User.id == UserCompany.user_id)
        # Признака «отключён» у пользователя нет — членство и есть допуск;
        # отсекаем только тех, кто месяц не заходил: письмо в мёртвый ящик
        # доставкой не считается.
        .where(UserCompany.company_id == uuid.UUID(cid),
               User.last_seen_at > datetime.now(timezone.utc) - timedelta(days=30))
    )).all()
    out: list[str] = []
    for member, user in rows:
        mods = await resolve_member_modules(member, db)
        if mods is None or "pulse" in mods or any(str(m).startswith("pulse:") for m in mods):
            out.append(user.email)
    return out


def _render(company: str, cards: list[dict], as_of: str | None) -> tuple[str, str]:
    """Письмо — тот же текст, что на экране: одна карточка = один абзац."""
    alerts = sum(1 for c in cards if c["level"] == "alert")
    subject = (f"{company}: {len(cards)} на экране дня"
               + (f", из них тревожных {alerts}" if alerts else ""))
    lines = [f"Экран дня, {datetime.now(TZ):%d.%m.%Y}", ""]
    for c in cards:
        mark = "!" if c["level"] == "alert" else "·"
        lines.append(f"{mark} {c['title']}")
        lines.append(f"  {c['insight']}")
        lines.append("")
    if as_of:
        lines.append(f"Данные сети на {as_of[:10]}.")
    lines.append("Открыть «Пульс»: раздел «Экран дня» в пространстве.")
    return subject, "\n".join(lines)


async def run_once() -> int:
    """Один проход по компаниям. Возвращает число отправленных писем."""
    sent = 0
    async with async_session_factory() as db:
        if not (await db.execute(text(
            "select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar_one():
            return 0
        try:
            for cid, name in await _companies_due(db):
                # Импорт здесь: роутер тянет за собой пол-приложения, а модуль
                # должен подниматься даже когда «Пульс» в стеке не включён.
                # Считаем ровно тот же экран, что видит человек, — второй набор
                # правил для писем разошёлся бы с экраном за месяц.
                from app.routers.pulse_router import pulse_day_data

                day = await pulse_day_data(db, cid)
                cards, as_of = day["cards"], day["as_of"]
                if not cards:
                    continue        # спокойный день — письма нет
                emails = await _recipients(db, cid)
                if not emails:
                    continue
                subject, body = _render(name, cards, as_of)
                await send_notice(emails, subject, body)
                await db.execute(text("""
                    insert into audit_events (id, company_id, user_id, user_name,
                                              action, details, timestamp)
                    values (gen_random_uuid(), :cid, 'system', 'Пульс',
                            'pulse.digest', :det, now())
                """), {"cid": cid, "det": f"карточек: {len(cards)}, адресатов: {len(emails)}"})
                await db.commit()
                sent += 1
                log.info("дайджест «Пульса» отправлен: %s, карточек %d, адресатов %d",
                         name, len(cards), len(emails))
        finally:
            await db.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await db.commit()
    return sent


async def run_forever() -> None:
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:                      # noqa: BLE001
            log.warning("дайджест «Пульса» не отправлен: %s", e)
        await asyncio.sleep(TICK_SECONDS)
