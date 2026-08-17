from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocArchiveEvent, DocCard, DocCase, DocDestructionAct, DocDestructionItem,
    DocExport, DocInboxItem, DocLegalHold, DocShareLink, DocVersion,
    EzsSiteDoc, MailAttachment, MailMessage, OpsCounterpartyDoc, SourceFile,
    StoreDocFile, TaskAttachment, User,
)
from app.services import file_store


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()


def classify_external_export_status(status: str) -> str | None:
    if status in {"placed", "downloaded"}:
        return "known_copy"
    if status == "pending" or status not in {"placed", "downloaded", "failed"}:
        return "unresolved"
    return None


async def document_snapshot(db: AsyncSession, doc: DocCard) -> dict[str, Any]:
    case_row = await db.get(DocCase, doc.case_id) if doc.case_id else None
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id,
    ).order_by(DocVersion.role, DocVersion.revision, DocVersion.id))).scalars().all()
    exports = (await db.execute(select(DocExport).where(
        DocExport.doc_id == doc.id,
    ).order_by(DocExport.created_at, DocExport.id))).scalars().all()
    shares = (await db.execute(select(DocShareLink).where(
        DocShareLink.doc_id == doc.id,
    ).order_by(DocShareLink.created_at, DocShareLink.id))).scalars().all()
    placed_exports = [
        row for row in exports
        if classify_external_export_status(row.status) == "known_copy"
    ]
    unresolved_exports = [
        row for row in exports
        if classify_external_export_status(row.status) == "unresolved"
    ]

    def export_snapshot(row: DocExport) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "status": row.status,
            "target_id": str(row.target_id) if row.target_id else None,
            "package_name": row.package_name,
            "package_path": row.package_path,
            "package_sha256": row.package_sha256,
            "size_bytes": row.size_bytes,
            "content": row.content,
            "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    return {
        "card": {
            "id": str(doc.id),
            "status": doc.status,
            "retention_state": doc.retention_state,
            "confidentiality": doc.confidentiality,
            "kind_id": str(doc.kind_id),
            "kind_code": doc.kind_code,
            "family": doc.family,
            "direction": doc.direction,
            "title": doc.title,
            "summary": doc.summary,
            "attrs": doc.attrs,
            "reg_number": doc.reg_number,
            "reg_date": doc.reg_date.isoformat() if doc.reg_date else None,
            "external_number": doc.external_number,
            "external_date": (
                doc.external_date.isoformat() if doc.external_date else None
            ),
            "organization_id": str(doc.organization_id) if doc.organization_id else None,
            "counterparty_id": str(doc.counterparty_id) if doc.counterparty_id else None,
            "counterparty_name": doc.counterparty_name,
            "subject_ref": doc.subject_ref,
            "object_id": doc.object_id,
            "department_id": str(doc.department_id) if doc.department_id else None,
            "responsible_id": str(doc.responsible_id) if doc.responsible_id else None,
            "signatory_id": str(doc.signatory_id) if doc.signatory_id else None,
            "due_at": doc.due_at.isoformat() if doc.due_at else None,
            "source": doc.source,
            "source_ref": doc.source_ref,
            "current_revision": doc.current_revision,
            "has_files": doc.has_files,
            "case_id": str(doc.case_id) if doc.case_id else None,
            "storage_until": doc.storage_until.isoformat() if doc.storage_until else None,
            "retention_extended_until": (
                doc.retention_extended_until.isoformat()
                if doc.retention_extended_until else None
            ),
            "retention_class": doc.retention_class,
            "retention_snapshot": doc.retention_snapshot,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        },
        "case": ({
            "id": str(case_row.id),
            "year": case_row.year,
            "index": case_row.index,
            "title": case_row.title,
            "storage_term": case_row.storage_term,
            "storage_years": case_row.storage_years,
            "epk": case_row.epk,
            "retention_basis": case_row.retention_basis,
            "retention_class": case_row.retention_class,
        } if case_row else None),
        "versions": [{
            "id": str(row.id),
            "revision": row.revision,
            "role": row.role,
            "file_id": str(row.file_id),
            "file_name": row.file_name,
            "mime": row.mime,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "is_current": row.is_current,
            "tombstoned_at": (row.tombstoned_at.isoformat()
                              if row.tombstoned_at else None),
        } for row in versions],
        "known_external_copies": [export_snapshot(row) for row in placed_exports],
        "unresolved_external_exports": [
            export_snapshot(row) for row in unresolved_exports
        ],
        "has_unresolved_external_exports": bool(unresolved_exports),
        "known_share_links": [{
            "id": str(row.id),
            "recipient_name": row.recipient_name,
            "recipient_email": row.recipient_email,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "opened_count": row.opened_count,
            "acknowledged_at": (row.acknowledged_at.isoformat()
                                if row.acknowledged_at else None),
            "version_snapshot": row.version_snapshot,
            "card_snapshot": row.card_snapshot,
            "ack_evidence": row.ack_evidence,
            "revoked": row.revoked,
        } for row in shares],
    }


def external_export_blocker(snapshot: dict[str, Any]) -> str | None:
    unresolved = snapshot.get("unresolved_external_exports") or []
    if snapshot.get("has_unresolved_external_exports") or unresolved:
        return (
            "Есть незавершённая выгрузка документа; дождитесь размещения "
            "или зафиксируйте ошибку выгрузки"
        )
    return None


def external_export_change_blocker(frozen: dict[str, Any],
                                   current: dict[str, Any]) -> str | None:
    fields = (
        "known_external_copies",
        "unresolved_external_exports",
        "has_unresolved_external_exports",
    )
    frozen_state = {field: frozen.get(field) for field in fields}
    current_state = {field: current.get(field) for field in fields}
    if snapshot_hash(frozen_state) != snapshot_hash(current_state):
        return "Состояние внешних выгрузок изменилось после подготовки акта"
    return None


def effective_until(doc: DocCard) -> date | None:
    values = [value for value in (
        doc.storage_until, doc.retention_extended_until,
    ) if value is not None]
    return max(values) if values else None


async def active_holds(db: AsyncSession, company_id: uuid.UUID,
                       doc_id: uuid.UUID, *, lock: bool = False) -> list[DocLegalHold]:
    query = select(DocLegalHold).where(
        DocLegalHold.company_id == company_id,
        DocLegalHold.doc_id == doc_id,
        DocLegalHold.released_at.is_(None),
    ).order_by(DocLegalHold.placed_at, DocLegalHold.id)
    if lock:
        query = query.with_for_update()
    return list((await db.execute(query)).scalars().all())


def destruction_blocker(doc: DocCard, holds: list[DocLegalHold],
                        today: date) -> str | None:
    if doc.status != "archived":
        return "Документ ещё не принят во внутренний архив"
    if doc.retention_state == "legacy_review":
        return "Для документа прежней версии не подтверждено основание хранения"
    if doc.retention_state in {"permanent", "primary_purged", "destroyed"}:
        return "Текущее архивное состояние не допускает уничтожение"
    if holds:
        return "На документ установлен запрет уничтожения"
    until = effective_until(doc)
    if until is None:
        return "Срок хранения не определён или документ хранится постоянно"
    if until >= date(today.year, 1, 1):
        return "Срок хранения не истёк к 1 января текущего года"
    return None


async def append_event(db: AsyncSession, *, company_id: uuid.UUID,
                       kind: str, actor: User | None,
                       doc_id: uuid.UUID | None = None,
                       act_id: uuid.UUID | None = None,
                       payload: dict[str, Any] | None = None) -> DocArchiveEvent:
    await db.execute(select(func.pg_advisory_xact_lock(
        435_224, company_id.int % (2 ** 31))))
    scope = [DocArchiveEvent.company_id == company_id]
    if doc_id is not None:
        scope.append(DocArchiveEvent.doc_id == doc_id)
    elif act_id is not None:
        scope.extend((
            DocArchiveEvent.doc_id.is_(None),
            DocArchiveEvent.act_id == act_id,
        ))
    else:
        scope.extend((
            DocArchiveEvent.doc_id.is_(None),
            DocArchiveEvent.act_id.is_(None),
        ))
    previous = (await db.execute(select(DocArchiveEvent).where(
        *scope,
    ).order_by(DocArchiveEvent.created_at.desc(), DocArchiveEvent.id.desc())
        .limit(1).with_for_update())).scalar_one_or_none()
    event_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    actor_name = (actor.name or actor.email) if actor else "Платформа"
    body = {
        "id": str(event_id),
        "company_id": str(company_id),
        "doc_id": str(doc_id) if doc_id else None,
        "act_id": str(act_id) if act_id else None,
        "actor_id": str(actor.id) if actor else None,
        "actor_name": actor_name,
        "kind": kind,
        "payload": payload or {},
        "prev_hash": previous.event_hash if previous else None,
        "created_at": created_at.isoformat(),
    }
    event = DocArchiveEvent(
        id=event_id,
        company_id=company_id, doc_id=doc_id, act_id=act_id,
        actor_id=actor.id if actor else None,
        actor_name=actor_name,
        kind=kind, payload=payload or {},
        prev_hash=previous.event_hash if previous else None,
        event_hash=hashlib.sha256(_json(body).encode("utf-8")).hexdigest(),
        created_at=created_at,
    )
    db.add(event)
    return event


async def seal_act(db: AsyncSession, act: DocDestructionAct) -> tuple[dict[str, Any], str]:
    items = (await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.act_id == act.id,
    ).order_by(DocDestructionItem.doc_id))).scalars().all()
    snapshot = {
        "act": {
            "id": str(act.id),
            "number": act.act_number,
            "date": act.act_date.isoformat(),
            "basis": act.basis,
            "committee": act.committee or [],
            "organization_id": str(act.organization_id) if act.organization_id else None,
        },
        "items": [{
            "id": str(item.id),
            "doc_id": str(item.doc_id),
            "decision_id": str(item.decision_id),
            "snapshot_sha256": item.snapshot_sha256,
        } for item in items],
    }
    return snapshot, snapshot_hash(snapshot)


def _content_evidence(value: bytes | str | None) -> dict[str, Any]:
    if value is None:
        return {"present": False, "size_bytes": 0, "sha256": None}
    data = value.encode("utf-8") if isinstance(value, str) else value
    return {
        "present": True,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _mail_source_ref(row: MailMessage) -> str:
    return f"mail:{row.message_id or row.id}"[:200]


async def _incoming_mail_message(db: AsyncSession, doc: DocCard,
                                 *, lock: bool) -> MailMessage:
    if not doc.source_ref or not doc.source_ref.startswith("mail:"):
        raise ValueError("У почтового документа нет ссылки на исходное письмо")
    token = doc.source_ref[5:]
    if not token:
        raise ValueError("У почтового документа повреждена ссылка на исходное письмо")
    candidates = [MailMessage.message_id.startswith(token, autoescape=True)]
    try:
        candidates.append(MailMessage.id == uuid.UUID(token))
    except ValueError:
        pass
    query = select(MailMessage).where(
        MailMessage.company_id == doc.company_id,
        MailMessage.direction == "in",
        or_(*candidates),
    )
    if lock:
        query = query.with_for_update()
    rows = list((await db.execute(query)).scalars().all())
    rows = [row for row in rows if _mail_source_ref(row) == doc.source_ref]
    if len(rows) != 1:
        raise ValueError(
            "Исходное письмо документа не найдено однозначно; очистка остановлена",
        )
    return rows[0]


def no_local_mail_copy_attested(row: DocExport) -> bool:
    content = row.content if isinstance(row.content, dict) else {}
    attestation = content.get("no_local_copy_attestation")
    resolution = content.get("resolution")
    if not isinstance(attestation, dict) or not isinstance(resolution, dict):
        return False
    try:
        actor_id = uuid.UUID(str(attestation.get("attested_by")))
        attested_at = datetime.fromisoformat(str(attestation.get("attested_at")))
    except (TypeError, ValueError):
        return False
    return bool(
        actor_id
        and attested_at.tzinfo is not None
        and attestation.get("company_id") == str(row.company_id)
        and attestation.get("export_id") == str(row.id)
        and len(str(attestation.get("evidence") or "").strip()) >= 10
        and resolution.get("status") == "placed"
        and resolution.get("resolved_by") == attestation.get("attested_by")
        and resolution.get("resolved_at") == attestation.get("attested_at")
        and resolution.get("evidence") == attestation.get("evidence")
    )


def _export_mail_message_id(row: DocExport) -> uuid.UUID | None:
    content = row.content if isinstance(row.content, dict) else {}
    raw = content.get("mail_message_id")
    if raw is None:
        if content.get("channel") == "mail":
            if no_local_mail_copy_attested(row):
                return None
            raise ValueError(
                "У почтовой выгрузки нет ссылки на локальное исходящее письмо",
            )
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        if no_local_mail_copy_attested(row):
            return None
        raise ValueError(
            "У почтовой выгрузки повреждена ссылка на локальное исходящее письмо",
        ) from exc


def mail_link_disposition(
    linked_doc_ids: set[uuid.UUID], *, current_doc_id: uuid.UUID,
    act_item_statuses: dict[uuid.UUID, str],
    retention_states: dict[uuid.UUID, str],
) -> str:
    deferred = False
    for doc_id in linked_doc_ids:
        if retention_states.get(doc_id) in {"primary_purged", "destroyed"}:
            continue
        if doc_id == current_doc_id:
            continue
        item_status = act_item_statuses.get(doc_id)
        if item_status in {"primary_purged", "destroyed"}:
            continue
        if item_status in {"pending", "failed"}:
            deferred = True
            continue
        return "block"
    return "defer" if deferred else "clear"


async def _mail_purge_plan(db: AsyncSession, *, doc: DocCard,
                           act: DocDestructionAct,
                           lock: bool) -> dict[str, Any]:
    messages: dict[uuid.UUID, MailMessage] = {}
    if doc.source == "mail":
        incoming = await _incoming_mail_message(db, doc, lock=lock)
        messages[incoming.id] = incoming

    exports_query = select(DocExport).where(
        DocExport.company_id == doc.company_id,
        DocExport.doc_id == doc.id,
        DocExport.status.in_(("placed", "downloaded")),
    )
    if lock:
        exports_query = exports_query.with_for_update()
    own_exports = list((await db.execute(exports_query)).scalars().all())
    for export in own_exports:
        message_id = _export_mail_message_id(export)
        if message_id is None or message_id in messages:
            continue
        query = select(MailMessage).where(
            MailMessage.id == message_id,
            MailMessage.company_id == doc.company_id,
            MailMessage.direction == "out",
        )
        if lock:
            query = query.with_for_update()
        message = (await db.execute(query)).scalar_one_or_none()
        if message is None:
            if no_local_mail_copy_attested(export):
                continue
            raise ValueError(
                "Локальное исходящее письмо выгрузки не найдено; очистка остановлена",
            )
        messages[message.id] = message

    act_item_statuses = dict((await db.execute(select(
        DocDestructionItem.doc_id, DocDestructionItem.status,
    ).where(
        DocDestructionItem.company_id == doc.company_id,
        DocDestructionItem.act_id == act.id,
    ))).all())
    evidence: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for message in sorted(messages.values(), key=lambda row: str(row.id)):
        attachment_query = select(MailAttachment).where(
            MailAttachment.company_id == doc.company_id,
            MailAttachment.message_id == message.id,
        ).order_by(MailAttachment.id)
        if lock:
            attachment_query = attachment_query.with_for_update()
        attachments = list((await db.execute(
            attachment_query,
        )).scalars().all())
        if message.routed_to not in {None, "doc"}:
            raise ValueError(
                "Письмо используется другим рабочим маршрутом; очистка остановлена",
            )
        if any(row.intake_batch_id is not None for row in attachments):
            raise ValueError(
                "Вложение письма используется приёмкой первички; очистка остановлена",
            )

        linked_exports_query = select(DocExport).where(
            DocExport.company_id == doc.company_id,
            DocExport.content["mail_message_id"].astext == str(message.id),
        )
        if lock:
            linked_exports_query = linked_exports_query.with_for_update()
        linked_exports = list((await db.execute(
            linked_exports_query,
        )).scalars().all())
        linked_doc_ids = {row.doc_id for row in linked_exports}
        linked_file_ids: set[uuid.UUID] = set()
        for export in linked_exports:
            content = export.content if isinstance(export.content, dict) else {}
            for raw_file_id in content.get("file_ids") or []:
                try:
                    linked_file_ids.add(uuid.UUID(str(raw_file_id)))
                except ValueError:
                    raise ValueError(
                        "В почтовой выгрузке повреждена ссылка на файл",
                    )
        attachment_hashes: set[str] = set()
        for attachment in attachments:
            if attachment.sha256:
                attachment_hashes.add(attachment.sha256)
            content_sha256 = _content_evidence(attachment.content)["sha256"]
            if content_sha256:
                attachment_hashes.add(content_sha256)
        version_filters = []
        if linked_file_ids:
            version_filters.append(DocVersion.file_id.in_(linked_file_ids))
        if attachment_hashes:
            version_filters.append(DocVersion.sha256.in_(attachment_hashes))
        version_refs = []
        if version_filters:
            version_refs = list((await db.execute(select(
                DocVersion.doc_id, DocVersion.file_id, DocVersion.sha256,
            ).where(
                DocVersion.company_id == doc.company_id,
                or_(*version_filters),
            ))).all())
            linked_doc_ids.update(row.doc_id for row in version_refs)

        attachment_links: dict[uuid.UUID, set[uuid.UUID]] = {}
        for attachment in attachments:
            hashes = {attachment.sha256} if attachment.sha256 else set()
            content_sha256 = _content_evidence(attachment.content)["sha256"]
            if content_sha256:
                hashes.add(content_sha256)
            attachment_doc_ids = {
                row.doc_id for row in version_refs if row.sha256 in hashes
            }
            attachment_links[attachment.id] = attachment_doc_ids
            if ((message.raw_eml is not None or attachment.content is not None)
                    and not attachment_doc_ids):
                raise ValueError(
                    "Письмо содержит вложение, не связанное с документами акта; "
                    "очистка остановлена",
                )
        source_ref = _mail_source_ref(message)
        linked_doc_ids.update((await db.execute(select(DocCard.id).where(
            DocCard.company_id == doc.company_id,
            DocCard.source == "mail",
            DocCard.source_ref == source_ref,
        ))).scalars().all())

        disposition = "clear"
        retention_states: dict[uuid.UUID, str] = {}
        if linked_doc_ids:
            linked_docs_query = select(DocCard).where(
                DocCard.company_id == doc.company_id,
                DocCard.id.in_(linked_doc_ids),
            )
            if lock:
                linked_docs_query = linked_docs_query.with_for_update()
            linked_docs = list((await db.execute(
                linked_docs_query,
            )).scalars().all())
            retention_states = {
                row.id: row.retention_state for row in linked_docs
            }
            if len(retention_states) != len(linked_doc_ids):
                raise ValueError(
                    "Связь письма с документом повреждена; очистка остановлена",
                )
            disposition = mail_link_disposition(
                linked_doc_ids, current_doc_id=doc.id,
                act_item_statuses=act_item_statuses,
                retention_states=retention_states,
            )
            if disposition == "block":
                raise ValueError(
                    "Письмо содержит файлы других действующих документов; "
                    "очистка остановлена",
                )

        message_evidence = {
            "message_id": str(message.id),
            "rfc_message_id": message.message_id,
            "account_id": str(message.account_id) if message.account_id else None,
            "uid": message.uid,
            "direction": message.direction,
            "subject": message.subject,
            "from_name": message.from_name,
            "from_email": message.from_email,
            "to_emails": message.to_emails,
            "sent_at": message.sent_at.isoformat() if message.sent_at else None,
            "status": message.status,
            "routed_to": message.routed_to,
            "headers": _content_evidence(
                _json(message.headers) if message.headers is not None else None,
            ),
            "raw_eml": _content_evidence(message.raw_eml),
            "body_text": _content_evidence(message.body_text),
            "body_html": _content_evidence(message.body_html),
            "cleanup_deferred": disposition == "defer",
            "linked_doc_ids": sorted(str(value) for value in linked_doc_ids),
            "attachments": [{
                "id": str(row.id),
                "file_name": row.file_name,
                "content_type": row.content_type,
                "declared_size_bytes": row.size,
                "declared_sha256": row.sha256,
                "linked_doc_ids": sorted(
                    str(value) for value in attachment_links[row.id]
                ),
                "content": _content_evidence(row.content),
            } for row in attachments],
        }
        evidence.append(message_evidence)
        if disposition == "clear":
            rows.append({"message": message, "attachments": attachments})
    return {"rows": rows, "evidence": evidence}


def _clear_mail_plan(plan: dict[str, Any]) -> None:
    for row in plan["rows"]:
        message = row["message"]
        message.raw_eml = None
        message.body_text = None
        message.body_html = None
        for attachment in row["attachments"]:
            attachment.content = None


async def purge_act_mail_copies(db: AsyncSession, act: DocDestructionAct) -> dict[str, Any]:
    items = list((await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.company_id == act.company_id,
        DocDestructionItem.act_id == act.id,
    ).order_by(DocDestructionItem.doc_id).with_for_update())).scalars().all())
    if not items or any(
            item.status not in {"primary_purged", "destroyed"} for item in items):
        raise ValueError(
            "Почтовые копии очищаются только после всех документов акта",
        )
    docs = list((await db.execute(select(DocCard).where(
        DocCard.company_id == act.company_id,
        DocCard.id.in_([item.doc_id for item in items]),
    ).order_by(DocCard.id).with_for_update())).scalars().all())
    if len(docs) != len(items):
        raise ValueError("Не все документы акта найдены; очистка писем остановлена")

    plans = [
        await _mail_purge_plan(db, doc=doc, act=act, lock=True)
        for doc in docs
    ]
    evidence_by_id: dict[str, dict[str, Any]] = {}
    rows_by_id: dict[uuid.UUID, dict[str, Any]] = {}
    for plan in plans:
        for evidence in plan["evidence"]:
            if evidence.get("cleanup_deferred"):
                raise ValueError(
                    "Связанное письмо ещё нужно другому документу акта",
                )
            evidence_by_id[evidence["message_id"]] = evidence
        for row in plan["rows"]:
            rows_by_id[row["message"].id] = row
    final_plan = {
        "rows": list(rows_by_id.values()),
        "evidence": [evidence_by_id[key] for key in sorted(evidence_by_id)],
    }
    _clear_mail_plan(final_plan)
    return {
        "messages_cleared": len(rows_by_id),
        "evidence_sha256": snapshot_hash({"messages": final_plan["evidence"]}),
    }


async def _has_other_file_references(db: AsyncSession, file_id: uuid.UUID,
                                     doc_id: uuid.UUID) -> bool:
    checks = (
        select(DocVersion.id).where(
            DocVersion.file_id == file_id,
            DocVersion.doc_id != doc_id,
            DocVersion.archive_purged_at.is_(None),
        ),
        select(EzsSiteDoc.id).where(EzsSiteDoc.file_id == file_id),
        select(OpsCounterpartyDoc.id).where(OpsCounterpartyDoc.file_id == file_id),
        select(StoreDocFile.id).where(
            StoreDocFile.file_id == file_id,
            StoreDocFile.tombstoned_at.is_(None),
        ),
        select(TaskAttachment.file_id).where(TaskAttachment.file_id == file_id),
        select(DocInboxItem.id).where(
            DocInboxItem.file_id == file_id,
            (DocInboxItem.doc_id.is_(None) | (DocInboxItem.doc_id != doc_id)),
        ),
    )
    for query in checks:
        if await db.scalar(query.limit(1)) is not None:
            return True
    return False


async def _purge_plans(db: AsyncSession, versions: list[DocVersion],
                       doc_id: uuid.UUID, act_id: uuid.UUID,
                       root: Path) -> list[dict[str, Any]]:
    active = [row for row in versions if row.archive_purged_at is None]
    file_ids = sorted({row.file_id for row in active}, key=str)
    for file_id in file_ids:
        if await _has_other_file_references(db, file_id, doc_id):
            raise ValueError(
                "Файл используется другой записью; сначала разделите общий объект хранения",
            )

    plans: list[dict[str, Any]] = []
    paths: dict[Path, uuid.UUID] = {}
    quarantine_root = (root / ".archive-quarantine" / str(act_id)).resolve()
    if not quarantine_root.is_relative_to(root):
        raise ValueError("Каталог карантина находится вне управляемого хранилища")
    for file_id in file_ids:
        source = await db.get(SourceFile, file_id)
        related = [row for row in active if row.file_id == file_id]
        if source is None:
            plans.append({
                "file_id": file_id, "versions": related,
                "source": None, "quarantine": None,
                "initially_missing": True,
            })
            continue
        path = Path(source.storage_path).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Путь файла находится вне управляемого хранилища")
        owner = paths.get(path)
        if owner is not None and owner != file_id:
            raise ValueError("Несколько файловых объектов указывают на один путь хранения")
        paths[path] = file_id
        quarantine = (quarantine_root / str(file_id)).resolve()
        if not quarantine.is_relative_to(quarantine_root):
            raise ValueError("Путь карантина находится вне управляемого хранилища")
        if path.exists() and not path.is_file():
            raise ValueError("Путь файлового объекта не является обычным файлом")
        if quarantine.exists() and not quarantine.is_file():
            raise ValueError("Объект карантина не является обычным файлом")
        if path.exists() and quarantine.exists():
            raise ValueError("Одновременно существуют рабочая и карантинная копии файла")
        plans.append({
            "file_id": file_id, "versions": related,
            "source": path, "quarantine": quarantine,
            "initially_missing": (
                not path.exists() and not quarantine.exists()
                and not any(row.purge_result == "quarantine_intent"
                            for row in related)
            ),
        })
    return plans


def _purge_results(plans: list[dict[str, Any]]) -> dict[uuid.UUID, str]:
    results: dict[uuid.UUID, str] = {}
    for plan in plans:
        source = plan["source"]
        quarantine = plan["quarantine"]
        if plan["initially_missing"]:
            results[plan["file_id"]] = "missing"
        elif quarantine is not None and quarantine.exists():
            results[plan["file_id"]] = "quarantined"
        elif source is not None and source.exists():
            results[plan["file_id"]] = "restored"
        elif any(row.purge_result == "quarantine_intent"
                 for row in plan["versions"]):
            results[plan["file_id"]] = "removed_after_intent"
        else:
            results[plan["file_id"]] = "missing"
    return results


async def _record_purge_failure(db: AsyncSession, *, act: DocDestructionAct,
                                doc_id: uuid.UUID, actor: User,
                                plans: list[dict[str, Any]], error: str) -> None:
    act_id = act.id
    company_id = act.company_id
    results = _purge_results(plans)
    version_ids = [row.id for plan in plans for row in plan["versions"]]
    if version_ids:
        rows = list((await db.execute(select(DocVersion).where(
            DocVersion.id.in_(version_ids),
        ).with_for_update())).scalars().all())
        for row in rows:
            row.purge_result = results.get(row.file_id, "quarantine_failed")
            row.destruction_act_id = act_id
    await append_event(
        db, company_id=company_id, doc_id=doc_id, act_id=act_id,
        actor=actor, kind="purge_failed",
        payload={
            "error": error[:1000],
            "files": [
                {"file_id": str(file_id), "result": result}
                for file_id, result in sorted(
                    results.items(), key=lambda item: str(item[0]))
            ],
        },
    )
    await db.commit()


async def purge_item_files(db: AsyncSession, act: DocDestructionAct,
                           item: DocDestructionItem, actor: User,
                           *, execution_started_at: datetime | None = None) -> None:
    export_blocker = external_export_blocker(item.snapshot or {})
    if export_blocker:
        raise ValueError(export_blocker)
    doc = (await db.execute(select(DocCard).where(
        DocCard.id == item.doc_id,
        DocCard.company_id == act.company_id,
    ).with_for_update())).scalar_one()
    holds = await active_holds(db, act.company_id, doc.id, lock=True)
    if holds:
        raise ValueError("На документ установлен запрет уничтожения")
    current_snapshot = await document_snapshot(db, doc)
    current_export_blocker = external_export_blocker(current_snapshot)
    if current_export_blocker:
        raise ValueError(current_export_blocker)
    changed_exports = external_export_change_blocker(
        item.snapshot or {}, current_snapshot,
    )
    if changed_exports:
        raise ValueError(changed_exports)
    versions = list((await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id,
    ).order_by(DocVersion.id).with_for_update())).scalars().all())
    root = file_store.upload_dir().resolve()
    plans = await _purge_plans(db, versions, doc.id, act.id, root)
    mail_plan = await _mail_purge_plan(
        db, doc=doc, act=act, lock=True,
    )
    mail_evidence_hash = snapshot_hash({"messages": mail_plan["evidence"]})
    initially_missing = {
        plan["file_id"] for plan in plans if plan["initially_missing"]
    }
    intent_files = [{
        "file_id": str(plan["file_id"]),
        "version_ids": [str(row.id) for row in plan["versions"]],
        "quarantine": (
            str(plan["quarantine"].relative_to(root))
            if plan["quarantine"] is not None else None
        ),
    } for plan in plans]
    for version in versions:
        if version.archive_purged_at is None:
            version.purge_result = "quarantine_intent"
            version.destruction_act_id = act.id
    await append_event(
        db, company_id=act.company_id, doc_id=doc.id, act_id=act.id,
        actor=actor, kind="purge_intent",
        payload={
            "files": intent_files,
            "mail_copies": mail_plan["evidence"],
            "mail_evidence_sha256": mail_evidence_hash,
        },
    )
    await db.commit()

    lease_filters = [
        DocDestructionAct.id == act.id,
        DocDestructionAct.company_id == act.company_id,
    ]
    if execution_started_at is not None:
        lease_filters.extend((
            DocDestructionAct.status == "executing",
            DocDestructionAct.executed_by == actor.id,
            DocDestructionAct.executed_at == execution_started_at,
        ))
    lease_owned = await db.scalar(select(DocDestructionAct.id).where(
        *lease_filters,
    ).with_for_update())
    if lease_owned is None:
        raise ValueError("Право исполнения акта перешло другому запросу")
    item = (await db.execute(select(DocDestructionItem).where(
        DocDestructionItem.id == item.id,
        DocDestructionItem.act_id == act.id,
    ).with_for_update())).scalar_one()
    doc = (await db.execute(select(DocCard).where(
        DocCard.id == item.doc_id,
        DocCard.company_id == act.company_id,
    ).with_for_update())).scalar_one()
    holds = await active_holds(db, act.company_id, doc.id, lock=True)
    if holds:
        raise ValueError("На документ установлен запрет уничтожения")
    current_snapshot = await document_snapshot(db, doc)
    current_export_blocker = external_export_blocker(current_snapshot)
    if current_export_blocker:
        raise ValueError(current_export_blocker)
    changed_exports = external_export_change_blocker(
        item.snapshot or {}, current_snapshot,
    )
    if changed_exports:
        raise ValueError(changed_exports)
    versions = list((await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id,
    ).order_by(DocVersion.id).with_for_update())).scalars().all())
    plans = await _purge_plans(db, versions, doc.id, act.id, root)
    mail_plan = await _mail_purge_plan(
        db, doc=doc, act=act, lock=True,
    )
    if snapshot_hash({"messages": mail_plan["evidence"]}) != mail_evidence_hash:
        raise ValueError(
            "Локальные почтовые копии изменились после фиксации намерения",
        )
    for plan in plans:
        if plan["file_id"] in initially_missing:
            plan["initially_missing"] = True

    try:
        parents = sorted({
            plan["quarantine"].parent for plan in plans
            if plan["quarantine"] is not None
        }, key=str)
        for parent in parents:
            await asyncio.to_thread(parent.mkdir, parents=True, exist_ok=True)
        for plan in plans:
            source = plan["source"]
            quarantine = plan["quarantine"]
            if source is not None and quarantine is not None and source.exists():
                await asyncio.to_thread(source.replace, quarantine)
        for plan in plans:
            quarantine = plan["quarantine"]
            if quarantine is not None and quarantine.exists():
                await asyncio.to_thread(quarantine.unlink)
    except Exception as exc:
        error = f"Файлы не удалены полностью: {exc}"
        await _record_purge_failure(
            db, act=act, doc_id=doc.id, actor=actor,
            plans=plans, error=error,
        )
        raise ValueError(error) from exc

    now = datetime.now(timezone.utc)
    results = _purge_results(plans)
    for version in versions:
        version.content_text = None
        if version.archive_purged_at is None:
            version.archive_purged_at = now
            version.purge_result = results.get(version.file_id, "missing")
            version.destruction_act_id = act.id
    links = (await db.execute(select(DocShareLink).where(
        DocShareLink.doc_id == doc.id,
        DocShareLink.revoked.is_(False),
    ).with_for_update())).scalars().all()
    for link in links:
        link.revoked = True
    doc.summary = None
    doc.attrs = None
    doc.retention_state = "primary_purged"
    doc.primary_purged_at = now
    item.status = "primary_purged"
    item.purged_at = now
    item.error = None
    await append_event(
        db, company_id=act.company_id, doc_id=doc.id, act_id=act.id,
        actor=actor, kind="primary_purged",
        payload={
            "versions": len(versions), "shares_revoked": len(links),
            "mail_cleanup_deferred_to_act": bool(mail_plan["evidence"]),
            "mail_evidence_sha256": mail_evidence_hash,
            "files": [
                {"file_id": str(file_id), "result": result}
                for file_id, result in sorted(
                    results.items(), key=lambda row: str(row[0]))
            ],
        },
    )
