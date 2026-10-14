"""След выгрузки: кто, что и в каком объёме выгрузил.

Аудит вёлся только в export_router (выгрузка DataEntry). Реестр сессий ЭЗС
с персональными данными клиентов, реестр под УПД, матрица «станция × месяц»
и пакет в БП следа не оставляли: на вопрос «кто выгрузил клиентов за март»
ответить было нечем, хотя AuditEvent для этого и заведён.

Коммит здесь не делаем — сессию коммитит get_db на выходе из эндпоинта
(database.py:612). Явный db.commit() в эндпоинте выгрузки оборвал бы
транзакцию раньше времени.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, User


def log_export(db: AsyncSession, company_id: uuid.UUID, user: User, details: str, rows: int = 0) -> None:
    """Записать факт выгрузки.

    details пишем так, чтобы след читался без раскопок в коде: что выгружено,
    за какой период и сколько строк. «Экспорт xlsx» без объёма бесполезен —
    по нему не отличить выгрузку одной смены от выгрузки всей базы.
    """
    db.add(AuditEvent(
        company_id=company_id,
        user_id=str(user.id),
        user_name=user.name,
        action="exported",
        details=details,
    ))
    # Объём выгрузок человека за час: одна большая выгрузка (xlsx, zip) — один запрос,
    # счётчик запросов её не видит. Порог — эпизод журнала безопасности и тревога
    # суперадминам и админам компании, с именем (аудит 07.10.2026).
    from app import guard
    count, total = guard.note_export(str(user.id), rows or _rows_in(details))
    if count > guard.EXPORT_COUNT or total > guard.EXPORT_ROWS:
        import asyncio
        asyncio.create_task(guard.record(
            "mass_export", who=user.email, company_id=company_id, path=details[:200], hits=count,
            detail=f"{count} выгрузок, {total} строк за час; последняя: {details}"[:900]))


def _rows_in(details: str) -> int:
    """Число строк из текста следа («…, 1234 строк»), если вызывающий его не передал."""
    import re
    m = re.search(r"(\d[\d\s]*)\s*(строк|записей|файл)", details or "")
    return int(re.sub(r"\s", "", m.group(1))) if m else 0
