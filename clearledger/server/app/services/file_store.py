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
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceFile


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
) -> SourceFile:
    """Записать файл на диск и завести строку `source_files`.

    Возвращает саму запись (не сохранённую в базу): вызывающий сам решает, когда
    коммитить — файл почти всегда приезжает вместе с другой записью, и разъехаться
    они не должны.

    `purpose='attachment'` по умолчанию: `data` означает «сырьё для разбора» и
    попадает в счётчик документов компании, поэтому ставится осознанно.
    """
    file_id = uuid.uuid4()
    suffix = Path(file_name or "file").suffix[:20]
    path = upload_dir() / f"{file_id}{suffix}"
    path.write_bytes(data)

    row = SourceFile(
        id=file_id,
        company_id=company_id,
        file_name=file_name or "файл",
        mime_type=mime or "application/octet-stream",
        size=len(data),
        storage_path=str(path),
        fingerprint=hashlib.sha256(data).hexdigest(),
        purpose="data" if purpose == "data" else "attachment",
    )
    db.add(row)
    return row


def read(row: SourceFile) -> bytes:
    """Прочитать содержимое по записи. Отсутствие файла — не молчаливый пустой
    ответ, а ошибка: пустое вложение выглядит как «документ без содержимого»."""
    return Path(row.storage_path).read_bytes()
