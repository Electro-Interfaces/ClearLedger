"""
CRUD для ReconcileMapping — соответствий внешний ключ ↔ запись Catalog БП.

См. docs/sverka-spec.md §4. Используется reconciliation_service для
построчного матчинга (артикул поставщика → Номенклатура, station_id STS →
Catalog.Склады, pay_type → Catalog.ВидыОплат и т.п.).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Company, ReconcileMapping, User
from app.schemas import (
    ReconcileMappingCreate,
    ReconcileMappingResponse,
    ReconcileMappingUpdate,
)

router = APIRouter(prefix="/reconcile/mappings", tags=["Сверка / Маппинги"])


async def _resolve_company_id(value: str, db: AsyncSession) -> uuid.UUID:
    """Принимает UUID или slug компании, возвращает UUID."""
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    result = await db.execute(select(Company).where(Company.slug == value))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown company: {value}")
    return company.id


def _resp(m: ReconcileMapping) -> ReconcileMappingResponse:
    # Ручное преобразование UUID → str — model_validate(from_attributes=True)
    # не делает auto-cast UUID, валится с "Input should be a valid string".
    return ReconcileMappingResponse(
        id=str(m.id),
        companyId=str(m.company_id),
        kind=m.kind,
        sourceKey=m.source_key,
        targetRef=m.target_ref,
        targetName=m.target_name,
        confidence=m.confidence,
        method=m.method,
        note=m.note,
        createdAt=m.created_at,
        updatedAt=m.updated_at,
    )


@router.get("", response_model=list[ReconcileMappingResponse])
async def list_mappings(
    company_id: str = Query(...),
    kind: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    cid = await _resolve_company_id(company_id, db)
    stmt = select(ReconcileMapping).where(ReconcileMapping.company_id == cid)
    if kind:
        stmt = stmt.where(ReconcileMapping.kind == kind)
    stmt = stmt.order_by(ReconcileMapping.kind, ReconcileMapping.source_key)
    rows = (await db.execute(stmt)).scalars().all()
    return [_resp(m) for m in rows]


@router.post("", response_model=ReconcileMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    payload: ReconcileMappingCreate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    cid = await _resolve_company_id(payload.company_id, db)
    m = ReconcileMapping(
        id=uuid.uuid4(),
        company_id=cid,
        kind=payload.kind,
        source_key=payload.source_key.strip(),
        target_ref=payload.target_ref.strip(),
        target_name=payload.target_name,
        confidence=payload.confidence,
        method=payload.method,
        note=payload.note,
    )
    db.add(m)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Маппинг для kind={payload.kind} source_key={payload.source_key} уже существует",
        ) from exc
    await db.refresh(m)
    return _resp(m)


@router.patch("/{mapping_id}", response_model=ReconcileMappingResponse)
async def update_mapping(
    mapping_id: str,
    payload: ReconcileMappingUpdate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    try:
        mid = uuid.UUID(mapping_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    m = (await db.execute(select(ReconcileMapping).where(ReconcileMapping.id == mid))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    for field in ("source_key", "target_ref", "target_name", "confidence", "method", "note"):
        v = getattr(payload, field)
        if v is not None:
            setattr(m, field, v)
    await db.flush()
    await db.refresh(m)
    return _resp(m)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    mapping_id: str,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    try:
        mid = uuid.UUID(mapping_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    res = await db.execute(delete(ReconcileMapping).where(ReconcileMapping.id == mid))
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mapping not found")


@router.get("/stats", response_model=dict)
async def mapping_stats(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Сколько маппингов каждого вида заведено для компании.
    Используется в UI для KPI «Готовность сверки к запуску»."""
    cid = await _resolve_company_id(company_id, db)
    rows = (await db.execute(
        select(ReconcileMapping.kind, ReconcileMapping.method)
        .where(ReconcileMapping.company_id == cid)
    )).all()
    by_kind: dict[str, int] = {}
    by_method: dict[str, int] = {}
    for kind, method in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_method[method] = by_method.get(method, 0) + 1
    return {"total": len(rows), "byKind": by_kind, "byMethod": by_method}
