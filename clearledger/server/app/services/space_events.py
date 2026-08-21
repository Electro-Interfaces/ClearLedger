"""Исходящие события пространства: кто-то сделал — остальные узнали.

Ядро принимало события приложений (`inbound_events`) и не отдавало своих: факт
записывался в след документа и там же умирал. Подписаться на «документ
зарегистрирован» было неоткуда, поэтому каждое приложение, которому это нужно,
спрашивало Ядро само — то есть не спрашивало вовсе.

Устройство — транзакционный outbox, как в шине Поддержки, и конверт тот же
(CloudEvents 1.0, восемь атрибутов, подпись standard-webhooks). Общий конверт
важнее локального удобства: у получателя уже написан разбор и проверка подписи,
и второй формат означал бы второй разбор.

Два отличия от шины Поддержки, оба из её же граблей:

* **Веер по подписчикам разворачивается при постановке**, а не при доставке. Там
  строка одна на факт, и отказ одного получателя возвращает событие в очередь
  целиком — живые получают дубль столько раз, сколько мёртвый не ответил.
* **Молчащая подписка гасится** и об этом узнаёт человек. Там `failure_streak`
  растёт вечно, и никто об этом не спрашивает.

Срок ожидания (`stop_day_count`) взят из зоны `Subscriptions` ГОСТ Р 53898 — та
же мысль: подписчик заказывает не только типы событий, но и то, как долго они
ему интересны. Событие старше срока не доставляем, подписку, молчащую дольше
срока, выключаем.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventSubscription, OutboxEvent
from app.services import sso
from app.services.space_projection import _internal_base_url, _target

log = logging.getLogger("clearledger.events")

# Что пространство порождает. Каталог в коде, а не в справочнике: подписка не
# может ссылаться на событие, которого система не умеет издавать, и проверить
# это надо в тот момент, когда подписку заводят.
EVENT_TYPES: dict[str, str] = {
    "doc.registered": "Документ зарегистрирован",
    "doc.approval.completed": "Круг согласования пройден",
    "doc.rejected": "Документ отклонён на визе",
    "doc.acquainted": "С документом ознакомились",
    "doc.archived": "Документ передан в архив",
    # Работа коннекторов до сих пор следа не оставляла: канал отработал, не
    # отработал, привёз сто записей или ноль — узнать об этом можно было только
    # открыв журнал прогонов глазами. Подписаться на отказ канала было нельзя.
    "connector.sync.completed": "Канал завершил обмен",
    "connector.sync.failed": "Канал не смог завершить обмен",
}

SOURCE = "/elsyplus/core/docs"
# Один предел на все исходящие Ядра — как у возврата исхода круга виз. Второй
# счётчик означал бы вторую историю о том, где потерялось.
MAX_ATTEMPTS = 12
# Шаг обязан быть кратен тику планировщика (300 с), иначе экспонента в секундах
# выродится в «каждый тик»: 5м, 10м, 20м … и потолок 6 часов.
BACKOFF_BASE = timedelta(minutes=5)
BACKOFF_CAP = timedelta(hours=6)
DELIVERY_TIMEOUT = 10.0


def _key() -> bytes:
    """Ключ шифрования секретов подписок — производный от ключа стека."""
    raw = os.environ.get("EVENTS_SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
    if not raw:
        return b""
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def encrypt_secret(secret: str) -> str | None:
    key = _key()
    if not key or not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key).encrypt(secret.encode()).decode()


def decrypt_secret(token: str | None) -> str:
    if not token:
        return ""
    key = _key()
    if not key:
        return ""
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return Fernet(key).decrypt(token.encode()).decode()
    except InvalidToken:
        # Ключ стека сменился — подписать нечем. Падать нельзя: остальные
        # подписки должны продолжать работать, а эта покажет ошибку доставки.
        log.warning("секрет подписки не расшифрован: ключ стека изменился")
        return ""


def envelope(event_id: uuid.UUID, event_type: str, subject: str,
             occurred_at: datetime, data: dict[str, Any]) -> dict[str, Any]:
    """Конверт CloudEvents — ровно те же восемь атрибутов, что у Поддержки."""
    out = {
        "specversion": "1.0",
        "id": str(event_id),
        "source": SOURCE,
        "type": event_type,
        "time": occurred_at.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"),
        "datacontenttype": "application/json",
        "data": data,
    }
    if subject:
        out["subject"] = subject
    return out


def sign(secret: str, event_id: str, timestamp: int, body: str) -> str:
    """Подпись standard-webhooks: `v1,<base64 HMAC-SHA256>` над `id.ts.body`."""
    key = (base64.b64decode(secret[6:]) if secret.startswith("whsec_")
           else secret.encode())
    digest = hmac.new(key, f"{event_id}.{timestamp}.{body}".encode(),
                      hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


async def publish(db: AsyncSession, company_id: uuid.UUID, event_type: str,
                  subject: str, data: dict[str, Any], *,
                  occurred_at: datetime | None = None,
                  correlation_id: str | None = None) -> int:
    """Поставить событие в очередь — В ТОЙ ЖЕ транзакции, что и само изменение.

    Возвращает число адресатов. Ноль — законный исход: никто не подписан, значит
    доставлять некому, и очередь остаётся пустой. Хранить «событие без адресата»
    незачем — след факта живёт в истории документа, а не здесь.

    Сети в этой точке нет намеренно: отправка внутри бизнес-транзакции связала бы
    регистрацию документа с доступностью чужого сервиса.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"неизвестный тип события: {event_type}")
    rows = (await db.execute(select(EventSubscription).where(
        EventSubscription.company_id == company_id,
        EventSubscription.enabled.is_(True),
        EventSubscription.event_types.any(event_type)))).scalars().all()
    if not rows:
        return 0
    event_id = uuid.uuid4()
    when = occurred_at or datetime.now(timezone.utc)
    for sub in rows:
        db.add(OutboxEvent(
            event_id=event_id, subscription_id=sub.id, company_id=company_id,
            type=event_type, subject=subject, source=SOURCE, occurred_at=when,
            data=data, correlation_id=correlation_id))
    return len(rows)


def doc_data(doc: Any, actor: Any = None, **extra: Any) -> dict[str, Any]:
    """Тело события по карточке документа.

    Отдаём делопроизводственные реквизиты, а не карточку целиком. Наружу не
    уходят содержание, вложения и код проверки по ссылке: подписчику нужен факт
    и ключ, по которому он спросит остальное, если ему это положено.
    """
    body: dict[str, Any] = {
        "doc": {
            "id": str(doc.id),
            "kindCode": doc.kind_code,
            "family": doc.family,
            "direction": doc.direction,
            "title": doc.title,
            "regNumber": doc.reg_number,
            "regDate": doc.reg_date.isoformat() if doc.reg_date else None,
            "status": doc.status,
            "approvalStatus": getattr(doc, "approval_status", None),
            "organizationId": (str(doc.organization_id)
                               if doc.organization_id else None),
            "counterpartyId": (str(doc.counterparty_id)
                               if doc.counterparty_id else None),
            "counterpartyName": doc.counterparty_name or None,
            "subjectRef": doc.subject_ref,
            "objectId": doc.object_id,
        },
    }
    if actor is not None:
        # Идентификатора может не быть вовсе: визу ставит внешний участник по
        # ссылке или партнёрская система по ключу. Учётки за ними нет, и
        # `str(None)` в поле идентификатора у получателя — это строка «None»,
        # которую он честно попробует найти.
        actor_id = getattr(actor, "id", None)
        body["actor"] = {
            "kind": "user" if actor_id else "external",
            "id": str(actor_id) if actor_id else None,
            "name": actor.name or getattr(actor, "email", None),
        }
    else:
        # Круг мог запустить и закрыть узел маршрута процесса — человека там нет,
        # и придумывать техническую учётку ради формы поля не станем.
        body["actor"] = {"kind": "system", "id": None, "name": "Процесс"}
    body.update(extra)
    return body


def _backoff(attempts: int) -> timedelta:
    step = BACKOFF_BASE * (2 ** max(0, attempts - 1))
    return min(step, BACKOFF_CAP)


async def _send(db: AsyncSession, sub: EventSubscription,
                row: OutboxEvent) -> int:
    """Отдать событие подписчику. Возвращает код ответа, бросает при обрыве."""
    body_obj = envelope(row.event_id, row.type, row.subject, row.occurred_at,
                        row.data or {})
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if sub.target_kind == "app":
        # Токен `_target` подписан скоупом проекции — для событий берём свой:
        # право на проекцию справочников не должно втихую означать право слать
        # события. Приложение и пара компаний оттуда же, они общие.
        app_row, link, _ = await _target(db, row.company_id, sub.app_code or "")
        url = f"{_internal_base_url(app_row, sub.app_code or '')}{sub.path}"
        # У приложения своя нумерация компаний — отдаём его собственный ключ,
        # как это делает проекция. Наш UUID ему ничего не говорит.
        body_obj["data"] = dict(body_obj.get("data") or {})
        body_obj["data"]["companyId"] = link.external_company_id
        token = sso.sign_service_token(aud=sub.app_code or "", scope="events")
        if not token:
            raise RuntimeError("единый вход не настроен: нечем подписать вызов")
        headers["Authorization"] = f"Bearer {token}"
    else:
        url = sub.url or ""

    # Подписываем ровно ту строку, что уйдёт в сеть: пересборка тела на стороне
    # получателя дала бы другой байт и подпись бы не сошлась.
    body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    secret = decrypt_secret(sub.secret_enc)
    if secret:
        timestamp = int(row.occurred_at.timestamp())
        headers["webhook-id"] = str(row.event_id)
        headers["webhook-timestamp"] = str(timestamp)
        headers["webhook-signature"] = sign(secret, str(row.event_id),
                                            timestamp, body)
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
        resp = await client.post(url, content=body.encode("utf-8"),
                                 headers=headers)
    return resp.status_code


async def deliver_pending(db: AsyncSession, now: datetime,
                          limit: int = 50) -> int:
    """Разослать то, что ждёт. Возвращает число доставленных."""
    rows = (await db.execute(select(OutboxEvent).where(
        OutboxEvent.status == "pending",
        OutboxEvent.next_attempt_at <= now)
        .order_by(OutboxEvent.next_attempt_at)
        .limit(limit).with_for_update(skip_locked=True))).scalars().all()
    sent = 0
    for row in rows:
        sub = await db.get(EventSubscription, row.subscription_id)
        if sub is None or not sub.enabled:
            row.status = "cancelled"
            row.last_error = "подписка снята или выключена"
            continue
        # Протухшее не отправляем и попытку на него не тратим: подписчик заказал
        # срок, в течение которого событие ему интересно, и срок вышел.
        if row.occurred_at < now - timedelta(days=sub.stop_day_count):
            row.status = "expired"
            row.last_error = f"старше срока ожидания ({sub.stop_day_count} дн.)"
            continue
        row.attempts += 1
        try:
            code = await _send(db, sub, row)
            error = None if 200 <= code < 300 else f"HTTP {code}"
        except Exception as exc:  # noqa: BLE001 — обрыв связи не должен валить проход
            code, error = 0, str(exc)[:500]
        sub.last_delivery_at = now
        sub.last_status = code or None
        sub.last_error = error
        if error is None:
            row.status = "done"
            row.delivered_at = now
            row.last_error = None
            sub.failure_streak = 0
            sub.failing_since = None
            sent += 1
            continue
        row.last_error = error
        sub.failure_streak += 1
        sub.failing_since = sub.failing_since or now
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
        else:
            row.next_attempt_at = now + _backoff(row.attempts)
    return sent


async def disable_dead(db: AsyncSession, now: datetime) -> int:
    """Погасить подписки, молчащие дольше собственного срока ожидания.

    Гасим по сроку, а не по числу неудач: десять отказов за минуту — это сбой
    сети, а неделя молчания — это отключённый потребитель. И гасим ГРОМКО:
    молчаливая сдача хуже, чем видимая ошибка, — о ней никто не узнает.
    """
    rows = (await db.execute(select(EventSubscription).where(
        EventSubscription.enabled.is_(True),
        EventSubscription.failing_since.is_not(None)))).scalars().all()
    stopped = 0
    for sub in rows:
        if sub.failing_since is None:
            continue
        if sub.failing_since >= now - timedelta(days=sub.stop_day_count):
            continue
        sub.enabled = False
        sub.disabled_at = now
        sub.disabled_reason = (
            f"молчит дольше срока ожидания ({sub.stop_day_count} дн.)")
        pending = (await db.execute(select(OutboxEvent).where(
            OutboxEvent.subscription_id == sub.id,
            OutboxEvent.status == "pending"))).scalars().all()
        for row in pending:
            row.status = "cancelled"
            row.last_error = "подписка выключена как молчащая"
        log.warning("подписка %s выключена: %s", sub.id, sub.disabled_reason)
        stopped += 1
    return stopped
