"""Доставка оповещений о событиях пространства — в чат и на почту.

Каналы — те, что у пространства уже есть: служебный канал чата «Оповещения» (пишет
«Секретарь») и письмо. Внешних сервисов рассылки нет: сообщение должно
приходить туда, где человек и так работает.

Как устроено: события уже пишутся в журнал через `audit.log_audit`, поэтому подписка
навешивается ровно там — отдельного генератора событий не появляется. Категорию считает
`notify_catalog.category_for`, состав подписок хранит `NotificationRule`.

ponytail: доставка — fire-and-forget задача со своей сессией (`dispatch_async`). Оповещение
не должно ни задерживать ответ API, ни ронять запрос, если SMTP недоступен.
Ценой этого теряется гарантия доставки: упавшую отправку никто не повторит. Нужна
гарантия — таблица-исходящая (`outbox`) и фоновый разборщик, механизм для этого уже есть
в `channel_scheduler`.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notify_catalog import CATEGORIES, action_label, category_for, label_of
from app.models import Company, NotificationRule, User, UserCompany
from app.services import email_service

logger = logging.getLogger("clearledger.notify")

ALERTS_CHANNEL_TITLE = "Оповещения"


# ---------------------------------------------------------------------------
# Личное сообщение человеку
# ---------------------------------------------------------------------------
SECRETARY_EMAIL = "secretary@space.local"
SECRETARY_NAME = "Секретарь"


async def _admins_only(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """Политика пространства для системных оповещений и Секретаря."""
    company = await db.get(Company, company_id)
    return bool(company and (company.customization or {}).get(
        "system_notifications_admin_only") is True)


async def _secretary(db: AsyncSession, company_id: uuid.UUID) -> User:
    """Служебный участник, от чьего имени приходит личное напоминание.

    Заводится лениво и один раз, тем же приёмом, что «Процесс» в
    `services/errands.py`: пароль заведомо невалидный, войти этой учёткой
    нельзя. Отправитель нужен затем, что личное сообщение приходит в обычную
    комнату чата — а у сообщения должен быть автор, иначе в ленте оно выглядит
    сбоем, а не напоминанием.
    """
    import secrets

    user = (await db.execute(select(User).where(
        User.email == SECRETARY_EMAIL))).scalar_one_or_none()
    if user is None:
        user = User(email=SECRETARY_EMAIL, name=SECRETARY_NAME, role="user",
                    password_hash=f"!secretary-{secrets.token_hex(16)}")
        db.add(user)
        await db.flush()
    member = await db.get(UserCompany, (user.id, company_id))
    if member is None:
        db.add(UserCompany(user_id=user.id, company_id=company_id, role="user"))
        await db.flush()
    return user


async def notify_person(db: AsyncSession, company_id: uuid.UUID, user: User,
                        text: str, *, edit_message_id: uuid.UUID | None = None,
                        ttl: int | None = None,
                        urgency: str = "normal",
                        room_kind: str | None = None,
                        event_category: str | None = None) -> uuid.UUID | None:
    """Сообщение лично человеку — мимо подписок компании.

    `dispatch` рассылает по `NotificationRule` в общую комнату «Оповещения», и
    получателями там по умолчанию стоят администраторы. Личное напоминание
    администратору не адресуется никогда, поэтому маршрут свой, а транспорт —
    тот же чат пространства: счётчик непрочитанного, «без звука» и web-push у
    него уже есть, и второй такой механизм начал бы расходиться с первым.

    `edit_message_id` — править сказанное, а не говорить снова. Сводка окна
    дописывается в то же сообщение: новое на каждый повод превращает личную
    комнату в свалку, и напоминание тонет в ней ровно так же, как тонет
    напоминание в ленте Slack. Пропавшее сообщение (комнату почистили) не
    считается ошибкой — пишем новое.

    `room_kind=NOTICES_ROOM_KIND` — не в беседу с Секретарём, а в личный канал
    «Уведомления»: человек сам попросил держать поручения отдельно от напоминаний.

    Возвращает идентификатор сообщения: он и есть то, что правят в следующий
    раз. `None` — доставка не состоялась.
    """
    from app.models import ChatMessage, ChatParticipant, ChatRoom

    if await _admins_only(db, company_id) and not user.is_superadmin:
        company = await db.get(Company, company_id)
        # Только адресные события ТП с проверенными назначениями; остальные
        # системные сообщения сохраняют общую политику пространства.
        tp_allowed = (event_category == "tech_connection" and company is not None
                      and (company.customization or {}).get("tp_notifications_to_assignees") is True)
        if not tp_allowed:
            return None

    secretary = await _secretary(db, company_id)
    # Одна комната на пару «человек — Секретарь»: искать её по участникам, а не
    # по имени, иначе переименование комнаты заводит вторую.
    mine = select(ChatParticipant.room_id).where(ChatParticipant.user_id == user.id)
    room = (await db.execute(
        select(ChatRoom).where(
            ChatRoom.company_id == company_id,
            *((ChatRoom.type == "channel", ChatRoom.kind == room_kind,
               ChatRoom.is_active.is_(True)) if room_kind
              else (ChatRoom.type == "direct",)),
            ChatRoom.id.in_(mine),
            ChatRoom.id.in_(select(ChatParticipant.room_id).where(
                ChatParticipant.user_id == secretary.id))).limit(1))).scalar_one_or_none()
    if room is None:
        # Канал, а не беседа: писать в «Уведомления» некому, отвечает человек в
        # самой задаче. Владелец — Секретарь, поэтому поле ввода у человека закрыто.
        room = ChatRoom(company_id=company_id, type="channel" if room_kind else "direct",
                        kind=room_kind, name=NOTICES_ROOM_TITLE if room_kind else None,
                        created_by=secretary.id)
        db.add(room)
        await db.flush()
        db.add_all([
            ChatParticipant(room_id=room.id, user_id=user.id),
            ChatParticipant(room_id=room.id, user_id=secretary.id,
                            role="owner" if room_kind else "member"),
        ])
        await db.flush()

    message = None
    if edit_message_id is not None:
        message = await db.get(ChatMessage, edit_message_id)
        if message is not None and (message.room_id != room.id
                                    or message.deleted_at is not None):
            message = None
    if message is not None:
        message.content = text
        message.is_edited = True
        message.edited_at = datetime.now(timezone.utc)
    else:
        message = ChatMessage(room_id=room.id, user_id=secretary.id,
                              user_name=SECRETARY_NAME, type="text", content=text)
        db.add(message)
    await db.flush()

    # Открытую вкладку не дёргаем событием сокета: список чатов у неё и так
    # обновляется раз в минуту, а напоминанию минута роли не играет. Push нужен
    # именно закрытой вкладке — иначе напоминание догонит человека только при
    # следующем заходе.
    try:
        from app.services import web_push

        # В push разметки ссылок нет: «[№68 «…»](/docs/…)» → «№68 «…»».
        import re
        plain = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", text)
        web_push.push_room_async(room.id, SECRETARY_NAME, plain, secretary.id,
                                 ttl=ttl, urgency=urgency)
    except Exception as e:  # noqa: BLE001
        logger.debug("Напоминание не ушло в push: %s", e)
    return message.id


# ---------------------------------------------------------------------------
# Уведомления о поручениях: канал выбирает сам человек (личные настройки)
# ---------------------------------------------------------------------------
TASK_CHANNELS = ("secretary", "notices", "email")
# Чат — туда, где человек работает; письмо — прежнее поведение, его не отнимаем.
TASK_CHANNELS_DEFAULT = ("secretary", "email")
NOTICES_ROOM_KIND = "notices"
NOTICES_ROOM_TITLE = "Уведомления"


def task_channels(user: User) -> set[str]:
    """Куда человеку присылать уведомления о поручениях.

    Почтовый участник в пространство не заходит и чата не видит — ему только
    письмо, что бы ни стояло в настройке.
    """
    if user.mail_only:
        return {"email"}
    return set(user.task_notify or TASK_CHANNELS_DEFAULT) & set(TASK_CHANNELS)


# ---------------------------------------------------------------------------
# Какие письма человек хочет получать
# ---------------------------------------------------------------------------
# Канал «почта» отвечал на вопрос «писать или нет» целиком: человек, которому
# мешал поток ответов по чужим задачам, выключал почту и переставал получать
# в том числе «вам поручено». Теперь канал решает, писать ли вообще, а эти виды —
# что именно писать.
EMAIL_KINDS = ("task_assigned", "task_mention", "task_reply", "task_status", "digest", "meeting")
# NULL в профиле — получать всё: обновление не вправе молча отключить человеку
# письма, которые он получал вчера.
EMAIL_KINDS_DEFAULT = EMAIL_KINDS

EMAIL_KIND_LABELS: dict[str, str] = {
    "task_assigned": "Мне поручили задачу",
    "task_mention": "Меня упомянули в задаче",
    "task_reply": "Ответы и переписка по задаче",
    "task_status": "Задачу передали, выполнили или отменили",
    "digest": "Сводка дня",
    # Стандартный iMIP: письмо с файлом .ics — VK, Яндекс, Outlook, Gmail и
    # Apple сами кладут встречу в календарь, переносят и снимают её по отмене.
    "meeting": "Встречи — в мой почтовый календарь (VK, Яндекс, Outlook, Gmail)",
}


def is_away(user: User, on: "date | None" = None) -> bool:
    """Человека сейчас нет: отпуск, больничный, командировка.

    Границы включительные: «с 3 по 17» значит, что 17-го он ещё отсутствует.
    Одна дата без второй тоже считается: «с 3-го» — ушёл без известной даты
    возвращения, «по 17-е» — вернётся 18-го.
    """
    from datetime import date as _date

    if user.away_from is None and user.away_to is None:
        return False
    день = on or _date.today()
    if user.away_from is not None and день < user.away_from:
        return False
    if user.away_to is not None and день > user.away_to:
        return False
    return True


def email_kinds(user: User) -> set[str]:
    """Виды писем, которые человек согласен получать."""
    if user.email_notify is None:
        return set(EMAIL_KINDS_DEFAULT)
    return set(user.email_notify) & set(EMAIL_KINDS)


def wants_email(user: User, kind: str) -> bool:
    """Писать ли этому человеку письмо такого вида.

    Почтовому участнику письмо — единственный канал: отключить его значило бы
    отрезать человека от работы, и настройка видов к нему не применяется.
    Неизвестный вид доставляется: лучше лишнее письмо, чем потерянное.
    """
    if user.mail_only:
        return True
    if kind not in EMAIL_KINDS:
        return True
    return kind in email_kinds(user)


async def tell(db: AsyncSession, company_id: uuid.UUID, people, subject: str,
               text: str, task=None, kind: str = "task_assigned") -> None:
    """Уведомление о поручении — в каналы, которые выбрал каждый получатель.

    `kind` — вид письма (`EMAIL_KINDS`): почта уходит, только если человек
    согласен получать письма этого вида. На чат вид не влияет: там уведомление
    лежит в ленте, а не приходит в личный ящик.

    Письма уходят в фоне (`task_mail`), сообщения чата пишутся в сессию
    вызывающего: коммит за ним. Каждое сообщение — в своей точке сохранения,
    чтобы сбой чата не сорвал ни письмо, ни работу вызывающего.
    """
    from app.services import task_mail

    chat_text = f"{subject}\n{text}" if text else subject
    if task is not None:
        from app.services.task_scheduler import task_path

        chat_text += f"\n[Открыть задачу]({task_path(task)})"
    emails: list[str] = []
    for person in people:
        channels = task_channels(person)
        if "email" in channels and person.email and wants_email(person, kind):
            emails.append(person.email)
        for code, kind in (("secretary", None), ("notices", NOTICES_ROOM_KIND)):
            if code not in channels:
                continue
            try:
                async with db.begin_nested():
                    await notify_person(db, company_id, person, chat_text, room_kind=kind)
            except Exception as e:  # noqa: BLE001 — чат не должен ронять поручение
                logger.warning("Уведомление о поручении в чат (%s) не ушло: %s", code, e)
    task_mail.send_notice_async(emails, subject, text)


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
    if await _admins_only(db, company_id):
        q = q.where(User.is_superadmin.is_(True))
        return list((await db.execute(q)).scalars().all())
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
async def post_alert(
    db: AsyncSession, company_id: uuid.UUID, members: list[User], text: str,
) -> bool:
    """Написать в канал «Оповещения» компании: один, идемпотентно, состав досыпается.

    Канал односторонний: пишет «Секретарь», получатели читают. Без получателей канал
    не создаём: писать было бы некому.
    """
    from app.models import ChatMessage, ChatParticipant, ChatRoom

    admins_only = await _admins_only(db, company_id)
    if admins_only:
        members = [person for person in members if person.is_superadmin]
    if not members:
        return False
    secretary = await _secretary(db, company_id)
    # Свой канал узнаём по автору: одноимённый канал, заведённый человеком, не наш.
    room = (await db.execute(select(ChatRoom).where(
        ChatRoom.company_id == company_id, ChatRoom.type == "channel",
        ChatRoom.name == ALERTS_CHANNEL_TITLE, ChatRoom.created_by == secretary.id,
        ChatRoom.is_active.is_(True)).limit(1))).scalar_one_or_none()
    if room is None:
        room = ChatRoom(company_id=company_id, type="channel", name=ALERTS_CHANNEL_TITLE,
                        created_by=secretary.id)
        db.add(room)
        await db.flush()
        db.add(ChatParticipant(room_id=room.id, user_id=secretary.id, role="owner"))
    if admins_only:
        # Отзыв системной роли должен отзывать и чтение общего канала.
        allowed = select(User.id).where(User.is_superadmin.is_(True))
        await db.execute(delete(ChatParticipant).where(
            ChatParticipant.room_id == room.id,
            ChatParticipant.user_id != secretary.id,
            ChatParticipant.user_id.not_in(allowed)))
    joined = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == room.id))).scalars().all())
    db.add_all([ChatParticipant(room_id=room.id, user_id=p.id)
                for p in members if p.id not in joined])
    db.add(ChatMessage(room_id=room.id, user_id=secretary.id, user_name=SECRETARY_NAME,
                       type="text", content=text))
    await db.commit()
    try:
        from app.services import web_push

        web_push.push_room_async(room.id, ALERTS_CHANNEL_TITLE, text, secretary.id)
    except Exception as e:  # noqa: BLE001
        logger.debug("Оповещение не ушло в push: %s", e)
    return True


# ---------------------------------------------------------------------------
# Доставка
# ---------------------------------------------------------------------------
def _text(company_name: str, category: str, action: str, who: str | None,
          details: str | None) -> str:
    head = f"{label_of(category)} · {company_name}"
    body = f"{action_label(action)}"
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
            out["chat"] = await post_alert(db, company_id, people, text)
        except Exception as e:  # noqa: BLE001 — сбой чата не должен отменять письмо
            logger.warning("Оповещение в чат не ушло: %s", e)
            await db.rollback()
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
