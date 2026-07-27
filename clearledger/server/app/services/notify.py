"""Доставка оповещений о событиях пространства — в чат и на почту.

Каналы — те, что у пространства уже есть: служебная комната чата «Оповещения» (пишет
сервисный аккаунт Matrix) и письмо. Внешних сервисов рассылки нет: сообщение должно
приходить туда, где человек и так работает.

Как устроено: события уже пишутся в журнал через `audit.log_audit`, поэтому подписка
навешивается ровно там — отдельного генератора событий не появляется. Категорию считает
`notify_catalog.category_for`, состав подписок хранит `NotificationRule`.

ponytail: доставка — fire-and-forget задача со своей сессией (`dispatch_async`). Оповещение
не должно ни задерживать ответ API, ни ронять запрос, если Synapse или SMTP недоступны.
Ценой этого теряется гарантия доставки: упавшую отправку никто не повторит. Нужна
гарантия — таблица-исходящая (`outbox`) и фоновый разборщик, механизм для этого уже есть
в `channel_scheduler`.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notify_catalog import CATEGORIES, category_for, label_of
from app.models import (
    Company, MatrixGroupRoom, NotificationRule, User, UserCompany,
)
from app.services import email_service
from app.services import matrix_admin as ma
from app.services.matrix_chat import ensure_matrix_account

logger = logging.getLogger("clearledger.notify")

ALERTS_CHANNEL_TITLE = "Оповещения"


# ---------------------------------------------------------------------------
# Подписки
# ---------------------------------------------------------------------------
async def rules_for(db: AsyncSession, company_id: uuid.UUID) -> list[NotificationRule]:
    """Подписки компании. Отсутствующие категории досоздаются дефолтами каталога —
    иначе интерфейс показывал бы пустой экран, пока кто-нибудь не нажмёт «сохранить»."""
    rows = (await db.execute(select(NotificationRule).where(
        NotificationRule.company_id == company_id))).scalars().all()
    have = {r.category for r in rows}
    created = False
    for c in CATEGORIES:
        if c.code not in have:
            db.add(NotificationRule(company_id=company_id, category=c.code,
                                    enabled=c.default_on, via_chat=True, via_email=False))
            created = True
    if created:
        await db.commit()
        rows = (await db.execute(select(NotificationRule).where(
            NotificationRule.company_id == company_id))).scalars().all()
    order = {c.code: i for i, c in enumerate(CATEGORIES)}
    return sorted(rows, key=lambda r: order.get(r.category, 99))


async def _recipients(
    db: AsyncSession, company_id: uuid.UUID, rule: NotificationRule,
) -> list[User]:
    """Кому доставлять: перечисленные участники или все администраторы организации.

    Дефолт «администраторы» намеренно динамический: список людей в правиле пришлось бы
    поддерживать руками, и он устаревал бы при каждой смене состава.
    """
    q = (select(User).join(UserCompany, UserCompany.user_id == User.id)
         .where(UserCompany.company_id == company_id))
    ids = [str(x) for x in (rule.recipients or []) if x]
    if ids:
        try:
            q = q.where(User.id.in_([uuid.UUID(i) for i in ids]))
        except ValueError:
            logger.warning("Оповещения: в правиле %s нерасшифруемый получатель", rule.id)
            return []
    else:
        q = q.where(UserCompany.role == "admin")
    return list((await db.execute(q)).scalars().all())


# ---------------------------------------------------------------------------
# Канал «чат»: служебная комната пространства
# ---------------------------------------------------------------------------
async def ensure_alerts_room(
    db: AsyncSession, company_id: uuid.UUID, members: list[User],
) -> str | None:
    """Комната «Оповещения» компании: одна, идемпотентно, состав досыпается.

    Владелец комнаты — первый из получателей (кто-то должен быть с PL100), поэтому без
    получателей канал не создаём: писать было бы некому.
    """
    if not members:
        return None
    room = (await db.execute(select(MatrixGroupRoom).where(
        MatrixGroupRoom.company_id == company_id,
        MatrixGroupRoom.title == ALERTS_CHANNEL_TITLE))).scalar_one_or_none()
    if room is None:
        # Импорт здесь: matrix_chat тянет notify только в тестах, кольцо не нужно.
        from app.services.matrix_chat import create_group_room
        created = await create_group_room(
            db, company_id, members[0], ALERTS_CHANNEL_TITLE,
            [m.id for m in members[1:]], is_public=False)
        return created["roomId"]

    joined: set[str] = set()
    try:
        joined = set(await ma.get_joined_members(room.room_id))
    except Exception:  # noqa: BLE001 — комната недоступна: пишем всё равно, вход досыпем позже
        pass
    for person in members:
        mxid = await ensure_matrix_account(db, person)
        if mxid not in joined:
            try:
                await ma.force_join(room.room_id, mxid)
            except Exception:  # noqa: BLE001 — один невошедший не должен рвать доставку
                logger.warning("Оповещения: не удалось ввести %s в комнату", mxid)
    return room.room_id


# ---------------------------------------------------------------------------
# Доставка
# ---------------------------------------------------------------------------
def _text(company_name: str, category: str, action: str, who: str | None,
          details: str | None) -> str:
    head = f"{label_of(category)} · {company_name}"
    body = f"{action}"
    if who:
        body += f" — {who}"
    if details:
        body += f"\n{details}"
    return f"{head}\n{body}"


async def dispatch(
    db: AsyncSession, company_id: uuid.UUID, action: str,
    who: str | None = None, details: str | None = None,
) -> dict[str, Any]:
    """Разослать оповещение о событии по подпискам компании.

    Возвращает, что реально сделано — этим же путём работает кнопка «Проверить доставку»,
    поэтому результат нужен вызывающему, а не только логу.
    """
    category = category_for(action)
    rule = (await db.execute(select(NotificationRule).where(
        NotificationRule.company_id == company_id,
        NotificationRule.category == category))).scalar_one_or_none()
    if rule is None or not rule.enabled or not (rule.via_chat or rule.via_email):
        return {"category": category, "skipped": True}

    company = await db.get(Company, company_id)
    company_name = (company.short_name or company.name) if company else "организация"
    people = await _recipients(db, company_id, rule)
    if not people:
        return {"category": category, "skipped": True, "reason": "нет получателей"}

    text = _text(company_name, category, action, who, details)
    out: dict[str, Any] = {"category": category, "recipients": len(people)}

    if rule.via_chat:
        try:
            room_id = await ensure_alerts_room(db, company_id, people)
            if room_id:
                await ma.send_text(room_id, text)
                out["chat"] = True
        except Exception as e:  # noqa: BLE001 — Synapse может быть выключен в этом стеке
            logger.warning("Оповещение в чат не ушло: %s", e)
            out["chat"] = False

    if rule.via_email:
        emails = [p.email for p in people if p.email]
        try:
            out["email"] = await email_service.send_notice(
                emails, f"{label_of(category)} — {company_name}", text)
        except Exception as e:  # noqa: BLE001 — SMTP вне нашего контроля
            logger.warning("Оповещение письмом не ушло: %s", e)
            out["email"] = False

    return out


def dispatch_async(company_id, action: str, who: str | None = None,
                   details: str | None = None) -> None:
    """Поставить доставку в фон: своя сессия, ошибки только в лог.

    Вызывается из `log_audit`, то есть внутри чужой транзакции — поэтому ни сессию
    вызывающего не занимаем, ни ответ API не задерживаем.
    """
    async def _run() -> None:
        from app.database import async_session_factory
        try:
            async with async_session_factory() as session:
                await dispatch(session, company_id, action, who, details)
        except Exception as e:  # noqa: BLE001 — оповещение не должно ломать основной поток
            logger.warning("Доставка оповещения сорвалась (%s): %s", action, e)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        # Нет цикла событий (миграции, CLI-скрипты) — оповещать некому и незачем.
        pass
