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

import json
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import (
    assert_company_member, create_access_token, get_company_by_api_key, get_current_user,
    hash_password,
)
from app.database import get_db
from app.models import Company, PartnerSpace, User, UserCompany
from app.services import partner_bridge, sso, support_mirror

router = APIRouter(tags=["Пространства-партнёры"])


class OutgoingMessage(BaseModel):
    body: str
    subject_kind: str | None = None
    subject_ref: str | None = None


class GuestVisit(BaseModel):
    """Пропуск, с которым сотрудник партнёра входит в это пространство."""

    token: str
    space: str


class SupportReply(BaseModel):
    """Ответ оператора, который Координатор просит доставить в пространство клиента."""

    partner_code: str
    body: str
    author_name: str | None = None
    author_email: str | None = None
    external_id: str | None = None


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


@router.post("/eco/partner/outgoing")
async def support_reply(
    payload: SupportReply,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ответ поддержки — в пространство клиента.

    Обращение клиента доезжает до очереди Координатора зеркалом, и отвечает
    оператор там же, где отвечает на звонки и письма. Но связь с чужим
    пространством — адрес, ключ и лента — живёт в Ядре, и второй такой связи у
    Координатора нет и заводить её незачем: он просит доставить, Ядро доставляет.

    Зовут отсюда очередью с ретраями, поэтому `external_id` обязателен по смыслу:
    без него повтор положит клиенту ту же реплику второй раз.
    """
    body = payload.body.strip()
    if not body:
        raise HTTPException(400, "Пустое сообщение")
    partner = await partner_bridge.get_partner(db, company.id, payload.partner_code)
    if partner is None:
        raise HTTPException(404, f"Пространство «{payload.partner_code}» здесь не заведено")

    self_code = (await db.execute(
        select(Company.slug).where(Company.id == company.id))).scalar_one()
    row = await partner_bridge.send(
        db, company.id, partner, self_code=self_code, body=body,
        author_email=payload.author_email, author_name=payload.author_name,
        external_id=payload.external_id,
    )
    # Недоставленное — не отказ приёма: реплика записана в ленте, и повтор её не
    # продублирует. Но звавшему говорим правду, чтобы очередь попробовала снова.
    if row.delivery_error:
        raise HTTPException(502, row.delivery_error)
    return {"status": "sent", "id": str(row.id)}


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


@router.post("/partner-space/{code}/visit")
async def partner_visit(
    code: str,
    company_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Выписать себе пропуск в пространство клиента.

    Инженер работает у клиента своей учётной записью, а не заведённой в его
    контуре: учёток столько же, сколько клиентов, и каждая живёт своей жизнью —
    человек ушёл, а доступ остался. Пропуск живёт две минуты и выписывается на
    одно пространство: открытый к одному клиенту, он не откроет дверь к другому.
    """
    cid, partner = await _partner_for_user(db, company_id, code, user)
    # Пропуск выписывают своим. Внешний участник допущен в НАШЕ пространство, а не
    # в пространство нашего клиента: там он никто, и открывать ему дверь нечем.
    membership = await db.get(UserCompany, (user.id, cid))
    if membership is not None and membership.party_type == "partner":
        raise HTTPException(403, "Пропуск выписывается сотрудникам пространства")
    if not partner.is_active:
        raise HTTPException(409, "Связь с этим пространством выключена")
    if not partner.base_url:
        raise HTTPException(409, "У пространства не задан адрес")

    self_code = (await db.execute(select(Company.slug).where(Company.id == cid))).scalar_one()
    token = sso.sign_visit_token(user=user, space_code=partner.code, self_code=self_code)
    if not token:
        raise HTTPException(503, "Единый вход не настроен: нет ключа подписи")

    # Кто и куда ходил — вопрос, который задаст заказчик, и ответ на него должен
    # быть у нас, а не только у него.
    await log_audit(db, actor=user, company_id=cid, action="partner.visit",
                    target=partner.code)
    await db.commit()
    base = partner.base_url.rstrip("/")
    return {
        "url": f"{base}{partner_bridge.VISIT_PATH}#token={token}&space={self_code}",
        "space": partner.code,
        "name": partner.name or partner.code,
    }


@router.post("/eco/partner/visit")
async def accept_visit(
    payload: GuestVisit,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Впустить сотрудника партнёра по его пропуску.

    Сессии здесь нет и быть не может — человек как раз за ней и пришёл. Доверие
    держится на двух вещах: пропуск подписан ключом того пространства, которое у
    нас заведено, и заведено оно нами же, с ролью поставщика. Выключили запись —
    вход закрылся, и заводить у себя учётки для этого не нужно.

    Учётка гостя всё же появляется — иначе его действия некому приписать в
    журнале. Но заводит её вход, а не человек руками, и помечена она как инженер
    платформы: в составе пространства такой участник виден отдельной группой.
    """
    code = payload.space.strip()
    if not code:
        raise HTTPException(400, "Не указано пространство, выдавшее пропуск")

    partner = (await db.execute(select(PartnerSpace).where(
        PartnerSpace.code == code, PartnerSpace.role == "vendor",
        PartnerSpace.is_active.is_(True),
    ))).scalars().first()
    if partner is None:
        raise HTTPException(403, f"Пространство «{code}» здесь не заведено как поставщик")

    company = await db.get(Company, partner.company_id)
    keys = await partner_bridge.partner_jwks(partner)
    claims = _verify_visit(payload.token, keys, audience=f"space:{company.slug}")

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "В пропуске нет адреса сотрудника")

    guest = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if guest is None:
        # Пароля у такой учётки нет по смыслу: входят по пропуску, а не паролем.
        # Случайный хеш вместо пустого — чтобы «войти никак» не значило «войти без пароля».
        guest = User(email=email, name=claims.get("name") or email, role="user",
                     password_hash=hash_password(secrets.token_urlsafe(24)))
        db.add(guest)
        await db.flush()

    membership = await db.get(UserCompany, (guest.id, company.id))
    if membership is None:
        membership = UserCompany(user_id=guest.id, company_id=company.id, role="user",
                                 party_type="vendor")
        db.add(membership)
    elif membership.party_type != "vendor":
        # Человека могли завести здесь и руками. Права его при этом не трогаем:
        # что клиент выдал, то и остаётся, — но принадлежность говорим честно.
        membership.party_type = "vendor"

    await log_audit(db, actor=guest, company_id=company.id, action="partner.guest_in",
                    target=partner.code)
    await db.commit()
    return {
        "access_token": create_access_token(str(guest.id), guest.email),
        "token_type": "bearer",
        "company_id": str(company.id),
        "space": company.slug,
        "name": guest.name,
    }


def _verify_visit(token: str, jwks: dict[str, Any], *, audience: str) -> dict[str, Any]:
    """Проверить пропуск публичным ключом выдавшего пространства."""
    from jwt import PyJWTError, decode, get_unverified_header
    from jwt.algorithms import RSAAlgorithm

    try:
        kid = get_unverified_header(token).get("kid")
    except PyJWTError as e:
        raise HTTPException(400, f"Пропуск не читается: {e}") from e
    keys = jwks.get("keys") or []
    # Ключ по kid, а при единственном — он же: `kid` у стеков совпадает по
    # соглашению имени, и упереться в него значило бы не пустить никого.
    jwk = next((k for k in keys if k.get("kid") == kid), keys[0] if len(keys) == 1 else None)
    if jwk is None:
        raise HTTPException(403, "Ключ, которым подписан пропуск, у пространства не найден")
    try:
        return decode(token, RSAAlgorithm.from_jwk(json.dumps(jwk)),
                      algorithms=["RS256"], audience=audience)
    except PyJWTError as e:
        raise HTTPException(403, f"Пропуск отклонён: {e}") from e
