"""SSO ElsyPlus — лаунчер приложений, handoff-токен и JWKS.

Фаза 0 единой экосистемы: Ledger — временный провайдер идентичности (см.
`services/sso.py`). `/sso/authorize` вызывается ФРОНТОМ Ledger (bearer из
localStorage), а НЕ браузерным редиректом — при редиректе токен не долетел бы.
Фронт получает URL с токеном и делает переход сам.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import Company, User, UserCompany
from app.services import sso

settings = get_settings()
router = APIRouter(prefix="/sso", tags=["SSO ElsyPlus"])


@router.get("/apps")
async def list_apps(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Каталог приложений экосистемы для лаунчера (Фаза 0 — из конфига)."""
    return {"enabled": settings.sso_enabled, "apps": sso.sso_apps()}


@router.get("/authorize")
async def authorize(
    app: str = Query(..., description="код приложения-получателя"),
    company_id: str | None = Query(None, description="компания контекста (по умолчанию текущая)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Выпустить handoff-токен для приложения `app` и вернуть URL перехода.

    Токен короткоживущий (RS256, ~5 мин), целевое приложение проверит его по JWKS.
    """
    if not settings.sso_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "SSO не настроен (нет ключа подписи)")
    target = sso.find_app(app)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Неизвестное приложение: {app}")

    rows = (await db.execute(
        select(UserCompany, Company)
        .join(Company, Company.id == UserCompany.company_id)
        .where(UserCompany.user_id == user.id)
    )).all()
    companies = [{"id": str(c.id), "slug": c.slug, "role": uc.role} for uc, c in rows]
    cid = company_id or (str(user.company_id) if user.company_id
                         else (companies[0]["id"] if companies else None))

    token = sso.sign_sso_token(user=user, company_id=cid, companies=companies, aud=app)
    url = f"{target['base_url']}{target['callback']}#token={token}"
    return {"url": url, "app": app, "expires_in": settings.sso_token_ttl_seconds}


@router.get("/jwks.json")
async def jwks() -> dict[str, Any]:
    """Публичный JWKS — приложения экосистемы проверяют токены по kid."""
    return sso.public_jwks()
