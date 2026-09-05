import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException

from sqlalchemy import select
from app.models import DocSignatureEvidence, DocVersion, SourceFile
from app.services import file_store


async def message_file(db, cid, message):
    if not message.file_url:
        return None
    try:
        file_id = uuid.UUID(message.file_url.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        raise HTTPException(400, "Вложение недоступно для переноса") from None
    row = await db.get(SourceFile, file_id)
    if row is None or row.company_id != cid:
        raise HTTPException(404, "Вложение не найдено")
    if not row.storage_path or not Path(row.storage_path).is_file():
        raise HTTPException(409, "Файл отсутствует в хранилище. Восстановите вложение и повторите")
    return row


async def initial_version(db, cid, doc, source_file, actor):
    if source_file.company_id != cid or doc.company_id != cid:
        raise HTTPException(404, "Файл не найден")
    try:
        content = file_store.read(source_file)
    except (OSError, ValueError):
        raise HTTPException(409, "Файл отсутствует в хранилище. Восстановите вложение и повторите") from None
    db.add(DocVersion(company_id=cid, doc_id=doc.id, revision=1, role="body",
        file_id=source_file.id, file_name=source_file.file_name, mime=source_file.mime_type,
        size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), author_id=actor.id))
    doc.has_files = True
    doc.current_revision = 1
    await db.flush()


async def signed_current(db, doc):
    from app.services.doc_approvals import _document_snapshot
    snapshot, _ = await _document_snapshot(db, doc)
    signatures = (await db.execute(select(DocSignatureEvidence).where(
        DocSignatureEvidence.company_id == doc.company_id, DocSignatureEvidence.doc_id == doc.id,
        DocSignatureEvidence.verification_status == "verified"))).scalars().all()
    if any(all((s.document_snapshot or {}).get(key) == snapshot.get(key) for key in ("card", "files"))
           for s in signatures):
        return True
    if doc.status not in ("signed", "in_force", "executed"):
        return False
    versions = (await db.execute(select(DocVersion).where(DocVersion.doc_id == doc.id,
        DocVersion.is_current.is_(True), DocVersion.tombstoned_at.is_(None)))).scalars().all()
    bodies = [v.uploaded_at for v in versions if v.role == "body"]
    return any(v.role == "signed_scan" and (not bodies or v.uploaded_at >= max(bodies)) for v in versions)
