"""Узкие входы Поддержки: native Core chat и private ticket video."""
from __future__ import annotations

import uuid
from typing import Literal
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import App, AppCompanyLink, TicketVideoRoom, User, UserCompany
from app.services import jitsi
from app.services.ticket_communications import access, ensure_staff_room


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/support/tickets", tags=["Взаимодействие по заявке"],
    dependencies=[Depends(no_store)],
)


class TicketCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supportCompanyId: uuid.UUID


class CommunicationBinding(BaseModel):
    coreCompanyId: uuid.UUID
    supportCompanyId: uuid.UUID
    actorCoreUserId: uuid.UUID


class TicketChatOut(CommunicationBinding):
    roomId: uuid.UUID
    roomRef: str


class TicketVideoOut(CommunicationBinding):
    roomRef: str
    joinUrl: str
    moderator: bool
    expiresIn: Literal[120]


class StaffCandidate(BaseModel):
    coreUserId: uuid.UUID
    name: str


class StaffCandidatesOut(BaseModel):
    candidates: list[StaffCandidate]


class PrivateVideoUnavailable(BaseModel):
    code: Literal["private_video_unavailable"]
    message: str


class CommunicationUnavailable(BaseModel):
    detail: str | PrivateVideoUnavailable


def require_private_video():
    unavailable = HTTPException(503, {
        "code": "private_video_unavailable",
        "message": "Приватная видеосвязь заявки не настроена",
    })
    if not settings.jitsi_ticket_private_enabled or not settings.jitsi_enabled:
        raise unavailable
    try:
        key = jitsi._private_key()
        if not key or not isinstance(
            serialization.load_pem_private_key(key.encode(), password=None), RSAPrivateKey
        ):
            raise ValueError()
    except Exception:
        raise unavailable from None


async def _scope(db, support_cid):
    rows = (await db.execute(
        select(AppCompanyLink.company_id).join(App, App.id == AppCompanyLink.app_id)
        .where(App.code == "support", AppCompanyLink.external_company_id == str(support_cid))
        .limit(2)
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "Нет привязки компании Поддержки")
    if len(rows) != 1:
        raise HTTPException(409, "Неоднозначная привязка компании Поддержки")
    return rows[0]


@router.post("/{ticket_id}/chat", response_model=TicketChatOut)
async def ticket_chat(
    ticket_id: uuid.UUID, body: TicketCompany,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await _scope(db, body.supportCompanyId)
    room = await ensure_staff_room(db, cid, current_user, ticket_id)
    await access(db, cid, current_user, ticket_id, event={
        "kind": "staff_chat", "roomRef": f"core:chat:{room.id}",
    })
    return {
        "roomId": str(room.id), "roomRef": f"core:chat:{room.id}",
        "coreCompanyId": str(cid), "supportCompanyId": str(body.supportCompanyId),
        "actorCoreUserId": str(current_user.id),
    }


@router.post(
    "/{ticket_id}/video", response_model=TicketVideoOut,
    responses={503: {"model": CommunicationUnavailable}},
)
async def ticket_video(
    ticket_id: uuid.UUID, body: TicketCompany,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await _scope(db, body.supportCompanyId)
    proof = await access(db, cid, current_user, ticket_id)
    if not proof["canVideo"]:
        raise HTTPException(403, "Нет доступа к видеосвязи заявки")
    require_private_video()  # Before any durable room or Support trace.
    room_ref = f"ticket:{ticket_id}"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"ticket-video:{cid}:{ticket_id}"},
    )
    binding = await db.scalar(select(TicketVideoRoom).where(
        TicketVideoRoom.company_id == cid, TicketVideoRoom.ticket_id == ticket_id,
    ))
    if binding is None:
        binding = TicketVideoRoom(
            company_id=cid, ticket_id=ticket_id,
            room=jitsi.room_for(room_ref), created_by=current_user.id,
        )
        db.add(binding)
        await db.flush()
    room = binding.room
    await db.commit()
    # Waiting for a concurrent binding must not preserve stale staff privileges.
    proof = await access(db, cid, current_user, ticket_id)
    try:
        token = jitsi.sign_token(
            room, current_user.name, moderator=proof["canStaffChat"], ttl_seconds=120,
        )
        if not token:
            raise ValueError()
    except Exception:
        raise HTTPException(503, {
            "code": "private_video_unavailable",
            "message": "Приватная видеосвязь заявки не настроена",
        }) from None
    recorded = await access(db, cid, current_user, ticket_id, event={
        "kind": "video", "roomRef": room_ref,
    })
    if recorded["canStaffChat"] != proof["canStaffChat"]:
        # Never return a moderator token when the final ACL check became client-only.
        raise HTTPException(403, "Права изменились. Откройте видеосвязь заново")
    return {
        "roomRef": room_ref,
        "joinUrl": f"https://{settings.jitsi_domain}/{quote(room)}?jwt={token}",
        "moderator": proof["canStaffChat"], "expiresIn": 120,
        "coreCompanyId": str(cid), "supportCompanyId": str(body.supportCompanyId),
        "actorCoreUserId": str(current_user.id),
    }


@router.post("/{ticket_id}/staff-candidates", response_model=StaffCandidatesOut)
async def staff_candidates(
    ticket_id: uuid.UUID, body: TicketCompany,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await _scope(db, body.supportCompanyId)
    candidates = await access(db, cid, current_user, ticket_id, candidates=True)
    result = []
    for candidate in candidates["candidates"]:
        try:
            uid = uuid.UUID(candidate["coreUserId"])
        except (ValueError, TypeError):
            raise HTTPException(503, "Поддержка не подтвердила участников") from None
        user = await db.get(User, uid)
        if (user is not None and not user.mail_only
                and await db.get(UserCompany, (uid, cid)) is not None):
            result.append({"coreUserId": str(uid), "name": user.name})
    return {"candidates": result}
