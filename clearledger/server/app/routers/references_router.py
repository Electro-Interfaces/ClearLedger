"""
CRUD для НСИ (справочники): контрагенты, организации, номенклатура, договоры.
Все ответы в camelCase для прямой совместимости с фронтендом.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.utils import resolve_company_id
from app.models import (
    BankAccount,
    Contract,
    Counterparty,
    NomenclatureItem,
    Organization,
    User,
    Warehouse,
)
from app.schemas import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    ContractCreate,
    ContractResponse,
    ContractUpdate,
    CounterpartyCreate,
    CounterpartyResponse,
    CounterpartyUpdate,
    NomenclatureCreate,
    NomenclatureResponse,
    NomenclatureUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)

router = APIRouter(prefix="/references", tags=["НСИ (Справочники)"])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _ts(dt: datetime | None) -> str:
    """Конвертирует datetime в ISO строку."""
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    return dt.isoformat()


def _parse_uuid(val: str, label: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Невалидный {label}")


# ---------------------------------------------------------------------------
# Counterparty (Контрагенты)
# ---------------------------------------------------------------------------

def _counterparty_resp(cp: Counterparty) -> CounterpartyResponse:
    return CounterpartyResponse(
        id=str(cp.id),
        companyId=str(cp.company_id),
        inn=cp.inn,
        kpp=cp.kpp,
        name=cp.name,
        shortName=cp.short_name,
        type=cp.type,
        aliases=cp.aliases or [],
        createdAt=_ts(cp.created_at),
        updatedAt=_ts(cp.updated_at),
    )


@router.get("/counterparties", response_model=list[CounterpartyResponse])
async def list_counterparties(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(Counterparty)
        .where(Counterparty.company_id == cid)
        .order_by(Counterparty.name)
    )
    return [_counterparty_resp(c) for c in result.scalars().all()]


@router.post(
    "/counterparties",
    response_model=CounterpartyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_counterparty(
    body: CounterpartyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    cp = Counterparty(
        company_id=cid,
        inn=body.inn,
        kpp=body.kpp,
        name=body.name,
        short_name=body.shortName,
        type=body.type,
        aliases=body.aliases,
    )
    db.add(cp)
    await db.flush()
    return _counterparty_resp(cp)


@router.patch("/counterparties/{item_id}", response_model=CounterpartyResponse)
async def update_counterparty(
    item_id: str,
    body: CounterpartyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Counterparty).where(Counterparty.id == uid))
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    if body.inn is not None:
        cp.inn = body.inn
    if body.kpp is not None:
        cp.kpp = body.kpp
    if body.name is not None:
        cp.name = body.name
    if body.shortName is not None:
        cp.short_name = body.shortName
    if body.type is not None:
        cp.type = body.type
    if body.aliases is not None:
        cp.aliases = body.aliases

    await db.flush()
    return _counterparty_resp(cp)


@router.delete("/counterparties/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_counterparty(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Counterparty).where(Counterparty.id == uid))
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Контрагент не найден")
    await db.delete(cp)


# ---------------------------------------------------------------------------
# Organization (Организации)
# ---------------------------------------------------------------------------

def _org_resp(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=str(org.id),
        companyId=str(org.company_id),
        inn=org.inn,
        kpp=org.kpp,
        ogrn=org.ogrn,
        name=org.name,
        bankAccount=org.bank_account,
        bankBik=org.bank_bik,
        createdAt=_ts(org.created_at),
        updatedAt=_ts(org.updated_at),
    )


@router.get("/organizations", response_model=list[OrganizationResponse])
async def list_organizations(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(Organization)
        .where(Organization.company_id == cid)
        .order_by(Organization.name)
    )
    return [_org_resp(o) for o in result.scalars().all()]


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    org = Organization(
        company_id=cid,
        inn=body.inn,
        kpp=body.kpp,
        ogrn=body.ogrn,
        name=body.name,
        bank_account=body.bankAccount,
        bank_bik=body.bankBik,
    )
    db.add(org)
    await db.flush()
    return _org_resp(org)


@router.patch("/organizations/{item_id}", response_model=OrganizationResponse)
async def update_organization(
    item_id: str,
    body: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Organization).where(Organization.id == uid))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")

    if body.inn is not None:
        org.inn = body.inn
    if body.kpp is not None:
        org.kpp = body.kpp
    if body.ogrn is not None:
        org.ogrn = body.ogrn
    if body.name is not None:
        org.name = body.name
    if body.bankAccount is not None:
        org.bank_account = body.bankAccount
    if body.bankBik is not None:
        org.bank_bik = body.bankBik

    await db.flush()
    return _org_resp(org)


@router.delete("/organizations/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Organization).where(Organization.id == uid))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    await db.delete(org)


# ---------------------------------------------------------------------------
# Nomenclature (Номенклатура)
# ---------------------------------------------------------------------------

def _nom_resp(n: NomenclatureItem) -> NomenclatureResponse:
    return NomenclatureResponse(
        id=str(n.id),
        companyId=str(n.company_id),
        code=n.code,
        name=n.name,
        unit=n.unit,
        unitLabel=n.unit_label,
        vatRate=n.vat_rate,
        createdAt=_ts(n.created_at),
        updatedAt=_ts(n.updated_at),
    )


@router.get("/nomenclature", response_model=list[NomenclatureResponse])
async def list_nomenclature(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(NomenclatureItem)
        .where(NomenclatureItem.company_id == cid)
        .order_by(NomenclatureItem.name)
    )
    return [_nom_resp(n) for n in result.scalars().all()]


@router.post(
    "/nomenclature",
    response_model=NomenclatureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_nomenclature(
    body: NomenclatureCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    n = NomenclatureItem(
        company_id=cid,
        code=body.code,
        name=body.name,
        unit=body.unit,
        unit_label=body.unitLabel,
        vat_rate=body.vatRate,
    )
    db.add(n)
    await db.flush()
    return _nom_resp(n)


@router.patch("/nomenclature/{item_id}", response_model=NomenclatureResponse)
async def update_nomenclature(
    item_id: str,
    body: NomenclatureUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(NomenclatureItem).where(NomenclatureItem.id == uid))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Номенклатура не найдена")

    if body.code is not None:
        n.code = body.code
    if body.name is not None:
        n.name = body.name
    if body.unit is not None:
        n.unit = body.unit
    if body.unitLabel is not None:
        n.unit_label = body.unitLabel
    if body.vatRate is not None:
        n.vat_rate = body.vatRate

    await db.flush()
    return _nom_resp(n)


@router.delete("/nomenclature/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nomenclature(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(NomenclatureItem).where(NomenclatureItem.id == uid))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Номенклатура не найдена")
    await db.delete(n)


# ---------------------------------------------------------------------------
# Contract (Договоры)
# ---------------------------------------------------------------------------

def _contract_resp(c: Contract) -> ContractResponse:
    return ContractResponse(
        id=str(c.id),
        companyId=str(c.company_id),
        number=c.number,
        date=c.date,
        counterpartyId=c.counterparty_id,
        organizationId=c.organization_id,
        type=c.type,
        amountLimit=c.amount_limit,
        createdAt=_ts(c.created_at),
        updatedAt=_ts(c.updated_at),
    )


@router.get("/contracts", response_model=list[ContractResponse])
async def list_contracts(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(Contract)
        .where(Contract.company_id == cid)
        .order_by(Contract.date.desc())
    )
    return [_contract_resp(c) for c in result.scalars().all()]


@router.post(
    "/contracts",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    body: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    c = Contract(
        company_id=cid,
        number=body.number,
        date=body.date,
        counterparty_id=body.counterpartyId,
        organization_id=body.organizationId,
        type=body.type,
        amount_limit=body.amountLimit,
    )
    db.add(c)
    await db.flush()
    return _contract_resp(c)


@router.patch("/contracts/{item_id}", response_model=ContractResponse)
async def update_contract(
    item_id: str,
    body: ContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Contract).where(Contract.id == uid))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")

    if body.number is not None:
        c.number = body.number
    if body.date is not None:
        c.date = body.date
    if body.counterpartyId is not None:
        c.counterparty_id = body.counterpartyId
    if body.organizationId is not None:
        c.organization_id = body.organizationId
    if body.type is not None:
        c.type = body.type
    if body.amountLimit is not None:
        c.amount_limit = body.amountLimit

    await db.flush()
    return _contract_resp(c)


@router.delete("/contracts/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Contract).where(Contract.id == uid))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")
    await db.delete(c)


# ---------------------------------------------------------------------------
# Warehouse (Склады / АЗС)
# ---------------------------------------------------------------------------

def _warehouse_resp(w: Warehouse) -> WarehouseResponse:
    return WarehouseResponse(
        id=str(w.id),
        companyId=str(w.company_id),
        code=w.code,
        name=w.name,
        address=w.address,
        type=w.type,
        createdAt=_ts(w.created_at),
        updatedAt=_ts(w.updated_at),
    )


@router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(Warehouse)
        .where(Warehouse.company_id == cid)
        .order_by(Warehouse.name)
    )
    return [_warehouse_resp(w) for w in result.scalars().all()]


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_warehouse(
    body: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    w = Warehouse(
        company_id=cid,
        code=body.code,
        name=body.name,
        address=body.address,
        type=body.type,
    )
    db.add(w)
    await db.flush()
    return _warehouse_resp(w)


@router.patch("/warehouses/{item_id}", response_model=WarehouseResponse)
async def update_warehouse(
    item_id: str,
    body: WarehouseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Warehouse).where(Warehouse.id == uid))
    w = result.scalar_one_or_none()
    if not w:
        raise HTTPException(status_code=404, detail="Склад не найден")

    if body.code is not None:
        w.code = body.code
    if body.name is not None:
        w.name = body.name
    if body.address is not None:
        w.address = body.address
    if body.type is not None:
        w.type = body.type

    await db.flush()
    return _warehouse_resp(w)


@router.delete("/warehouses/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(Warehouse).where(Warehouse.id == uid))
    w = result.scalar_one_or_none()
    if not w:
        raise HTTPException(status_code=404, detail="Склад не найден")
    await db.delete(w)


# ---------------------------------------------------------------------------
# BankAccount (Банковские счета)
# ---------------------------------------------------------------------------

def _bank_account_resp(ba: BankAccount) -> BankAccountResponse:
    return BankAccountResponse(
        id=str(ba.id),
        companyId=str(ba.company_id),
        number=ba.number,
        bankName=ba.bank_name,
        bik=ba.bik,
        corrAccount=ba.corr_account,
        currency=ba.currency,
        organizationId=ba.organization_id,
        createdAt=_ts(ba.created_at),
        updatedAt=_ts(ba.updated_at),
    )


@router.get("/bank-accounts", response_model=list[BankAccountResponse])
async def list_bank_accounts(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(BankAccount)
        .where(BankAccount.company_id == cid)
        .order_by(BankAccount.bank_name)
    )
    return [_bank_account_resp(ba) for ba in result.scalars().all()]


@router.post(
    "/bank-accounts",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bank_account(
    body: BankAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    ba = BankAccount(
        company_id=cid,
        number=body.number,
        bank_name=body.bankName,
        bik=body.bik,
        corr_account=body.corrAccount,
        currency=body.currency,
        organization_id=body.organizationId,
    )
    db.add(ba)
    await db.flush()
    return _bank_account_resp(ba)


@router.patch("/bank-accounts/{item_id}", response_model=BankAccountResponse)
async def update_bank_account(
    item_id: str,
    body: BankAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(BankAccount).where(BankAccount.id == uid))
    ba = result.scalar_one_or_none()
    if not ba:
        raise HTTPException(status_code=404, detail="Банковский счёт не найден")

    if body.number is not None:
        ba.number = body.number
    if body.bankName is not None:
        ba.bank_name = body.bankName
    if body.bik is not None:
        ba.bik = body.bik
    if body.corrAccount is not None:
        ba.corr_account = body.corrAccount
    if body.currency is not None:
        ba.currency = body.currency
    if body.organizationId is not None:
        ba.organization_id = body.organizationId

    await db.flush()
    return _bank_account_resp(ba)


@router.delete("/bank-accounts/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bank_account(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(item_id)
    result = await db.execute(select(BankAccount).where(BankAccount.id == uid))
    ba = result.scalar_one_or_none()
    if not ba:
        raise HTTPException(status_code=404, detail="Банковский счёт не найден")
    await db.delete(ba)
