"""CRUD для настроек (key-value store)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Settings, User
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingValue(BaseModel):
    value: dict


class SettingOut(BaseModel):
    key: str
    value: dict
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SettingOut])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Все настройки."""
    result = await db.execute(select(Settings))
    return [SettingOut.model_validate(s) for s in result.scalars().all()]


@router.get("/{key}", response_model=SettingOut)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Настройка по ключу."""
    result = await db.execute(select(Settings).where(Settings.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Настройка не найдена")
    return SettingOut.model_validate(setting)


@router.put("/{key}", response_model=SettingOut)
async def upsert_setting(
    key: str,
    data: SettingValue,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner")),
):
    """Создать или обновить настройку."""
    result = await db.execute(select(Settings).where(Settings.key == key))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = data.value
    else:
        setting = Settings(key=key, value=data.value)
        db.add(setting)

    await db.commit()
    await db.refresh(setting)
    return SettingOut.model_validate(setting)


@router.delete("/{key}", status_code=204)
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    """Удалить настройку."""
    result = await db.execute(select(Settings).where(Settings.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Настройка не найдена")
    await db.delete(setting)
    await db.commit()
