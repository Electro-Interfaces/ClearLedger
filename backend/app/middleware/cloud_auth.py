"""API-key аутентификация для облачного аудитора (TSupport → ClearLedger)."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Settings as SettingsModel


async def verify_cloud_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Проверяет X-Cloud-API-Key заголовок.
    Ключ берётся из БД (settings.cloud_api_key) или из ENV (CLOUD_API_KEY).
    """
    api_key = request.headers.get("X-Cloud-API-Key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Отсутствует X-Cloud-API-Key",
        )

    # Сначала проверяем ENV/config
    if settings.cloud_api_key and api_key == settings.cloud_api_key:
        return True

    # Потом проверяем БД (таблица settings)
    result = await db.execute(
        select(SettingsModel).where(SettingsModel.key == "cloud_api_key")
    )
    db_setting = result.scalar_one_or_none()
    if db_setting and db_setting.value and api_key == db_setting.value.get("value", ""):
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Неверный API-ключ",
    )
