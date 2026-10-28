"""Личные теги: цветные пометки человека на встречах, поручениях и документах.

Видит их только хозяин (решение МАГа 28.10.2026): тег не меняет предмет ни для
кого, поэтому повесить его можно и на чужую встречу, и на чужое поручение.
Общий для всех ярлык уже есть — метка компании в «Треке», второй такой не нужен.

Список отдаётся целиком, вместе со всеми привязками: тегов у человека десятки,
привязок — сотни, а нужны они везде сразу (покрасить календарь, отфильтровать
список). ponytail: всё одним ответом; разбивать по предметам, когда у кого-то
привязок станет десятки тысяч.
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import PersonalTag, PersonalTagLink, User
from app.routers.work_router import _assert_work, _uuid_or_400

router = APIRouter(prefix="/work", tags=["Трек"])

# Тона палитры фронта (src/lib/tagTones.ts). Свободный цвет не принимаем: он
# обязан читаться и в светлой, и в тёмной теме.
ТОНА = ("slate", "blue", "teal", "green", "amber", "orange", "red", "violet")
# Что можно пометить. Чаты — следующим выпуском (`chat_msg:`, `chat_room:`).
ПРЕДМЕТ = re.compile(r"^(event|task|doc):[0-9a-f-]{36}$")
ПРЕДЕЛ_ТЕГОВ = 100


class TagIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=40)
    color: str = "blue"


class TagAction(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=40)
    color: str | None = None
    delete: bool = False


class AssignIn(BaseModel):
    company_id: str
    target_ref: str
    tag_ids: list[str] = Field(default_factory=list, max_length=ПРЕДЕЛ_ТЕГОВ)


def _out(t: PersonalTag) -> dict:
    return {"id": str(t.id), "name": t.name, "color": t.color, "position": t.position}


def _тон(color: str | None) -> str:
    if color not in ТОНА:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Такого цвета нет в палитре")
    return color


async def _мои(db: AsyncSession, cid: uuid.UUID, user: User) -> list[PersonalTag]:
    return list((await db.execute(select(PersonalTag).where(
        PersonalTag.company_id == cid, PersonalTag.user_id == user.id)
        .order_by(PersonalTag.position, PersonalTag.name))).scalars())


@router.get("/tags")
async def tags_mine(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Мои теги и на чём они висят: `links` — предмет → список id тегов."""
    cid = await _assert_work(company_id, current_user, db)
    теги = await _мои(db, cid, current_user)
    links: dict[str, list[str]] = {}
    if теги:
        for tag_id, ref in (await db.execute(select(PersonalTagLink.tag_id, PersonalTagLink.target_ref)
                                             .where(PersonalTagLink.tag_id.in_([t.id for t in теги])))).all():
            links.setdefault(ref, []).append(str(tag_id))
    return {"tags": [_out(t) for t in теги], "links": links}


@router.post("/tags", status_code=status.HTTP_201_CREATED)
async def tag_create(
    payload: TagIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    имя = payload.name.strip()
    if not имя:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У тега должно быть имя")
    теги = await _мои(db, cid, current_user)
    if any(t.name.lower() == имя.lower() for t in теги):
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой тег уже есть")
    if len(теги) >= ПРЕДЕЛ_ТЕГОВ:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Тегов не больше {ПРЕДЕЛ_ТЕГОВ}")
    row = PersonalTag(company_id=cid, user_id=current_user.id, name=имя,
                      color=_тон(payload.color), position=len(теги))
    db.add(row)
    await db.commit()
    return _out(row)


@router.post("/tags/{tag_id}")
async def tag_action(
    tag_id: str,
    payload: TagAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Переименовать, перекрасить или удалить. Удаление снимает тег со всех
    предметов, сами предметы не трогает."""
    cid = await _assert_work(payload.company_id, current_user, db)
    row = await db.get(PersonalTag, _uuid_or_400(tag_id, "tag_id"))
    if row is None or row.company_id != cid or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тег не найден")
    if payload.delete:
        await db.delete(row)
        await db.commit()
        return {"deleted": True}
    if payload.name is not None:
        имя = payload.name.strip()
        занято = (await db.execute(select(func.count()).select_from(PersonalTag).where(
            PersonalTag.company_id == cid, PersonalTag.user_id == current_user.id,
            func.lower(PersonalTag.name) == имя.lower(), PersonalTag.id != row.id))).scalar_one()
        if not имя or занято:
            raise HTTPException(status.HTTP_409_CONFLICT, "Такой тег уже есть")
        row.name = имя
    if payload.color is not None:
        row.color = _тон(payload.color)
    await db.commit()
    return _out(row)


@router.post("/tags-assign")
async def tags_assign(
    payload: AssignIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Теги предмета целиком: что пришло — то и висит, остальные мои снимаются."""
    cid = await _assert_work(payload.company_id, current_user, db)
    ref = payload.target_ref.strip().lower()
    if not ПРЕДМЕТ.match(ref):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот предмет пометить нельзя")
    мои = {t.id: t for t in await _мои(db, cid, current_user)}
    хочу = {_uuid_or_400(i, "tag_ids") for i in payload.tag_ids}
    if хочу - set(мои):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тег не найден")
    if мои:
        await db.execute(delete(PersonalTagLink).where(
            PersonalTagLink.target_ref == ref, PersonalTagLink.tag_id.in_(list(мои))))
    for tag_id in хочу:
        db.add(PersonalTagLink(tag_id=tag_id, target_ref=ref))
    await db.commit()
    return {"target_ref": ref, "tag_ids": sorted(str(i) for i in хочу)}
