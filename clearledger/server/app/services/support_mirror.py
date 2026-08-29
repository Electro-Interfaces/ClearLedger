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
        "companyId": link.external_company_id,
        # Адрес автора в его пространстве — по нему обращения одного человека
        # соберутся в один тред, как у звонившего собираются звонки.
        "email": message.author_email or f"{partner.code}@space.local",
        "name": f"{message.author_name or 'Сотрудник'} · {who}",
        "body": message.body,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return False
    return resp.status_code < 400
