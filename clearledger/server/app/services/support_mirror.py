"""Обращение из пространства клиента — в очередь нашей Поддержки.

Зачем зеркало, а не отдельный экран. У оператора уже есть одна очередь, куда
сходятся звонки, письма и обращения с сайта. Если разговор с пространством
заказчика показывать отдельно, у дежурного станет два места, куда смотреть, — и
второе он смотреть перестанет. Поэтому сообщение из чужого пространства ложится
тем же `inbox_thread`, только каналом `web` и с пометкой, откуда пришло.

Канал `web`, а не свой: список каналов у Координатора закрыт CHECK-ограничением
(`call`, `telegram`, `whatsapp`, `email`, `sms`, `web`, `other`), и заводить в нём
восьмое значение ради пометки — менять схему приложения из Ядра. Откуда пришло,
видно по теме обращения и по `meta`.

Мост не обязан работать, чтобы работала переписка: если Координатора в стеке нет
или он молчит, сообщение всё равно записано у нас в ленте (`eco_partner_messages`),
и человек его увидит. Зеркало — удобство оператора, а не место хранения.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PartnerMessage, PartnerSpace, PartnerTopic
from app.services import space_projection

TIMEOUT = 10.0
log = logging.getLogger("clearledger.support_mirror")


async def mirror_incoming(
    db: AsyncSession, company_id: uuid.UUID, partner: PartnerSpace, message: PartnerMessage,
) -> bool:
    """Положить пришедшее сообщение в очередь Координатора. Тихо, без исключений.

    Возвращает, дошло ли. Неудача не откатывает приём: сообщение уже принято, и
    отказать отправителю из-за нашей внутренней доставки значило бы заставить его
    слать повторно то, что мы уже взяли.
    """
    try:
        app_row, link, token = await space_projection._target(db, company_id, "support")
    except space_projection.ProjectionError as exc:
        message.mirror_error = str(exc)[:500]
        return False

    url = (f"{space_projection._internal_base_url(app_row, 'support')}"
           f"/api/v1/eco/inbox/web")
    who = partner.name or partner.code
    payload = {
        # Чья это очередь. У клиента компания в Поддержке своя — тогда обращение
        # ложится к нему, и сроки с историей считаются по нему, а не общей кучей.
        # Не сказано чья — падает в нашу, как было: терять обращение из-за
        # незаполненной настройки нельзя.
        "companyId": partner.support_company_id or link.external_company_id,
        # Адрес автора в его пространстве — по нему обращения одного человека
        # соберутся в один тред, как у звонившего собираются звонки.
        "email": message.author_email or f"{partner.code}@space.local",
        "name": f"{message.author_name or 'Сотрудник'} · {who}",
        "body": message.body,
        "externalId": f"partner:{company_id}:{message.id}",
        # Чей это разговор — тредом, а не догадкой по тексту темы: по этой метке
        # ответ оператора уедет обратно в пространство клиента, а не упрётся в
        # отсутствующий канальный коннектор.
        "partnerCode": partner.code,
        "partnerName": who,
    }
    # Обращение — одна ветка на обеих сторонах (docs/BRIDGE.md §4.3). Тред у
    # оператора ключуется его кодом: второй сотрудник клиента, написавший по тому
    # же вопросу, попадает в тот же разговор, а не заводит соседний.
    if message.topic_id is not None:
        topic = await db.get(PartnerTopic, message.topic_id)
        if topic is not None:
            payload |= {"topic": topic.code,
                        "topicTitle": f"{who} · {topic.title}",
                        "subjectLabel": topic.subject_label}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        message.mirror_error = f"{type(exc).__name__}: Поддержка не подтвердила приём"
        return False
    if not 200 <= resp.status_code < 300:
        message.mirror_error = f"Поддержка ответила HTTP {resp.status_code}"
        return False
    try:
        result = resp.json()
    except ValueError:
        result = None
    if not isinstance(result, dict) or result.get("ok") is not True or not result.get("threadId"):
        message.mirror_error = "Поддержка не подтвердила создание обращения"
        return False
    return True


async def deliver_pending(db, now: datetime, bucket=None, *, message_id=None) -> int:
    stmt = (select(PartnerMessage, PartnerSpace)
            .join(PartnerSpace, PartnerSpace.id == PartnerMessage.partner_id)
            .where(PartnerMessage.mirror_pending.is_(True),
                   PartnerMessage.direction == "in", PartnerSpace.role == "client",
                   PartnerSpace.is_active.is_(True),
                   or_(PartnerMessage.mirror_next_at.is_(None), PartnerMessage.mirror_next_at <= now))
            .order_by(PartnerMessage.created_at)
            .with_for_update(of=PartnerMessage, skip_locked=True).limit(20))
    if message_id is not None:
        stmt = stmt.where(PartnerMessage.id == message_id)
    sent = 0
    for message, partner in (await db.execute(stmt)).all():
        message.mirror_attempts += 1
        if await mirror_incoming(db, message.company_id, partner, message):
            message.mirror_pending = False
            message.mirrored_at = now
            message.mirror_error = None
            message.mirror_next_at = None
            sent += 1
        else:
            delay = min(300 * (2 ** min(message.mirror_attempts - 1, 7)), 21600)
            message.mirror_next_at = now + timedelta(seconds=delay)
            log.warning("Обращение %s ожидает доставки в Поддержку: %s", message.id, message.mirror_error)
    await db.commit()
    return sent


async def mirror_mail(
    db: AsyncSession, company_id: uuid.UUID, message, reply_inbox: str | None = None,
) -> bool:
    """Письмо клиента — в ту же очередь, где звонки и разговоры из пространств.

    Два источника обращения — письмо и чат — должны запускать одно движение, иначе
    оператору приходится помнить, где ещё посмотреть. Поэтому письмо не остаётся
    строкой в переписке: оно встаёт в очередь каналом `email`.

    В `meta` уезжает обратный адрес и ящик, которым отвечать: почтовые ящики и
    подписи живут в Ядре, и ответ оператора вернётся сюда же, а не уйдёт из
    Координатора своим каналом.
    """
    try:
        app_row, link, token = await space_projection._target(db, company_id, "support")
    except space_projection.ProjectionError:
        return False

    url = (f"{space_projection._internal_base_url(app_row, 'support')}"
           f"/api/v1/eco/inbox/message")
    body = (message.body_text or "").strip() or "(письмо без текста)"
    payload = {
        "companyId": link.external_company_id,
        "email": message.from_email,
        "name": message.from_name or message.from_email,
        "body": body,
        "channel": "email",
        "subject": message.subject or "Письмо",
        # Тема письма — ключ разговора: ответы на неё лягут в тот же тред, а новое
        # письмо о другом заведёт свой, как и в кабинете сайта.
        "topic": f"mail:{(message.subject or '').strip().lower()[:80]}",
        "meta": {
            "mail_message_id": str(message.id),
            "mail_reply_to": message.from_email,
            "mail_inbox": reply_inbox or "",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return False
    return resp.status_code < 400
