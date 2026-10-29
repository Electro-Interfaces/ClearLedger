"""Одна точка записи файла пространства.

До этого файл в хранилище клали восемь мест, и каждое считало путь по-своему:
приёмка — в относительный `uploads` (то есть в рабочий каталог процесса), задачи
и документы проекта — в `UPLOAD_DIR` из окружения с запасным `/app/uploads`.
Пока всё работает в одном контейнере, разница незаметна; после переезда часть
файлов ищется не там, где лежит.

Здесь путь считается один раз, и запись в `source_files` идёт вместе с записью
на диск: строка без файла и файл без строки одинаково бесполезны.

Хранилище локальное. Когда понадобится объектное, менять придётся только этот
файл — ради этого он и заведён.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import SourceFile

logger = logging.getLogger(__name__)
_PENDING = "file_store.pending_transactions"


@dataclass
class _Files:
    paths: dict[Path, uuid.UUID] = field(default_factory=dict)
    committed: bool = False


def _current(session):
    return session.get_nested_transaction() or session.get_transaction()


def _track(db, path, file_id):
    session = db.sync_session if isinstance(db, AsyncSession) else db
    # Lightweight adapters used by pure metadata tests have no SQL transaction.
    # Production SQLAlchemy Sessions (including AsyncSession proxies) use events.
    if isinstance(session, Session):
        transaction = _current(session)
        if transaction is None:
            raise RuntimeError("SourceFile must belong to a Session transaction")
        pending = session.info.setdefault(_PENDING, {})
        pending.setdefault(transaction, _Files()).paths[path] = file_id


@event.listens_for(Session, "after_commit")
def _file_commit(session):
    bucket = session.info.get(_PENDING, {}).get(_current(session))
    if bucket is not None:
        bucket.committed = True


@event.listens_for(Session, "after_rollback")
def _file_rollback(session):
    # Also covers DBAPI rollback caused by a failed flush, before caller cleanup.
    bucket = session.info.get(_PENDING, {}).pop(_current(session), None)
    if bucket is not None:
        for path, file_id in bucket.paths.items():
            _remove_new_file(path, file_id)


@event.listens_for(Session, "after_transaction_end")
def _file_transaction_end(session, transaction):
    pending = session.info.get(_PENDING)
    if pending is None:
        return
    bucket = pending.pop(transaction, None)
    if bucket is not None:
        if bucket.committed and transaction.parent is not None:
            # RELEASE SAVEPOINT is provisional until its parent commits.
            pending.setdefault(transaction.parent, _Files()).paths.update(bucket.paths)
        elif not bucket.committed:
            # Includes rollback and Session.close() without a commit.
            for path, file_id in bucket.paths.items():
                _remove_new_file(path, file_id)
    if not pending:
        session.info.pop(_PENDING, None)


def _remove_new_file(path: Path, file_id: uuid.UUID) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Не удалось удалить новый файл после ошибки: %s", file_id)


def upload_dir() -> Path:
    """Каталог хранения. Создаётся при первом обращении."""
    path = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def put(
    db: AsyncSession,
    company_id: uuid.UUID,
    data: bytes,
    *,
    file_name: str,
    mime: str | None = None,
    purpose: str = "attachment",
    file_id: uuid.UUID | None = None,
    storage_suffix: str | None = None,
) -> SourceFile:
    """Записать файл на диск и завести строку `source_files`.

    Возвращает саму запись (не сохранённую в базу): вызывающий сам решает, когда
    коммитить — файл почти всегда приезжает вместе с другой записью, и разъехаться
    они не должны.

    `purpose='attachment'` по умолчанию: `data` означает «сырьё для разбора» и
    попадает в счётчик документов компании, поэтому ставится осознанно.
    """
    return put_generated(db, company_id, lambda target: target.write(data),
        file_name=file_name, mime=mime, purpose=purpose, file_id=file_id,
        storage_suffix=storage_suffix)


def put_generated(
    db: AsyncSession, company_id: uuid.UUID, write: Callable[[BinaryIO], object], *,
    file_name: str, mime: str | None = None, purpose: str = "attachment",
    file_id: uuid.UUID | None = None, storage_suffix: str | None = None,
) -> SourceFile:
    """Write bytes/archives through one exclusive, transaction-owned primitive.

    The callback writes a seekable stream without creating a second temp file or
    materializing large archives in memory. It must not commit the Session.
    """
    # A preallocated ID is an internal caller capability, never a client path.
    if file_id is not None and not isinstance(file_id, uuid.UUID):
        raise ValueError("Предварительно выделенный file_id должен быть UUID")
    file_id = file_id or uuid.uuid4()
    suffix = Path(file_name or "file").suffix[:20] if storage_suffix is None else storage_suffix
    if (not isinstance(suffix, str) or len(suffix) > 20 or "/" in suffix or "\\" in suffix
            or (suffix and not suffix.startswith("."))):
        raise ValueError("Недопустимое расширение файла хранилища")
    path = upload_dir() / f"{file_id}{suffix}"
    created = False
    try:
        # A preallocated ID or collision must never overwrite existing bytes.
        with path.open("xb+") as target:
            created = True
            write(target)
            size = target.seek(0, os.SEEK_END)
            target.seek(0)
            fingerprint = hashlib.file_digest(target, "sha256").hexdigest()
        row = SourceFile(
            id=file_id,
            company_id=company_id,
            file_name=file_name or "файл",
            mime_type=mime or "application/octet-stream",
            size=size,
            storage_path=str(path),
            fingerprint=fingerprint,
            purpose="data" if purpose == "data" else "attachment",
        )
        db.add(row)
        _track(db, path, file_id)
    except BaseException:
        if created:
            _remove_new_file(path, file_id)
        raise
    return row


async def put_and_flush(db: AsyncSession, company_id: uuid.UUID, data: bytes, **kwargs) -> SourceFile:
    """Flush convenience; commit ownership stays with the calling use case.

    Events also clean subsequent rollback/cancel/close, including SAVEPOINT.
    """
    row = put(db, company_id, data, **kwargs)
    try:
        await db.flush()
    except BaseException:
        _remove_new_file(Path(row.storage_path), row.id)
        raise
    return row


def read(row: SourceFile) -> bytes:
    """Прочитать содержимое по записи. Отсутствие файла — не молчаливый пустой
    ответ, а ошибка: пустое вложение выглядит как «документ без содержимого»."""
    return Path(row.storage_path).read_bytes()
