"""Чат экосистемы на Matrix (модель «как в Ангаре») — REST /api/mchat/*.

Плоская модель: сессия (mint per-user токен), группы (комнаты + своя таблица), личка,
папки, публичные комнаты, поиск людей. Сообщения/треды-темы живут в Matrix (клиент
`matrix-js-sdk`), сюда не проксируются. Всё скоупится по ВЫБРАННОЙ компании
(`X-Company-Id`) — строгая изоляция пространств (Ур. 2). Параллельно старому /chat.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import User
from app.services import matrix_chat as mc

settings = get_settings()

router = APIRouter(prefix="/mchat", tags=["Чат (Matrix)"],
                   dependencies=[Depends(capture_company_header)])


def _require_chat() -> None:
    if not settings.chat_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Чат не настроен (нет Matrix)")


# ── сессия ──

@router.get("/session")
async def session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Выдать браузеру сессию Matrix (публичный homeserver + mxid + свежий per-user токен)."""
    _require_chat()
    return await mc.issue_session(db, user)


# ── группы ──

class GroupCreate(BaseModel):
    title: str = Field(..., max_length=120)
    participantIds: list[uuid.UUID] = Field(default_factory=list)
    isPublic: bool = False


@router.get("/groups")
async def list_groups(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return {"rooms": await mc.list_my_group_rooms(db, cid, user)}


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return await mc.create_group_room(db, cid, user, payload.title, payload.participantIds, payload.isPublic)


# ── личные сообщения ──

@router.post("/dm")
async def open_dm(other_user_id: uuid.UUID = Body(..., embed=True, alias="userId"),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    try:
        room_id = await mc.ensure_dm_room(db, cid, user, other_user_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return {"roomId": room_id}


# ── публичные комнаты ──

@router.get("/public")
async def public_rooms(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return {"rooms": await mc.list_public_rooms(db, cid)}


@router.post("/join")
async def join_room(room_id: str = Body(..., embed=True, alias="roomId"),
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    try:
        await mc.join_public_room(db, cid, user, room_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return {"roomId": room_id, "joined": True}


# ── папки ──

class FolderPayload(BaseModel):
    name: str | None = Field(None, max_length=40)
    roomIds: list[str] | None = None
    order: list[uuid.UUID] | None = None   # переупорядочивание (PATCH)


@router.get("/folders")
async def get_folders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return {"folders": await mc.list_folders(db, cid, user)}


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def add_folder(payload: FolderPayload,
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return await mc.create_folder(db, cid, user, payload.name or "", payload.roomIds or [])


@router.patch("/folders/{folder_id}")
async def patch_folder(folder_id: uuid.UUID, payload: FolderPayload,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    if payload.order is not None:
        await mc.reorder_folders(db, cid, user, payload.order)
        return {"ok": True}
    ok = await mc.update_folder(db, cid, user, folder_id, payload.name, payload.roomIds)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
    return {"ok": True}


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_folder(folder_id: uuid.UUID,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    await mc.delete_folder(db, cid, user, folder_id)


# ── люди ──

@router.get("/people")
async def people(q: str = Query(""),
                 user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_chat()
    cid = await scope_company_id(user, db)
    return {"people": await mc.search_people(db, cid, q, user.id)}
