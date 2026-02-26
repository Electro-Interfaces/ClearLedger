"""CRUD для компаний."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Company, User
from app.schemas.companies import CompanyCreate, CompanyUpdate, CompanyOut
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Список всех компаний."""
    result = await db.execute(select(Company).order_by(Company.name))
    return [CompanyOut.model_validate(c) for c in result.scalars().all()]


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Компания по ID."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return CompanyOut.model_validate(company)


@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(
    data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner")),
):
    """Создание компании (admin/owner)."""
    existing = await db.execute(select(Company).where(Company.id == data.id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Компания с таким ID уже существует")

    company = Company(**data.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return CompanyOut.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: str,
    data: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin", "owner")),
):
    """Обновление компании (admin/owner)."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Компания не найдена")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)
    return CompanyOut.model_validate(company)
