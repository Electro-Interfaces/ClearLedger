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

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.deps import get_owned
from app.models import ExportPacket, User
from app.schemas import (
    ExportPacketCreate,
    ExportPacketResponse,
    ExportPacketUpdate,
)

router = APIRouter(prefix="/export-packets", tags=["Выгрузка в 1С (L3)"])


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
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
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
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(payload.company_id, current_user, db)
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
    p = await get_owned(ExportPacket, pid, _u, db)  # 404 для чужого/несуществующего

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
    p = await get_owned(ExportPacket, pid, _u, db)  # 404 для чужого/несуществующего
    await db.delete(p)


@router.get("/stats", response_model=dict)
async def packet_stats(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
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


@router.post("/build")
async def build_packets_from_clean(
    company_id: str = Query(...),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Собрать ExportPackets из L2 (DataEntry layer='clean') за период.

    Правила агрегации:
      shift_orp:    ОДНА смена = 1 пакет; ключ TL|СМЕНА|{system}|{station}|{shift}
                    (= натуральный ключ нативного пути .cfe, Module.bsl:1297).
                    НЕ группируем по дню: иначе многосменные дни склеиваются и
                    ПолучитьСтатус в .cfe не находит документ → задвоение на
                    живой бухгалтерии. Нет полного натурального ключа → пакет НЕ строим.
      purchase_ttn: одна ТТН = один пакет

    Идемпотентно: если для группы уже есть draft/queued/sent пакет — пропускаем.
    """
    from app.models import DataEntry  # local import чтобы не плодить top-level

    cid = await assert_company_member(company_id, current_user, db)
    stmt = select(DataEntry).where(
        DataEntry.company_id == cid,
        DataEntry.layer == "clean",
    )
    if date_from:
        # docDate из meta — фильтр на стороне Python (JSONB filter сложнее)
        pass
    rows = (await db.execute(stmt)).scalars().all()

    # Группировка.
    # shift_orp группируем по ПОЛНОМУ натуральному ключу (система, станция, смена) —
    # одна смена = один пакет. Это ровно ключ нативного пути .cfe.
    shift_groups: dict[tuple[str, str, str], list] = {}  # (system, station, shift) -> entries
    ttn_entries: list = []
    skipped_no_key = 0
    for e in rows:
        meta = e.meta or {}
        d = (meta.get("docDate") or meta.get("shift_date") or "")[:10]
        if date_from and d and d < date_from:
            continue
        if date_to and d and d > date_to:
            continue
        if e.doc_type_id == "shift_orp" or e.subcategory_id == "shifts":
            # Натуральный ключ ДОЛЖЕН присутствовать целиком; иначе пакет НЕ строим
            # (fail-safe: лучше пропустить, чем выгрузить смену под неоднозначным
            # ключом и задвоить документ в .cfe на живой бухгалтерии).
            system = str(meta.get("system_code") or "").strip()
            station = str(meta.get("station_code") or "").strip()
            shift = str(meta.get("shift_number") or meta.get("shift_id") or "").strip()
            if not (system and station and shift):
                skipped_no_key += 1
                continue
            shift_groups.setdefault((system, station, shift), []).append(e)
        elif e.doc_type_id == "purchase_ttn" or e.subcategory_id == "ttn":
            ttn_entries.append(e)

    created_packets = 0
    skipped = 0

    # shift_orp: один пакет на (система, станция, смена) = натуральный ключ .cfe
    for (system, station, shift), entries in shift_groups.items():
        # = КлючЗагрузки нативного пути (NefteUchet TL_Загрузка Module.bsl:1297)
        marker = f"TL|СМЕНА|{system}|{station}|{shift}"
        day = (entries[0].meta.get("docDate") or entries[0].meta.get("shift_date") or "")[:10]
        existing = (await db.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == cid,
                ExportPacket.kind == "shift_orp",
                ExportPacket.payload["marker"].astext == marker,
                ExportPacket.status.in_(["draft", "queued", "sent", "acked"]),
            )
        )).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        total = sum(float(e.meta.get("totalAmount") or 0) for e in entries)
        total_liters = sum(float(e.meta.get("totalLiters") or 0) for e in entries)
        # Агрегация по видам топлива в пределах ОДНОЙ смены
        fuel_agg: dict[str, dict[str, float | str]] = {}
        for e in entries:
            for fb in (e.meta.get("fuel_breakdown") or []):
                code = str(fb.get("fuel_code") or fb.get("fuel_name") or "")
                if not code:
                    continue
                row = fuel_agg.setdefault(code, {
                    "fuel_code": code,
                    "fuel_name": fb.get("fuel_name") or "",
                    "liters":    0.0,
                    "amount":    0.0,
                })
                row["liters"] = float(row["liters"]) + float(fb.get("liters") or 0)
                row["amount"] = float(row["amount"]) + float(fb.get("amount") or 0)
        db.add(ExportPacket(
            id=uuid.uuid4(),
            company_id=cid,
            kind="shift_orp",
            idem_key=marker,            # = натуральный ключ .cfe (DB-страховка от задвоения)
            source_entry_ids=[str(e.id) for e in entries],
            status="draft",
            payload={
                "marker": marker,                       # = idem_key (натуральный ключ .cfe)
                "idem_key": marker,
                "natural_key": {"system": system, "station": station, "shift": shift},
                "system_code": system,
                "station_code": station,
                "shift_number": shift,
                "date": day,
                "entries_count": len(entries),
                "total_amount": total,
                "total_liters": total_liters,
                "fuel_breakdown": list(fuel_agg.values()),
            },
        ))
        created_packets += 1

    # purchase_ttn: 1:1
    for e in ttn_entries:
        meta = e.meta or {}
        ttn_no = meta.get("docNumber") or meta.get("ttn_number") or ""
        # TODO(blocker#1): привести к нативному ключу .cfe TL|ТТН|... (Module.bsl:1378) —
        # точная форма ключа ТТН требует сверки с боевым расширением.
        marker = f"purchase_ttn:{ttn_no}:{(meta.get('docDate') or '')[:10]}"
        existing = (await db.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == cid,
                ExportPacket.kind == "purchase_ttn",
                ExportPacket.payload["marker"].astext == marker,
                ExportPacket.status.in_(["draft", "queued", "sent", "acked"]),
            )
        )).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        db.add(ExportPacket(
            id=uuid.uuid4(),
            company_id=cid,
            kind="purchase_ttn",
            idem_key=marker,            # TODO: привести к нативному ключу .cfe TL|ТТН|...
            source_entry_ids=[str(e.id)],
            status="draft",
            payload={
                "marker": marker,
                "ttn_number": ttn_no,
                "ttn_date": meta.get("docDate") or "",
                "supplier_inn": meta.get("inn", ""),
                "supplier_name": meta.get("supplier_name", ""),
                "fuel_name": meta.get("fuel_name", ""),
                "doc_volume_l": meta.get("doc_volume_l", ""),
                "fact_volume_l": meta.get("fact_volume_l", ""),
            },
        ))
        created_packets += 1

    await db.flush()
    return {
        "created": created_packets,
        "skipped": skipped,
        "skipped_no_natural_key": skipped_no_key,
        "considered_clean_entries": len(rows),
    }


# ─── HTTP API для расширения 1С (TradeLedger.cfe тянет/квитирует) ────

@router.get("/queue", response_model=list[ExportPacketResponse])
async def queue_for_extension(
    company_id: str = Query(...),
    kind: str | None = Query(None),
    mark_as_sent: bool = Query(True, description="Перевести выданные пакеты в status=sent"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Очередь пакетов для расширения 1С. Возвращает draft+queued.
    При mark_as_sent=true (по умолчанию) — атомарно меняет их статус
    на 'sent' и заполняет sent_at, чтобы расширение их видело только
    один раз (idempotent от своей стороны через ack)."""
    cid = await assert_company_member(company_id, current_user, db)
    stmt = select(ExportPacket).where(
        ExportPacket.company_id == cid,
        ExportPacket.status.in_(["draft", "queued"]),
    )
    if kind:
        stmt = stmt.where(ExportPacket.kind == kind)
    stmt = stmt.order_by(ExportPacket.created_at)
    packets = (await db.execute(stmt)).scalars().all()

    if mark_as_sent and packets:
        now = datetime.now(tz=timezone.utc)
        for p in packets:
            p.status = "sent"
            p.sent_at = now
        await db.flush()

    return [_resp(p) for p in packets]


@router.post("/{packet_id}/ack")
async def ack_packet(
    packet_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Расширение 1С квитирует загрузку пакета.

    Body может содержать:
      target_doc_external_id: GUID документа в БП (Ref_Key из 1С)
      target_doc_id:          UUID AccountingDoc в TradeLedger (если расширение
                              предварительно его узнало через sync_documents)
      reject_reason:          если status='rejected'

    Если ни target_doc_external_id ни target_doc_id не передано — auto-link
    проверится позже при следующем sync_documents.
    """
    from app.models import AccountingDoc
    try:
        pid = uuid.UUID(packet_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid id") from exc
    # 404 для чужого/несуществующего: иначе чужой тенант квитировал пакет и смена
    # /ТТН не доходила до 1С.
    p = await get_owned(ExportPacket, pid, _u, db)

    reject = body.get("reject_reason")
    if reject:
        p.status = "rejected"
        p.reject_reason = str(reject)[:1000]
    else:
        p.status = "acked"
        p.acked_at = datetime.now(tz=timezone.utc)
        # Опциональный auto-link на L4
        target_ext = body.get("target_doc_external_id")
        target_id = body.get("target_doc_id")
        if target_id:
            try:
                p.target_doc_id = uuid.UUID(target_id)
            except ValueError:
                pass
        elif target_ext:
            doc = (await db.execute(
                select(AccountingDoc).where(
                    AccountingDoc.company_id == p.company_id,
                    AccountingDoc.external_id == str(target_ext),
                )
            )).scalar_one_or_none()
            if doc:
                p.target_doc_id = doc.id

    await db.flush()
    await db.refresh(p)
    return {
        "id": str(p.id),
        "status": p.status,
        "target_doc_id": str(p.target_doc_id) if p.target_doc_id else None,
        "acked_at": p.acked_at.isoformat() if p.acked_at else None,
        "reject_reason": p.reject_reason,
    }


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
    from app.models import AccountingDoc
    # Проверяем владение документом (404 для чужого) — иначе утекают пакеты чужой компании.
    await get_owned(AccountingDoc, did, _u, db)
    rows = (await db.execute(
        select(ExportPacket).where(ExportPacket.target_doc_id == did)
    )).scalars().all()
    return [_resp(p) for p in rows]
