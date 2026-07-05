"""Видеоконференции TradeLedger — создание Jitsi-встречи (модераторская + гостевая ссылки)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.config import get_settings
from app.models import User
from app.services import jitsi

settings = get_settings()
router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("/config")
async def meetings_config(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Доступны ли конференции (для показа кнопки на фронте)."""
    return {"enabled": settings.jitsi_enabled, "domain": settings.jitsi_domain}


@router.post("")
async def create_meeting(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Создать видеоконференцию: случайная комната + ссылки организатора и гостя.

    Организатор открывает `moderator_url` (с токеном), `guest_url` рассылает участникам —
    они входят гостями, когда организатор уже в комнате."""
    if not settings.jitsi_enabled:
        raise HTTPException(503, "Видеоконференции не настроены (нет ключа подписи)")
    room = jitsi.new_room()
    return jitsi.meeting_urls(room, current_user.name)
