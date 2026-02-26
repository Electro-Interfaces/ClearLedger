"""Email-коннектор: IMAP polling → intake pipeline.

Периодически проверяет почтовый ящик, скачивает письма с вложениями,
сохраняет файлы в Layer 1 и создаёт raw_entries в staging.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.database import async_session
from app.models.models import Connector, Source, RawEntry
from app.services.storage import store_file
from app.services.parser import parse_file

logger = logging.getLogger("email_connector")


async def poll_email_connector(connector_id: str) -> dict[str, Any]:
    """Проверяет почтовый ящик и обрабатывает новые письма.

    Connector.config должен содержать:
    {
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "email": "docs@company.ru",
        "password": "...",
        "folder": "INBOX",
        "mark_read": true
    }
    """
    connector_uuid = UUID(connector_id)

    async with async_session() as db:
        result = await db.execute(
            select(Connector).where(Connector.id == connector_uuid)
        )
        connector = result.scalar_one_or_none()
        if not connector:
            return {"error": "Коннектор не найден"}

        config = connector.config or {}
        if not config.get("imap_host") or not config.get("email"):
            return {"error": "Не настроен IMAP"}

        company_id = connector.company_id
        category_id = connector.category_id

    # IMAP в отдельном потоке (синхронный протокол)
    loop = asyncio.get_event_loop()
    attachments = await loop.run_in_executor(
        None,
        _fetch_emails,
        config,
    )

    # Обрабатываем вложения асинхронно (одна сессия на весь batch)
    stats = {"processed": attachments["processed"], "attachments": 0, "errors": attachments["errors"]}
    if attachments["items"]:
        async with async_session() as db:
            for att in attachments["items"]:
                try:
                    await _save_attachment(
                        db, company_id, category_id,
                        att["filename"], att["content"], att["mime_type"],
                        att["subject"], att["sender"],
                    )
                    stats["attachments"] += 1
                except Exception as e:
                    logger.error(f"Ошибка сохранения вложения {att['filename']}: {e}")
                    stats["errors"] += 1
            await db.commit()

    return stats


def _fetch_emails(config: dict) -> dict[str, Any]:
    """Синхронная функция для работы с IMAP. Возвращает собранные вложения."""
    result: dict[str, Any] = {"processed": 0, "errors": 0, "items": []}

    try:
        imap = imaplib.IMAP4_SSL(
            config["imap_host"],
            config.get("imap_port", 993),
        )
        imap.login(config["email"], config["password"])
        imap.select(config.get("folder", "INBOX"))

        # Ищем непрочитанные
        _, message_ids = imap.search(None, "UNSEEN")
        ids = message_ids[0].split()

        for msg_id in ids[:50]:  # лимит на один poll
            try:
                _, data = imap.fetch(msg_id, "(RFC822)")
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header(msg.get("Subject", ""))
                sender = _decode_header(msg.get("From", ""))

                # Собираем вложения
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = part.get_filename()
                    if not filename:
                        continue

                    filename = _decode_header(filename)
                    content = part.get_payload(decode=True)
                    if not content:
                        continue

                    mime_type = part.get_content_type()
                    result["items"].append({
                        "filename": filename,
                        "content": content,
                        "mime_type": mime_type,
                        "subject": subject,
                        "sender": sender,
                    })

                # Помечаем как прочитанное
                if config.get("mark_read", True):
                    imap.store(msg_id, "+FLAGS", "\\Seen")

                result["processed"] += 1

            except Exception as e:
                logger.error(f"Ошибка обработки письма {msg_id}: {e}")
                result["errors"] += 1

        imap.close()
        imap.logout()

    except Exception as e:
        logger.error(f"IMAP ошибка: {e}")
        result["errors"] += 1

    return result


async def _save_attachment(
    db,
    company_id: str,
    category_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
    email_subject: str,
    email_sender: str,
) -> None:
    """Сохраняет вложение: файл → Source → RawEntry (в рамках переданной сессии)."""
    file_path, fingerprint, file_size = store_file(
        company_id=company_id,
        category_id=category_id,
        subcategory_id="email",
        original_filename=filename,
        content=content,
    )

    parsed = parse_file(content, mime_type, filename)

    source = Source(
        company_id=company_id,
        file_name=filename,
        mime_type=mime_type,
        file_size=file_size,
        file_path=file_path,
        fingerprint=fingerprint,
    )
    db.add(source)
    await db.flush()

    raw_entry = RawEntry(
        company_id=company_id,
        source_id=source.id,
        file_name=filename,
        mime_type=mime_type,
        extracted_text=parsed["extracted_text"],
        extracted_fields={
            **parsed["extracted_fields"],
            "_email_subject": email_subject,
            "_email_sender": email_sender,
        },
        page_count=parsed["page_count"],
        processing_status="parsed",
    )
    db.add(raw_entry)


def _decode_header(value: str | None) -> str:
    """Декодирует MIME-заголовок."""
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for text, charset in parts:
        if isinstance(text, bytes):
            result.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(text)
    return " ".join(result)
