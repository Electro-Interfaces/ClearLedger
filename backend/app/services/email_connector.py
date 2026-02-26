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
    async with async_session() as db:
        result = await db.execute(
            select(Connector).where(Connector.id == connector_id)
        )
        connector = result.scalar_one_or_none()
        if not connector:
            return {"error": "Коннектор не найден"}

        config = connector.config or {}
        if not config.get("imap_host") or not config.get("email"):
            return {"error": "Не настроен IMAP"}

    # IMAP в отдельном потоке (синхронный протокол)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _fetch_emails,
        connector.id,
        connector.company_id,
        connector.category_id,
        config,
    )


def _fetch_emails(
    connector_id: str,
    company_id: str,
    category_id: str,
    config: dict,
) -> dict[str, Any]:
    """Синхронная функция для работы с IMAP."""
    stats = {"processed": 0, "attachments": 0, "errors": 0}

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

                # Обрабатываем вложения
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

                    # Сохраняем через intake pipeline
                    _process_attachment_sync(
                        company_id, category_id,
                        filename, content, mime_type,
                        subject, sender,
                    )
                    stats["attachments"] += 1

                # Помечаем как прочитанное
                if config.get("mark_read", True):
                    imap.store(msg_id, "+FLAGS", "\\Seen")

                stats["processed"] += 1

            except Exception as e:
                logger.error(f"Ошибка обработки письма {msg_id}: {e}")
                stats["errors"] += 1

        imap.close()
        imap.logout()

    except Exception as e:
        logger.error(f"IMAP ошибка: {e}")
        stats["errors"] += 1

    return stats


def _process_attachment_sync(
    company_id: str,
    category_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
    email_subject: str,
    email_sender: str,
) -> None:
    """Синхронная обработка вложения (вызывается из IMAP-потока)."""
    import asyncio

    async def _async():
        file_path, fingerprint, file_size = store_file(
            company_id=company_id,
            category_id=category_id,
            subcategory_id="email",
            original_filename=filename,
            content=content,
        )

        parsed = parse_file(content, mime_type, filename)

        async with async_session() as db:
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
            await db.commit()

    # Запуск async в синхронном контексте
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_async())
    finally:
        loop.close()


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
