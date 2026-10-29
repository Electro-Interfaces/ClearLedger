"""Document/version/source chain and confined local file delivery."""
import os
from pathlib import Path
import stat
import uuid
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import or_, select
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.models import ChatMessage, ConfSession, DocVersion, SourceFile, StoreDocFile, TaskAttachment


def _open_beneath(root, storage_path):
    root = Path(root).absolute()
    try:
        parts = Path(os.path.abspath(storage_path)).relative_to(root).parts
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError()
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError()
        return descriptor
    except (OSError, ValueError, TypeError):
        raise HTTPException(404, "Not found") from None


async def content(query, doc_id, version_id, upload_dir):
    doc = await query.detail("documents", doc_id)
    try:
        version_uuid = uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(404, "Not found") from None
    version = await query.db.scalar(select(DocVersion).where(
        DocVersion.id == version_uuid, DocVersion.doc_id == doc.id,
        DocVersion.company_id == query.facts.company_id,
        DocVersion.tombstoned_at.is_(None), DocVersion.archive_purged_at.is_(None)))
    if version is None:
        raise HTTPException(404, "Not found")
    source = await query.db.scalar(select(SourceFile).where(
        SourceFile.id == version.file_id, SourceFile.company_id == query.facts.company_id))
    if source is None:
        raise HTTPException(404, "Not found")
    # A document link must not bypass private task/chat/recording/station guards
    # on shared bytes. Until their common file policy is extracted, this product
    # API deliberately does not publish cross-domain SourceFile content.
    shared = await query.db.scalar(select(or_(
        select(ChatMessage.id).where(ChatMessage.file_url == f"/api/files/{source.id}").exists(),
        select(ConfSession.id).where(ConfSession.recording_file_id == source.id).exists(),
        select(StoreDocFile.id).where(StoreDocFile.file_id == source.id).exists(),
        select(TaskAttachment.id).where(TaskAttachment.file_id == source.id).exists(),
    )))
    if shared:
        raise HTTPException(404, "Not found")
    from app.services.doc_access import _can_doc, authorize_docs_file_download
    if not await _can_doc(query.db, query.facts.company_id, doc, query.facts.user, "download"):
        raise HTTPException(404, "Not found")
    await authorize_docs_file_download(query.db, query.facts.user, source.id)
    descriptor = _open_beneath(upload_dir, source.storage_path)
    handle = os.fdopen(descriptor, "rb")

    def chunks():
        try:
            while chunk := handle.read(65536):
                yield chunk
        finally:
            handle.close()

    filename = Path(version.file_name).name
    return StreamingResponse(chunks(), media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
                 "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(handle.close))
