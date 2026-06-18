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

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.deps import CompanyDep, get_owned
from app.models import Channel, ReconcileMapping, User
from app.schemas import (
    ReconcileMappingCreate,
    ReconcileMappingResponse,
    ReconcileMappingUpdate,
)

router = APIRouter(prefix="/reconcile/mappings", tags=["Сверка / Маппинги"])


def _resp(m: ReconcileMapping) -> ReconcileMappingResponse:
    # Ручное преобразование UUID → str — model_validate(from_attributes=True)
    # не делает auto-cast UUID, валится с "Input should be a valid string".
    return ReconcileMappingResponse(
        id=str(m.id),
        companyId=str(m.company_id),
        channelId=str(m.channel_id) if m.channel_id else None,
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
    cid: CompanyDep,
    kind: str | None = Query(None),
    channel_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ReconcileMapping).where(ReconcileMapping.company_id == cid)
    if kind:
        stmt = stmt.where(ReconcileMapping.kind == kind)
    if channel_id:
        import uuid as _uuid
        stmt = stmt.where(ReconcileMapping.channel_id == _uuid.UUID(channel_id))
    stmt = stmt.order_by(ReconcileMapping.kind, ReconcileMapping.source_key)
    rows = (await db.execute(stmt)).scalars().all()
    return [_resp(m) for m in rows]


@router.post("", response_model=ReconcileMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    payload: ReconcileMappingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(payload.company_id, current_user, db)
    # Маппинг-override на канал — канал должен принадлежать той же компании.
    if payload.channel_id:
        ch = await get_owned(Channel, uuid.UUID(payload.channel_id), current_user, db)
        if ch.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Канал другой компании")
    m = ReconcileMapping(
        id=uuid.uuid4(),
        company_id=cid,
        channel_id=uuid.UUID(payload.channel_id) if payload.channel_id else None,
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
    current_user: User = Depends(get_current_user),
):
    try:
        mid = uuid.UUID(mapping_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    m = await get_owned(ReconcileMapping, mid, current_user, db)
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
    current_user: User = Depends(get_current_user),
):
    try:
        mid = uuid.UUID(mapping_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    m = await get_owned(ReconcileMapping, mid, current_user, db)
    await db.delete(m)


# ─── Автосопряжение ──────────────────────────────────────────────────


@router.post("/auto-detect", response_model=dict)
async def auto_detect_mappings(
    cid: CompanyDep,
    kind: str | None = Query(None, description="Фильтр по kind: station|fuel|paytype|nomenclature|counterparty. None = все"),
    db: AsyncSession = Depends(get_db),
):
    """Анализирует данные локальной БД и возвращает предложения маппинга.
    НЕ записывает в БД — только предложения. Применить через /auto-apply.
    Если задан kind — фильтрует предложения только этого вида."""
    from app.services.mapping_autodetect_service import MappingAutoDetectService
    svc = MappingAutoDetectService(db)
    suggestions = await svc.detect_all(cid)
    if kind:
        suggestions = [s for s in suggestions if s.kind == kind]
    # Группируем по kind для KPI
    by_kind: dict[str, int] = {}
    by_confidence: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for s in suggestions:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + 1
        if s.confidence >= 90:
            by_confidence["high"] += 1
        elif s.confidence >= 70:
            by_confidence["medium"] += 1
        else:
            by_confidence["low"] += 1
    return {
        "total": len(suggestions),
        "by_kind": by_kind,
        "by_confidence": by_confidence,
        "suggestions": [
            {
                "kind": s.kind,
                "source_key": s.source_key,
                "source_label": s.source_label,
                "target_ref": s.target_ref,
                "target_name": s.target_name,
                "confidence": s.confidence,
                "method": s.method,
                "note": s.note,
            } for s in suggestions
        ],
    }


from pydantic import BaseModel  # noqa: E402


class SuggestionItem(BaseModel):
    kind: str
    source_key: str
    source_label: str | None = None
    target_ref: str
    target_name: str | None = None
    confidence: int
    method: str
    note: str | None = None


class AutoApplyPayload(BaseModel):
    company_id: str
    suggestions: list[SuggestionItem]
    min_confidence: int = 80


@router.post("/auto-apply", response_model=dict)
async def auto_apply_mappings(
    payload: AutoApplyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Применяет полученный список предложений с confidence ≥ min_confidence.
    UI обычно сначала вызывает /auto-detect, даёт пользователю отфильтровать,
    потом передаёт оставшиеся в этот endpoint."""
    from app.services.mapping_autodetect_service import (
        MappingAutoDetectService,
        MappingSuggestion,
    )
    cid = await assert_company_member(payload.company_id, current_user, db)
    svc = MappingAutoDetectService(db)
    sugg = [
        MappingSuggestion(
            kind=s.kind,
            source_key=s.source_key,
            source_label=s.source_label or "",
            target_ref=s.target_ref,
            target_name=s.target_name or "",
            confidence=s.confidence,
            method=s.method,
            note=s.note,
        ) for s in payload.suggestions
    ]
    details = await svc.apply(cid, sugg, min_confidence=payload.min_confidence)
    return details


@router.get("/stats", response_model=dict)
async def mapping_stats(
    cid: CompanyDep,
    db: AsyncSession = Depends(get_db),
):
    """Сколько маппингов каждого вида заведено для компании.
    Используется в UI для KPI «Готовность сверки к запуску»."""
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
