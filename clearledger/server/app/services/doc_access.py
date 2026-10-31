"""Общая policy доступа к карточкам и файлам документооборота.

HTTP-адаптеры и проекции используют одни правила. Функции ожидают проверенный
контекст компании: SQL clauses дополняют tenant-фильтр вызывающей выборки,
а не заменяют его. SourceFile и DocVersion сохраняют отдельные жизненные циклы.
Проверка break-glass может записывать использование и аудит в текущую транзакцию;
модуль не делает commit и не владеет HTTP-маршрутами.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import resolve_member_modules
from app.models import (
    DocAccessGrant, DocAcquaint, DocApproval, DocBreakGlassAccess, DocCard,
    DocInboxItem, DocKind, DocVersion, User, UserCompany,
)
from app.services import doc_approvals
from app.services.service_accounts import not_service

_CONTENT_PERMISSIONS = {
    "read", "download", "print", "edit", "export", "send", "approve",
    "sign", "archive",
}

_BREAK_GLASS_PERMISSIONS = {"read", "download", "print"}


def _visible(d: DocCard, user: User) -> bool:
    """Базовая видимость до правил карточки и рабочих назначений."""
    if d.confidentiality == "company":
        return True
    return user.id in {d.author_id, d.responsible_id, d.signatory_id}


async def _access_rows(db: AsyncSession, cid: uuid.UUID,
                       d: DocCard) -> list[DocAccessGrant]:
    scopes = [
        (DocAccessGrant.scope_type == "doc") & (DocAccessGrant.scope_id == d.id),
    ]
    if d.inherit_kind_acl:
        scopes.append(
            (DocAccessGrant.scope_type == "kind")
            & (DocAccessGrant.scope_id == d.kind_id)
        )
    return (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        or_(*scopes)))).scalars().all()


async def _subject_ids(db: AsyncSession, cid: uuid.UUID,
                       user: User) -> dict[str, uuid.UUID | None]:
    membership = await db.get(UserCompany, (user.id, cid))
    return {
        "user": user.id,
        "role": membership.role_id if membership else None,
        "department": membership.department_id if membership else None,
    }


def _matches_subject(row: DocAccessGrant,
                     subjects: dict[str, uuid.UUID | None]) -> bool:
    return subjects.get(row.subject_type) == row.subject_id


def _denied(rows: list[DocAccessGrant],
            subjects: dict[str, uuid.UUID | None], permission: str) -> bool:
    denied = {permission}
    if permission in _CONTENT_PERMISSIONS:
        denied.add("read")
    return any(
        _matches_subject(row, subjects)
        and denied.intersection(row.denied_permissions or [])
        for row in rows
    )


async def _active_break_glass(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                              user: User, permission: str,
                              *, record_use: bool = True) -> bool:
    if permission not in _BREAK_GLASS_PERMISSIONS:
        return False
    row = (await db.execute(select(DocBreakGlassAccess).where(
        DocBreakGlassAccess.company_id == cid,
        DocBreakGlassAccess.doc_id == d.id,
        DocBreakGlassAccess.user_id == user.id,
        DocBreakGlassAccess.revoked_at.is_(None),
        DocBreakGlassAccess.expires_at > func.now(),
        DocBreakGlassAccess.permissions.contains([permission]),
    ).order_by(DocBreakGlassAccess.created_at.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return False
    if record_use:
        row.last_used_at = datetime.now(timezone.utc)
        row.use_count = int(row.use_count or 0) + 1
        await log_audit(
            db, actor=user, company_id=cid, action="doc.break_glass.use",
            target=str(d.id), details={"permission": permission,
                                       "access_id": str(row.id)},
        )
    return True


async def _action_policy_allows(db: AsyncSession, cid: uuid.UUID,
                                rows: list[DocAccessGrant], action: str,
                                principal_id: uuid.UUID | None) -> bool:
    policies = [row for row in rows if action in (row.permissions or [])
                or action in (row.denied_permissions or [])]
    if not policies:
        return True
    if principal_id is None:
        return False
    membership = await db.get(UserCompany, (principal_id, cid))
    subjects = {
        "user": principal_id,
        "role": membership.role_id if membership else None,
        "department": membership.department_id if membership else None,
    }
    matched = [row for row in policies
               if subjects.get(row.subject_type) == row.subject_id]
    if any(action in (row.denied_permissions or []) for row in matched):
        return False
    allow_policies = [row for row in policies if action in (row.permissions or [])]
    return not allow_policies or any(
        action in (row.permissions or []) for row in matched)


async def _can_doc(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                   user: User, permission: str,
                   *, record_break_glass_use: bool = True) -> bool:
    if (d.retention_state == "destruction_authorized"
            and permission in {"download", "print", "send", "export"}):
        return False
    if (d.retention_state in {"primary_purged", "destroyed"}
            and permission in _CONTENT_PERMISSIONS - {"read", "archive"}):
        return False
    rows = await _access_rows(db, cid, d)
    subjects = await _subject_ids(db, cid, user)
    if user.is_superadmin:
        if permission == "archive":
            return False
        if d.confidentiality != "strict":
            return True
        return await _active_break_glass(
            db, cid, d, user, permission,
            record_use=record_break_glass_use,
        )
    if permission != "read" and permission != "manage_acl":
        if not await _can_doc(
                db, cid, d, user, "read",
                record_break_glass_use=record_break_glass_use):
            return False
    if _denied(rows, subjects, permission):
        return False

    if permission == "read":
        inherited = {"read", "edit"}
        if _visible(d, user) or any(
                _matches_subject(row, subjects)
                and inherited.intersection(row.permissions or []) for row in rows):
            return True
        assigned = await db.scalar(select(or_(
            select(DocApproval.id).where(
                DocApproval.doc_id == d.id,
                DocApproval.assignee_id == user.id,
            ).exists(),
            select(DocAcquaint.id).where(
                DocAcquaint.doc_id == d.id,
                DocAcquaint.user_id == user.id,
            ).exists(),
        )))
        if assigned:
            return True
        principals = await doc_approvals.active_principals_for(db, cid, user.id)
        if (d.signatory_id in principals
                and d.status in ("draft", "registered")):
            return True
        if not principals:
            return False
        deputy_assignment = await db.scalar(select(DocApproval.id).where(
            DocApproval.doc_id == d.id,
            DocApproval.assignee_id.in_(principals),
            DocApproval.round == d.approval_round,
            DocApproval.status == "pending",
        ).limit(1))
        return deputy_assignment is not None

    granted = any(
        _matches_subject(row, subjects)
        and permission in (row.permissions or []) for row in rows)
    membership = await db.get(UserCompany, (user.id, cid))
    if permission == "edit":
        return granted or user.id in {d.author_id, d.responsible_id} or bool(
            d.confidentiality != "private"
            and membership and membership.role == "admin")
    if permission == "approve":
        assignees = (await db.execute(select(DocApproval.assignee_id).where(
            DocApproval.doc_id == d.id,
            DocApproval.status == "pending",
        ))).scalars().all()
        for assignee_id in {item for item in assignees if item}:
            is_assignee = user.id == assignee_id
            is_deputy = user.id in await doc_approvals.active_deputy_for(
                db, cid, assignee_id)
            if ((is_assignee or is_deputy)
                    and await _action_policy_allows(
                        db, cid, rows, "approve", assignee_id)):
                return True
        return False
    if permission == "sign":
        deputies = (await doc_approvals.active_deputy_for(db, cid, d.signatory_id)
                    if d.signatory_id else [])
        if bool(
            (user.id == d.signatory_id or user.id in deputies)
            and await _action_policy_allows(
                db, cid, rows, "sign", d.signatory_id)
        ):
            return True
        sign_rows = list((await db.execute(select(DocApproval).where(
            DocApproval.doc_id == d.id,
            DocApproval.round == d.approval_round,
            DocApproval.status == "pending",
        ))).scalars().all())
        for approval in sign_rows:
            if doc_approvals.step_kind(approval) != "sign":
                continue
            is_assignee = user.id == approval.assignee_id
            is_deputy = bool(
                approval.assignee_id
                and user.id in await doc_approvals.active_deputy_for(
                    db, cid, approval.assignee_id)
            )
            if ((is_assignee or is_deputy)
                    and await _action_policy_allows(
                        db, cid, rows, "sign", approval.assignee_id)):
                return True
        return False
    if permission == "manage_acl":
        return granted or user.id in {d.author_id, d.responsible_id} or bool(
            membership and membership.role == "admin")
    if permission == "archive":
        return granted or bool(membership and membership.role == "admin")
    if permission in {"download", "print", "send", "export"}:
        if granted:
            return True
        if d.confidentiality == "strict":
            return False
        fallback = "read" if permission in {"download", "print"} else "edit"
        return await _can_doc(
            db, cid, d, user, fallback,
            record_break_glass_use=record_break_glass_use,
        )
    return granted


async def _assert_doc_permission(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                                 user: User, permission: str) -> None:
    if not await _can_doc(db, cid, d, user, permission):
        message = "Документ закрыт" if permission == "read" else "Недостаточно прав на документ"
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)


async def _can_manage_doc_access(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                                 user: User) -> bool:
    return await _can_doc(db, cid, d, user, "manage_acl")


async def _assert_manage_doc_access(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                                    user: User) -> None:
    if not await _can_manage_doc_access(db, cid, d, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Права карточки меняет её владелец или администратор пространства")


async def _can_process_inbox(db: AsyncSession, cid: uuid.UUID, user: User) -> bool:
    if user.is_superadmin:
        return True
    membership = await db.get(UserCompany, (user.id, cid))
    subjects = await _subject_ids(db, cid, user)
    subject_filters = [
        and_(DocAccessGrant.subject_type == subject_type,
             DocAccessGrant.subject_id == subject_id)
        for subject_type, subject_id in subjects.items() if subject_id
    ]
    if not subject_filters:
        return False
    denied = await db.scalar(select(DocAccessGrant.id).join(
        DocKind,
        and_(DocAccessGrant.scope_type == "kind",
             DocAccessGrant.scope_id == DocKind.id),
    ).where(
        DocAccessGrant.company_id == cid,
        DocKind.company_id == cid,
        DocKind.family == "incoming",
        DocKind.is_active.is_(True),
        or_(*subject_filters),
        or_(
            DocAccessGrant.denied_permissions.contains(["read"]),
            DocAccessGrant.denied_permissions.contains(["edit"]),
        ),
    ).limit(1))
    if denied is not None:
        return False
    if membership is not None and membership.role == "admin":
        return True
    grant = await db.scalar(select(DocAccessGrant.id).join(
        DocKind,
        and_(DocAccessGrant.scope_type == "kind",
             DocAccessGrant.scope_id == DocKind.id),
    ).where(
        DocAccessGrant.company_id == cid,
        DocKind.company_id == cid,
        DocKind.family == "incoming",
        DocKind.is_active.is_(True),
        or_(*subject_filters),
        DocAccessGrant.permissions.contains(["edit"]),
    ).limit(1))
    return grant is not None


async def _assert_process_inbox(db: AsyncSession, cid: uuid.UUID, user: User) -> None:
    if not await _can_process_inbox(db, cid, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Приём из СЭД доступен администратору или делопроизводителю "
            "с правом правки входящего вида",
        )


async def _available_actions(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                             kind: DocKind | None, user: User) -> list[str]:
    actions: list[str] = []
    can_edit = await _can_doc(db, cid, d, user, "edit")
    can_sign = await _can_doc(db, cid, d, user, "sign")
    if can_sign and d.signatory_id != user.id:
        deputies = (await doc_approvals.active_deputy_for(db, cid, d.signatory_id)
                    if d.signatory_id else [])
        can_sign = user.id in deputies
    if can_edit and d.status in ("draft", "registered") and d.approval_status != "pending":
        actions.append("edit")
    # Реплика в историю — отдельное действие, а не побочный эффект правки.
    # `edit` снимается, как только документ вступил в силу, и витрина гасила
    # вместе с реквизитами поле реплики — ровно тогда, когда записать
    # «созвонились, срок перенесли» важнее всего. Круг людей тот же, привязки
    # к состоянию нет: реплика ничего в документе не меняет.
    if can_edit:
        actions.append("note")
    if can_edit and d.status == "draft" and not d.reg_number:
        actions.append("register")
    if (can_edit and kind and kind.route and d.status in ("draft", "registered")
            and d.approval_status != "pending"
            and (not kind.requires_registration or bool(d.reg_number))):
        actions.append("start_approval")
    if can_edit and d.approval_status == "pending":
        actions.append("cancel_approval")
    if (can_sign and d.status in ("draft", "registered")
            and (not kind or not kind.requires_registration or bool(d.reg_number))
            and (not kind or (not kind.route and not d.approval_round)
                 or d.approval_status == "approved")):
        actions.append("put_in_force")
    if can_edit and d.status == "in_force":
        actions.append("execute")
    if (can_edit and d.status not in ("archived", "cancelled")
            and d.approval_status != "pending"):
        actions.append("manage_case")
    if can_edit and d.status == "executed" and d.case_id:
        actions.append("archive")
    if can_edit and d.status in ("draft", "registered", "in_force"):
        actions.append("cancel")
    return actions


async def _readable_docs(db: AsyncSession, cid: uuid.UUID, rows: list[DocCard],
                         user: User) -> list[DocCard]:
    if user.is_superadmin:
        return [row for row in rows if row.confidentiality != "strict"]
    result: list[DocCard] = []
    for row in rows:
        if await _can_doc(db, cid, row, user, "read"):
            result.append(row)
    return result


async def _readable_doc_clause(
    db: AsyncSession, cid: uuid.UUID, user: User,
) -> Any:
    if user.is_superadmin:
        return DocCard.confidentiality != "strict"
    subjects = await _subject_ids(db, cid, user)
    subject_filters = [
        and_(DocAccessGrant.subject_type == subject_type,
             DocAccessGrant.subject_id == subject_id)
        for subject_type, subject_id in subjects.items() if subject_id
    ]
    inherited = {"read", "edit"}
    principals = await doc_approvals.active_principals_for(db, cid, user.id)
    clauses = [
        DocCard.confidentiality == "company",
        DocCard.author_id == user.id,
        DocCard.responsible_id == user.id,
        DocCard.signatory_id == user.id,
        select(DocApproval.id).where(
            DocApproval.company_id == cid,
            DocApproval.doc_id == DocCard.id,
            DocApproval.assignee_id == user.id,
        ).correlate(DocCard).exists(),
        select(DocAcquaint.id).where(
            DocAcquaint.company_id == cid,
            DocAcquaint.doc_id == DocCard.id,
            DocAcquaint.user_id == user.id,
        ).correlate(DocCard).exists(),
    ]
    if principals:
        clauses.append(and_(
            DocCard.signatory_id.in_(principals),
            DocCard.status.in_(("draft", "registered")),
        ))
        clauses.append(select(DocApproval.id).where(
            DocApproval.company_id == cid,
            DocApproval.doc_id == DocCard.id,
            DocApproval.assignee_id.in_(principals),
            DocApproval.round == DocCard.approval_round,
            DocApproval.status == "pending",
        ).correlate(DocCard).exists())
    if subject_filters:
        clauses.append(select(DocAccessGrant.id).where(
            DocAccessGrant.company_id == cid,
            or_(*subject_filters),
            or_(*[
                DocAccessGrant.permissions.contains([permission])
                for permission in inherited
            ]),
            or_(
                and_(DocAccessGrant.scope_type == "doc",
                     DocAccessGrant.scope_id == DocCard.id),
                and_(DocAccessGrant.scope_type == "kind",
                     DocAccessGrant.scope_id == DocCard.kind_id,
                     DocCard.inherit_kind_acl.is_(True)),
            ),
        ).correlate(DocCard).exists())
        denied = select(DocAccessGrant.id).where(
            DocAccessGrant.company_id == cid,
            or_(*subject_filters),
            DocAccessGrant.denied_permissions.contains(["read"]),
            or_(
                and_(DocAccessGrant.scope_type == "doc",
                     DocAccessGrant.scope_id == DocCard.id),
                and_(DocAccessGrant.scope_type == "kind",
                     DocAccessGrant.scope_id == DocCard.kind_id,
                     DocCard.inherit_kind_acl.is_(True)),
            ),
        ).correlate(DocCard).exists()
        return and_(or_(*clauses), ~denied)
    return or_(*clauses)


async def _archiveable_doc_clause(
    db: AsyncSession, cid: uuid.UUID, user: User,
) -> Any:
    if user.is_superadmin:
        return false()
    readable = await _readable_doc_clause(db, cid, user)
    subjects = await _subject_ids(db, cid, user)
    subject_filters = [
        and_(DocAccessGrant.subject_type == subject_type,
             DocAccessGrant.subject_id == subject_id)
        for subject_type, subject_id in subjects.items() if subject_id
    ]
    scope = or_(
        and_(DocAccessGrant.scope_type == "doc",
             DocAccessGrant.scope_id == DocCard.id),
        and_(DocAccessGrant.scope_type == "kind",
             DocAccessGrant.scope_id == DocCard.kind_id,
             DocCard.inherit_kind_acl.is_(True)),
    )
    denied = select(DocAccessGrant.id).where(
        DocAccessGrant.company_id == cid,
        or_(*subject_filters),
        DocAccessGrant.denied_permissions.contains(["archive"]),
        scope,
    ).correlate(DocCard).exists()
    membership = await db.get(UserCompany, (user.id, cid))
    if membership is not None and membership.role == "admin":
        allowed = true()
    else:
        allowed = select(DocAccessGrant.id).where(
            DocAccessGrant.company_id == cid,
            or_(*subject_filters),
            DocAccessGrant.permissions.contains(["archive"]),
            scope,
        ).correlate(DocCard).exists()
    return and_(readable, allowed, ~denied)


async def _docs_members(db: AsyncSession, cid: uuid.UUID,
                        user_ids: set[uuid.UUID] | None = None,
                        department_id: uuid.UUID | None = None) -> dict[uuid.UUID, User]:
    # Служебные участники («Процесс», «Секретарь») сюда не попадают: они не
    # ознакомятся, не завизируют и не откроют карточку — им нечем. Видимыми
    # авторами событий они при этом остаются.
    statement = (select(User, UserCompany)
                 .join(UserCompany, UserCompany.user_id == User.id)
                 .where(UserCompany.company_id == cid, User.mail_only.is_(False),
                        not_service()))
    if user_ids is not None:
        if not user_ids:
            return {}
        statement = statement.where(User.id.in_(user_ids))
    if department_id is not None:
        statement = statement.where(UserCompany.department_id == department_id)
    allowed: dict[uuid.UUID, User] = {}
    for user, membership in (await db.execute(statement)).all():
        if user.is_superadmin or membership.role == "admin":
            allowed[user.id] = user
            continue
        modules = await resolve_member_modules(membership, db)
        if modules is None or "docs" in modules or any(
                key.startswith("docs:") for key in modules):
            allowed[user.id] = user
    return allowed


async def authorize_docs_file_download(db: AsyncSession, user: User,
                                       file_id: uuid.UUID) -> None:
    """Проверка доступа к файлу документа при скачивании по прямой ссылке.

    Членства в компании мало: закрытый документ виден только автору,
    ответственному и подписанту, а адрес файла легко переслать. Файлы вне «Дела»
    сюда не попадают — у них нет строки в `doc_versions`, и проверка их не
    касается.
    """
    rows = (await db.execute(select(DocVersion).where(
        DocVersion.file_id == file_id))).scalars().all()
    if rows:
        docs = (await db.execute(select(DocCard).where(
            DocCard.id.in_({row.doc_id for row in rows})))).scalars().all()
        by_id = {doc.id: doc for doc in docs}
        for version in rows:
            doc = by_id.get(version.doc_id)
            if doc is None:
                continue
            if (version.tombstoned_at is None
                    and version.archive_purged_at is None):
                if await _can_doc(db, doc.company_id, doc, user, "download"):
                    return
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")

    inbox = (await db.execute(select(DocInboxItem).where(
        DocInboxItem.file_id == file_id))).scalars().all()
    if not inbox:
        return
    for item in inbox:
        if item.doc_id:
            doc = await db.get(DocCard, item.doc_id)
            if doc is not None and await _can_doc(
                    db, item.company_id, doc, user, "download"):
                return
        elif await _can_process_inbox(db, item.company_id, user):
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")


async def authorize_docs_file_egress(db: AsyncSession, user: User,
                                     file_ids: list[uuid.UUID]) -> list[DocCard]:
    if not file_ids:
        return []
    rows = list((await db.execute(select(DocVersion).where(
        DocVersion.file_id.in_(file_ids),
    ))).scalars().all())
    if not rows:
        return []
    docs = list((await db.execute(select(DocCard).where(
        DocCard.id.in_({row.doc_id for row in rows}),
    ).order_by(DocCard.id).with_for_update())).scalars().all())
    by_id = {doc.id: doc for doc in docs}
    authorized_docs: dict[uuid.UUID, DocCard] = {}
    for file_id in set(file_ids):
        related = [row for row in rows if row.file_id == file_id]
        if not related:
            continue
        allowed = False
        for version in related:
            doc = by_id.get(version.doc_id)
            if (doc is None or version.tombstoned_at is not None
                    or version.archive_purged_at is not None
                    or doc.retention_state in {
                        "destruction_authorized", "primary_purged", "destroyed"}):
                continue
            if await _can_doc(db, doc.company_id, doc, user, "send"):
                allowed = True
                authorized_docs[doc.id] = doc
                break
        if not allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл вложения не найден")
    return [authorized_docs[key] for key in sorted(authorized_docs)]
