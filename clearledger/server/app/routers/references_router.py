"""
CRUD для НСИ (справочники): контрагенты, организации, номенклатура, договоры.
Все ответы в camelCase для прямой совместимости с фронтендом.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    BankAccount,
    Contract,
    ContractDimension,
    ContractLocation,
    Counterparty,
    NomenclatureItem,
    Organization,
    ServiceLocation,
    User,
    Warehouse,
)
from app.schemas import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    ContractCreate,
    ContractDimensionsResponse,
    ContractDimensionUpdate,
    ContractResponse,
    ContractScopeUpdate,
    ContractUpdate,
    CounterpartyBrief,
    CounterpartyLocationsResponse,
    CounterpartiesPage,
    LocationBrief,
    LocationContractBrief,
    LocationContractsResponse,
    CounterpartyCreate,
    CounterpartyResponse,
    CounterpartyUpdate,
    NomenclatureCreate,
    NomenclaturePage,
    NomenclatureResponse,
    NomenclatureUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationsPage,
    OrganizationUpdate,
    WarehouseCreate,
    WarehouseResponse,
    WarehousesPage,
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
        fullName=cp.full_name,
        okpo=cp.okpo,
        type=cp.type,
        kind=cp.kind,
        aliases=cp.aliases or [],
        externalRef=cp.external_ref,
        createdAt=_ts(cp.created_at),
        updatedAt=_ts(cp.updated_at),
    )


@router.get("/counterparties", response_model=list[CounterpartyResponse])
async def list_counterparties(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(Counterparty)
        .where(Counterparty.company_id == cid)
        .order_by(Counterparty.name)
    )
    return [_counterparty_resp(c) for c in result.scalars().all()]


@router.get("/counterparties/search", response_model=CounterpartiesPage)
async def search_counterparties(
    company_id: str = Query(...),
    q: str | None = Query(None, description="Поиск по name/inn/short_name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    base = select(Counterparty).where(Counterparty.company_id == cid)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(
            Counterparty.name.ilike(like),
            Counterparty.short_name.ilike(like),
            Counterparty.inn.ilike(like),
        ))
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    result = await db.execute(
        base.order_by(Counterparty.name).limit(limit).offset(offset)
    )
    return CounterpartiesPage(
        items=[_counterparty_resp(c) for c in result.scalars().all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


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
    cid = await assert_company_member(body.company_id, current_user, db)
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
        fullName=org.full_name,
        okpo=org.okpo,
        legalAddress=org.legal_address,
        actualAddress=org.actual_address,
        phone=org.phone,
        email=org.email,
        directorName=org.director_name,
        directorPosition=org.director_position,
        accountantName=org.accountant_name,
        createdAt=_ts(org.created_at),
        updatedAt=_ts(org.updated_at),
    )


@router.get("/organizations", response_model=list[OrganizationResponse])
async def list_organizations(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(Organization)
        .where(Organization.company_id == cid)
        .order_by(Organization.name)
    )
    return [_org_resp(o) for o in result.scalars().all()]


@router.get("/organizations/search", response_model=OrganizationsPage)
async def search_organizations(
    company_id: str = Query(...),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    base = select(Organization).where(Organization.company_id == cid)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(
            Organization.name.ilike(like),
            Organization.inn.ilike(like),
        ))
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    result = await db.execute(
        base.order_by(Organization.name).limit(limit).offset(offset)
    )
    return OrganizationsPage(
        items=[_org_resp(o) for o in result.scalars().all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


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
    cid = await assert_company_member(body.company_id, current_user, db)
    org = Organization(
        company_id=cid,
        inn=body.inn,
        kpp=body.kpp,
        ogrn=body.ogrn,
        name=body.name,
        bank_account=body.bankAccount,
        bank_bik=body.bankBik,
        full_name=body.fullName,
        okpo=body.okpo,
        legal_address=body.legalAddress,
        actual_address=body.actualAddress,
        phone=body.phone,
        email=body.email,
        director_name=body.directorName,
        director_position=body.directorPosition,
        accountant_name=body.accountantName,
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
    if body.fullName is not None:
        org.full_name = body.fullName
    if body.okpo is not None:
        org.okpo = body.okpo
    if body.legalAddress is not None:
        org.legal_address = body.legalAddress
    if body.actualAddress is not None:
        org.actual_address = body.actualAddress
    if body.phone is not None:
        org.phone = body.phone
    if body.email is not None:
        org.email = body.email
    if body.directorName is not None:
        org.director_name = body.directorName
    if body.directorPosition is not None:
        org.director_position = body.directorPosition
    if body.accountantName is not None:
        org.accountant_name = body.accountantName

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
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(NomenclatureItem)
        .where(NomenclatureItem.company_id == cid)
        .order_by(NomenclatureItem.name)
    )
    return [_nom_resp(n) for n in result.scalars().all()]


@router.get("/nomenclature/search", response_model=NomenclaturePage)
async def search_nomenclature(
    company_id: str = Query(...),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    base = select(NomenclatureItem).where(NomenclatureItem.company_id == cid)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(
            NomenclatureItem.name.ilike(like),
            NomenclatureItem.code.ilike(like),
        ))
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    result = await db.execute(
        base.order_by(NomenclatureItem.name).limit(limit).offset(offset)
    )
    return NomenclaturePage(
        items=[_nom_resp(n) for n in result.scalars().all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


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
    cid = await assert_company_member(body.company_id, current_user, db)
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
        kind=c.kind,
        currency=c.currency,
        validUntil=c.valid_until,
        isClosed=c.is_closed,
        scopeType=c.scope_type,
        externalRef=c.external_ref,
        createdAt=_ts(c.created_at),
        updatedAt=_ts(c.updated_at),
    )


@router.get("/contracts", response_model=list[ContractResponse])
async def list_contracts(
    company_id: str = Query(...),
    counterparty_id: str | None = Query(None, description="Фильтр по GUID контрагента (Владелец)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    stmt = select(Contract).where(Contract.company_id == cid)
    if counterparty_id:
        stmt = stmt.where(Contract.counterparty_id == counterparty_id)
    result = await db.execute(stmt.order_by(Contract.date.desc()))
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
    cid = await assert_company_member(body.company_id, current_user, db)
    c = Contract(
        company_id=cid,
        number=body.number,
        date=body.date,
        counterparty_id=body.counterpartyId,
        organization_id=body.organizationId,
        type=body.type,
        amount_limit=body.amountLimit,
        kind=body.kind,
        currency=body.currency,
        valid_until=body.validUntil,
        scope_type=body.scopeType,
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
    if body.kind is not None:
        c.kind = body.kind
    if body.currency is not None:
        c.currency = body.currency
    if body.validUntil is not None:
        c.valid_until = body.validUntil
    if body.isClosed is not None:
        c.is_closed = body.isClosed
    if body.scopeType is not None:
        c.scope_type = body.scopeType

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
# Ось договор ↔ торговые точки (Фаза 2)
# ---------------------------------------------------------------------------

def _location_brief(loc: ServiceLocation) -> LocationBrief:
    return LocationBrief(id=loc.id, code=loc.code, name=loc.name, type=loc.type)


def _cp_keys(cp: Counterparty) -> list[str]:
    """Идентификаторы контрагента в Contract.counterparty_id: GUID 1С (external_ref)
    и наш UUID (для договоров, созданных вручную)."""
    return [k for k in (cp.external_ref, str(cp.id)) if k]


@router.put("/contracts/{item_id}/scope", response_model=ContractResponse)
async def set_contract_scope(
    item_id: str,
    body: ContractScopeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Установить охват договора: company | locations (набор точек) | unassigned."""
    if body.scopeType not in ("company", "locations", "unassigned"):
        raise HTTPException(status_code=422, detail="Недопустимый scopeType")
    uid = _parse_uuid(item_id)
    c = (await db.execute(select(Contract).where(Contract.id == uid))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")
    await assert_company_member(str(c.company_id), current_user, db)

    c.scope_type = body.scopeType
    # Связи пересобираем заново (для company/unassigned — очищаем).
    await db.execute(delete(ContractLocation).where(ContractLocation.contract_id == c.id))
    if body.scopeType == "locations":
        ids = list(dict.fromkeys(body.locationIds))  # уникальные, порядок сохранён
        if ids:
            valid = set((await db.execute(
                select(ServiceLocation.id).where(
                    ServiceLocation.company_id == c.company_id,
                    ServiceLocation.id.in_(ids),
                )
            )).scalars().all())
            for lid in ids:
                if lid in valid:
                    db.add(ContractLocation(
                        company_id=c.company_id, contract_id=c.id, location_id=lid,
                    ))
    await db.flush()
    # execute(delete)/insert истекают атрибуты c — освежаем перед сериализацией
    # (иначе lazy-load в async-контексте → MissingGreenlet).
    await db.refresh(c)
    return _contract_resp(c)


@router.get("/contracts/{item_id}/locations", response_model=list[LocationBrief])
async def get_contract_locations(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Точки конкретного договора (для scope=locations)."""
    uid = _parse_uuid(item_id)
    c = (await db.execute(select(Contract).where(Contract.id == uid))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")
    await assert_company_member(str(c.company_id), current_user, db)
    rows = (await db.execute(
        select(ServiceLocation)
        .join(ContractLocation, ContractLocation.location_id == ServiceLocation.id)
        .where(ContractLocation.contract_id == c.id)
        .order_by(ServiceLocation.name)
    )).scalars().all()
    return [_location_brief(loc) for loc in rows]


@router.get("/counterparties/{item_id}/locations", response_model=CounterpartyLocationsResponse)
async def get_counterparty_locations(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Где работает контрагент: объединение охватов его договоров.
    Есть company-договор → «Вся компания»; иначе union точек locations-договоров."""
    uid = _parse_uuid(item_id)
    cp = (await db.execute(select(Counterparty).where(Counterparty.id == uid))).scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Контрагент не найден")
    await assert_company_member(str(cp.company_id), current_user, db)

    contracts = (await db.execute(
        select(Contract).where(
            Contract.company_id == cp.company_id,
            Contract.counterparty_id.in_(_cp_keys(cp)),
        )
    )).scalars().all()
    if not contracts:
        return CounterpartyLocationsResponse(scope="none", locations=[], contractsCount=0, unassignedCount=0)

    unassigned = sum(1 for c in contracts if c.scope_type == "unassigned")
    if any(c.scope_type == "company" for c in contracts):
        return CounterpartyLocationsResponse(
            scope="company", locations=[], contractsCount=len(contracts), unassignedCount=unassigned,
        )
    loc_ids = [c.id for c in contracts if c.scope_type == "locations"]
    locs: list[ServiceLocation] = []
    if loc_ids:
        locs = (await db.execute(
            select(ServiceLocation).distinct()
            .join(ContractLocation, ContractLocation.location_id == ServiceLocation.id)
            .where(ContractLocation.contract_id.in_(loc_ids))
            .order_by(ServiceLocation.name)
        )).scalars().all()
    return CounterpartyLocationsResponse(
        scope="locations" if locs else "none",
        locations=[_location_brief(loc) for loc in locs],
        contractsCount=len(contracts),
        unassignedCount=unassigned,
    )


@router.get("/locations/{loc_id}/contracts", response_model=LocationContractsResponse)
async def get_location_contracts(
    loc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Договоры точки: адресные (точка ∈ contract_locations) + общекомпанейские
    (scope=company). Контрагенты — distinct владельцы этих договоров."""
    loc = (await db.execute(
        select(ServiceLocation).where(ServiceLocation.id == loc_id)
    )).scalar_one_or_none()
    if not loc:
        raise HTTPException(status_code=404, detail="Точка не найдена")
    await assert_company_member(str(loc.company_id), current_user, db)

    addressed = (await db.execute(
        select(ContractLocation.contract_id).where(ContractLocation.location_id == loc.id)
    )).scalars().all()
    cond = Contract.scope_type == "company"
    if addressed:
        cond = or_(cond, Contract.id.in_(addressed))
    contracts = (await db.execute(
        select(Contract).where(Contract.company_id == loc.company_id, cond)
        .order_by(Contract.date.desc())
    )).scalars().all()

    # Резолв имён контрагентов по counterparty_id (GUID external_ref или наш UUID).
    keys = {c.counterparty_id for c in contracts if c.counterparty_id}
    cp_map: dict[str, Counterparty] = {}
    if keys:
        uuid_keys = []
        for k in keys:
            try:
                uuid_keys.append(uuid.UUID(k))
            except (ValueError, AttributeError, TypeError):
                pass
        cp_cond = Counterparty.external_ref.in_(keys)
        if uuid_keys:
            cp_cond = or_(cp_cond, Counterparty.id.in_(uuid_keys))
        cps = (await db.execute(
            select(Counterparty).where(
                Counterparty.company_id == loc.company_id, cp_cond,
            )
        )).scalars().all()
        for cp in cps:
            if cp.external_ref:
                cp_map[cp.external_ref] = cp
            cp_map[str(cp.id)] = cp

    briefs: list[LocationContractBrief] = []
    seen: dict[str, CounterpartyBrief] = {}
    for c in contracts:
        cp = cp_map.get(c.counterparty_id)
        briefs.append(LocationContractBrief(
            id=str(c.id), number=c.number, date=c.date, kind=c.kind,
            scopeType=c.scope_type, companyWide=(c.scope_type == "company"),
            counterpartyId=c.counterparty_id,
            counterpartyName=cp.name if cp else None,
            counterpartyInn=cp.inn if cp else None,
        ))
        if c.counterparty_id and c.counterparty_id not in seen:
            seen[c.counterparty_id] = CounterpartyBrief(
                externalRef=cp.external_ref if cp else c.counterparty_id,
                name=cp.name if cp else "(неизвестный контрагент)",
                inn=cp.inn if cp else None,
            )
    return LocationContractsResponse(contracts=briefs, counterparties=list(seen.values()))


# ---------------------------------------------------------------------------
# Обобщённые грани договора по разрезам (Фаза 3): номенклатура, каналы и др.
# ---------------------------------------------------------------------------

def _dims_grouped(rows: list[ContractDimension]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r.dim_type, []).append(r.dim_ref)
    return out


@router.get("/contracts/{item_id}/dimensions", response_model=ContractDimensionsResponse)
async def get_contract_dimensions(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Все грани договора по разрезам (dim_type → набор элементов)."""
    uid = _parse_uuid(item_id)
    c = (await db.execute(select(Contract).where(Contract.id == uid))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")
    await assert_company_member(str(c.company_id), current_user, db)
    rows = (await db.execute(
        select(ContractDimension).where(ContractDimension.contract_id == c.id)
    )).scalars().all()
    return ContractDimensionsResponse(dimensions=_dims_grouped(rows))


@router.put("/contracts/{item_id}/dimensions/{dim_type}", response_model=ContractDimensionsResponse)
async def set_contract_dimension(
    item_id: str,
    dim_type: str,
    body: ContractDimensionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Заменить набор элементов разреза dim_type у договора (пусто = снять ограничение)."""
    uid = _parse_uuid(item_id)
    c = (await db.execute(select(Contract).where(Contract.id == uid))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Договор не найден")
    await assert_company_member(str(c.company_id), current_user, db)

    await db.execute(delete(ContractDimension).where(
        ContractDimension.contract_id == c.id,
        ContractDimension.dim_type == dim_type,
    ))
    refs = list(dict.fromkeys(r.strip() for r in body.refs if r and r.strip()))
    for ref in refs:
        db.add(ContractDimension(
            company_id=c.company_id, contract_id=c.id, dim_type=dim_type, dim_ref=ref,
        ))
    await db.flush()
    rows = (await db.execute(
        select(ContractDimension).where(ContractDimension.contract_id == c.id)
    )).scalars().all()
    return ContractDimensionsResponse(dimensions=_dims_grouped(rows))


@router.get("/dimensions/{dim_type}/contracts", response_model=list[ContractResponse])
async def get_dimension_contracts(
    dim_type: str,
    ref: str = Query(..., description="dim_ref элемента разреза (id/код/external_ref)"),
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обратная навигация: договоры, явно ограниченные данным элементом разреза
    (например, договоры именно по этой номенклатуре или каналу)."""
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(
        select(Contract)
        .join(ContractDimension, ContractDimension.contract_id == Contract.id)
        .where(
            Contract.company_id == cid,
            ContractDimension.dim_type == dim_type,
            ContractDimension.dim_ref == ref,
        )
        .order_by(Contract.date.desc())
    )).scalars().all()
    return [_contract_resp(c) for c in rows]


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
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(Warehouse)
        .where(Warehouse.company_id == cid)
        .order_by(Warehouse.name)
    )
    return [_warehouse_resp(w) for w in result.scalars().all()]


@router.get("/warehouses/search", response_model=WarehousesPage)
async def search_warehouses(
    company_id: str = Query(...),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    base = select(Warehouse).where(Warehouse.company_id == cid)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(
            Warehouse.name.ilike(like),
            Warehouse.code.ilike(like),
            Warehouse.address.ilike(like),
        ))
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    result = await db.execute(
        base.order_by(Warehouse.name).limit(limit).offset(offset)
    )
    return WarehousesPage(
        items=[_warehouse_resp(w) for w in result.scalars().all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


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
    cid = await assert_company_member(body.company_id, current_user, db)
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
    cid = await assert_company_member(company_id, current_user, db)
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
    cid = await assert_company_member(body.company_id, current_user, db)
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
