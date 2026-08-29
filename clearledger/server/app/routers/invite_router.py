"""Приглашение на встречу для того, у кого нет учётной записи.

Зачем это нужно. Партнёр, подрядчик или представитель заказчика не заведёт себе
учётку ради одного совещания, а позвать его надо, и ответ его получить тоже.

Почему не «пользователь с флагом». Почтовый участник (`users.mail_only`)
существует ради чата: он состоит в компании и виден в её составе. Завести такого
ради приглашения значит выдать человеку место в пространстве за одну встречу — и
однажды забыть его там.

**У гостя нет календаря.** У него есть страница встречи. Это не ограничение
интерфейса, а граница в коде: календарь с фильтрами течёт при первой забытой
проверке, отдельная скупая ручка — нет. Здесь гость видит одну встречу, отвечает,
предлагает другое время и забирает `.ics`; материалы — только те, что открыли
явно, и каждый по своей ссылке со своими правами.

На «нет», «отозвана» и «встреча отменена» ответ одинаковый там, где это возможно:
подсказывать, что ссылка когда-то существовала, незачем.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    CalendarEvent, CalendarGuest, CalendarMaterial, User,
)
from app.services import ics

router = APIRouter(prefix="/invite", tags=["Приглашение"])


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Хеш токена — то, что хранится в базе вместо него самого."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def _guest_or_404(db: AsyncSession, token: str) -> tuple[CalendarGuest, CalendarEvent]:
    guest = (await db.execute(select(CalendarGuest).where(
        CalendarGuest.token_hash == token_hash(token),
        CalendarGuest.revoked_at.is_(None)))).scalar_one_or_none()
    if guest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    ev = await db.get(CalendarEvent, guest.event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    return guest, ev


def _out(guest: CalendarGuest, ev: CalendarEvent, organizer: User | None,
         materials: list[CalendarMaterial]) -> dict[str, Any]:
    return {
        "title": ev.title,
        "description": ev.description,
        "starts_at": ev.starts_at,
        "ends_at": ev.ends_at,
        "all_day": ev.all_day,
        "tz": ev.tz,
        "location": ev.location,
        # Ссылка на видеовстречу гостевая, не модераторская: рассылать
        # модераторскую значит отдать права ведущего всем, кого позвали.
        "conference_url": ev.conference_url,
        "cancelled": ev.status == "cancelled",
        "cancel_reason": ev.cancel_reason,
        "organizer": organizer.name if organizer else None,
        # Состав встречи гостю не показываем: кто ещё позван — сведение о
        # компании, а не о его участии.
        "you": {
            "name": guest.name,
            "email": guest.email,
            "response": guest.response,
            "comment": guest.comment,
            "proposed_starts_at": guest.proposed_starts_at,
            "proposed_ends_at": guest.proposed_ends_at,
        },
        "materials": [{
            "title": m.title, "url": m.share_url,
        } for m in materials if m.share_url],
    }


@router.get("/{token}")
async def invite_card(token: str, db: AsyncSession = Depends(get_db)):
    """Карточка встречи для гостя."""
    guest, ev = await _guest_or_404(db, token)
    if guest.opened_at is None:
        guest.opened_at = datetime.now(timezone.utc)
        await db.commit()
    organizer = await db.get(User, ev.organizer_id)
    materials = list((await db.execute(select(CalendarMaterial).where(
        CalendarMaterial.event_id == ev.id))).scalars())
    return _out(guest, ev, organizer, materials)


class RsvpIn(BaseModel):
    response: str = Field(pattern="^(accepted|declined|tentative)$")
    comment: str | None = Field(None, max_length=300)


@router.post("/{token}/respond")
async def invite_respond(token: str, payload: RsvpIn,
                         db: AsyncSession = Depends(get_db)):
    """Ответ гостя: буду · может быть · не буду."""
    guest, ev = await _guest_or_404(db, token)
    if ev.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Встреча отменена")
    guest.response = payload.response
    guest.comment = (payload.comment or "").strip() or None
    guest.responded_at = datetime.now(timezone.utc)
    await db.commit()
    return {"response": guest.response}


class ProposeIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    comment: str | None = Field(None, max_length=300)


@router.post("/{token}/propose")
async def invite_propose(token: str, payload: ProposeIn,
                         db: AsyncSession = Depends(get_db)):
    """Предложить другое время.

    Само по себе предложение ничего не двигает: перенос — решение организатора.
    Гость при этом считается отказавшимся от предложенного часа, иначе в составе
    он выглядел бы согласившимся на время, которое сам же просит поменять.
    """
    guest, ev = await _guest_or_404(db, token)
    if ev.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Встреча отменена")
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Конец не может быть раньше начала")
    guest.proposed_starts_at = payload.starts_at
    guest.proposed_ends_at = payload.ends_at
    guest.response = "declined"
    guest.comment = (payload.comment or "").strip() or None
    guest.responded_at = datetime.now(timezone.utc)
    await db.commit()
    return {"proposed_starts_at": guest.proposed_starts_at,
            "proposed_ends_at": guest.proposed_ends_at}


@router.get("/{token}/ics")
async def invite_ics(token: str, db: AsyncSession = Depends(get_db)):
    """Файл для чужого календаря.

    Без него приглашение живёт только в почте: человек прочтёт письмо и в нужный
    час будет занят другим.
    """
    guest, ev = await _guest_or_404(db, token)
    organizer = await db.get(User, ev.organizer_id)
    текст = ics.event_ics(
        uid=f"{ev.id}@trek.elsyplus",
        title=ev.title, starts_at=ev.starts_at, ends_at=ev.ends_at,
        description=ev.description, location=ev.location,
        url=ev.conference_url,
        organizer_email=organizer.email if organizer else None,
        organizer_name=organizer.name if organizer else None,
        cancelled=ev.status == "cancelled",
        # Отменённая уходит с большим номером: тем же UID и большим SEQUENCE
        # чужой календарь убирает встречу, а новым UID оставил бы обе.
        sequence=1 if ev.status == "cancelled" else 0)
    return Response(
        content=текст, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="meeting.ics"'})
