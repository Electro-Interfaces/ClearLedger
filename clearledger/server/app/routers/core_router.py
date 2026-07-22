"""ElsyPlus Core — состояние Ядра и платформенных сервисов (для «Центра управления»).

Даёт администратору экосистемы мгновенную картину: версия/окружение, статус SSO,
объём реестра приложений, счётчики компаний/пользователей и состояние платформенных
сервисов (чат/конференции/почта — подключены? живы?). Только суперадмин экосистемы.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import App, AppModule, Company, User
from app.services import sso

router = APIRouter(prefix="/core", tags=["ElsyPlus Core — состояние"])
settings = get_settings()


def _require_super(user: User) -> None:
    """Состояние экосистемы — только суперадмину (Ур. 1)."""
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права суперадминистратора экосистемы")


async def _chat_status() -> str:
    """Пинг Matrix homeserver: up/down/not_configured."""
    url = settings.synapse_url
    if not url:
        return "not_configured"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(url.rstrip("/") + "/health")
            return "up" if r.status_code == 200 else "down"
    except Exception:  # noqa: BLE001 — недоступность = down, не роняем статус
        return "down"


@router.get("/status")
async def core_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сводное состояние Ядра и платформенных сервисов экосистемы."""
    _require_super(user)
    from app.main import APP_VERSION  # lazy — избегаем циклического импорта

    jwks = sso.public_jwks()

    async def _count(model) -> int:
        return int((await db.execute(select(func.count()).select_from(model))).scalar() or 0)

    apps_n = await _count(App)
    mods_n = await _count(AppModule)
    comp_n = await _count(Company)
    user_n = await _count(User)

    services = [
        {"code": "chat", "name": "Чат (Matrix)",
         "configured": bool(settings.synapse_url), "status": await _chat_status()},
        {"code": "conf", "name": "Конференции (Jitsi)",
         "configured": bool(settings.jitsi_signing_key),
         "status": "configured" if settings.jitsi_signing_key else "not_configured"},
        {"code": "mail", "name": "Почта (SMTP)",
         "configured": bool(settings.smtp_host),
         "status": "configured" if settings.smtp_host else "not_configured"},
    ]

    return {
        "version": APP_VERSION,
        "env": settings.app_env,
        "sso": {
            "enabled": settings.sso_enabled, "issuer": settings.sso_issuer,
            "kid": settings.sso_kid, "jwksKeys": len(jwks.get("keys", [])),
            "apps": len(sso.sso_apps()),
        },
        "registry": {"apps": apps_n, "modules": mods_n},
        "counts": {"companies": comp_n, "users": user_n},
        "services": services,
    }
