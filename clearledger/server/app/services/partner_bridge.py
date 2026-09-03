"""Мост между пространствами: разговор с техподдержкой ведётся из своего контура.

Задача, которую он решает. Наши люди заведены в пространстве клиента и работают
внутри него — инженер должен видеть и править, это его функция, и она остаётся.
Но когда клиент ПИШЕТ нам, разговор обязан идти в нашем пространстве: там очередь
поддержки, история по всем клиентам и люди, которые дежурят. Иначе поддержка живёт
в чужом контуре, у неё нет своей ленты, и второго клиента она обслуживать не может.

Как устроено. Оба конца — экземпляры одного Ядра, поэтому доставка симметрична:
одна ручка принимает сообщение, один сервис его отправляет, а разница только в
роли записи (`client` / `vendor`) и в том, что у поддержки сообщение дополнительно
зеркалится в очередь Координатора.

Чего здесь НЕТ намеренно:

* Matrix-федерации. Она запрещена инвариантом стека (`federation_domain_whitelist:
  []`), и правильно: изоляция контейнеров важнее удобства. Разговор переносим
  сообщениями, а не общим сервером.
* Второй шины. Событийная шина Ядра (`space_events`) возит ФАКТЫ предметной
  области подписчикам. Здесь ходит разговор между двумя known-собеседниками, и
  ему нужна не рассылка, а адресная доставка с ответом.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PartnerMessage, PartnerSpace, PartnerTopic

DELIVERY_TIMEOUT = 15.0
# Путь приёмника у партнёра. Совпадает с нашим: обе стороны — одно Ядро.
INBOX_PATH = "/api/eco/partner/message"
# Куда уезжает состояние обращения: его ведёт та сторона, которая делает работу.
STATE_PATH = "/api/eco/partner/topic-state"
# Состояния обращения — общий словарь на оба конца (docs/BRIDGE.md §4.1). Короткий
# намеренно: стадии заявки, SLA и исполнители — наше внутреннее устройство, и
# клиенту от них нужен только ответ «чей ход и чем кончилось».
STATES = ("new", "in_progress", "waiting", "resolved", "closed")
# Где у партнёра лежит его публичный ключ и куда приходит гость. Пути те же, что у
# нас: оба конца — одно Ядро.
JWKS_PATH = "/api/sso/jwks.json"
VISIT_PATH = "/space-guest"


class BridgeError(RuntimeError):
    pass


def partner_key(partner: PartnerSpace) -> str:
    """Ключ доступа к партнёру: из окружения по ссылке, а не из базы.

    Пустая ссылка — не поломка настройки, а прямое «связь ещё не включили»:
    запись о партнёре может существовать раньше, чем стороны обменялись ключами.
    """
    if not partner.secret_ref:
        return ""
    return os.getenv(partner.secret_ref, "")


async def partner_jwks(partner: PartnerSpace) -> dict[str, Any]:
    """Публичные ключи партнёра — ими проверяется его пропуск.

    Ключ берём у него самого, а не из своей настройки: он его меняет, и
    переспросить дешевле, чем разбирать «почему инженер вдруг не входит».
    """
    if not partner.base_url:
        raise BridgeError("У пространства не задан адрес")
    url = f"{partner.base_url.rstrip('/')}{JWKS_PATH}"
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise BridgeError(f"Пространство недоступно: {e}") from e
    if resp.status_code >= 400:
        raise BridgeError(f"Пространство ответило {resp.status_code} на запрос ключей")
    return resp.json()


async def get_partner(
    db: AsyncSession, company_id: uuid.UUID, code: str, role: str | None = None,
) -> PartnerSpace | None:
    stmt = select(PartnerSpace).where(
        PartnerSpace.company_id == company_id, PartnerSpace.code == code,
        PartnerSpace.is_active.is_(True),
    )
    if role:
        stmt = stmt.where(PartnerSpace.role == role)
    return (await db.execute(stmt)).scalars().first()


async def ensure_topic(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, code: str, *,
    title: str = "", subject_kind: str | None = None, subject_ref: str | None = None,
    subject_label: str | None = None, opened_by_id: uuid.UUID | None = None,
) -> PartnerTopic:
    """Обращение с этим кодом — найти или завести (docs/BRIDGE.md §4.1).

    Код присваивает зачинатель, и он один на обе стороны. Поэтому пришедшее
    обращение заводится тем же кодом, каким живёт у соседа: иначе ответ вернулся
    бы в новую ветку, и разговор разошёлся бы надвое.

    Заголовок у уже заведённого не переписываем: обращение называет тот, кто его
    открыл, а реплики соседа несут заголовок лишь затем, чтобы новое обращение
    было чем назвать.
    """
    row = (await db.execute(select(PartnerTopic).where(
        PartnerTopic.partner_id == partner.id, PartnerTopic.code == code,
    ))).scalars().first()
    if row is not None:
        return row
    row = PartnerTopic(
        company_id=company_id, partner_id=partner.id, code=code,
        title=(title or "").strip()[:300] or "Обращение",
        subject_kind=subject_kind, subject_ref=subject_ref,
        subject_label=subject_label, opened_by_id=opened_by_id,
        last_message_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row


async def topics(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, limit: int = 200,
) -> list[dict[str, Any]]:
    """Обращения к этому пространству, свежие сверху — так их и читают."""
    res = await db.execute(
        select(PartnerTopic)
        .where(PartnerTopic.company_id == company_id,
               PartnerTopic.partner_id == partner.id)
        .order_by(PartnerTopic.last_message_at.desc().nullslast(),
                  PartnerTopic.created_at.desc())
        .limit(limit)
    )
    return [{
        "code": t.code,
        "title": t.title,
        "state": t.state,
        "number": t.external_number,
        "subjectLabel": t.subject_label,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
        "lastMessageAt": t.last_message_at.isoformat() if t.last_message_at else None,
    } for t in res.scalars().all()]


async def apply_state(
    db: AsyncSession, partner: PartnerSpace, code: str, *,
    state: str | None, number: str | None,
) -> PartnerTopic | None:
    """Состояние обращения, названное соседом. Чужое обращение не заводим.

    Состояние ведёт та сторона, которая делает работу. Прийти оно может только по
    известному обращению: сообщение заводит разговор, состояние — нет, иначе
    ошибка в коде темы породила бы у нас пустую строку в списке.
    """
    row = (await db.execute(select(PartnerTopic).where(
        PartnerTopic.partner_id == partner.id, PartnerTopic.code == code,
    ))).scalars().first()
    if row is None:
        return None
    if state in STATES:
        row.state = state
        row.closed_at = datetime.now(UTC) if state == "closed" else None
    if number is not None:
        row.external_number = number.strip()[:60] or None
    await db.commit()
    return row


async def send_state(partner: PartnerSpace, self_code: str, topic: PartnerTopic) -> str | None:
    """Сообщить соседу состояние обращения. Возвращает ошибку или None.

    Отдельно от реплики, потому что это не разговор: «принято», «в работе»,
    «решено» не должны засорять ленту строками, которые человек не писал.
    """
    key = partner_key(partner)
    if not partner.base_url or not key:
        return "Связь с пространством не включена"
    url = f"{partner.base_url.rstrip('/')}{STATE_PATH}"
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            resp = await client.post(url, json={
                "topic": topic.code,
                "state": topic.state,
                "number": topic.external_number,
            }, headers={"X-Cloud-API-Key": key, "X-Eco-Space": self_code})
    except httpx.HTTPError as e:
        return f"Не доставлено: {e}"
    if resp.status_code >= 400:
        return f"Партнёр ответил {resp.status_code}: {resp.text[:200]}"
    return None


async def record_incoming(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, payload: dict[str, Any],
) -> tuple[PartnerMessage, bool]:
    """Записать пришедшее сообщение. Возвращает (запись, новое ли оно).

    Повтор — штатная работа сети, а не ошибка: отправитель ретраит по коду ответа.
    Поэтому дубль по `external_id` тихо возвращается как уже принятый.
    """
    external_id = str(payload.get("id") or "").strip() or None
    if external_id:
        existing = (await db.execute(select(PartnerMessage).where(
            PartnerMessage.partner_id == partner.id,
            PartnerMessage.direction == "in",
            PartnerMessage.external_id == external_id,
        ))).scalars().first()
        if existing is not None:
            return existing, False

    topic = None
    topic_code = str(payload.get("topic") or "").strip()[:64]
    if topic_code:
        topic = await ensure_topic(
            db, company_id, partner, topic_code,
            title=str(payload.get("topicTitle") or ""),
            subject_label=(payload.get("subjectLabel") or None))
        topic.last_message_at = datetime.now(UTC)

    row = PartnerMessage(
        company_id=company_id, partner_id=partner.id, direction="in",
        topic_id=topic.id if topic is not None else None,
        author_email=(payload.get("authorEmail") or None),
        author_name=(payload.get("authorName") or None),
        body=str(payload.get("body") or "").strip(),
        subject_kind=(payload.get("subjectKind") or None),
        subject_ref=(payload.get("subjectRef") or None),
        external_id=external_id,
    )
    db.add(row)
    partner.last_seen_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return row, True


async def send(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, *,
    self_code: str, body: str,
    author_email: str | None = None, author_name: str | None = None,
    subject_kind: str | None = None, subject_ref: str | None = None,
    external_id: str | None = None, topic: PartnerTopic | None = None,
) -> PartnerMessage:
    """Отправить сообщение партнёру и записать его у себя.

    Порядок важен: сначала пишем к себе, потом отправляем. Если связь оборвётся,
    сообщение останется в ленте с пометкой, почему не дошло, — а не исчезнет
    вместе с ошибкой сети.

    `external_id` — идентификатор сообщения у того, кто нас позвал (у Координатора
    это его `inbox_messages.id`). Человек пишет один раз и ключа не имеет, а
    Координатор шлёт очередью с ретраями: без ключа второй заход положил бы в
    ленту клиента ту же реплику второй раз.
    """
    if external_id:
        already = (await db.execute(select(PartnerMessage).where(
            PartnerMessage.partner_id == partner.id,
            PartnerMessage.direction == "out",
            PartnerMessage.external_id == external_id,
        ))).scalars().first()
        if already is not None:
            return already

    row = PartnerMessage(
        company_id=company_id, partner_id=partner.id, direction="out",
        topic_id=topic.id if topic is not None else None,
        author_email=author_email, author_name=author_name, body=body.strip(),
        subject_kind=subject_kind, subject_ref=subject_ref,
        external_id=external_id,
    )
    db.add(row)
    if topic is not None:
        topic.last_message_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)

    key = partner_key(partner)
    if not partner.base_url or not key:
        row.delivery_error = "Связь с пространством не включена: нет адреса или ключа"
        await db.commit()
        return row

    url = f"{partner.base_url.rstrip('/')}{INBOX_PATH}"
    payload = {
        "id": str(row.id),
        "body": row.body,
        "authorEmail": row.author_email,
        "authorName": row.author_name,
        "subjectKind": row.subject_kind,
        "subjectRef": row.subject_ref,
    }
    if topic is not None:
        # Заголовок и подпись предмета едут с КАЖДОЙ репликой, а не только с
        # первой: связь могли включить позже, и у соседа обращение заводится тем
        # сообщением, которое доехало первым, — безымянным ему быть нельзя.
        payload |= {"topic": topic.code, "topicTitle": topic.title,
                    "subjectLabel": topic.subject_label}
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers={
                "X-Cloud-API-Key": key,
                # Кто пишет — НАШ код пространства, а не код адресата. Получатель
                # ищет у себя запись с этим кодом: у него мы заведены под своим
                # именем. Отправь мы код партнёра — он искал бы запись о самом себе
                # и не нашёл бы её никогда.
                "X-Eco-Space": self_code,
            })
    except httpx.HTTPError as e:
        row.delivery_error = f"Не доставлено: {e}"
        await db.commit()
        return row

    if resp.status_code >= 400:
        row.delivery_error = f"Партнёр ответил {resp.status_code}: {resp.text[:200]}"
    else:
        row.delivered_at = datetime.now(UTC)
        row.delivery_error = None
    await db.commit()
    return row


async def feed(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, limit: int = 200,
    topic: PartnerTopic | None = None,
) -> list[dict[str, Any]]:
    """Лента разговора с партнёром, старые сверху — читают её как переписку.

    Без обращения отдаётся вся переписка с пространством: так читают историю и так
    выглядит связь, заведённая до появления обращений.
    """
    stmt = (
        select(PartnerMessage)
        .where(PartnerMessage.company_id == company_id,
               PartnerMessage.partner_id == partner.id)
    )
    if topic is not None:
        stmt = stmt.where(PartnerMessage.topic_id == topic.id)
    res = await db.execute(stmt.order_by(PartnerMessage.created_at.desc()).limit(limit))
    rows = list(res.scalars().all())
    rows.reverse()
    return [{
        "id": str(r.id),
        "direction": r.direction,
        "body": r.body,
        "authorName": r.author_name,
        "authorEmail": r.author_email,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "delivered": r.delivered_at is not None if r.direction == "out" else True,
        "error": r.delivery_error,
    } for r in rows]
