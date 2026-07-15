"""
Настройки компании: кастомизации профиля (отключённые категории, подкатегории, типы документов, коннекторы).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import Company, User, UserCompany
from app.schemas import CompanyCustomization

router = APIRouter(prefix="/settings", tags=["Настройки"])


@router.get("/customizations", response_model=dict[str, CompanyCustomization])
async def get_all_customizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кастомизации ДОСТУПНЫХ компаний (словарь slug → customization).
    Суперадмин — все; обычный юзер — только свои (иначе утечка списка компаний)."""
    query = select(Company).where(Company.customization.isnot(None))
    if not current_user.is_superadmin:
        query = query.join(UserCompany, UserCompany.company_id == Company.id).where(
            UserCompany.user_id == current_user.id
        )
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
    """Обновить кастомизацию профиля компании (только член компании)."""
    # assert_company_member резолвит UUID|slug + проверяет доступ (400/403).
    cid = await assert_company_member(company_id, current_user, db)
    company = await db.get(Company, cid)
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
