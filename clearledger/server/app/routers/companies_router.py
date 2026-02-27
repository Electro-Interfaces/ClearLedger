"""
CRUD для компаний.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Company, User
from app.schemas import CompanyCreate, CompanyResponse, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["Компании"])


def _company_response(company: Company) -> CompanyResponse:
    """Конвертирует ORM Company в схему ответа."""
    return CompanyResponse(
        id=str(company.id),
        name=company.name,
        slug=company.slug,
        short_name=company.short_name,
        profile_id=company.profile_id,
        color=company.color,
        inn=company.inn,
        created_at=company.created_at,
    )


async def _get_company_or_404(
    company_id: str, db: AsyncSession
) -> Company:
    """Получает компанию по UUID или slug."""
    # Сначала пробуем как UUID
    try:
        uid = uuid.UUID(company_id)
        result = await db.execute(select(Company).where(Company.id == uid))
        company = result.scalar_one_or_none()
        if company:
            return company
    except ValueError:
        pass

    # Fallback: ищем по slug
    result = await db.execute(select(Company).where(Company.slug == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Компания не найдена",
        )
    return company


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список всех компаний."""
    query = select(Company).order_by(Company.created_at.desc())
    result = await db.execute(query)
    companies = result.scalars().all()
    return [_company_response(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить компанию по ID."""
    company = await _get_company_or_404(company_id, db)
    return _company_response(company)


@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_company(
    body: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать новую компанию."""
    # Проверка уникальности slug
    existing = await db.execute(
        select(Company).where(Company.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Компания со slug '{body.slug}' уже существует",
        )

    company = Company(
        name=body.name,
        slug=body.slug,
        short_name=body.short_name,
        profile_id=body.profile_id,
        color=body.color,
        inn=body.inn,
    )
    db.add(company)
    await db.flush()
    return _company_response(company)


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    body: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Частичное обновление компании."""
    company = await _get_company_or_404(company_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(company, field, value)

    await db.flush()
    return _company_response(company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удаление компании."""
    company = await _get_company_or_404(company_id, db)
    await db.delete(company)
