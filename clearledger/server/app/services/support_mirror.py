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

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PartnerMessage, PartnerSpace
from app.services import space_projection

TIMEOUT = 10.0


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
    except space_projection.ProjectionError:
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
        # Чей это разговор — тредом, а не догадкой по тексту темы: по этой метке
        # ответ оператора уедет обратно в пространство клиента, а не упрётся в
        # отсутствующий канальный коннектор.
        "partnerCode": partner.code,
        "partnerName": who,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return False
    return resp.status_code < 400


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
