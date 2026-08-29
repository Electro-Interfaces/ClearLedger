"""Разговор между пространствами: приём, лента, отправка.

Не путать с `partner_router.py` — там партнёр в ПРОЦЕССЕ: чужая система
согласует один наш документ по одноразовому праву. Здесь другое: два полноценных
пространства, наше и заказчика, разговаривают друг с другом постоянно.

Три ручки на обе стороны моста (`services/partner_bridge.py`):

* `POST /eco/partner/message` — принять сообщение от другого пространства. Ключ
  интеграции, как у остальных машинных входов; сессии здесь нет.
* `GET  /partner-space/{code}/feed` — прочитать разговор человеку.
* `POST /partner-space/{code}/message` — написать в другое пространство.

У заказчика этим пользуются его сотрудники («написать в техподдержку»), у нас —
оператор поддержки. Код один, потому что и там и там это одно и то же: переписка
двух пространств.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_company_by_api_key, get_current_user
from app.database import get_db
from app.models import Company, PartnerSpace, User
from app.services import partner_bridge, support_mirror

router = APIRouter(tags=["Пространства-партнёры"])


class OutgoingMessage(BaseModel):
    body: str
    subject_kind: str | None = None
    subject_ref: str | None = None


@router.post("/eco/partner/message")
async def accept_partner_message(
    request: Request,
    x_eco_space: str | None = Header(None, alias="X-Eco-Space"),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять сообщение от другого пространства.

    Отправитель называет себя заголовком `X-Eco-Space` — кодом, под которым он у
    нас заведён. Незнакомого не принимаем: ключ доказывает, что стучится свой, но
    не говорит, чей это разговор, а класть переписку в чужую ленту нельзя.
    """
    payload = await request.json()
    code = (x_eco_space or payload.get("space") or "").strip()
    if not code:
        raise HTTPException(400, "Не указано пространство отправителя (X-Eco-Space)")

    partner = await partner_bridge.get_partner(db, company.id, code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{code}» здесь не заведено")
    if not str(payload.get("body") or "").strip():
        raise HTTPException(400, "Пустое сообщение")

    row, is_new = await partner_bridge.record_incoming(db, company.id, partner, payload)
    # Пришло клиенту — это ответ поддержки, и ему довольно ленты. Пришло НАМ —
    # это обращение, и оно должно встать в очередь оператора рядом со звонками.
    if is_new and partner.role == "client":
        await support_mirror.mirror_incoming(db, company.id, partner, row)
    return {"status": "accepted" if is_new else "duplicate", "id": str(row.id)}


async def _partner_for_user(
    db: AsyncSession, company_id: str, code: str, user: User,
) -> tuple[uuid.UUID, PartnerSpace]:
    cid = await assert_company_member(company_id, user, db)
    partner = await partner_bridge.get_partner(db, cid, code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{code}» не заведено")
    return cid, partner


@router.get("/partner-space/spaces")
async def partner_spaces(
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """С какими пространствами связано это: кто они нам и включена ли связь."""
    cid = await assert_company_member(company_id, user, db)
    res = await db.execute(select(PartnerSpace).where(
        PartnerSpace.company_id == cid).order_by(PartnerSpace.name))
    return {"items": [{
        "code": p.code, "name": p.name or p.code, "role": p.role,
        "baseUrl": p.base_url, "isActive": p.is_active,
        # Ключ не показываем и показывать не будем — только то, включена ли связь.
        "linked": bool(p.base_url and partner_bridge.partner_key(p)),
        "lastSeenAt": p.last_seen_at.isoformat() if p.last_seen_at else None,
    } for p in res.scalars().all()]}


@router.get("/partner-space/{code}/feed")
async def partner_feed(
    code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Переписка с этим пространством."""
    cid, partner = await _partner_for_user(db, company_id, code, user)
    return {
        "partner": {"code": partner.code, "name": partner.name or partner.code,
                    "role": partner.role,
                    "linked": bool(partner.base_url and partner_bridge.partner_key(partner))},
        "messages": await partner_bridge.feed(db, cid, partner),
    }


@router.post("/partner-space/{code}/message")
async def partner_send(
    code: str,
    payload: OutgoingMessage,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Написать в другое пространство от своего имени."""
    cid, partner = await _partner_for_user(db, company_id, code, user)
    if not payload.body.strip():
        raise HTTPException(400, "Пустое сообщение")
    # Свой код пространства — им получатель нас узнаёт. Берём slug компании,
    # он же код стека: другого имени у пространства нет.
    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    row = await partner_bridge.send(
        db, cid, partner, self_code=self_code, body=payload.body,
        author_email=user.email, author_name=user.name or user.email,
        subject_kind=payload.subject_kind, subject_ref=payload.subject_ref,
    )
    return {
        "id": str(row.id),
        "delivered": row.delivered_at is not None,
        # Ошибку доставки отдаём человеку сразу: он должен знать, что сообщение
        # осталось у нас, а не думать, что оно ушло.
        "error": row.delivery_error,
    }
