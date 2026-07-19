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


def log_export(db: AsyncSession, company_id: uuid.UUID, user: User, details: str) -> None:
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
