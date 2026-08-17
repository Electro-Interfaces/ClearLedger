from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    DocArchiveEvent, DocCard, DocCase, DocDestructionAct, DocDestructionItem,
    DocEvent, DocExport, DocLegalHold, DocRetentionDecision, DocShareLink,
    DocVersion, MailMessage, User,
)
from app.routers.docs_router import (
    _archiveable_doc_clause, _assert_doc_permission, _doc_or_404, _uuid_or_400,
)
from app.services import doc_archive

router = APIRouter(prefix="/docs", tags=["Трек: архив"])
_BUSINESS_TIMEZONE = ZoneInfo("Europe/Moscow")
_EXECUTION_LEASE_TTL = timedelta(hours=2)


class HoldIn(BaseModel):
    company_id: str
    authority: str = Field(..., min_length=3, max_length=300)
    reference: str | None = Field(None, max_length=300)
    reason: str = Field(..., min_length=3, max_length=1000)


class HoldReleaseIn(BaseModel):
    company_id: str
    reason: str = Field(..., min_length=3, max_length=1000)


class RetentionDecisionIn(BaseModel):
    company_id: str
    decision: str = Field(..., pattern="^(destroy|extend|permanent)$")
    reason: str = Field(..., min_length=10, max_length=2000)
    epk_reference: str | None = Field(None, max_length=500)
    new_storage_until: date | None = None


class LegacyConfirmIn(BaseModel):
    company_id: str
    retention_class: str = Field(
        ..., pattern="^(temporary|epk|permanent|unclassified)$")
    basis: str = Field(..., min_length=3, max_length=500)
    reason: str = Field(..., min_length=10, max_length=2000)


class ActCreateIn(BaseModel):
    company_id: str
    act_number: str = Field(..., min_length=1, max_length=80)
    act_date: date
    basis: str = Field(..., min_length=10, max_length=2000)
    committee: list[str] = Field(..., min_length=2, max_length=20)
    doc_ids: list[str] = Field(..., min_length=1, max_length=200)


class ActActionIn(BaseModel):
    company_id: str


class ActCancelIn(BaseModel):
    company_id: str
    reason: str = Field(..., min_length=10, max_length=1000)


class BackupAttestationIn(BaseModel):
    company_id: str
    evidence: str = Field(..., min_length=10, max_length=2000)
    external_copies_evidence: str | None = Field(None, max_length=2000)


class ExportResolutionIn(BaseModel):
    company_id: str
    resolution: str = Field(..., pattern="^(placed|failed)$")
    evidence: str = Field(..., min_length=10, max_length=2000)
    no_local_copy: bool = False


async def _lock_doc(db: AsyncSession, cid: uuid.UUID,
                    doc_id: uuid.UUID) -> DocCard:
    row = (await db.execute(select(DocCard).where(
        DocCard.company_id == cid, DocCard.id == doc_id,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return row


async def _assert_archive_access(db: AsyncSession, cid: uuid.UUID,
                                 doc: DocCard, user: User) -> None:
    await _assert_doc_permission(db, cid, doc, user, "read")
    await _assert_doc_permission(db, cid, doc, user, "archive")


def _hold_out(row: DocLegalHold) -> dict:
    return {
        "id": str(row.id), "authority": row.authority,
        "reference": row.reference, "reason": row.reason,
        "placed_by": str(row.placed_by) if row.placed_by else None,
        "placed_at": row.placed_at.isoformat() if row.placed_at else None,
        "released_by": str(row.released_by) if row.released_by else None,
        "released_at": row.released_at.isoformat() if row.released_at else None,
        "release_reason": row.release_reason,
    }


def _decision_out(row: DocRetentionDecision) -> dict:
    return {
        "id": str(row.id), "decision": row.decision, "reason": row.reason,
        "epk_reference": row.epk_reference,
        "new_storage_until": (row.new_storage_until.isoformat()
                              if row.new_storage_until else None),
        "snapshot_sha256": row.snapshot_sha256,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _act_out(row: DocDestructionAct, item_count: int | None = None) -> dict:
    return {
        "id": str(row.id), "organization_id": (
            str(row.organization_id) if row.organization_id else None),
        "act_number": row.act_number, "act_date": row.act_date.isoformat(),
        "basis": row.basis, "committee": row.committee or [],
        "status": row.status,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approved_by": str(row.approved_by) if row.approved_by else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "executed_by": str(row.executed_by) if row.executed_by else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "backup_attested_by": (str(row.backup_attested_by)
                               if row.backup_attested_by else None),
        "backup_attested_at": (row.backup_attested_at.isoformat()
                               if row.backup_attested_at else None),
        "backup_evidence": row.backup_evidence,
        "sealed_sha256": row.sealed_sha256,
        "error": None if row.status == "cancelled" else row.error,
        "cancellation_reason": row.error if row.status == "cancelled" else None,
        "items": item_count,
    }


def _document_act_out(row: DocDestructionAct,
                      item: DocDestructionItem) -> dict:
    result = _act_out(row)
    result["backup_evidence"] = None
    result["error"] = item.error
    result["item_status"] = item.status
    result["item_error"] = item.error
    result["has_known_external_copies"] = bool(
        (item.snapshot or {}).get("known_external_copies")
        or (item.snapshot or {}).get("known_share_links")
    )
    return result


def _unresolved_export_out(row: DocExport) -> dict:
    content = row.content if isinstance(row.content, dict) else {}
    return {
        "id": str(row.id), "status": row.status,
        "package_name": row.package_name,
        "channel": (content.get("channel") or (
            "mail" if content.get("mail_message_id")
            or content.get("rfc_message_id") else None)),
        "error": row.error,
        "no_local_copy_attested": doc_archive.no_local_mail_copy_attested(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _encode_archive_cursor(doc: DocCard) -> str:
    value = json.dumps({
        "storage_until": doc.storage_until.isoformat() if doc.storage_until else None,
        "id": str(doc.id),
    }, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_archive_cursor(value: str) -> tuple[date | None, uuid.UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        raw_until = payload.get("storage_until")
        until = date.fromisoformat(raw_until) if raw_until is not None else None
        return until, uuid.UUID(str(payload["id"]))
    except (binascii.Error, KeyError, TypeError, UnicodeDecodeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Неверный курсор архивной очереди")


@router.get("/archive/queue")
async def archive_queue(
    company_id: str = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    conditions = [
        DocCard.company_id == cid,
        DocCard.status == "archived",
        await _archiveable_doc_clause(db, cid, current_user),
    ]
    if cursor:
        cursor_until, cursor_id = _decode_archive_cursor(cursor)
        if cursor_until is None:
            conditions.append(and_(
                DocCard.storage_until.is_(None), DocCard.id > cursor_id,
            ))
        else:
            conditions.append(or_(
                DocCard.storage_until > cursor_until,
                and_(DocCard.storage_until == cursor_until,
                     DocCard.id > cursor_id),
                DocCard.storage_until.is_(None),
            ))
    rows = list((await db.execute(select(DocCard).where(
        *conditions,
    ).order_by(DocCard.storage_until.asc().nullslast(), DocCard.id)
        .limit(limit + 1))).scalars().all())
    has_more = len(rows) > limit
    page = rows[:limit]
    hold_doc_ids = set()
    if page:
        hold_doc_ids = set((await db.execute(select(DocLegalHold.doc_id).where(
            DocLegalHold.company_id == cid,
            DocLegalHold.doc_id.in_([doc.id for doc in page]),
            DocLegalHold.released_at.is_(None),
        ))).scalars().all())
    today = datetime.now(_BUSINESS_TIMEZONE).date()
    result = []
    for doc in page:
        held = doc.id in hold_doc_ids
        result.append({
            "id": str(doc.id), "title": doc.title,
            "reg_number": doc.reg_number,
            "organization_id": (str(doc.organization_id)
                                if doc.organization_id else None),
            "storage_until": (doc.storage_until.isoformat()
                              if doc.storage_until else None),
            "retention_extended_until": (
                doc.retention_extended_until.isoformat()
                if doc.retention_extended_until else None),
            "retention_state": doc.retention_state,
            "retention_class": doc.retention_class,
            "hold": held,
            "blocker": doc_archive.destruction_blocker(
                doc, [True] if held else [], today),
        })
    return {
        "documents": result,
        "next_cursor": (_encode_archive_cursor(page[-1])
                        if has_more and page else None),
    }


async def _assertible_archive(db: AsyncSession, cid: uuid.UUID,
                              doc: DocCard, user: User) -> bool:
    try:
        await _assert_archive_access(db, cid, doc, user)
        return True
    except HTTPException:
        return False


@router.get("/archive/acts")
async def list_acts(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(
        DocDestructionAct, func.count(DocDestructionItem.id),
    ).outerjoin(DocDestructionItem,
                DocDestructionItem.act_id == DocDestructionAct.id).where(
        DocDestructionAct.company_id == cid,
    ).group_by(DocDestructionAct.id).order_by(
        DocDestructionAct.act_date.desc(),
        DocDestructionAct.created_at.desc(),
    ))).all()
    visible = []
    for act, count in rows:
        doc_ids = list((await db.execute(select(DocDestructionItem.doc_id).where(
            DocDestructionItem.act_id == act.id))).scalars().all())
        if not doc_ids:
            continue
        docs = list((await db.execute(select(DocCard).where(
            DocCard.company_id == cid, DocCard.id.in_(doc_ids)))).scalars().all())
        if len(docs) == len(doc_ids) and all([
            await _assertible_archive(db, cid, doc, current_user) for doc in docs
        ]):
            visible.append(_act_out(act, count))
    return {"acts": visible}


@router.post("/archive/exports/{export_id}/resolve")
async def resolve_external_export(
    export_id: str,
    payload: ExportResolutionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    row = (await db.execute(select(DocExport).where(
        DocExport.company_id == cid,
        DocExport.id == _uuid_or_400(export_id, "export_id"),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Отправка не найдена")
    doc = await _lock_doc(db, cid, row.doc_id)
    await _assert_archive_access(db, cid, doc, current_user)
    row = (await db.execute(select(DocExport).where(
        DocExport.company_id == cid, DocExport.id == row.id,
    ).execution_options(populate_existing=True).with_for_update())).scalar_one()
    if row.status not in {"pending", "unknown"}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Исход отправки уже зафиксирован")
    previous_status = row.status
    previous_error = row.error
    resolved_at = datetime.now(timezone.utc)
    content = dict(row.content or {})
    content.pop("no_local_copy_attestation", None)
    is_mail_export = (
        content.get("channel") == "mail"
        or content.get("mail_message_id") is not None
        or content.get("rfc_message_id") is not None
    )
    local_message = None
    if payload.resolution == "placed" and is_mail_export:
        local_filters = []
        raw_message_id = content.get("mail_message_id")
        if raw_message_id is not None:
            try:
                local_filters.append(MailMessage.id == uuid.UUID(str(raw_message_id)))
            except ValueError:
                pass
        if content.get("rfc_message_id"):
            local_filters.append(
                MailMessage.message_id == str(content["rfc_message_id"]),
            )
        if local_filters:
            local_rows = list((await db.execute(select(MailMessage).where(
                MailMessage.company_id == cid,
                MailMessage.direction == "out",
                or_(*local_filters),
            ).with_for_update())).scalars().all())
            unique_rows = {candidate.id: candidate for candidate in local_rows}
            if len(unique_rows) > 1:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Локальная копия письма определена неоднозначно",
                )
            local_message = next(iter(unique_rows.values()), None)
        if local_message is not None:
            if payload.no_local_copy:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Локальная копия письма найдена; подтверждать её отсутствие нельзя",
                )
            content["mail_message_id"] = str(local_message.id)
            content["rfc_message_id"] = local_message.message_id
        else:
            if not payload.no_local_copy:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Подтвердите, что локальная копия письма отсутствует",
                )
            content["no_local_copy_attestation"] = {
                "company_id": str(cid),
                "export_id": str(row.id),
                "attested_by": str(current_user.id),
                "attested_at": resolved_at.isoformat(),
                "evidence": payload.evidence.strip(),
            }
    row.status = payload.resolution
    row.error = None if payload.resolution == "placed" else previous_error
    row.content = {
        **content,
        "resolution": {
            "status": payload.resolution,
            "evidence": payload.evidence.strip(),
            "previous_status": previous_status,
            "previous_error": previous_error,
            "resolved_by": str(current_user.id),
            "resolved_at": resolved_at.isoformat(),
        },
    }
    await doc_archive.append_event(
        db, company_id=cid, doc_id=doc.id, actor=current_user,
        kind="external_export_resolved",
        payload={
            "export_id": str(row.id), "status": row.status,
            "evidence": payload.evidence.strip(),
            "no_local_copy_attested": doc_archive.no_local_mail_copy_attested(row),
        },
    )
    await log_audit(
        db, actor=current_user, company_id=cid,
        action="doc.archive.export.resolve", target=str(doc.id),
        details={"export_id": str(row.id), "status": row.status,
                 "previous_status": previous_status,
                 "no_local_copy_attested": (
                     doc_archive.no_local_mail_copy_attested(row))},
    )
    await db.commit()
    return _unresolved_export_out(row)


@router.get("/{doc_id}/archive")
async def get_document_archive(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    doc = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, doc, current_user, "read")
    holds = list((await db.execute(select(DocLegalHold).where(
        DocLegalHold.company_id == cid, DocLegalHold.doc_id == doc.id,
    ).order_by(DocLegalHold.placed_at.desc()))).scalars().all())
    decisions = list((await db.execute(select(DocRetentionDecision).where(
        DocRetentionDecision.company_id == cid,
        DocRetentionDecision.doc_id == doc.id,
    ).order_by(DocRetentionDecision.created_at.desc()))).scalars().all())
    item_rows = (await db.execute(select(
        DocDestructionItem, DocDestructionAct,
    ).join(DocDestructionAct, DocDestructionAct.id == DocDestructionItem.act_id).where(
        DocDestructionItem.company_id == cid,
        DocDestructionItem.doc_id == doc.id,
    ).order_by(DocDestructionAct.created_at.desc()))).all()
    archive_events = list((await db.execute(select(DocArchiveEvent).where(
        DocArchiveEvent.company_id == cid,
        DocArchiveEvent.doc_id == doc.id,
    ).order_by(DocArchiveEvent.created_at, DocArchiveEvent.id))).scalars().all())
    can_manage = await _assertible_archive(db, cid, doc, current_user)
    unresolved_exports = list((await db.execute(select(DocExport).where(
        DocExport.company_id == cid, DocExport.doc_id == doc.id,
        DocExport.status.in_(("pending", "unknown")),
    ).order_by(DocExport.created_at, DocExport.id))).scalars().all())
    active = [row for row in holds if row.released_at is None]
    return {
        "retention_state": doc.retention_state,
        "retention_class": doc.retention_class,
        "retention_snapshot": doc.retention_snapshot,
        "storage_until": doc.storage_until.isoformat() if doc.storage_until else None,
        "retention_extended_until": (
            doc.retention_extended_until.isoformat()
            if doc.retention_extended_until else None),
        "archive_accepted_at": (doc.archive_accepted_at.isoformat()
                                if doc.archive_accepted_at else None),
        "primary_purged_at": (doc.primary_purged_at.isoformat()
                              if doc.primary_purged_at else None),
        "destroyed_at": doc.destroyed_at.isoformat() if doc.destroyed_at else None,
        "can_manage": can_manage,
        "blocker": doc_archive.destruction_blocker(
            doc, active, datetime.now(_BUSINESS_TIMEZONE).date()),
        "holds": [_hold_out(row) for row in holds],
        "decisions": [_decision_out(row) for row in decisions],
        "unresolved_exports": [
            _unresolved_export_out(row) for row in unresolved_exports
        ],
        "acts": [_document_act_out(act, item) for item, act in item_rows],
        "events": [{
            "id": str(event.id), "kind": event.kind,
            "doc_id": str(event.doc_id) if event.doc_id else None,
            "act_id": str(event.act_id) if event.act_id else None,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "actor_name": event.actor_name,
            "payload": event.payload or {},
            "prev_hash": event.prev_hash,
            "event_hash": event.event_hash,
            "created_at": event.created_at.isoformat(),
        } for event in archive_events],
    }


@router.post("/{doc_id}/archive/holds", status_code=status.HTTP_201_CREATED)
async def place_hold(
    doc_id: str,
    payload: HoldIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    doc = await _lock_doc(db, cid, _uuid_or_400(doc_id, "doc_id"))
    await _assert_archive_access(db, cid, doc, current_user)
    if doc.retention_state == "destroyed":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Уничтожение документа уже подтверждено")
    row = DocLegalHold(
        company_id=cid, doc_id=doc.id,
        authority=payload.authority.strip(),
        reference=(payload.reference or "").strip() or None,
        reason=payload.reason.strip(), placed_by=current_user.id,
    )
    db.add(row)
    await doc_archive.append_event(
        db, company_id=cid, doc_id=doc.id, actor=current_user,
        kind="hold_placed",
        payload={"authority": row.authority, "reference": row.reference,
                 "reason": row.reason},
    )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.hold", target=str(doc.id),
                    details={"authority": row.authority, "reference": row.reference})
    await db.commit()
    await db.refresh(row)
    return _hold_out(row)


@router.post("/archive/holds/{hold_id}/release")
async def release_hold(
    hold_id: str,
    payload: HoldReleaseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    row = (await db.execute(select(DocLegalHold).where(
        DocLegalHold.company_id == cid,
        DocLegalHold.id == _uuid_or_400(hold_id, "hold_id"),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запрет не найден")
    doc = await _lock_doc(db, cid, row.doc_id)
    await _assert_archive_access(db, cid, doc, current_user)
    row = (await db.execute(select(DocLegalHold).where(
        DocLegalHold.company_id == cid,
        DocLegalHold.id == row.id,
    ).execution_options(populate_existing=True).with_for_update())).scalar_one()
    if row.released_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Запрет уже снят")
    row.released_at = datetime.now(timezone.utc)
    row.released_by = current_user.id
    row.release_reason = payload.reason.strip()
    await doc_archive.append_event(
        db, company_id=cid, doc_id=doc.id, actor=current_user,
        kind="hold_released", payload={"hold_id": str(row.id),
                                       "reason": row.release_reason},
    )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.hold.release", target=str(doc.id),
                    details={"hold_id": str(row.id), "reason": row.release_reason})
    await db.commit()
    return _hold_out(row)


@router.post("/{doc_id}/archive/decisions", status_code=status.HTTP_201_CREATED)
async def decide_retention(
    doc_id: str,
    payload: RetentionDecisionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    doc = await _lock_doc(db, cid, _uuid_or_400(doc_id, "doc_id"))
    await _assert_archive_access(db, cid, doc, current_user)
    holds = await doc_archive.active_holds(db, cid, doc.id, lock=True)
    if holds:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала снимите действующий запрет уничтожения")
    if doc.status != "archived":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Экспертиза проводится после приёма во внутренний архив")
    if doc.retention_state in {"primary_purged", "destroyed"}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Решение по уже выбывшему документу не меняется")
    if doc.retention_state == "legacy_review":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала подтвердите основание хранения прежнего архива")
    active_act = await db.scalar(select(DocDestructionItem.id).where(
        DocDestructionItem.company_id == cid,
        DocDestructionItem.doc_id == doc.id,
        DocDestructionItem.status.in_(("pending", "primary_purged", "failed")),
    ).limit(1))
    if active_act is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Документ уже включён в незавершённый акт")
    snapshot = await doc_archive.document_snapshot(db, doc)
    if payload.decision == "destroy":
        blocker = doc_archive.destruction_blocker(
            doc, holds, datetime.now(_BUSINESS_TIMEZONE).date())
        if blocker:
            raise HTTPException(status.HTTP_409_CONFLICT, blocker)
        case_row = await db.get(DocCase, doc.case_id) if doc.case_id else None
        if ((case_row and case_row.epk) or doc.retention_class == "epk") and not (
                payload.epk_reference or "").strip():
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Для документа ЭПК укажите решение комиссии")
        doc.retention_state = "destruction_ready"
    elif payload.decision == "extend":
        current_until = doc_archive.effective_until(doc)
        if payload.new_storage_until is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Укажите новый срок хранения")
        if current_until and payload.new_storage_until <= current_until:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Новый срок должен быть позже действующего")
        doc.retention_extended_until = payload.new_storage_until
        doc.retention_state = "archived"
    else:
        if payload.new_storage_until is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Для постоянного хранения дата не указывается")
        doc.retention_state = "permanent"
        doc.retention_class = "permanent"
    row = DocRetentionDecision(
        company_id=cid, doc_id=doc.id, decision=payload.decision,
        reason=payload.reason.strip(),
        epk_reference=(payload.epk_reference or "").strip() or None,
        new_storage_until=payload.new_storage_until,
        snapshot=snapshot, snapshot_sha256=doc_archive.snapshot_hash(snapshot),
        created_by=current_user.id,
    )
    db.add(row)
    await doc_archive.append_event(
        db, company_id=cid, doc_id=doc.id, actor=current_user,
        kind="retention_decided",
        payload={"decision": row.decision, "reason": row.reason,
                 "epk_reference": row.epk_reference,
                 "new_storage_until": str(row.new_storage_until or "")},
    )
    db.add(DocEvent(
        doc_id=doc.id, kind="archive", user_id=current_user.id,
        actor_name=current_user.name or current_user.email,
        to_value=payload.decision, note=payload.reason.strip(),
    ))
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.decision", target=str(doc.id),
                    details={"decision": payload.decision,
                             "snapshot_sha256": row.snapshot_sha256})
    await db.commit()
    await db.refresh(row)
    return _decision_out(row)


@router.post("/{doc_id}/archive/confirm-legacy")
async def confirm_legacy_archive(
    doc_id: str,
    payload: LegacyConfirmIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    doc = await _lock_doc(db, cid, _uuid_or_400(doc_id, "doc_id"))
    await _assert_archive_access(db, cid, doc, current_user)
    if doc.status != "archived" or doc.retention_state != "legacy_review":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Подтверждение требуется только архиву прежней версии")
    if await doc_archive.active_holds(db, cid, doc.id, lock=True):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала снимите действующий запрет уничтожения")
    snapshot = await doc_archive.document_snapshot(db, doc)
    snapshot["legacy_confirmation"] = {
        "basis": payload.basis.strip(),
        "reason": payload.reason.strip(),
        "retention_class": payload.retention_class,
        "confirmed_by": str(current_user.id),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    doc.retention_snapshot = snapshot
    doc.retention_class = payload.retention_class
    doc.retention_state = (
        "permanent" if payload.retention_class == "permanent" else "archived")
    await doc_archive.append_event(
        db, company_id=cid, doc_id=doc.id, actor=current_user,
        kind="legacy_retention_confirmed",
        payload=snapshot["legacy_confirmation"],
    )
    await log_audit(
        db, actor=current_user, company_id=cid,
        action="doc.archive.legacy.confirm", target=str(doc.id),
        details=snapshot["legacy_confirmation"],
    )
    await db.commit()
    return {"retention_state": doc.retention_state,
            "retention_class": doc.retention_class,
            "retention_snapshot": doc.retention_snapshot}


@router.post("/archive/acts", status_code=status.HTTP_201_CREATED)
async def create_act(
    payload: ActCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    today = datetime.now(_BUSINESS_TIMEZONE).date()
    if payload.act_date > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Дата акта не может быть в будущем")
    doc_ids = sorted({_uuid_or_400(value, "doc_id") for value in payload.doc_ids})
    docs = list((await db.execute(select(DocCard).where(
        DocCard.company_id == cid, DocCard.id.in_(doc_ids),
    ).order_by(DocCard.id).with_for_update())).scalars().all())
    if len(docs) != len(doc_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ акта не найден")
    organization_ids = {doc.organization_id for doc in docs}
    if len(organization_ids) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "В одном акте должны быть документы одного юрлица")
    decisions: dict[uuid.UUID, DocRetentionDecision] = {}
    for doc in docs:
        await _assert_archive_access(db, cid, doc, current_user)
        holds = await doc_archive.active_holds(db, cid, doc.id, lock=True)
        blocker = doc_archive.destruction_blocker(doc, holds, today)
        if blocker or doc.retention_state != "destruction_ready":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{doc.reg_number or doc.title}: {blocker or 'нет решения об уничтожении'}")
        decision = (await db.execute(select(DocRetentionDecision).where(
            DocRetentionDecision.company_id == cid,
            DocRetentionDecision.doc_id == doc.id,
            DocRetentionDecision.decision == "destroy",
        ).order_by(DocRetentionDecision.created_at.desc()).limit(1))).scalar_one_or_none()
        if decision is None:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Нет решения экспертизы об уничтожении")
        decisions[doc.id] = decision
    act = DocDestructionAct(
        company_id=cid, organization_id=next(iter(organization_ids)),
        act_number=payload.act_number.strip(), act_date=payload.act_date,
        basis=payload.basis.strip(),
        committee=[value.strip() for value in payload.committee if value.strip()],
        status="draft", created_by=current_user.id,
    )
    if len(act.committee) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "В комиссии должно быть не менее двух участников")
    db.add(act)
    await db.flush()
    for doc in docs:
        decision = decisions[doc.id]
        snapshot = await doc_archive.document_snapshot(db, doc)
        if blocker := doc_archive.external_export_blocker(snapshot):
            raise HTTPException(status.HTTP_409_CONFLICT, blocker)
        db.add(DocDestructionItem(
            company_id=cid, act_id=act.id, doc_id=doc.id,
            decision_id=decision.id, snapshot=snapshot,
            snapshot_sha256=doc_archive.snapshot_hash(snapshot), status="pending",
        ))
    await db.flush()
    await doc_archive.append_event(
        db, company_id=cid, act_id=act.id, actor=current_user,
        kind="act_created", payload={"number": act.act_number,
                                     "documents": len(docs)},
    )
    for doc in docs:
        await doc_archive.append_event(
            db, company_id=cid, doc_id=doc.id, act_id=act.id,
            actor=current_user, kind="act_created",
            payload={"number": act.act_number},
        )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.act.create", target=str(act.id),
                    details={"number": act.act_number, "documents": len(docs)})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Номер акта уже занят или документ уже включён в другой акт")
    await db.refresh(act)
    return _act_out(act, len(docs))


@router.post("/archive/acts/{act_id}/approve")
async def approve_act(
    act_id: str,
    payload: ActActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    act = (await db.execute(select(DocDestructionAct).where(
        DocDestructionAct.company_id == cid,
        DocDestructionAct.id == _uuid_or_400(act_id, "act_id"),
    ).with_for_update())).scalar_one_or_none()
    if act is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт не найден")
    if act.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Акт уже рассмотрен")
    if act.created_by == current_user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Составитель акта не может сам его утвердить")
    items = list((await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.act_id == act.id,
    ).order_by(DocDestructionItem.doc_id).with_for_update())).scalars().all())
    links: list[DocShareLink] = []
    for item in items:
        doc = await _lock_doc(db, cid, item.doc_id)
        await _assert_archive_access(db, cid, doc, current_user)
        if await doc_archive.active_holds(db, cid, doc.id, lock=True):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "На один из документов установлен запрет уничтожения")
        links.extend(list((await db.execute(select(DocShareLink).where(
            DocShareLink.doc_id == doc.id,
            DocShareLink.revoked.is_(False),
        ).with_for_update())).scalars().all()))
        current = await doc_archive.document_snapshot(db, doc)
        if blocker := doc_archive.external_export_blocker(current):
            raise HTTPException(status.HTTP_409_CONFLICT, blocker)
        if doc_archive.snapshot_hash(current) != item.snapshot_sha256:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Состав документа изменился после подготовки акта")
        doc.retention_state = "destruction_authorized"
    act.sealed_snapshot, act.sealed_sha256 = await doc_archive.seal_act(db, act)
    act.status = "approved"
    act.approved_by = current_user.id
    act.approved_at = datetime.now(timezone.utc)
    for link in links:
        link.revoked = True
    await doc_archive.append_event(
        db, company_id=cid, act_id=act.id, actor=current_user,
        kind="act_approved", payload={"sealed_sha256": act.sealed_sha256,
                                      "shares_revoked": len(links)},
    )
    for item in items:
        await doc_archive.append_event(
            db, company_id=cid, doc_id=item.doc_id, act_id=act.id,
            actor=current_user, kind="act_approved",
            payload={"act_number": act.act_number},
        )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.act.approve", target=str(act.id),
                    details={"sealed_sha256": act.sealed_sha256})
    await db.commit()
    return _act_out(act, len(items))


@router.post("/archive/acts/{act_id}/cancel")
async def cancel_act(
    act_id: str,
    payload: ActCancelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    act = (await db.execute(select(DocDestructionAct).where(
        DocDestructionAct.company_id == cid,
        DocDestructionAct.id == _uuid_or_400(act_id, "act_id"),
    ).with_for_update())).scalar_one_or_none()
    if act is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт не найден")
    if act.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Отменить можно только неутверждённый акт")
    items = list((await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.act_id == act.id,
    ).order_by(DocDestructionItem.doc_id).with_for_update())).scalars().all())
    for item in items:
        doc = await _lock_doc(db, cid, item.doc_id)
        await _assert_archive_access(db, cid, doc, current_user)
        item.status = "cancelled"
    act.status = "cancelled"
    act.error = payload.reason.strip()
    await doc_archive.append_event(
        db, company_id=cid, act_id=act.id, actor=current_user,
        kind="act_cancelled", payload={"reason": act.error},
    )
    for item in items:
        await doc_archive.append_event(
            db, company_id=cid, doc_id=item.doc_id, act_id=act.id,
            actor=current_user, kind="act_cancelled",
            payload={"act_number": act.act_number, "reason": act.error},
        )
    await log_audit(
        db, actor=current_user, company_id=cid,
        action="doc.archive.act.cancel", target=str(act.id),
        details={"reason": act.error},
    )
    await db.commit()
    return _act_out(act, len(items))


@router.post("/archive/acts/{act_id}/execute")
async def execute_act(
    act_id: str,
    payload: ActActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    aid = _uuid_or_400(act_id, "act_id")
    act = (await db.execute(select(DocDestructionAct).where(
        DocDestructionAct.company_id == cid, DocDestructionAct.id == aid,
    ))).scalar_one_or_none()
    if act is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт не найден")
    if act.status not in {"approved", "executing", "failed"}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Акт уже завершён или не готов к исполнению")
    if act.created_by == current_user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Составитель акта не может исполнять уничтожение")
    if act.approved_by == current_user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Утвердивший акт не может исполнять уничтожение")
    now = datetime.now(timezone.utc)
    lease_cutoff = now - _EXECUTION_LEASE_TTL
    if (act.status == "executing" and act.executed_at is not None
            and act.executed_at > lease_cutoff):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Исполнение акта уже начато другим сотрудником")
    observed_status = act.status
    observed_executed_at = act.executed_at
    item_ids = list((await db.execute(select(DocDestructionItem.id).where(
        DocDestructionItem.act_id == act.id,
        DocDestructionItem.status.in_(("pending", "failed")),
    ).order_by(DocDestructionItem.doc_id))).scalars().all())
    for item_id in item_ids:
        item = await db.get(DocDestructionItem, item_id)
        doc = await db.get(DocCard, item.doc_id) if item else None
        if doc is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Документ акта не найден")
        await _assert_archive_access(db, cid, doc, current_user)
    expected_lease = (
        DocDestructionAct.executed_at.is_(None)
        if observed_executed_at is None
        else DocDestructionAct.executed_at == observed_executed_at
    )
    claimed = await db.scalar(update(DocDestructionAct).where(
        DocDestructionAct.company_id == cid,
        DocDestructionAct.id == aid,
        DocDestructionAct.status == observed_status,
        expected_lease,
    ).values(
        status="executing", executed_by=current_user.id,
        executed_at=now, error=None,
    ).returning(DocDestructionAct.id))
    if claimed is None:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Исполнение акта уже захвачено другим запросом")
    lease_started_at = now
    await db.commit()
    errors: list[str] = []
    for item_id in item_ids:
        act = (await db.execute(select(DocDestructionAct).where(
            DocDestructionAct.id == aid,
            DocDestructionAct.company_id == cid,
            DocDestructionAct.status == "executing",
            DocDestructionAct.executed_by == current_user.id,
            DocDestructionAct.executed_at == lease_started_at,
        ).with_for_update())).scalar_one_or_none()
        if act is None:
            await db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Право исполнения акта перешло другому запросу")
        item = (await db.execute(select(DocDestructionItem).where(
            DocDestructionItem.id == item_id,
            DocDestructionItem.company_id == cid,
            DocDestructionItem.act_id == aid,
        ).with_for_update())).scalar_one()
        try:
            await doc_archive.purge_item_files(
                db, act, item, current_user,
                execution_started_at=lease_started_at,
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — ошибка обязана остаться в акте
            await db.rollback()
            lease_owned = await db.scalar(select(DocDestructionAct.id).where(
                DocDestructionAct.id == aid,
                DocDestructionAct.company_id == cid,
                DocDestructionAct.status == "executing",
                DocDestructionAct.executed_by == current_user.id,
                DocDestructionAct.executed_at == lease_started_at,
            ))
            if lease_owned is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Право исполнения акта перешло другому запросу",
                ) from exc
            item = (await db.execute(select(DocDestructionItem).where(
                DocDestructionItem.id == item_id,
                DocDestructionItem.company_id == cid,
                DocDestructionItem.act_id == aid,
            ).with_for_update())).scalar_one()
            if item.status not in {"primary_purged", "destroyed"}:
                item.status = "failed"
                item.error = str(exc)[:1000]
            errors.append(f"{item.doc_id}: {item.error}")
            await db.commit()
    act = (await db.execute(select(DocDestructionAct).where(
        DocDestructionAct.id == aid,
        DocDestructionAct.company_id == cid,
        DocDestructionAct.status == "executing",
        DocDestructionAct.executed_by == current_user.id,
        DocDestructionAct.executed_at == lease_started_at,
    ).with_for_update())).scalar_one_or_none()
    if act is None:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Право исполнения акта перешло другому запросу")
    left = await db.scalar(select(func.count()).select_from(DocDestructionItem).where(
        DocDestructionItem.act_id == aid,
        DocDestructionItem.status != "primary_purged",
    ))
    mail_cleanup = None
    mail_cleanup_error = None
    if not left:
        try:
            mail_cleanup = await doc_archive.purge_act_mail_copies(db, act)
        except ValueError as exc:
            mail_cleanup_error = str(exc)[:1000]
            errors.append(f"Почтовые копии: {mail_cleanup_error}")
    failed = int(left or 0) + (1 if mail_cleanup_error else 0)
    act.status = "failed" if failed else "primary_purged"
    act.error = "\n".join(errors)[:2000] or None
    await doc_archive.append_event(
        db, company_id=cid, act_id=act.id, actor=current_user,
        kind="act_execution_failed" if failed else "act_primary_purged",
        payload={
            "failed": failed, "error": act.error,
            "mail_cleanup": mail_cleanup,
        },
    )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.act.execute", target=str(act.id),
                    details={"status": act.status, "failed": failed,
                             "mail_cleanup": mail_cleanup})
    await db.commit()
    if failed:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Уничтожение не завершено; ошибка сохранена в акте")
    return _act_out(act)


@router.post("/archive/acts/{act_id}/confirm-backup-purge")
async def confirm_backup_purge(
    act_id: str,
    payload: BackupAttestationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    act = (await db.execute(select(DocDestructionAct).where(
        DocDestructionAct.company_id == cid,
        DocDestructionAct.id == _uuid_or_400(act_id, "act_id"),
    ).with_for_update())).scalar_one_or_none()
    if act is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Акт не найден")
    if act.status == "destroyed":
        return _act_out(act)
    if act.status != "primary_purged":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала удалите файлы из рабочего хранилища")
    if current_user.id in {act.created_by, act.approved_by, act.executed_by}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Резервные копии подтверждает четвёртый независимый сотрудник")
    items = list((await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.act_id == act.id,
    ).order_by(DocDestructionItem.doc_id).with_for_update())).scalars().all())
    has_known_external_copies = any(
        bool((item.snapshot or {}).get("known_external_copies")
             or (item.snapshot or {}).get("known_share_links"))
        for item in items
    )
    external_evidence = (payload.external_copies_evidence or "").strip()
    if has_known_external_copies and len(external_evidence) < 10:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Укажите подтверждение удаления или учёта известных внешних копий",
        )
    for item in items:
        doc = await _lock_doc(db, cid, item.doc_id)
        await _assert_archive_access(db, cid, doc, current_user)
        if await doc_archive.active_holds(db, cid, doc.id, lock=True):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "На один из документов установлен запрет уничтожения")
        retained_shared = await db.scalar(select(DocVersion.id).where(
            DocVersion.doc_id == doc.id,
            DocVersion.purge_result == "shared_blob_retained",
        ).limit(1))
        if retained_shared is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Общий файловый объект ещё используется другой записью",
            )
        item.status = "destroyed"
        doc.retention_state = "destroyed"
        doc.destroyed_at = datetime.now(timezone.utc)
        await doc_archive.append_event(
            db, company_id=cid, doc_id=doc.id, act_id=act.id,
            actor=current_user, kind="destroyed",
            payload={"act_number": act.act_number},
        )
    act.status = "destroyed"
    act.backup_attested_by = current_user.id
    act.backup_attested_at = datetime.now(timezone.utc)
    act.backup_evidence = {
        "evidence": payload.evidence.strip(),
        "external_copies_evidence": external_evidence or None,
        "known_external_copies": has_known_external_copies,
    }
    await doc_archive.append_event(
        db, company_id=cid, act_id=act.id, actor=current_user,
        kind="act_destroyed",
        payload={"backup_evidence": act.backup_evidence,
                 "documents": len(items)},
    )
    await log_audit(db, actor=current_user, company_id=cid,
                    action="doc.archive.act.destroyed", target=str(act.id),
                    details={"documents": len(items),
                             "backup_evidence": act.backup_evidence})
    await db.commit()
    return _act_out(act, len(items))
