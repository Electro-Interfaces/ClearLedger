"""
Настройки компании: кастомизации профиля (отключённые категории, подкатегории, типы документов, коннекторы).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Company, User
from app.schemas import CompanyCustomization

router = APIRouter(prefix="/settings", tags=["Настройки"])


@router.get("/customizations", response_model=dict[str, CompanyCustomization])
async def get_all_customizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Все кастомизации по всем компаниям (словарь companyId → customization)."""
    query = select(Company).where(Company.customization.isnot(None))
    result = await db.execute(query)
    companies = result.scalars().all()

    out: dict[str, CompanyCustomization] = {}
    for company in companies:
        if company.customization:
            # Ключи в slug (фронтенд использует slug как id)
            key = company.slug
            out[key] = CompanyCustomization(
                disabledCategories=company.customization.get("disabledCategories", []),
                disabledSubcategories=company.customization.get("disabledSubcategories", []),
                disabledDocTypes=company.customization.get("disabledDocTypes", []),
                disabledConnectors=company.customization.get("disabledConnectors", []),
            )
    return out


@router.patch("/customizations-{company_id}")
async def update_customization(
    company_id: str,
    body: CompanyCustomization,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обновить кастомизацию профиля компании."""
    # company_id может быть UUID или slug
    company = None
    try:
        uid = uuid.UUID(company_id)
        result = await db.execute(select(Company).where(Company.id == uid))
        company = result.scalar_one_or_none()
    except ValueError:
        pass

    if company is None:
        result = await db.execute(select(Company).where(Company.slug == company_id))
        company = result.scalar_one_or_none()

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Компания не найдена",
        )

    company.customization = {
        "disabledCategories": body.disabledCategories,
        "disabledSubcategories": body.disabledSubcategories,
        "disabledDocTypes": body.disabledDocTypes,
        "disabledConnectors": body.disabledConnectors,
    }
    await db.flush()

    return {"ok": True}
