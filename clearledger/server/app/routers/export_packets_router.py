"""
CRUD ExportPacket — L3 слой (что выгружаем в 1С).
См. docs/sverka-spec.md §0 — 4-слойная архитектура данных.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Company, ExportPacket, User
from app.schemas import (
    ExportPacketCreate,
    ExportPacketResponse,
    ExportPacketUpdate,
)

router = APIRouter(prefix="/export-packets", tags=["Выгрузка в 1С (L3)"])


async def _resolve_company_id(value: str, db: AsyncSession) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    result = await db.execute(select(Company).where(Company.slug == value))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown company: {value}")
    return company.id


def _resp(p: ExportPacket) -> ExportPacketResponse:
    return ExportPacketResponse(
        id=str(p.id),
        companyId=str(p.company_id),
        kind=p.kind,
        sourceEntryIds=[str(x) for x in (p.source_entry_ids or [])],
        status=p.status,
        payload=p.payload or {},
        sentAt=p.sent_at,
        ackedAt=p.acked_at,
        rejectReason=p.reject_reason,
        targetDocId=str(p.target_doc_id) if p.target_doc_id else None,
        createdAt=p.created_at,
        updatedAt=p.updated_at,
    )


@router.get("", response_model=list[ExportPacketResponse])
async def list_packets(
    company_id: str = Query(...),
    kind: str | None = Query(None),
    pkt_status: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    cid = await _resolve_company_id(company_id, db)
    stmt = select(ExportPacket).where(ExportPacket.company_id == cid)
    if kind:
        stmt = stmt.where(ExportPacket.kind == kind)
    if pkt_status:
        stmt = stmt.where(ExportPacket.status == pkt_status)
    stmt = stmt.order_by(ExportPacket.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_resp(p) for p in rows]


@router.post("", response_model=ExportPacketResponse, status_code=status.HTTP_201_CREATED)
async def create_packet(
    payload: ExportPacketCreate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    cid = await _resolve_company_id(payload.company_id, db)
    p = ExportPacket(
        id=uuid.uuid4(),
        company_id=cid,
        kind=payload.kind,
        source_entry_ids=payload.source_entry_ids,
        payload=payload.payload,
        status="draft",
    )
    db.add(p)
    await db.flush()
    await db.refresh(p)
    return _resp(p)


@router.patch("/{packet_id}", response_model=ExportPacketResponse)
async def update_packet(
    packet_id: str,
    payload: ExportPacketUpdate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    try:
        pid = uuid.UUID(packet_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    p = (await db.execute(select(ExportPacket).where(ExportPacket.id == pid))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")

    # Автозаполнение sent_at/acked_at при смене статуса
    if payload.status:
        if payload.status == "sent" and not p.sent_at:
            p.sent_at = datetime.now(tz=timezone.utc)
        if payload.status == "acked" and not p.acked_at:
            p.acked_at = datetime.now(tz=timezone.utc)
        p.status = payload.status
    if payload.payload is not None:
        p.payload = payload.payload
    if payload.sent_at is not None:
        p.sent_at = payload.sent_at
    if payload.acked_at is not None:
        p.acked_at = payload.acked_at
    if payload.reject_reason is not None:
        p.reject_reason = payload.reject_reason
    if payload.target_doc_id is not None:
        try:
            p.target_doc_id = uuid.UUID(payload.target_doc_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid target_doc_id") from exc

    await db.flush()
    await db.refresh(p)
    return _resp(p)


@router.delete("/{packet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_packet(
    packet_id: str,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    try:
        pid = uuid.UUID(packet_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    res = await db.execute(delete(ExportPacket).where(ExportPacket.id == pid))
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")


@router.get("/stats", response_model=dict)
async def packet_stats(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    cid = await _resolve_company_id(company_id, db)
    rows = (await db.execute(
        select(ExportPacket.status, ExportPacket.kind, func.count())
        .where(ExportPacket.company_id == cid)
        .group_by(ExportPacket.status, ExportPacket.kind)
    )).all()
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for st, kn, n in rows:
        by_status[st] = by_status.get(st, 0) + n
        by_kind[kn] = by_kind.get(kn, 0) + n
    return {"total": sum(by_status.values()), "byStatus": by_status, "byKind": by_kind}


@router.get("/by-doc/{doc_id}", response_model=list[ExportPacketResponse])
async def packets_by_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Какие L3-пакеты привели к этому L4-документу. Используется в
    DocumentDetailSheet чтобы показать «Загружено в 1С» бейдж."""
    try:
        did = uuid.UUID(doc_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid doc id") from exc
    rows = (await db.execute(
        select(ExportPacket).where(ExportPacket.target_doc_id == did)
    )).scalars().all()
    return [_resp(p) for p in rows]
