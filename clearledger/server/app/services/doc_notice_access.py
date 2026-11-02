"""Текущий нативный READ для доверенной ссылки уведомления о регистрации.

Вызывающий передаёт чистую собственную Session получателя, отдельно от корня
регистрации. Адаптер не добавляет ACL и не записывает использование break-glass.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, native_claims_context
from app.models import DocCard, User, UserCompany
from app.scope import (
    current_object_scope, current_organization,
    set_request_organization, set_request_scope,
)
from app.services.doc_access import _can_doc


@contextmanager
def doc_notice_context():
    """Восстановить auth/object/org, в том числе после отказа или ошибки."""
    objects, organization = current_object_scope(), current_organization()
    with native_claims_context(None, None):
        try:
            set_request_scope(None)
            set_request_organization(None)
            yield
        finally:
            set_request_organization(organization)
            set_request_scope(objects)


@dataclass(frozen=True, slots=True)
class AuthorizedDocNotice:
    email: str
    number: str
    title: str


async def authorized_doc_notice(
    db: AsyncSession, company_id: UUID, doc_id: UUID, user_id: UUID,
) -> AuthorizedDocNotice | None:
    """Вернуть только текущие разрешённые поля после нативных product/READ checks.

    Каждому получателю нужна свежая Session. Нельзя кэшировать разрешение всей
    рассылки через ожидание транспорта предыдущего получателя.
    """
    with doc_notice_context():
        user = await db.get(User, user_id)
        if user is None or not user.email:
            return None
        # Явное членство требуется и глобальному суперадмину.
        member = await db.get(UserCompany, (user.id, company_id))
        if member is None:
            return None
        try:
            cid = await assert_company_product(str(company_id), user, db, "docs")
        except HTTPException as error:
            if error.status_code in (400, 401, 403, 404):
                return None
            raise
        if cid != company_id:
            return None
        doc = await db.get(DocCard, doc_id)
        if doc is None or doc.company_id != company_id:
            return None
        if not await _can_doc(db, cid, doc, user, "read", record_break_glass_use=False):
            return None
        return AuthorizedDocNotice(email=user.email, number=doc.reg_number or "",
                                   title=doc.title[:200])
