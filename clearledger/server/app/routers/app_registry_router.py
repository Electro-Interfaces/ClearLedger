"""ElsyPlus Core — API реестра приложений/модулей на компанию.

Серверная замена localStorage-демо: читает членство компании, отдаёт эффективный
список приложений/модулей; правки (вкл/выкл) — только админ компании/суперадмин.
Питает лаунчер (SSO) и админку «Приложения».
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User, UserCompany
from app.services import app_registry

router = APIRouter(prefix="/registry", tags=["ElsyPlus Core — реестр приложений"])


async def _require_admin(company_id, user: User, db: AsyncSession) -> uuid.UUID:
    """Членство + права админа компании (или суперадмин) для правок реестра."""
    cid = await assert_company_member(company_id, user, db)
    if user.is_superadmin:
        return cid
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора компании")
    return cid


@router.get("/company-apps")
async def get_company_apps(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Приложения и модули компании с эффективным признаком enabled."""
    cid = await assert_company_member(company_id, user, db)
    return {"apps": await app_registry.company_apps(db, cid)}


@router.put("/company-apps/{app_id}")
async def put_company_app(
    app_id: uuid.UUID, company_id: str = Query(...),
    enabled: bool = Body(..., embed=True),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Включить/выключить приложение для компании."""
    cid = await _require_admin(company_id, user, db)
    await app_registry.set_app(db, cid, app_id, enabled)
    return {"appId": str(app_id), "enabled": enabled}


@router.put("/company-apps/{app_id}/modules/{module_code}")
async def put_company_module(
    app_id: uuid.UUID, module_code: str, company_id: str = Query(...),
    enabled: bool = Body(..., embed=True),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Включить/выключить модуль приложения для компании."""
    cid = await _require_admin(company_id, user, db)
    await app_registry.set_module(db, cid, app_id, module_code, enabled)
    return {"appId": str(app_id), "moduleCode": module_code, "enabled": enabled}
