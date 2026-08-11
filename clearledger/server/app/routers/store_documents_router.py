from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_module_access, get_current_user
from app.business_access import (
    ROLE_STATION_ADMINISTRATOR,
    SCOPE_STATION,
    has_network_merchandiser,
)
from app.database import get_db
from app.deps import capture_company_header, scope_company_id
from app.models import (
    Company,
    CompanyRole,
    SourceFile,
    StoreDocFile,
    StoreDocMeta,
    StoreDocumentProjection,
    StoreDocumentProjectionLine,
    StoreDocumentRelation,
    User,
    UserCompany,
)
from app.services import ops_terms
from app.services.store_document_contract import PROJECTION_DOCUMENT_KINDS
from app.services.store_documents import (
    normalized_document_payload,
    rebuild_store_document_projection,
    safe_document_detail,
)
from app.services.store_document_print import печатная_форма
from app.services.store_document_snapshot import queue_onec_document_snapshot


# Счётчик и фильтр обязаны быть одним выражением: иначе «не готовы к учёту: 12»
# и отобранные по этой кнопке 9 строк расходятся, и верить нельзя ни тому, ни
# другому.
COUNTER_CONDITIONS = {
    # чек и смена неучётные: их карантин не работа для человека, а свойство
    # кассовой ленты. Оставлять их в «требуют внимания» значит утопить в
    # шестистах чеках три накладные, из-за которых счётчик и заведён
    "attention": lambda: (
        StoreDocumentProjection.requires_attention.is_(True),
        StoreDocumentProjection.document_kind.not_in(("fiscal_receipt", "store_shift")),
    ),
    "missing_evidence": lambda: (
        StoreDocumentProjection.document_kind.in_(("purchase", "return_purchase")),
        StoreDocumentProjection.has_files.is_(False),
    ),
    "not_accounting_ready": lambda: (
        StoreDocumentProjection.document_kind.not_in(("fiscal_receipt", "store_shift")),
        StoreDocumentProjection.accounting_status.not_in(
            ("ready", "accepted", "not_applicable")),
    ),
    "onec_mismatch": lambda: (
        StoreDocumentProjection.discrepancy_status.in_(
            ("minor", "material", "critical", "unmatched")),
    ),
}

FILE_ROLES = ("накладная", "упд", "акт", "опись", "фото", "прочее")
FILE_MIME_TYPES = (
    "application/pdf", "image/jpeg", "image/png", "image/webp",
)


async def _require_store_module(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    company_id = await scope_company_id(user, db)
    access = await resolve_document_access(user, db, company_id)
    if access.is_superadmin or access.is_accountant:
        return
    await check_module_access(user, company_id, db, "store")


router = APIRouter(
    prefix="/store/documents",
    tags=["Магазин: документы"],
    dependencies=[Depends(capture_company_header), Depends(_require_store_module)],
)


@dataclass(frozen=True)
class DocumentAccess:
    company_id: uuid.UUID
    is_superadmin: bool
    is_merchandiser: bool
    is_accountant: bool
    station_ids: frozenset[int]

    @property
    def network(self) -> bool:
        return self.is_superadmin or self.is_merchandiser or self.is_accountant

    @property
    def can_raw(self) -> bool:
        return self.is_superadmin or self.is_accountant


async def resolve_document_access(
    user: User, db: AsyncSession, company_id: uuid.UUID | None = None,
) -> DocumentAccess:
    company_id = company_id or await scope_company_id(user, db)
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    membership = await db.get(UserCompany, (user.id, company_id))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    station_ids = set()
    for grant in grants:
        if (str((grant or {}).get("role")) != ROLE_STATION_ADMINISTRATOR
                or str((grant or {}).get("scope_type")) != SCOPE_STATION):
            continue
        try:
            station_ids.add(int(grant.get("scope_id")))
        except (TypeError, ValueError):
            continue
    merchandiser = has_network_merchandiser(grants, company.slug)
    accountant = False
    if membership is not None and membership.role_id is not None:
        role = await db.get(CompanyRole, membership.role_id)
        accountant = bool(role and role.name.casefold() == "бухгалтер")
    access = DocumentAccess(
        company_id, bool(user.is_superadmin), merchandiser, accountant,
        frozenset(station_ids),
    )
    if not access.network and not access.station_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к документам магазина")
    return access


def _station_allowed(access: DocumentAccess, station_id: int | None) -> bool:
    if station_id is None:
        return access.network
    return access.network or station_id in access.station_ids


def _file_write_allowed(
    access: DocumentAccess, station_id: int | None, document_kind: str | None = None,
) -> bool:
    if document_kind in {"fiscal_receipt", "store_shift"}:
        return False
    if access.is_superadmin or access.is_merchandiser:
        return True
    return station_id is not None and station_id in access.station_ids


async def _projection(
    db: AsyncSession, access: DocumentAccess, record_id: uuid.UUID,
) -> StoreDocumentProjection:
    row = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.id == record_id,
        StoreDocumentProjection.company_id == access.company_id,
    ))).scalar_one_or_none()
    if row is None or not _station_allowed(access, row.station_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return row


def _brief(row: StoreDocumentProjection) -> dict:
    return {
        "record_id": str(row.id), "document_id": str(row.document_id),
        "kind": row.document_kind, "source": row.source_kind,
        "projection_source": row.projection_source,
        "document_role": row.document_role,
        "accounting_group_id": str(row.accounting_group_id) if row.accounting_group_id else None,
        "station_id": row.station_id, "number": row.number,
        "document_at": row.document_at, "counterparty": row.counterparty_name,
        "counterparty_inn": row.counterparty_inn,
        "amount": float(row.amount or 0),
        "vat_amount": None if row.vat_amount is None else float(row.vat_amount),
        "operational_status": row.operational_status, "sync_status": row.sync_status,
        "accounting_status": row.accounting_status,
        "discrepancy_status": row.discrepancy_status,
        "requires_attention": row.requires_attention,
        "has_files": row.has_files, "has_fuel": row.has_fuel,
        "revision": row.revision,
    }


def _legacy_doc_ref(row: StoreDocumentProjection) -> str | None:
    if row.source_kind == "receipt":
        return f"receipt:{row.source_record_id}"
    if row.source_kind == "edge_document":
        return f"station:{row.source_record_id}"
    return None


async def _file_projection(
    db: AsyncSession, company_id: uuid.UUID, row: StoreDocFile,
) -> StoreDocumentProjection | None:
    if row.record_id is not None:
        return (await db.execute(select(StoreDocumentProjection).where(
            StoreDocumentProjection.company_id == company_id,
            StoreDocumentProjection.id == row.record_id,
        ))).scalar_one_or_none()
    if row.doc_ref.startswith("receipt:"):
        source_kind = "receipt"
        source_record_id = row.doc_ref.removeprefix("receipt:")
    elif row.doc_ref.startswith("station:"):
        source_kind = "edge_document"
        source_record_id = row.doc_ref.removeprefix("station:")
    else:
        return None
    return (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == company_id,
        StoreDocumentProjection.source_kind == source_kind,
        StoreDocumentProjection.source_record_id == source_record_id,
    ))).scalar_one_or_none()


async def authorize_legacy_document_ref(
    db: AsyncSession, user: User, company_id: uuid.UUID, doc_ref: str, *, write: bool,
) -> tuple[DocumentAccess, StoreDocumentProjection | None]:
    access = await resolve_document_access(user, db, company_id)
    probe = SimpleNamespace(record_id=None, doc_ref=doc_ref)
    document = await _file_projection(db, company_id, probe)
    if document is None:
        if not access.network:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
        if write and not (access.is_superadmin or access.is_merchandiser):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
        return access, None
    await _projection(db, access, document.id)
    if write and not _file_write_allowed(
            access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    return access, document


@router.post("/rebuild")
async def rebuild_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    if not (access.is_superadmin or access.is_merchandiser):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Пересборка доступна товароведу сети")
    result = await rebuild_store_document_projection(db, access.company_id)
    await db.commit()
    return result


@router.get("")
async def list_documents(
    station_id: int | None = Query(None),
    stations: str | None = Query(None, description="Коды АЗС через запятую"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    kind: str | None = Query(None),
    q: str | None = Query(None),
    supplier: str | None = Query(None),
    operational_status: str | None = Query(None),
    sync_status: str | None = Query(None),
    accounting_status: str | None = Query(None),
    discrepancy_status: str | None = Query(None),
    source: str | None = Query(None),
    warehouse: str | None = Query(None, description="UUID склада или его название"),
    attention: bool | None = Query(None),
    has_files: bool | None = Query(None),
    counter: str | None = Query(
        None, description="Отобрать ровно то, что посчитал счётчик реестра"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    base_conditions = [
        StoreDocumentProjection.company_id == access.company_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.document_kind.in_(PROJECTION_DOCUMENT_KINDS),
    ]
    requested_stations: set[int] = set()
    if stations:
        raw_stations = [value.strip() for value in stations.split(",") if value.strip()]
        if any(not value.isdigit() for value in raw_stations):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Коды АЗС должны быть целыми числами")
        requested_stations.update(int(value) for value in raw_stations)
    if station_id is not None:
        requested_stations.add(station_id)
    if access.network:
        if requested_stations:
            base_conditions.append(or_(
                StoreDocumentProjection.station_id.in_(sorted(requested_stations)),
                StoreDocumentProjection.station_id.is_(None),
            ))
    else:
        allowed = set(access.station_ids)
        if requested_stations:
            allowed.intersection_update(requested_stations)
        base_conditions.append(StoreDocumentProjection.station_id.in_(sorted(allowed)))
    if date_from is not None:
        base_conditions.append(StoreDocumentProjection.document_at >= datetime.combine(
            date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        base_conditions.append(StoreDocumentProjection.document_at < datetime.combine(
            date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    filter_conditions = []
    if kind:
        if kind not in PROJECTION_DOCUMENT_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный вид документа")
        filter_conditions.append(StoreDocumentProjection.document_kind == kind)
    if operational_status:
        filter_conditions.append(
            StoreDocumentProjection.operational_status == operational_status)
    if sync_status:
        filter_conditions.append(StoreDocumentProjection.sync_status == sync_status)
    if source:
        filter_conditions.append(StoreDocumentProjection.projection_source == source)
    if supplier and supplier.strip():
        supplier_pattern = f"%{supplier.strip()}%"
        filter_conditions.append(or_(
            StoreDocumentProjection.counterparty_name.ilike(supplier_pattern),
            StoreDocumentProjection.counterparty_inn.ilike(supplier_pattern),
        ))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filter_conditions.append(or_(
            StoreDocumentProjection.number.ilike(pattern),
            StoreDocumentProjection.counterparty_name.ilike(pattern),
            StoreDocumentProjection.counterparty_inn.ilike(pattern),
        ))
    if warehouse and warehouse.strip():
        raw_warehouse = warehouse.strip()
        try:
            filter_conditions.append(
                StoreDocumentProjection.warehouse_id == uuid.UUID(raw_warehouse))
        except ValueError:
            # у документа станции канонического склада может ещё не быть —
            # тогда единственное, что о нём известно, это название в шапке
            warehouse_pattern = f"%{raw_warehouse}%"
            filter_conditions.append(or_(
                StoreDocumentProjection.header["warehouse"].astext.ilike(
                    warehouse_pattern),
                StoreDocumentProjection.header["warehouse_to"].astext.ilike(
                    warehouse_pattern),
            ))

    counter_conditions = []
    if counter:
        if counter not in COUNTER_CONDITIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный счётчик")
        counter_conditions.extend(COUNTER_CONDITIONS[counter]())
    if attention is not None:
        counter_conditions.append(StoreDocumentProjection.requires_attention.is_(attention))
    if has_files is not None:
        counter_conditions.append(StoreDocumentProjection.has_files.is_(has_files))
    if accounting_status:
        counter_conditions.append(
            StoreDocumentProjection.accounting_status == accounting_status)
    if discrepancy_status:
        counter_conditions.append(
            StoreDocumentProjection.discrepancy_status == discrepancy_status)

    stats_conditions = [*base_conditions, *filter_conditions]
    counter_names = tuple(COUNTER_CONDITIONS)
    stats_row = (await db.execute(select(
        *[func.count().filter(*COUNTER_CONDITIONS[name]()) for name in counter_names],
        # реестр — проекция, и человек должен видеть, на какой момент она собрана
        func.max(StoreDocumentProjection.rebuilt_at),
    ).select_from(StoreDocumentProjection).where(*stats_conditions))).one()

    conditions = [*stats_conditions, *counter_conditions]
    total = (await db.execute(select(func.count()).select_from(
        StoreDocumentProjection).where(*conditions))).scalar() or 0
    rows = (await db.execute(select(StoreDocumentProjection).where(*conditions)
                             .order_by(StoreDocumentProjection.document_at.desc().nullslast(),
                                       StoreDocumentProjection.id)
                             .offset(offset).limit(limit))).scalars().all()
    return {
        "documents": [_brief(row) for row in rows], "total": int(total),
        "limit": limit, "offset": offset,
        "stats": {name: int(stats_row[index] or 0)
                  for index, name in enumerate(counter_names)},
        "rebuilt_at": stats_row[len(counter_names)],
        "rebuild_allowed": access.is_superadmin or access.is_merchandiser,
    }


@router.post("/snapshot/queue")
async def queue_document_snapshot(
    station_id: int = Query(..., gt=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    if not access.network:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуется сетевая роль")
    try:
        task, created = await queue_onec_document_snapshot(
            db, access.company_id, station_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return {
        "task_id": str(task.id), "created": created,
        "kind": task.kind, "station_id": task.station_id,
        "revision": int((task.payload or {}).get("revision") or 0),
        "content_hash": (task.payload or {}).get("content_hash"),
        "headers": len((task.payload or {}).get("headers") or []),
    }


@router.get("/{record_id}")
async def document_detail(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    line_refs = (await db.execute(select(StoreDocumentProjectionLine).where(
        StoreDocumentProjectionLine.company_id == access.company_id,
        StoreDocumentProjectionLine.record_id == row.id,
    ).order_by(StoreDocumentProjectionLine.ordinal))).scalars().all()
    payload = await normalized_document_payload(db, row)
    safe_payload = safe_document_detail(row, payload)
    result = _brief(row)
    result.update({
        "header": row.header,
        "file_write_allowed": _file_write_allowed(
            access, row.station_id, row.document_kind),
        "line_refs": [{"section": item.source_section,
                       "line_id": item.source_line_id, "ordinal": item.ordinal}
                      for item in line_refs],
        "document": safe_payload,
    })
    return result


@router.get("/{record_id}/print", response_class=HTMLResponse)
async def document_print_form(
    record_id: uuid.UUID,
    variant: str = Query("main", pattern="^(main|diff)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Печатная форма документа на привычном бланке (ТОРГ-12, ИНВ-3, ТОРГ-2, …)."""
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    payload = safe_document_detail(row, await normalized_document_payload(db, row))
    company = await db.get(Company, access.company_id)
    form = печатная_форма(
        row, payload, компания=getattr(company, "name", "") or "", вариант=variant)
    if form is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Расхождений в документе нет — акт не печатается пустым"
            if variant == "diff" else
            "У этого вида документа нет печатной формы: чек печатает касса, "
            "смена — архив продаж, переоценка оформляется приказом по ценам",
        )
    return HTMLResponse(form)


@router.get("/{record_id}/relations")
async def document_relations(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    await _projection(db, access, record_id)
    relations = (await db.execute(select(StoreDocumentRelation).where(
        StoreDocumentRelation.company_id == access.company_id,
        StoreDocumentRelation.record_id == record_id,
    ))).scalars().all()
    result = []
    for relation in relations:
        if relation.related_record_id is None:
            if relation.relation_kind == "stock_movement":
                metadata = relation.metadata_json or {}
                movement_id = metadata.get("id")
                movement_kind = metadata.get("kind")
                if movement_id and movement_kind:
                    result.append({
                        "kind": "stock_movement",
                        "movement": {
                            "id": str(movement_id), "kind": str(movement_kind),
                            "count": 1,
                        },
                    })
            continue
        try:
            related = await _projection(db, access, relation.related_record_id)
        except HTTPException:
            continue
        result.append({"kind": relation.relation_kind, "related": _brief(related)})
    return {"relations": result, "total": len(result)}


@router.get("/{record_id}/payload")
async def document_payload(
    record_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    row = await _projection(db, access, record_id)
    if not access.can_raw:
        return {
            "available": bool(row.raw_payload_available),
            "status": row.accounting_status,
            "detail": "Полезная нагрузка доступна бухгалтеру",
        }
    return {"available": bool(row.raw_payload_available),
            "payload": await normalized_document_payload(db, row)}


@router.get("/{record_id}/files")
async def document_files(
    record_id: uuid.UUID,
    include_tombstones: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    legacy_ref = _legacy_doc_ref(document)
    file_scope = StoreDocFile.record_id == record_id
    if legacy_ref:
        file_scope = or_(file_scope, StoreDocFile.doc_ref == legacy_ref)
    conditions = [StoreDocFile.company_id == access.company_id, file_scope]
    if not include_tombstones:
        conditions.append(StoreDocFile.tombstoned_at.is_(None))
    rows = (await db.execute(select(StoreDocFile).where(*conditions)
                             .order_by(StoreDocFile.uploaded_at.desc()))).scalars().all()
    return {"files": [{
        "id": str(row.id), "role": row.role or row.kind,
        "file_name": row.file_name, "mime": row.mime, "size_bytes": row.size_bytes,
        "sha256": row.sha256, "revision": row.revision,
        "uploaded_at": row.uploaded_at, "tombstoned_at": row.tombstoned_at,
        "download_url": f"/api/store/documents/{record_id}/files/{row.id}/download",
    } for row in rows], "total": len(rows)}


@router.post("/{record_id}/files", status_code=201)
async def document_file_upload(
    record_id: uuid.UUID,
    role: str = Query("накладная"),
    note: str | None = Query(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    if not _file_write_allowed(access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    if role not in FILE_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная роль файла")
    if (file.content_type or "") not in FILE_MIME_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Разрешены PDF, JPEG, PNG и WebP")
    content = await file.read()
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пуст или больше 25 МБ")
    checksum = hashlib.sha256(content).hexdigest()
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
    ), {"scope_key": f"store-document-file:{access.company_id}:{record_id}"})
    existing = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.company_id == access.company_id,
        StoreDocFile.record_id == record_id,
        StoreDocFile.revision == document.revision,
        StoreDocFile.role == role,
        StoreDocFile.sha256 == checksum,
    ))).scalar_one_or_none()
    if existing is not None:
        return {"id": str(existing.id), "created": False, "sha256": checksum}
    file_id = uuid.uuid4()
    file_path = Path(os.environ.get("UPLOAD_DIR", "/app/uploads")) / (
        f"{file_id}{Path(file.filename or 'file').suffix}"
    )
    try:
        await ops_terms.store_file(
            db, access.company_id, file.filename, file.content_type, content,
            file_id=file_id)
        row = StoreDocFile(
            company_id=access.company_id,
            doc_ref=f"projection:{record_id}",
            record_id=record_id,
            document_id=document.document_id,
            station_id=document.station_id,
            kind=role,
            role=role,
            sha256=checksum,
            revision=document.revision,
            file_id=file_id,
            file_name=file.filename or "документ",
            mime=file.content_type,
            size_bytes=len(content),
            note=note,
            uploaded_by=user.id,
            author_id=user.id,
        )
        db.add(row)
        document.has_files = True
        meta = (await db.execute(select(StoreDocMeta).where(
            StoreDocMeta.company_id == access.company_id,
            StoreDocMeta.record_id == record_id,
        ))).scalar_one_or_none()
        if meta is None:
            db.add(StoreDocMeta(
                company_id=access.company_id, doc_ref=f"projection:{record_id}",
                record_id=record_id, document_id=document.document_id,
                revision=document.revision, updated_by=user.id,
            ))
        await db.commit()
    except Exception:
        await db.rollback()
        file_path.unlink(missing_ok=True)
        raise
    return {"id": str(row.id), "created": True, "sha256": checksum}


@router.delete("/{record_id}/files/{file_row_id}")
async def document_file_tombstone(
    record_id: uuid.UUID,
    file_row_id: uuid.UUID,
    reason: str = Query(..., min_length=3, max_length=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    if not _file_write_allowed(access, document.station_id, document.document_kind):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только просмотр")
    row = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.id == file_row_id,
        StoreDocFile.company_id == access.company_id,
        or_(StoreDocFile.record_id == record_id,
            StoreDocFile.doc_ref == (_legacy_doc_ref(document) or "")),
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    if row.tombstoned_at is None:
        row.tombstoned_at = datetime.now(timezone.utc)
        row.tombstoned_by = user.id
        row.tombstone_reason = reason.strip()
    remaining_scope = StoreDocFile.record_id == record_id
    legacy_ref = _legacy_doc_ref(document)
    if legacy_ref:
        remaining_scope = or_(remaining_scope, StoreDocFile.doc_ref == legacy_ref)
    remaining = (await db.execute(select(func.count()).select_from(StoreDocFile).where(
        StoreDocFile.company_id == access.company_id,
        remaining_scope,
        StoreDocFile.id != file_row_id,
        StoreDocFile.tombstoned_at.is_(None),
    ))).scalar() or 0
    document.has_files = bool(remaining)
    await db.commit()
    return {"ok": True, "tombstoned": True}


@router.get("/{record_id}/files/{file_row_id}/download")
async def document_file_download(
    record_id: uuid.UUID,
    file_row_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access = await resolve_document_access(user, db)
    document = await _projection(db, access, record_id)
    row = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.id == file_row_id,
        StoreDocFile.company_id == access.company_id,
        or_(StoreDocFile.record_id == record_id,
            StoreDocFile.doc_ref == (_legacy_doc_ref(document) or "")),
        StoreDocFile.tombstoned_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    source = await db.get(SourceFile, row.file_id)
    if source is None or source.company_id != access.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    path = Path(source.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
    return FileResponse(str(path), media_type=source.mime_type, filename=source.file_name)


async def authorize_store_file_download(
    db: AsyncSession, user: User, file_id: uuid.UUID,
) -> None:
    rows = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.file_id == file_id,
    ))).scalars().all()
    if not rows:
        return
    for row in rows:
        if row.tombstoned_at is not None:
            continue
        try:
            access = await resolve_document_access(user, db, row.company_id)
            document = await _file_projection(db, row.company_id, row)
            if document is None:
                continue
            await _projection(db, access, document.id)
            return
        except HTTPException:
            continue
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
