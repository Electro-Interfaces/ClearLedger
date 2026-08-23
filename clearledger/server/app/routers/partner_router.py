"""Партнёр в процессе: чужая система согласует наш документ, не входя в пространство.

Внешний участник у нас уже был — человек, которому уходит одноразовая ссылка на
почту. Он работает, пока по ту сторону человек. Учётная система контрагента,
шлюз оператора или служба заказчика письмо не читают и по ссылке не кликают: им
нужен свой вход, свой ключ и предсказуемый ответ.

Модель отношений — «мы внутри системы, они её часть»: партнёр видит ровно один
документ, ровно на тот срок, пока открыт его шаг, и ровно те поля, что нужны для
решения. Учётной записи ему не заводим — она дала бы доступ ко всему остальному
пространству, а нужен один шаг одного маршрута.

Опознаётся именным ключом (`SpaceInboundKey`, заголовок `X-Cloud-API-Key`): в
базе только SHA-256, отозвать одного можно, не трогая остальных, и в журнале
видно, кто именно приходил.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    DocApproval, DocCard, DocEvent, DocKind, DocVersion, SpaceInboundKey,
)
from app.services import doc_approvals

router = APIRouter(prefix="/partner", tags=["Партнёр"])


class PartnerActor:
    """Кто поставил визу, когда по ту сторону не человек.

    `doc_approvals.decide` ждёт объект с `id`, `name` и `email` — тех же полей,
    что у пользователя. Для партнёра `id` пуст: в следе документа честнее видеть
    название системы, чем выдуманную учётку, которой не существует.
    """

    def __init__(self, key: SpaceInboundKey, signer: str | None = None):
        self.id = None
        self.email = None
        who = (signer or "").strip()
        self.name = (f"{key.consumer} — {who}" if who
                     else f"{key.consumer} (партнёр)")


async def partner_key(
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> SpaceInboundKey:
    """Опознать партнёра по именному ключу.

    Легаси-ключ компании здесь не принимается намеренно, в отличие от общей
    аутентификации внешних систем: он один на всех потребителей, и по нему
    невозможно сказать, КТО поставил визу. Для приёма данных это терпимо, для
    подписи под документом — нет.
    """
    key_hash = hashlib.sha256(x_cloud_api_key.encode()).hexdigest()
    key = (await db.execute(select(SpaceInboundKey).where(
        SpaceInboundKey.key_hash == key_hash,
        SpaceInboundKey.revoked_at.is_(None)))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Ключ партнёра не опознан")
    key.last_used_at = datetime.now(timezone.utc)
    return key


async def _open_approval(db: AsyncSession, key: SpaceInboundKey,
                         doc_id: uuid.UUID) -> DocApproval:
    """Открытый шаг этого партнёра по этому документу — или 404.

    Не «есть ли документ», а «ждут ли от него решения прямо сейчас». Разница
    существенна: иначе по ключу можно было бы читать любой документ компании,
    достаточно угадать идентификатор.
    """
    row = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == key.company_id,
        DocApproval.doc_id == doc_id,
        DocApproval.actor_kind == "partner",
        DocApproval.actor_ref == str(key.id),
        DocApproval.status == "pending"))).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Документ не найден или решение по нему не ожидается")
    return row


async def _projection(db: AsyncSession, doc: DocCard,
                      approval: DocApproval) -> dict[str, Any]:
    """Что партнёр видит. Реквизиты и текущие файлы — не карточка целиком.

    Наружу не уходят внутренняя переписка, лист согласования, права, история и
    гриф: партнёру нужно понять, что он согласует, а не как у нас устроена
    работа.
    """
    kind_name = await db.scalar(select(DocKind.name).where(DocKind.id == doc.kind_id))
    files = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id,
        DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None),
        DocVersion.archive_purged_at.is_(None)))).scalars().all()
    return {
        "id": str(doc.id),
        "kind": kind_name,
        "title": doc.title,
        "summary": doc.summary,
        "reg_number": doc.reg_number,
        "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
        "counterparty_name": doc.counterparty_name or None,
        "subject_ref": doc.subject_ref,
        "step": {
            "code": approval.step_code,
            "name": approval.step_name,
            "round": approval.round,
            "due_at": approval.due_at.isoformat() if approval.due_at else None,
        },
        "files": [{
            "id": str(version.file_id),
            "name": version.file_name,
            "size_bytes": version.size_bytes,
            "sha256": version.sha256,
        } for version in files],
    }


@router.get("/documents")
async def pending_documents(
    key: SpaceInboundKey = Depends(partner_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Что ждёт решения этого партнёра.

    Очередь, а не уведомление: партнёрская система может опрашивать нас сама, и
    так ей не нужно ни хранить состояние, ни бояться пропустить событие. Кому
    удобнее подписка — есть шина событий.
    """
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == key.company_id,
        DocApproval.actor_kind == "partner",
        DocApproval.actor_ref == str(key.id),
        DocApproval.status == "pending").order_by(
            DocApproval.due_at.asc().nullslast(),
            DocApproval.activated_at))).scalars().all()
    out = []
    for approval in rows:
        doc = await db.get(DocCard, approval.doc_id)
        if doc is not None:
            out.append(await _projection(db, doc, approval))
    await db.commit()
    return {"documents": out, "count": len(out)}


@router.get("/documents/{doc_id}")
async def partner_document(
    doc_id: str,
    key: SpaceInboundKey = Depends(partner_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        ident = uuid.UUID(doc_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный doc_id")
    approval = await _open_approval(db, key, ident)
    doc = await db.get(DocCard, ident)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    out = await _projection(db, doc, approval)
    await db.commit()
    return out


class PartnerDecisionIn(BaseModel):
    approved: bool
    # Кто именно решил на стороне партнёра. Не обязательно, но если система это
    # знает — в лист согласования попадёт человек, а не только имя системы.
    signer: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=2000)


@router.post("/documents/{doc_id}/decide")
async def partner_decide(
    doc_id: str,
    payload: PartnerDecisionIn,
    request: Request,
    key: SpaceInboundKey = Depends(partner_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Решение партнёра по открытому шагу.

    Отказ без причины не принимаем — то же правило, что и для своих: возврат без
    объяснения бессмыслен, автор не поймёт, что править.
    """
    try:
        ident = uuid.UUID(doc_id)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный doc_id")
    comment = (payload.comment or "").strip() or None
    if not payload.approved and not comment:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "При отказе нужна причина")

    approval = await _open_approval(db, key, ident)
    doc = await db.get(DocCard, ident)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")

    actor = PartnerActor(key, payload.signer)
    # Обстоятельства решения пишем в след ДО самого решения: оно может закрыть
    # круг и увести документ дальше, а откуда пришёл ответ — относится к этому
    # моменту.
    db.add(DocEvent(
        doc_id=doc.id, kind="approval", user_id=None, actor_name=actor.name,
        # Род действующего берём у ключа: по одной подписи «Аудитор Поддержки»
        # не отличить чужую систему от нашего агента, а спрашивать с них
        # по-разному.
        actor_kind=key.actor_kind,
        to_value=("решение агента" if key.actor_kind == "agent"
                  else "решение партнёра"),
        note=f"ключ {key.key_prefix}…, адрес "
             f"{request.client.host if request.client else 'неизвестен'}"))
    result = await doc_approvals.decide(
        db, key.company_id, doc, approval, actor, payload.approved, comment)
    if result.get("error"):
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, result["error"])
    await db.commit()
    return {"status": result.get("status"),
            "decided_at": datetime.now(timezone.utc).isoformat()}
