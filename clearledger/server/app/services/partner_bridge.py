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

from app.models import PartnerMessage, PartnerSpace

DELIVERY_TIMEOUT = 15.0
# Путь приёмника у партнёра. Совпадает с нашим: обе стороны — одно Ядро.
INBOX_PATH = "/api/eco/partner/message"


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

    row = PartnerMessage(
        company_id=company_id, partner_id=partner.id, direction="in",
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
) -> PartnerMessage:
    """Отправить сообщение партнёру и записать его у себя.

    Порядок важен: сначала пишем к себе, потом отправляем. Если связь оборвётся,
    сообщение останется в ленте с пометкой, почему не дошло, — а не исчезнет
    вместе с ошибкой сети.
    """
    row = PartnerMessage(
        company_id=company_id, partner_id=partner.id, direction="out",
        author_email=author_email, author_name=author_name, body=body.strip(),
        subject_kind=subject_kind, subject_ref=subject_ref,
    )
    db.add(row)
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
) -> list[dict[str, Any]]:
    """Лента разговора с партнёром, старые сверху — читают её как переписку."""
    res = await db.execute(
        select(PartnerMessage)
        .where(PartnerMessage.company_id == company_id,
               PartnerMessage.partner_id == partner.id)
        .order_by(PartnerMessage.created_at.desc()).limit(limit)
    )
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
