"""CRUD API для справочников НСИ (контрагенты, организации, номенклатура, договоры)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import Counterparty, Organization, Nomenclature, Contract, User
from app.api.deps import get_current_user

router = APIRouter(prefix="/references", tags=["references"])


# ============================================================
# Pydantic schemas
# ============================================================

class CounterpartyOut(BaseModel):
    id: UUID
    company_id: str
    inn: str
    kpp: str | None = None
    name: str
    short_name: str | None = None
    type: str
    aliases: list[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class CounterpartyCreate(BaseModel):
    inn: str
    kpp: str | None = None
    name: str
    short_name: str | None = None
    type: str = "ЮЛ"
    aliases: list[str] = []

class OrganizationOut(BaseModel):
    id: UUID
    company_id: str
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str
    bank_account: str | None = None
    bank_bik: str | None = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class OrganizationCreate(BaseModel):
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str
    bank_account: str | None = None
    bank_bik: str | None = None

class NomenclatureOut(BaseModel):
    id: UUID
    company_id: str
    code: str
    name: str
    unit: str
    unit_label: str
    vat_rate: float
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class NomenclatureCreate(BaseModel):
    code: str
    name: str
    unit: str = "796"
    unit_label: str = "шт"
    vat_rate: float = 20

class ContractOut(BaseModel):
    id: UUID
    company_id: str
    number: str
    date: str | None = None
    counterparty_id: UUID | None = None
    organization_id: UUID | None = None
    type: str
    amount_limit: float | None = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class ContractCreate(BaseModel):
    number: str
    date: str | None = None
    counterparty_id: UUID | None = None
    organization_id: UUID | None = None
    type: str = "Прочее"
    amount_limit: float | None = None


# ============================================================
# Counterparties
# ============================================================

@router.get("/counterparties", response_model=list[CounterpartyOut])
async def list_counterparties(
    company_id: str,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(Counterparty).where(Counterparty.company_id == company_id)
    if search:
        # pg_trgm fuzzy search
        q = q.where(Counterparty.name.ilike(f"%{search}%"))
    q = q.order_by(Counterparty.name)
    result = await db.execute(q)
    return [CounterpartyOut.model_validate(r) for r in result.scalars().all()]


@router.post("/counterparties", response_model=CounterpartyOut, status_code=201)
async def create_counterparty(
    company_id: str,
    body: CounterpartyCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    cp = Counterparty(
        company_id=company_id,
        inn=body.inn,
        kpp=body.kpp,
        name=body.name,
        short_name=body.short_name,
        type=body.type,
        aliases=body.aliases,
    )
    db.add(cp)
    await db.commit()
    await db.refresh(cp)
    return CounterpartyOut.model_validate(cp)


@router.delete("/counterparties/{cp_id}", status_code=204)
async def delete_counterparty(
    cp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Counterparty).where(Counterparty.id == cp_id))
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Контрагент не найден")
    await db.delete(cp)
    await db.commit()


# ============================================================
# Organizations
# ============================================================

@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(Organization).where(Organization.company_id == company_id).order_by(Organization.name)
    result = await db.execute(q)
    return [OrganizationOut.model_validate(r) for r in result.scalars().all()]


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
async def create_organization(
    company_id: str,
    body: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    org = Organization(
        company_id=company_id,
        inn=body.inn,
        kpp=body.kpp,
        ogrn=body.ogrn,
        name=body.name,
        bank_account=body.bank_account,
        bank_bik=body.bank_bik,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut.model_validate(org)


@router.delete("/organizations/{org_id}", status_code=204)
async def delete_organization(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Организация не найдена")
    await db.delete(org)
    await db.commit()


# ============================================================
# Nomenclature
# ============================================================

@router.get("/nomenclature", response_model=list[NomenclatureOut])
async def list_nomenclature(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(Nomenclature).where(Nomenclature.company_id == company_id).order_by(Nomenclature.name)
    result = await db.execute(q)
    return [NomenclatureOut.model_validate(r) for r in result.scalars().all()]


@router.post("/nomenclature", response_model=NomenclatureOut, status_code=201)
async def create_nomenclature(
    company_id: str,
    body: NomenclatureCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    nom = Nomenclature(
        company_id=company_id,
        code=body.code,
        name=body.name,
        unit=body.unit,
        unit_label=body.unit_label,
        vat_rate=body.vat_rate,
    )
    db.add(nom)
    await db.commit()
    await db.refresh(nom)
    return NomenclatureOut.model_validate(nom)


@router.delete("/nomenclature/{nom_id}", status_code=204)
async def delete_nomenclature(
    nom_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Nomenclature).where(Nomenclature.id == nom_id))
    nom = result.scalar_one_or_none()
    if not nom:
        raise HTTPException(404, "Номенклатура не найдена")
    await db.delete(nom)
    await db.commit()


# ============================================================
# Contracts
# ============================================================

@router.get("/contracts", response_model=list[ContractOut])
async def list_contracts(
    company_id: str,
    counterparty_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(Contract).where(Contract.company_id == company_id)
    if counterparty_id:
        q = q.where(Contract.counterparty_id == counterparty_id)
    q = q.order_by(Contract.number)
    result = await db.execute(q)
    return [ContractOut.model_validate(r) for r in result.scalars().all()]


@router.post("/contracts", response_model=ContractOut, status_code=201)
async def create_contract(
    company_id: str,
    body: ContractCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ctr = Contract(
        company_id=company_id,
        number=body.number,
        date=body.date,
        counterparty_id=body.counterparty_id,
        organization_id=body.organization_id,
        type=body.type,
        amount_limit=body.amount_limit,
    )
    db.add(ctr)
    await db.commit()
    await db.refresh(ctr)
    return ContractOut.model_validate(ctr)


@router.delete("/contracts/{ctr_id}", status_code=204)
async def delete_contract(
    ctr_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Contract).where(Contract.id == ctr_id))
    ctr = result.scalar_one_or_none()
    if not ctr:
        raise HTTPException(404, "Договор не найден")
    await db.delete(ctr)
    await db.commit()
