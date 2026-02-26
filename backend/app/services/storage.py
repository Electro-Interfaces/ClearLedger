"""Файловое хранилище Layer 1 — immutable оригиналы."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import settings


def store_file(
    company_id: str,
    category_id: str,
    subcategory_id: str,
    original_filename: str,
    content: bytes,
) -> tuple[str, str, int]:
    """Сохраняет файл в папочную структуру Layer 1.

    Returns:
        (file_path, fingerprint, file_size)
    """
    now = datetime.now(timezone.utc)
    source_uuid = uuid4().hex[:8]

    # Безопасное имя файла
    safe_name = original_filename.replace("/", "_").replace("\\", "_")

    # /data/storage/{company}/{year}/{month}/{category}/{subcategory}/{uuid}_{name}
    rel_dir = os.path.join(
        company_id,
        str(now.year),
        f"{now.month:02d}",
        category_id,
        subcategory_id,
    )
    rel_path = os.path.join(rel_dir, f"{source_uuid}_{safe_name}")
    abs_dir = os.path.join(settings.storage_root, rel_dir)
    abs_path = os.path.join(settings.storage_root, rel_path)

    Path(abs_dir).mkdir(parents=True, exist_ok=True)

    with open(abs_path, "wb") as f:
        f.write(content)

    fingerprint = hashlib.sha256(content).hexdigest()

    return rel_path, fingerprint, len(content)


def get_file_path(rel_path: str) -> str:
    """Возвращает абсолютный путь к файлу."""
    return os.path.join(settings.storage_root, rel_path)
