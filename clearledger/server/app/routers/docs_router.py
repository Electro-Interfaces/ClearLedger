"""
Приложение «Трек» — документооборот и работа компании.

Документ здесь самостоятельный объект: у него вид, реквизиты, регистрационный
номер, редакции файла и след. Поручение по документу ставится «Задачами» — там
уже есть сроки, эскалация и внешние участники, и второй такой движок заводить
незачем.

Отличие от «Задач» по существу: задача отвечает на вопрос «кто и что делает»,
документ — «что зарегистрировано и где лежит». Из задачи не построить реестр
входящих за квартал, потому что у неё нет ни корреспондента, ни даты самого
документа, ни номера; из документа не построить работу, потому что у него нет
исполнителя и стадии. Поэтому две сущности, связанные ссылкой.

Все действия над карточкой — одной ручкой `/docs/{id}/action`, как у задач.
Регистрация вынесена отдельно: она выдаёт номер из счётчика, и смешивать её с
правкой полей нельзя.
"""
import hashlib
import re
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    CompanyRole, Counterparty, Department, DocAccessGrant, DocApproval, DocCard,
    DocCase, DocEvent, DocKind, DocRelation, DocAcquaint, DocExchangeTarget,
    DocExport, DocInboxItem, DocLabelLink,
    DocShareLink, UserSubstitution,
    DocVersion, Organization, SourceFile, Task, TaskEvent, TaskLabel,
    TaskType, TaskWorkItem, User, UserCompany,
)
from app.routers import doc_share_router
from app.services import (
    doc_approvals, doc_exchange, doc_print, doc_text, doc_verify, file_store, mail_send,
)
from app.services.doc_numbers import next_number, render, scope_key

router = APIRouter(prefix="/docs", tags=["Трек"])

_LIST_LIMIT = 500
_FAMILIES = ("ord", "incoming", "outgoing", "internal", "contract", "other")
_STATUSES = ("draft", "registered", "in_force", "executed", "archived", "cancelled")
_SCOPES = ("kind", "kind_year", "kind_org", "kind_org_year")
# Что принимаем файлом. Список тот же, что у документов склада: расширять его
# нужно осознанно, а не «на всякий случай» — вложение уходит людям и наружу.
_MIME_ALLOWED = {
    "application/pdf", "image/jpeg", "image/png", "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/msword", "application/vnd.ms-excel", "text/plain",
}
_MAX_FILE_BYTES = 25 * 1024 * 1024
_RUSSIAN_TEXT_SEARCH = literal_column("'russian'::regconfig")
_FIELD_TYPES = {"text", "textarea", "number", "date", "boolean", "select"}
_FIELD_CODE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_BUSINESS_TIMEZONE = ZoneInfo("Europe/Moscow")

# Заготовки видов: то, что есть в любой компании. Заводятся кнопкой из раздела
# «Виды», а не молча при первом запросе: справочник компании создаёт человек.
STARTER_KINDS: list[dict[str, Any]] = [
    {"code": "doc_in", "name": "Входящее письмо", "family": "incoming",
     "direction": "in", "number_prefix": "ВХ",
     "desc": "Корреспонденция от контрагентов и органов"},
    {"code": "doc_out", "name": "Исходящее письмо", "family": "outgoing",
     "direction": "out", "number_prefix": "ИСХ",
     "desc": "Письма, которые компания отправляет сама"},
    {"code": "order", "name": "Приказ", "family": "ord", "direction": "none",
     "number_prefix": "ПР", "desc": "Приказы по основной деятельности"},
    {"code": "memo", "name": "Служебная записка", "family": "internal",
     "direction": "none", "number_prefix": "СЗ",
     "desc": "Внутренняя переписка подразделений"},
]


# ── Помощники ────────────────────────────────────────────────────────────────


def _uuid_or_400(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неверный {field}")


def _clean_fields(value: Any) -> list[dict[str, Any]]:
    """Оставить исполнимую схему реквизитов, а не произвольный JSON."""
    if not isinstance(value, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Схема реквизитов должна быть списком")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Каждый реквизит должен быть объектом")
        code = str(raw.get("code") or "").strip()
        label = str(raw.get("label") or "").strip()[:120]
        field_type = str(raw.get("type") or "text").strip()
        if field_type == "string":
            field_type = "text"
        if not _FIELD_CODE.fullmatch(code):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Неверный код реквизита: {code or 'пусто'}")
        if code in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Реквизит {code} задан дважды")
        if not label:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"У реквизита {code} нет названия")
        if field_type not in _FIELD_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Неизвестный тип реквизита {field_type}")
        field = {
            "code": code, "label": label, "type": field_type,
            "required": bool(raw.get("required", False)),
        }
        if field_type == "select":
            options = [str(item).strip()[:120] for item in (raw.get("options") or [])
                       if str(item).strip()]
            if not options:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"У списка {label} нет вариантов")
            field["options"] = list(dict.fromkeys(options))
        seen.add(code)
        result.append(field)
    return result


def _validate_attrs(kind: DocKind, attrs: Any, *, required: bool) -> dict[str, Any]:
    """Проверить значения по схеме вида перед регистрацией и согласованием."""
    values = attrs or {}
    if not isinstance(values, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Реквизиты документа должны быть объектом")
    fields = kind.fields or []
    if not fields:
        return values
    allowed = {field["code"] for field in fields}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Неизвестные реквизиты: {', '.join(unknown)}")
    for field in fields:
        code = field["code"]
        value = values.get(code)
        missing = value is None or value == "" or value == []
        if required and field.get("required") and missing:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Заполните обязательный реквизит «{field['label']}»")
        if missing:
            continue
        field_type = field.get("type", "text")
        valid = (
            (field_type in ("text", "textarea", "select") and isinstance(value, str))
            or (field_type == "number" and isinstance(value, (int, float))
                and not isinstance(value, bool))
            or (field_type == "boolean" and isinstance(value, bool))
        )
        if field_type == "date" and isinstance(value, str):
            try:
                date_type.fromisoformat(value)
                valid = True
            except ValueError:
                valid = False
        if not valid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Неверное значение реквизита «{field['label']}»")
        if field_type == "select" and value not in (field.get("options") or []):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Выберите допустимое значение «{field['label']}»")
    return values


async def _kind_or_404(db: AsyncSession, cid: uuid.UUID, kind_id) -> DocKind:
    k = (await db.execute(select(DocKind).where(
        DocKind.company_id == cid,
        DocKind.id == _uuid_or_400(kind_id, "kind_id")))).scalar_one_or_none()
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вид документа не найден")
    return k


async def _doc_or_404(db: AsyncSession, cid: uuid.UUID, doc_id) -> DocCard:
    d = (await db.execute(select(DocCard).where(
        DocCard.company_id == cid,
        DocCard.id == _uuid_or_400(doc_id, "doc_id")))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return d


async def _organization_id(db: AsyncSession, cid: uuid.UUID,
                           value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    organization_id = _uuid_or_400(value, "organization_id")
    exists = await db.scalar(select(Organization.id).where(
        Organization.company_id == cid, Organization.id == organization_id))
    if exists is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Юрлицо не принадлежит выбранной компании")
    return organization_id


def _visible(d: DocCard, user: User) -> bool:
    """Базовая видимость до правил карточки и рабочих назначений."""
    if d.confidentiality != "private":
        return True
    return user.is_superadmin or user.id in {d.author_id, d.responsible_id, d.signatory_id}

async def _access_rows(db: AsyncSession, cid: uuid.UUID,
                       d: DocCard) -> list[DocAccessGrant]:
    return (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        or_(
            (DocAccessGrant.scope_type == "doc") & (DocAccessGrant.scope_id == d.id),
            (DocAccessGrant.scope_type == "kind") & (DocAccessGrant.scope_id == d.kind_id),
        )))).scalars().all()


async def _subject_ids(db: AsyncSession, cid: uuid.UUID,
                       user: User) -> dict[str, uuid.UUID | None]:
    membership = await db.get(UserCompany, (user.id, cid))
    return {
        "user": user.id,
        "role": membership.role_id if membership else None,
        "department": membership.department_id if membership else None,
    }


async def _can_doc(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                   user: User, permission: str) -> bool:
    if user.is_superadmin:
        return True
    rows = await _access_rows(db, cid, d)
    subjects = await _subject_ids(db, cid, user)

    def matches(row: DocAccessGrant) -> bool:
        return subjects.get(row.subject_type) == row.subject_id

    if permission == "read":
        inherited = {"read", "edit", "approve", "sign"}
        if _visible(d, user) or any(
                matches(row) and inherited.intersection(row.permissions or []) for row in rows):
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
        if not principals:
            return False
        deputy_assignment = await db.scalar(select(DocApproval.id).where(
            DocApproval.doc_id == d.id,
            DocApproval.assignee_id.in_(principals),
        ).limit(1))
        return deputy_assignment is not None

    granted = any(matches(row) and permission in (row.permissions or []) for row in rows)
    membership = await db.get(UserCompany, (user.id, cid))
    if permission == "edit":
        return granted or user.id in {d.author_id, d.responsible_id} or bool(
            membership and membership.role == "admin")
    if permission == "approve":
        assignees = (await db.execute(select(DocApproval.assignee_id).where(
            DocApproval.doc_id == d.id,
            DocApproval.status == "pending",
        ))).scalars().all()
        if granted or user.id in assignees:
            return True
        for assignee_id in {item for item in assignees if item}:
            if user.id in await doc_approvals.active_deputy_for(db, cid, assignee_id):
                return True
        return False
    if permission == "sign":
        if user.id == d.signatory_id:
            return True
        deputies = (await doc_approvals.active_deputy_for(db, cid, d.signatory_id)
                    if d.signatory_id else [])
        return granted or user.id in deputies
    return granted


async def _assert_doc_permission(db: AsyncSession, cid: uuid.UUID, d: DocCard,
                                 user: User, permission: str) -> None:
    if not await _can_doc(db, cid, d, user, permission):
        message = "Документ закрыт" if permission == "read" else "Недостаточно прав на документ"
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)


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
    if can_edit and d.status == "executed" and d.case_id:
        actions.append("archive")
    if can_edit and d.status in ("draft", "registered", "in_force"):
        actions.append("cancel")
    return actions


async def _readable_docs(db: AsyncSession, cid: uuid.UUID, rows: list[DocCard],
                         user: User) -> list[DocCard]:
    if user.is_superadmin:
        return rows
    visible = {d.id for d in rows if _visible(d, user)}
    hidden = [d for d in rows if d.id not in visible]
    if not hidden:
        return rows
    subjects = await _subject_ids(db, cid, user)
    grants = (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        or_(
            (DocAccessGrant.scope_type == "doc")
            & DocAccessGrant.scope_id.in_([d.id for d in hidden]),
            (DocAccessGrant.scope_type == "kind")
            & DocAccessGrant.scope_id.in_([d.kind_id for d in hidden]),
        )))).scalars().all()
    inherited = {"read", "edit", "approve", "sign"}
    matching = [g for g in grants if subjects.get(g.subject_type) == g.subject_id
                and inherited.intersection(g.permissions or [])]
    doc_scopes = {g.scope_id for g in matching if g.scope_type == "doc"}
    kind_scopes = {g.scope_id for g in matching if g.scope_type == "kind"}
    visible.update(d.id for d in hidden
                   if d.id in doc_scopes or d.kind_id in kind_scopes)
    principals = await doc_approvals.active_principals_for(db, cid, user.id)
    assignee_ids = [user.id, *principals]
    assigned = set((await db.execute(select(DocApproval.doc_id).where(
        DocApproval.company_id == cid,
        DocApproval.doc_id.in_([d.id for d in hidden]),
        DocApproval.assignee_id.in_(assignee_ids),
    ))).scalars().all())
    assigned.update((await db.execute(select(DocAcquaint.doc_id).where(
        DocAcquaint.company_id == cid,
        DocAcquaint.doc_id.in_([d.id for d in hidden]),
        DocAcquaint.user_id == user.id,
    ))).scalars().all())
    visible.update(assigned)
    return [d for d in rows if d.id in visible]


def _card_out(d: DocCard, names: dict[str, str] | None = None,
              organizations: dict[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
    organizations = organizations or {}
    return {
        "id": str(d.id), "kind_id": str(d.kind_id), "kind_code": d.kind_code,
        "kind_name": names.get(str(d.kind_id), ""),
        "family": d.family, "direction": d.direction,
        "title": d.title, "summary": d.summary, "status": d.status,
        "reg_number": d.reg_number,
        "reg_date": d.reg_date.isoformat() if d.reg_date else None,
        "number_manual": d.number_manual,
        "organization_id": str(d.organization_id) if d.organization_id else None,
        "organization_name": organizations.get(str(d.organization_id), ""),
        "counterparty_id": str(d.counterparty_id) if d.counterparty_id else None,
        "counterparty_name": d.counterparty_name,
        "external_number": d.external_number,
        "external_date": d.external_date.isoformat() if d.external_date else None,
        "subject_ref": d.subject_ref,
        "object_id": str(d.object_id) if d.object_id else None,
        "author_id": str(d.author_id) if d.author_id else None,
        "responsible_id": str(d.responsible_id) if d.responsible_id else None,
        "signatory_id": str(d.signatory_id) if d.signatory_id else None,
        "due_at": d.due_at.isoformat() if d.due_at else None,
        "confidentiality": d.confidentiality,
        "attrs": d.attrs or {},
        "source": d.source, "source_ref": d.source_ref,
        "current_revision": d.current_revision, "has_files": d.has_files,
        "case_id": str(d.case_id) if d.case_id else None,
        "storage_until": d.storage_until.isoformat() if d.storage_until else None,
        "approval_status": d.approval_status, "approval_round": d.approval_round,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _kind_out(k: DocKind) -> dict[str, Any]:
    return {
        "id": str(k.id), "code": k.code, "name": k.name, "description": k.description,
        "family": k.family, "direction": k.direction,
        "number_template": k.number_template, "number_scope": k.number_scope,
        "number_prefix": k.number_prefix, "fields": k.fields or [],
        "route": k.route or [],
        "default_case_id": str(k.default_case_id) if k.default_case_id else None,
        "errand_type_id": str(k.errand_type_id) if k.errand_type_id else None,
        "requires_registration": k.requires_registration,
        "is_active": k.is_active, "sort_order": k.sort_order,
    }


async def _assert_admin(db: AsyncSession, cid: uuid.UUID, user: User) -> None:
    """Справочник видов и нумерацию правит администратор пространства: от них
    зависит номер, который потом стоит в документе и нигде не переписывается."""
    from app.models import UserCompany
    if user.is_superadmin:
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Виды документов правит администратор пространства")


# ── Виды документов ──────────────────────────────────────────────────────────


class KindIn(BaseModel):
    company_id: str
    code: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    family: str = Field("internal", pattern="^(ord|incoming|outgoing|internal|contract|other)$")
    direction: str = Field("none", pattern="^(in|out|none)$")
    number_template: str = Field("{prefix}-{yyyy}-{n:04d}", max_length=80)
    number_scope: str = Field("kind_org_year", pattern="^(kind|kind_year|kind_org|kind_org_year)$")
    number_prefix: str = Field("", max_length=20)
    fields: list[dict] = Field(default_factory=list)
    # Маршрут согласования вида. Санитайзер оставляет только известные ключи:
    # иначе в JSONB копится то, что никто не читает, но все боятся удалить.
    route: list[dict] = Field(default_factory=list)
    default_case_id: str | None = None
    errand_type_id: str | None = None
    requires_registration: bool = True
    is_active: bool = True
    sort_order: int = 100


@router.get("/kinds")
async def list_kinds(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(DocKind).where(DocKind.company_id == cid)
                             .order_by(DocKind.sort_order, DocKind.name))).scalars().all()
    return {"kinds": [_kind_out(k) for k in rows]}


@router.post("/kinds", status_code=status.HTTP_201_CREATED)
async def create_kind(
    payload: KindIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    dup = (await db.execute(select(DocKind.id).where(
        DocKind.company_id == cid, DocKind.code == payload.code))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вид с таким кодом уже есть")
    k = DocKind(
        company_id=cid, code=payload.code, name=payload.name,
        description=payload.description, family=payload.family,
        direction=payload.direction, number_template=payload.number_template,
        number_scope=payload.number_scope, number_prefix=payload.number_prefix,
        fields=_clean_fields(payload.fields) or None,
        route=doc_approvals.clean_route(payload.route) or None,
        default_case_id=_uuid_or_400(payload.default_case_id, "default_case_id")
        if payload.default_case_id else None,
        errand_type_id=_uuid_or_400(payload.errand_type_id, "errand_type_id")
        if payload.errand_type_id else None,
        requires_registration=payload.requires_registration,
        is_active=payload.is_active, sort_order=payload.sort_order)
    db.add(k)
    await db.commit()
    await db.refresh(k)
    return _kind_out(k)


@router.put("/kinds/{kind_id}")
async def update_kind(
    kind_id: str,
    payload: KindIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    k = await _kind_or_404(db, cid, kind_id)
    for field in ("name", "description", "family", "direction", "number_template",
                  "number_scope", "number_prefix", "requires_registration",
                  "is_active", "sort_order"):
        setattr(k, field, getattr(payload, field))
    k.fields = _clean_fields(payload.fields) or None
    k.route = doc_approvals.clean_route(payload.route) or None
    k.default_case_id = (_uuid_or_400(payload.default_case_id, "default_case_id")
                         if payload.default_case_id else None)
    k.errand_type_id = (_uuid_or_400(payload.errand_type_id, "errand_type_id")
                        if payload.errand_type_id else None)
    await db.commit()
    await db.refresh(k)
    return _kind_out(k)


@router.post("/kinds/starter", status_code=status.HTTP_201_CREATED)
async def create_starter_kinds(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести обычный набор видов. Идемпотентно: существующие коды пропускаются,
    поэтому кнопку можно нажать дважды и ничего не задвоится."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    have = set((await db.execute(select(DocKind.code).where(
        DocKind.company_id == cid))).scalars().all())
    # Поручение по документу ставится обычным типом задачи, если он заведён.
    errand = (await db.execute(select(TaskType.id).where(
        TaskType.company_id == cid, TaskType.code == "errand"))).scalar_one_or_none()
    added = 0
    for spec in STARTER_KINDS:
        if spec["code"] in have:
            continue
        db.add(DocKind(
            company_id=cid, code=spec["code"], name=spec["name"],
            description=spec.get("desc"), family=spec["family"],
            direction=spec["direction"], number_prefix=spec["number_prefix"],
            errand_type_id=errand, sort_order=100 + added))
        added += 1
    if added:
        await db.commit()
    return {"added": added}


# ── Реестр ───────────────────────────────────────────────────────────────────


# ── Права уровня записи ──────────────────────────────────────────────────────


class AccessGrantIn(BaseModel):
    company_id: str
    scope_type: str = Field(..., pattern="^(doc|kind)$")
    scope_id: str
    subject_type: str = Field(..., pattern="^(user|role|department)$")
    subject_id: str
    permissions: list[str]


async def _check_access_refs(db: AsyncSession, cid: uuid.UUID,
                             payload: AccessGrantIn) -> tuple[uuid.UUID, uuid.UUID]:
    scope_id = _uuid_or_400(payload.scope_id, "scope_id")
    subject_id = _uuid_or_400(payload.subject_id, "subject_id")
    scope_model = DocCard if payload.scope_type == "doc" else DocKind
    scope = await db.get(scope_model, scope_id)
    if scope is None or scope.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Область доступа не найдена")
    if payload.subject_type == "user":
        subject = await db.get(UserCompany, (subject_id, cid))
    elif payload.subject_type == "role":
        subject = await db.get(CompanyRole, subject_id)
    else:
        subject = await db.get(Department, subject_id)
    if subject is None or (payload.subject_type != "user" and subject.company_id != cid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Получатель доступа не найден")
    return scope_id, subject_id


@router.get("/access")
async def list_access_grants(
    company_id: str = Query(...),
    doc_id: str | None = Query(None),
    kind_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    scopes: list[tuple[str, uuid.UUID]] = []
    if doc_id:
        doc = await _doc_or_404(db, cid, doc_id)
        await _assert_doc_permission(db, cid, doc, current_user, "read")
        scopes.extend((("doc", doc.id), ("kind", doc.kind_id)))
    elif kind_id:
        kind = await _kind_or_404(db, cid, kind_id)
        scopes.append(("kind", kind.id))
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен doc_id или kind_id")

    rows = (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        or_(*[(DocAccessGrant.scope_type == scope_type)
              & (DocAccessGrant.scope_id == scope_id)
              for scope_type, scope_id in scopes])))).scalars().all()
    names: dict[tuple[str, uuid.UUID], str] = {}
    for subject_type, model in (("user", User), ("role", CompanyRole),
                                ("department", Department)):
        ids = {row.subject_id for row in rows if row.subject_type == subject_type}
        if ids:
            for value in (await db.execute(select(model).where(model.id.in_(ids)))).scalars():
                names[(subject_type, value.id)] = value.name
    return {"grants": [{
        "id": str(row.id), "scope_type": row.scope_type,
        "scope_id": str(row.scope_id), "subject_type": row.subject_type,
        "subject_id": str(row.subject_id),
        "subject_name": names.get((row.subject_type, row.subject_id), ""),
        "permissions": row.permissions or [],
        "inherited": bool(doc_id and row.scope_type == "kind"),
    } for row in rows]}


@router.post("/access", status_code=status.HTTP_201_CREATED)
async def save_access_grant(
    payload: AccessGrantIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    scope_id, subject_id = await _check_access_refs(db, cid, payload)
    allowed = {"read", "edit", "approve", "sign"}
    permissions = [value for value in dict.fromkeys(payload.permissions) if value in allowed]
    if not permissions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не выбрано ни одного права")
    row = (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        DocAccessGrant.scope_type == payload.scope_type,
        DocAccessGrant.scope_id == scope_id,
        DocAccessGrant.subject_type == payload.subject_type,
        DocAccessGrant.subject_id == subject_id))).scalar_one_or_none()
    if row is None:
        row = DocAccessGrant(
            company_id=cid, scope_type=payload.scope_type, scope_id=scope_id,
            subject_type=payload.subject_type, subject_id=subject_id,
            created_by=current_user.id)
        db.add(row)
    row.permissions = permissions
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "permissions": row.permissions}


@router.delete("/access/{grant_id}")
async def delete_access_grant(
    grant_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    row = (await db.execute(select(DocAccessGrant).where(
        DocAccessGrant.company_id == cid,
        DocAccessGrant.id == _uuid_or_400(grant_id, "grant_id")))).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"deleted": row is not None}


@router.post("/search/reindex")
async def reindex_doc_versions(
    company_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Дозаполнить текст у старых редакций после включения полнотекстового поиска."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    rows = (await db.execute(select(DocVersion).where(
        DocVersion.company_id == cid, DocVersion.content_text.is_(None),
        DocVersion.tombstoned_at.is_(None)).order_by(DocVersion.uploaded_at).limit(limit)
    )).scalars().all()
    indexed = 0
    skipped = 0
    for version in rows:
        source = await db.get(SourceFile, version.file_id)
        if source is None:
            skipped += 1
            continue
        try:
            content = file_store.read(source)
        except OSError:
            skipped += 1
            continue
        extracted = await doc_text.extract(
            content, version.mime or source.mime_type or "application/octet-stream",
            version.file_name)
        version.content_text = extracted or ""
        if extracted:
            indexed += 1
        else:
            skipped += 1
    await db.commit()
    remaining = await db.scalar(select(func.count()).select_from(DocVersion).where(
        DocVersion.company_id == cid, DocVersion.content_text.is_(None),
        DocVersion.tombstoned_at.is_(None)))
    return {"processed": len(rows), "indexed": indexed, "skipped": skipped,
            "remaining": remaining or 0}


@router.get("")
async def list_docs(
    company_id: str = Query(...),
    family: str | None = Query(None),
    direction: str | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    kind_id: str | None = Query(None),
    counterparty_id: str | None = Query(None),
    responsible_id: str | None = Query(None),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    q: str | None = Query(None),
    mine: bool = Query(False),
    limit: int = Query(200, ge=1, le=_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Реестр документов. Период считается по дате регистрации, а для
    незарегистрированных — по дате создания карточки: иначе черновики выпадают
    из любого отбора и теряются."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocCard).where(DocCard.company_id == cid)
    if mine:
        stmt = stmt.where(or_(DocCard.author_id == current_user.id,
                              DocCard.responsible_id == current_user.id))
    if family:
        stmt = stmt.where(DocCard.family == family)
    if direction:
        stmt = stmt.where(DocCard.direction == direction)
    if status_:
        stmt = stmt.where(DocCard.status == status_)
    if kind_id:
        stmt = stmt.where(DocCard.kind_id == _uuid_or_400(kind_id, "kind_id"))
    if counterparty_id:
        stmt = stmt.where(DocCard.counterparty_id
                          == _uuid_or_400(counterparty_id, "counterparty_id"))
    if responsible_id:
        stmt = stmt.where(DocCard.responsible_id
                          == _uuid_or_400(responsible_id, "responsible_id"))
    if date_from:
        stmt = stmt.where(func.coalesce(DocCard.reg_date,
                                        func.date(DocCard.created_at)) >= date_from)
    if date_to:
        stmt = stmt.where(func.coalesce(DocCard.reg_date,
                                        func.date(DocCard.created_at)) <= date_to)
    if q:
        query = q.strip()
        like = f"%{query}%"
        version_match = select(DocVersion.id).where(
            DocVersion.doc_id == DocCard.id,
            DocVersion.tombstoned_at.is_(None),
            func.to_tsvector(
                _RUSSIAN_TEXT_SEARCH,
                func.coalesce(DocVersion.content_text, literal_column("''")),
            ).op("@@")(func.plainto_tsquery(_RUSSIAN_TEXT_SEARCH, query)),
        ).exists()
        stmt = stmt.where(or_(DocCard.title.ilike(like),
                              DocCard.reg_number.ilike(like),
                              DocCard.external_number.ilike(like),
                              DocCard.counterparty_name.ilike(like),
                              version_match))
    stmt = stmt.order_by(DocCard.reg_date.desc().nullslast(),
                         DocCard.created_at.desc()).offset(offset).limit(limit)
    rows = await _readable_docs(db, cid, (await db.execute(stmt)).scalars().all(),
                                current_user)
    names = dict((await db.execute(select(DocKind.id, DocKind.name).where(
        DocKind.company_id == cid))).all())
    names = {str(k): v for k, v in names.items()}
    organizations = {str(key): value for key, value in (await db.execute(select(
        Organization.id, Organization.name).where(
        Organization.company_id == cid))).all()}
    return {"docs": [_card_out(d, names, organizations) for d in rows], "count": len(rows)}


# ── Карточка ─────────────────────────────────────────────────────────────────


class DocIn(BaseModel):
    company_id: str
    kind_id: str
    title: str = Field(..., min_length=1, max_length=500)
    summary: str | None = None
    organization_id: str | None = None
    counterparty_id: str | None = None
    counterparty_name: str = ""
    external_number: str | None = None
    external_date: date_type | None = None
    subject_ref: str | None = None
    object_id: str | None = None
    responsible_id: str | None = None
    signatory_id: str | None = None
    due_at: datetime | None = None
    confidentiality: str = Field("company", pattern="^(company|private)$")
    attrs: dict = Field(default_factory=dict)
    source: str = Field("manual", pattern="^(manual|intake|mail|chat|edo|api)$")
    source_ref: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_doc(
    payload: DocIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести карточку. Номера у неё пока нет: регистрация — отдельное действие,
    и черновик обязан отличаться от зарегистрированного документа."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    kind = await _kind_or_404(db, cid, payload.kind_id)
    attrs = _validate_attrs(kind, payload.attrs, required=False)

    name = payload.counterparty_name.strip()
    if payload.counterparty_id and not name:
        name = (await db.execute(select(Counterparty.name).where(
            Counterparty.id == _uuid_or_400(payload.counterparty_id, "counterparty_id")
        ))).scalar_one_or_none() or ""

    d = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title=payload.title.strip(), summary=payload.summary,
        organization_id=await _organization_id(db, cid, payload.organization_id),
        counterparty_id=_uuid_or_400(payload.counterparty_id, "counterparty_id")
        if payload.counterparty_id else None,
        counterparty_name=name,
        external_number=payload.external_number, external_date=payload.external_date,
        subject_ref=payload.subject_ref,
        # Ключ объекта сети строковый, приводить его к UUID нельзя.
        object_id=payload.object_id or None,
        author_id=current_user.id,
        responsible_id=_uuid_or_400(payload.responsible_id, "responsible_id")
        if payload.responsible_id else None,
        signatory_id=_uuid_or_400(payload.signatory_id, "signatory_id")
        if payload.signatory_id else None,
        due_at=payload.due_at, confidentiality=payload.confidentiality,
        attrs=attrs or None, source=payload.source, source_ref=payload.source_ref)
    db.add(d)
    await db.flush()
    db.add(DocEvent(doc_id=d.id, kind="created", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=kind.name))
    await db.commit()
    await db.refresh(d)
    return _card_out(d, {str(kind.id): kind.name})


class RegisterIn(BaseModel):
    company_id: str
    # Ручной номер нужен только при переносе нашего прежнего журнала. Номер
    # корреспондента хранится в external_number и в наш журнал не попадает.
    reg_number: str | None = Field(None, max_length=60)
    reg_date: date_type | None = None
    manual_reason: str | None = Field(None, max_length=500)


@router.post("/{doc_id}/register")
async def register_doc(
    doc_id: str,
    payload: RegisterIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Присвоить регистрационный номер.

    Повторная регистрация запрещена: номер, однажды выданный, остаётся за
    документом навсегда — даже если документ потом отменят.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Документ уже зарегистрирован под номером {d.reg_number}")
    if d.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Зарегистрировать можно только черновик")
    if d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Во время согласования реквизиты зафиксированы. "
                            "Сначала отмените круг")

    kind = await _kind_or_404(db, cid, d.kind_id)
    _validate_attrs(kind, d.attrs, required=True)
    today = datetime.now(_BUSINESS_TIMEZONE).date()
    on_date = payload.reg_date or today
    if on_date > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Дата регистрации не может быть в будущем")

    if "org" in kind.number_scope and d.organization_id is None:
        organizations = list((await db.execute(select(Organization.id).where(
            Organization.company_id == cid).order_by(Organization.id))).scalars().all())
        if len(organizations) == 1:
            d.organization_id = organizations[0]
        elif len(organizations) > 1:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Выберите юрлицо: у компании несколько журналов")

    manual_number = payload.reg_number.strip() if payload.reg_number is not None else ""
    if payload.reg_number is not None and not manual_number:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Ручной регистрационный номер не может быть пустым")
    if manual_number:
        await _assert_admin(db, cid, current_user)
        reason = (payload.manual_reason or "").strip()
        if len(reason) < 3:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Укажите причину переноса номера из прежнего журнала")
        number = manual_number
        d.number_manual = True
    else:
        reason = ""
        scope = scope_key(kind.code, d.organization_id, on_date, kind.number_scope)
        n = await next_number(db, cid, scope)
        org_code = ""
        if d.organization_id:
            # Префикс юрлица — тот же реквизит, которым нумерует документы 1С.
            org_code = (await db.execute(select(Organization.prefix).where(
                Organization.id == d.organization_id))).scalar_one_or_none() or ""
        number = render(kind.number_template, prefix=kind.number_prefix, number=n,
                        on_date=on_date, org_code=org_code, kind_code=kind.code)

    d.reg_number = number
    d.reg_date = on_date
    await doc_verify.ensure_token(db, d)
    d.registered_by = current_user.id
    if d.status == "draft":
        d.status = "registered"
    if d.approval_status in ("approved", "rejected"):
        d.approval_status = "none"

    # Дело и срок хранения фиксируются ЗДЕСЬ и больше не пересчитываются: правка
    # справочника сроков не должна задним числом делать вчерашние документы
    # подлежащими уничтожению.
    if d.case_id is None and kind.default_case_id:
        d.case_id = kind.default_case_id
    if d.case_id and d.storage_until is None:
        case = await db.get(DocCase, d.case_id)
        if case is not None and case.storage_years is not None:
            # Срок считается от конца года регистрации, как в перечне.
            d.storage_until = date_type(on_date.year + case.storage_years, 12, 31)
    db.add(DocEvent(doc_id=d.id, kind="registered", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=number, note=reason or None))
    await log_audit(db, actor=current_user, company_id=cid, action="doc.register",
                    target=number, details={"title": d.title[:200], "kind": kind.code,
                                             "manual": bool(manual_number),
                                             "manual_reason": reason or None})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Номер занят: так бывает при ручном вводе. Счётчик при этом откатился
        # вместе с транзакцией, поэтому пропуска в нумерации не остаётся.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Номер {number} уже занят другим документом")
    await db.refresh(d)
    return _card_out(d)


class ActionIn(BaseModel):
    company_id: str
    status: str | None = Field(None, pattern="^(draft|registered|in_force|executed|archived|cancelled)$")
    title: str | None = None
    summary: str | None = None
    organization_id: str | None = None
    responsible_id: str | None = None
    signatory_id: str | None = None
    due_at: datetime | None = None
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    external_number: str | None = None
    external_date: date_type | None = None
    object_id: str | None = None
    confidentiality: str | None = Field(None, pattern="^(company|private)$")
    attrs: dict | None = None
    note: str | None = None


_STATUS_TRANSITIONS = {
    "draft": {"in_force", "cancelled"},
    "registered": {"in_force", "cancelled"},
    "in_force": {"executed", "cancelled"},
    "executed": {"archived"},
    "archived": set(),
    "cancelled": set(),
}


async def _assert_signatory_identity(db: AsyncSession, cid: uuid.UUID,
                                     d: DocCard, user: User) -> None:
    if d.signatory_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Назначьте подписанта документа")
    if user.id == d.signatory_id:
        return
    deputies = await doc_approvals.active_deputy_for(db, cid, d.signatory_id)
    if user.id not in deputies:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Ввести документ в действие может только назначенный "
                            "подписант или его действующий заместитель")


def _material_action_fields(payload: ActionIn) -> set[str]:
    return set(payload.model_fields_set) - {"company_id", "note", "status"}


@router.post("/{doc_id}/action")
async def doc_action(
    doc_id: str,
    payload: ActionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Всё, что делают с карточкой, кроме регистрации: правка полей, смена
    состояния, реплика. Одна точка — одна проверка прав и один способ записать
    след, иначе половина изменений остаётся без автора."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    material_fields = _material_action_fields(payload)
    if payload.status == "in_force" and not material_fields:
        await _assert_doc_permission(db, cid, d, current_user, "sign")
    else:
        await _assert_doc_permission(db, cid, d, current_user, "edit")
    if payload.status and material_fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Смена состояния и правка реквизитов выполняются отдельно")
    if material_fields and d.status not in ("draft", "registered"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Действующий или закрытый документ изменяют новой редакцией")
    if material_fields and d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Во время согласования реквизиты зафиксированы. "
                            "Сначала отмените круг")
    who = current_user.name or current_user.email
    kind = await _kind_or_404(db, cid, d.kind_id)

    if payload.status and payload.status != d.status:
        if payload.status not in _STATUS_TRANSITIONS.get(d.status, set()):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Переход {d.status} → {payload.status} не разрешён")
        if d.status == "draft" and payload.status == "in_force" and kind.requires_registration:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Сначала зарегистрируйте документ")
        if payload.status == "in_force":
            _validate_attrs(kind, d.attrs, required=True)
            if (kind.route or d.approval_round) and d.approval_status != "approved":
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Сначала завершите согласование текущей редакции")
            await _assert_signatory_identity(db, cid, d, current_user)
        if payload.status == "archived" and d.case_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Перед передачей в архив поместите документ в дело")
        if payload.status == "cancelled" and not (payload.note or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Укажите причину отмены документа")
        if payload.status == "cancelled" and d.approval_status == "pending":
            await doc_approvals.cancel(db, d, current_user, payload.note.strip())
        db.add(DocEvent(doc_id=d.id, kind="status", user_id=current_user.id,
                        actor_name=who, from_value=d.status, to_value=payload.status,
                        note=payload.note))
        d.status = payload.status
        if payload.status in ("executed", "archived", "cancelled"):
            d.closed_at = datetime.now(timezone.utc)

    simple = {
        "title": payload.title, "summary": payload.summary,
        "external_number": payload.external_number,
        "counterparty_name": payload.counterparty_name,
        "confidentiality": payload.confidentiality,
    }
    changed_material = False
    for field, value in simple.items():
        if value is None:
            continue
        old = getattr(d, field)
        if str(old or "") == str(value):
            continue
        setattr(d, field, value)
        changed_material = True
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=who, from_value=str(old or "")[:200],
                        to_value=str(value)[:200], note=field))

    for field, raw in (("responsible_id", payload.responsible_id),
                       ("signatory_id", payload.signatory_id),
                       ("counterparty_id", payload.counterparty_id)):
        if raw is None:
            continue
        value = _uuid_or_400(raw, field) if raw else None
        if getattr(d, field) == value:
            continue
        setattr(d, field, value)
        changed_material = True
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=who, to_value=str(value or ""), note=field))

    if payload.organization_id is not None:
        if d.reg_number:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Юрлицо зарегистрированного документа не меняется")
        value = await _organization_id(db, cid, payload.organization_id)
        if d.organization_id != value:
            old = d.organization_id
            d.organization_id = value
            changed_material = True
            db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                            actor_name=who, from_value=str(old or ""),
                            to_value=str(value or ""), note="organization_id"))

    # Объект сети опознаётся строковым ключом, поэтому идёт отдельно от полей-UUID.
    if payload.object_id is not None and d.object_id != (payload.object_id or None):
        d.object_id = payload.object_id or None
        changed_material = True
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=who, to_value=payload.object_id or "", note="object_id"))

    if payload.due_at is not None and d.due_at != payload.due_at:
        d.due_at = payload.due_at
        changed_material = True
    if payload.external_date is not None and d.external_date != payload.external_date:
        d.external_date = payload.external_date
        changed_material = True
    if payload.attrs is not None:
        attrs = _validate_attrs(kind, payload.attrs, required=False)
        if d.attrs != attrs:
            d.attrs = attrs
            changed_material = True
    if changed_material and d.approval_status in ("approved", "rejected"):
        d.approval_status = "none"
        db.add(DocEvent(doc_id=d.id, kind="approval", user_id=current_user.id,
                        actor_name=who, to_value="нужно согласовать заново",
                        note="изменены реквизиты документа"))
    if payload.note and payload.status is None:
        db.add(DocEvent(doc_id=d.id, kind="comment", user_id=current_user.id,
                        actor_name=who, note=payload.note))

    await db.commit()
    await db.refresh(d)
    return _card_out(d)


# ── Согласование (вторая волна) ──────────────────────────────────────────────


class ApprovalStartIn(BaseModel):
    company_id: str
    # Разовый маршрут, если у вида его нет: так согласуют документ, для которого
    # заводить отдельный вид незачем.
    route: list[dict] | None = None


@router.post("/{doc_id}/approval/start", status_code=status.HTTP_201_CREATED)
async def approval_start(
    doc_id: str,
    payload: ApprovalStartIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Запустить круг согласования.

    Список согласующих разворачивается снимком: роль или отдел превращаются в
    конкретных людей здесь и сейчас. Иначе человек, сменивший отдел, унёс бы
    визу с собой, а документ завис бы без объяснения.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Согласование уже идёт: дождитесь виз или отмените круг")

    kind = await db.get(DocKind, d.kind_id)
    if kind is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вид документа не найден")
    if d.status not in ("draft", "registered"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Согласовать можно только рабочую редакцию документа")
    if kind.requires_registration and not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ")
    _validate_attrs(kind, d.attrs, required=True)
    route = payload.route if payload.route is not None else (kind.route if kind else None)
    res = await doc_approvals.start(db, cid, d, route or [], current_user)
    if "error" in res:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, res["error"])
    await db.commit()
    return res


class ApprovalCancelIn(BaseModel):
    company_id: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/{doc_id}/approval/cancel")
async def approval_cancel(
    doc_id: str,
    payload: ApprovalCancelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if d.approval_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Активного круга нет")
    result = await doc_approvals.cancel(db, d, current_user, payload.reason.strip())
    await db.commit()
    return result


class ApprovalDecideIn(BaseModel):
    company_id: str
    approved: bool
    comment: str | None = None


@router.post("/approvals/{approval_id}")
async def approval_decide(
    approval_id: str,
    payload: ApprovalDecideIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Поставить визу.

    Решает ТОЛЬКО тот, кому виза адресована. Ни администратор пространства, ни
    автор документа за него расписаться не могут: виза — юридический факт, и
    поставленная чужой рукой она превращает лист согласования в фикцию. Если
    согласующий недоступен, круг перезапускают с другим составом — это видно в
    истории, в отличие от подмены.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    row = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == cid,
        DocApproval.id == _uuid_or_400(approval_id, "approval_id")))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Виза не найдена")
    if not await doc_approvals.may_decide(db, cid, row, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Визу ставит тот, кому она адресована, "
                            "либо назначенный заместитель на время отсутствия")
    d = await _doc_or_404(db, cid, row.doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "approve")
    res = await doc_approvals.decide(db, cid, d, row, current_user,
                                     payload.approved, payload.comment)
    if "error" in res:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, res["error"])
    await db.commit()
    return res


@router.get("/approvals/mine")
async def approvals_mine(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Что ждёт моей визы. Экран «На мне» — единственный канал, на который можно
    опереться: оповещения уходят без гарантии доставки."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    principals = await doc_approvals.active_principals_for(db, cid, current_user.id)
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == cid,
        DocApproval.assignee_id.in_([current_user.id, *principals]),
        DocApproval.status == "pending").order_by(DocApproval.due_at.asc().nullslast())
    )).scalars().all()
    if not rows:
        return {"approvals": []}
    docs = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.id.in_({r.doc_id for r in rows})))).scalars().all()}
    return {"approvals": [{
        "id": str(r.id), "doc_id": str(r.doc_id),
        "step_name": r.step_name, "mode": r.mode,
        "acting_for": str(r.assignee_id) if r.assignee_id != current_user.id else None,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "doc_title": docs[r.doc_id].title if r.doc_id in docs else "",
        "doc_number": docs[r.doc_id].reg_number if r.doc_id in docs else None,
    } for r in rows if r.doc_id in docs]}


# ── Номенклатура дел ─────────────────────────────────────────────────────────


class CaseIn(BaseModel):
    company_id: str
    year: int = Field(..., ge=2000, le=2100)
    index: str = Field(..., min_length=1, max_length=20)
    title: str = Field(..., min_length=1, max_length=300)
    storage_term: str = Field("5 лет", max_length=60)
    storage_years: int | None = Field(None, ge=0, le=100)
    epk: bool = False
    organization_id: str | None = None
    department_id: str | None = None


@router.get("/cases")
async def list_cases(
    company_id: str = Query(...),
    year: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocCase).where(DocCase.company_id == cid)
    if year:
        stmt = stmt.where(DocCase.year == year)
    rows = (await db.execute(stmt.order_by(DocCase.year.desc(), DocCase.index))).scalars().all()
    return {"cases": [{
        "id": str(c.id), "year": c.year, "index": c.index, "title": c.title,
        "storage_term": c.storage_term, "storage_years": c.storage_years,
        "epk": c.epk, "status": c.status,
        "organization_id": str(c.organization_id) if c.organization_id else None,
    } for c in rows]}


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    c = DocCase(
        company_id=cid, year=payload.year, index=payload.index.strip(),
        title=payload.title.strip(), storage_term=payload.storage_term,
        storage_years=payload.storage_years, epk=payload.epk,
        organization_id=_uuid_or_400(payload.organization_id, "organization_id")
        if payload.organization_id else None,
        department_id=_uuid_or_400(payload.department_id, "department_id")
        if payload.department_id else None)
    db.add(c)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Дело с индексом {payload.index} за {payload.year} год уже есть")
    await db.refresh(c)
    return {"id": str(c.id), "index": c.index, "title": c.title}


@router.post("/cases/rollover")
async def rollover_cases(
    company_id: str = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Перенести номенклатуру на следующий год.

    Идемпотентно: дела, уже заведённые на целевой год, пропускаются. Переносятся
    только открытые — закрытое дело закрыто осознанно.
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    src = (await db.execute(select(DocCase).where(
        DocCase.company_id == cid, DocCase.year == year - 1,
        DocCase.status == "open"))).scalars().all()
    have = {(c.organization_id, c.index) for c in (await db.execute(select(DocCase).where(
        DocCase.company_id == cid, DocCase.year == year))).scalars().all()}
    added = 0
    for c in src:
        if (c.organization_id, c.index) in have:
            continue
        db.add(DocCase(
            company_id=cid, organization_id=c.organization_id, year=year,
            index=c.index, title=c.title, storage_term=c.storage_term,
            storage_years=c.storage_years, epk=c.epk,
            department_id=c.department_id))
        added += 1
    if added:
        await db.commit()
    return {"added": added, "year": year}


# ── Отправка контрагенту (третья волна) ──────────────────────────────────────


class ShareIn(BaseModel):
    company_id: str
    recipient_name: str | None = None
    recipient_email: str | None = None
    # Срок обязателен и ограничен: вечная ссылка на документ это утечка,
    # отложенная во времени.
    days: int = Field(14, ge=1, le=180)


@router.post("/{doc_id}/share", status_code=status.HTTP_201_CREATED)
async def create_share(
    doc_id: str,
    payload: ShareIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Дать контрагенту ссылку на документ.

    Юридический предел: подтверждение по ссылке — простая электронная подпись, и
    она работает, только если порядок её использования согласован в договоре.
    Это оговаривается в договоре, кодом такую дыру не закрыть.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ: наружу уходит номер")

    link = DocShareLink(
        company_id=cid, doc_id=d.id, token=doc_share_router.new_token(),
        recipient_name=(payload.recipient_name or "").strip() or None,
        recipient_email=(payload.recipient_email or "").strip() or None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.days),
        created_by=current_user.id)
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == d.id, DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None)).order_by(
        DocVersion.role, DocVersion.revision))).scalars().all()
    link.version_snapshot = [{
        "id": str(version.id), "role": version.role,
        "revision": version.revision, "file_name": version.file_name,
        "size": version.size_bytes, "sha256": version.sha256,
    } for version in versions]
    link.card_snapshot = {
        "title": d.title, "reg_number": d.reg_number,
        "reg_date": d.reg_date.isoformat() if d.reg_date else None,
        "summary": d.summary,
    }
    db.add(link)
    db.add(DocEvent(doc_id=d.id, kind="dispatch", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=link.recipient_name or link.recipient_email or "по ссылке",
                    note=f"ссылка на {payload.days} дн."))
    await db.commit()
    await db.refresh(link)
    return {"id": str(link.id), "token": link.token,
            "expires_at": link.expires_at.isoformat()}


@router.get("/{doc_id}/share")
async def list_shares(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "read")
    rows = (await db.execute(select(DocShareLink).where(
        DocShareLink.doc_id == d.id).order_by(
        DocShareLink.created_at.desc()))).scalars().all()
    return {"links": [{
        "id": str(r.id), "token": r.token,
        "recipient": r.recipient_name or r.recipient_email,
        "expires_at": r.expires_at.isoformat(),
        "revoked": r.revoked, "opened_count": r.opened_count,
        "last_opened_at": r.last_opened_at.isoformat() if r.last_opened_at else None,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "acknowledged_by": r.acknowledged_by_name,
    } for r in rows]}


@router.post("/share/{link_id}/revoke")
async def revoke_share(
    link_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отозвать ссылку. Запись остаётся: кто и когда смотрел документ — это след,
    и стирать его вместе со ссылкой нельзя."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    row = (await db.execute(select(DocShareLink).where(
        DocShareLink.company_id == cid,
        DocShareLink.id == _uuid_or_400(link_id, "link_id")))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ссылка не найдена")
    d = await _doc_or_404(db, cid, str(row.doc_id))
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    row.revoked = True
    await db.commit()
    return {"revoked": str(row.id)}


class SendIn(BaseModel):
    company_id: str
    account_id: str
    to: list[str] = Field(..., min_length=1)
    subject: str | None = None
    body: str | None = None
    # Прикладывать ли файлы документа. Иначе уходит только письмо с номером.
    with_files: bool = True


@router.post("/{doc_id}/send")
async def send_doc(
    doc_id: str,
    payload: SendIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отправить документ контрагенту почтой, с файлами.

    Письмо уходит с ящика компании и попадает в ту же переписку, что и остальная
    корреспонденция: отдельного контура отправки документов не заводим.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ: наружу уходит номер")

    files: list[uuid.UUID] = []
    if payload.with_files:
        files = list((await db.execute(select(DocVersion.file_id).where(
            DocVersion.doc_id == d.id, DocVersion.is_current.is_(True),
            DocVersion.tombstoned_at.is_(None)))).scalars().all())

    subject = (payload.subject or f"{d.reg_number} {d.title}").strip()[:300]
    date_part = d.reg_date.isoformat() if d.reg_date else ""
    default_body = "\n\n".join([
        f"Направляем документ {d.reg_number} от {date_part}.", d.title])
    body = (payload.body or default_body).strip()
    res = await mail_send.send_message(
        db, cid, account_id=_uuid_or_400(payload.account_id, "account_id"),
        to=payload.to, subject=subject, body=body,
        author=current_user.name or current_user.email, attachments=files)
    if "error" in res:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, res["error"])

    db.add(DocEvent(doc_id=d.id, kind="dispatch", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=", ".join(payload.to)[:200],
                    note=f"письмом, файлов: {len(files)}"))
    await db.commit()
    return {"sent": True, "attachments": len(files), **res}


@router.get("/{doc_id}/print")
async def print_doc(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Печатная форма: бланк с шапкой юрлица и листом согласования.

    Отдаём HTML, печатает браузер — PDF-движка в системе нет, и заводить его ради
    бланка дороже, чем печать через «Сохранить как PDF».
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "read")
    return HTMLResponse(await doc_print.render_card(db, d))


@router.post("/{doc_id}/verification")
async def verification_link(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Стабильная ссылка на проверку записи, не ссылка получателя на файлы."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Проверка доступна после регистрации")
    return {"url": await doc_verify.public_url(db, d), "code": d.verify_token}


# ── Регламент и разрезы: то же, что у поручений, но по документам ────────────
#
# Справочники общие с поручениями (метки, шаблоны, расписания, представления):
# в одном продукте человек не должен видеть два разных списка меток и два места
# для регламента. Отличается только область применения.


@router.get("/labels")
async def list_doc_labels(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Справочник меток пространства — общий с поручениями."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(TaskLabel).where(
        TaskLabel.company_id == cid).order_by(TaskLabel.name))).scalars().all()
    return {"labels": [{"id": str(r.id), "name": r.name, "color": r.color} for r in rows]}


class LabelIn(BaseModel):
    company_id: str
    name: str = Field(..., min_length=1, max_length=60)
    color: str = Field("slate", max_length=20)


@router.post("/labels", status_code=status.HTTP_201_CREATED)
async def create_doc_label(
    payload: LabelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    dup = (await db.execute(select(TaskLabel.id).where(
        TaskLabel.company_id == cid,
        func.lower(TaskLabel.name) == payload.name.strip().lower()))).scalar_one_or_none()
    if dup is not None:
        return {"id": str(dup), "duplicate": True}
    row = TaskLabel(company_id=cid, name=payload.name.strip(), color=payload.color)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "name": row.name, "color": row.color}


class DocLabelIn(BaseModel):
    company_id: str
    label_id: str
    on: bool = True


@router.post("/{doc_id}/labels")
async def toggle_doc_label(
    doc_id: str,
    payload: DocLabelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Повесить или снять метку. Одна ручка на оба действия: отдельная ручка на
    снятие означала бы две проверки прав на одно и то же."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    lid = _uuid_or_400(payload.label_id, "label_id")
    link = await db.get(DocLabelLink, (d.id, lid))
    if payload.on and link is None:
        db.add(DocLabelLink(doc_id=d.id, label_id=lid))
    elif not payload.on and link is not None:
        await db.delete(link)
    await db.commit()
    return {"on": payload.on}


class WorkItemIn(BaseModel):
    company_id: str
    minutes: int = Field(..., ge=1, le=24 * 60)
    work_date: date_type | None = None
    description: str | None = None


@router.post("/{doc_id}/time", status_code=status.HTTP_201_CREATED)
async def add_doc_time(
    doc_id: str,
    payload: WorkItemIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Записать время по документу.

    Дата работы отдельно от даты записи: время вносят задним числом, и «когда
    сделал» не равно «когда вспомнил записать».
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    row = TaskWorkItem(
        doc_id=d.id, user_id=current_user.id, created_by=current_user.id,
        work_date=payload.work_date or datetime.now(timezone.utc).date(),
        minutes=payload.minutes, description=payload.description)
    db.add(row)
    db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=f"{payload.minutes} мин", note="учёт времени"))
    await db.commit()
    return {"id": str(row.id), "minutes": row.minutes}


@router.get("/board")
async def docs_board(
    company_id: str = Query(...),
    family: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Доска: как идёт дело по процессу.

    Колонки — шаги маршрута согласования, а не состояния карточки: вопрос «где
    документ застрял» это вопрос о шаге и о том, кого ждут. Документы без
    запущенного согласования собраны отдельной колонкой.
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocCard).where(DocCard.company_id == cid,
                                 DocCard.status.notin_(("archived", "cancelled")))
    if family:
        stmt = stmt.where(DocCard.family == family)
    docs = await _readable_docs(
        db, cid, (await db.execute(stmt.limit(_LIST_LIMIT))).scalars().all(), current_user)
    if not docs:
        return {"columns": []}

    rows = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == cid,
        DocApproval.doc_id.in_([d.id for d in docs])))).scalars().all()
    live: dict[uuid.UUID, list[DocApproval]] = {}
    for r in rows:
        doc = next((x for x in docs if x.id == r.doc_id), None)
        if doc is not None and r.round == doc.approval_round:
            live.setdefault(r.doc_id, []).append(r)

    columns: dict[str, dict[str, Any]] = {}
    for d in docs:
        group = live.get(d.id, [])
        pending = [r for r in group if r.status == "pending"]
        if not group:
            key, name = "no_route", "Без согласования"
        elif pending:
            step = min(pending, key=lambda r: r.step_no)
            key, name = f"step:{step.step_no}", step.step_name
        elif any(r.status == "rejected" for r in group):
            key, name = "rejected", "Возвращены"
        else:
            key, name = "approved", "Согласованы"
        col = columns.setdefault(key, {"key": key, "name": name, "docs": []})
        col["docs"].append({
            "id": str(d.id), "title": d.title, "reg_number": d.reg_number,
            "status": d.status, "kind_name": d.kind_code,
            "waiting": len(pending),
            "due_at": d.due_at.isoformat() if d.due_at else None,
        })
    order = {"no_route": 0, "rejected": 90, "approved": 99}
    return {"columns": sorted(columns.values(),
                              key=lambda c: order.get(c["key"], int(
                                  c["key"].split(":")[1]) if ":" in c["key"] else 50))}


# ── Исполнительская дисциплина ───────────────────────────────────────────────


@router.get("/reports/discipline")
async def approval_discipline(
    company_id: str = Query(...),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Длительность согласований, задержки и доля прохождения с первого круга."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = (select(DocApproval, DocCard, DocKind.name)
            .join(DocCard, DocCard.id == DocApproval.doc_id)
            .join(DocKind, DocKind.id == DocCard.kind_id)
            .where(DocApproval.company_id == cid))
    if date_from:
        stmt = stmt.where(DocApproval.created_at >= datetime.combine(
            date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(DocApproval.created_at < datetime.combine(
            date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"summary": {"documents": 0, "completed": 0, "pending": 0,
                            "first_pass_rate": 0}, "by_kind": [], "people": []}

    users = {approval.assignee_id for approval, _, _ in rows if approval.assignee_id}
    names = {user.id: (user.name or user.email) for user in (await db.execute(
        select(User).where(User.id.in_(users)))).scalars().all()}
    by_doc: dict[uuid.UUID, dict[str, Any]] = {}
    by_person: dict[uuid.UUID, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for approval, doc, kind_name in rows:
        group = by_doc.setdefault(doc.id, {
            "doc": doc, "kind": kind_name, "created": approval.created_at,
            "decided": approval.decided_at, "pending": False, "round": approval.round,
        })
        group["created"] = min(group["created"], approval.created_at)
        if approval.decided_at and (group["decided"] is None
                                    or approval.decided_at > group["decided"]):
            group["decided"] = approval.decided_at
        group["pending"] = group["pending"] or approval.status == "pending"
        group["round"] = max(group["round"], approval.round)

        if approval.assignee_id:
            person = by_person.setdefault(approval.assignee_id, {
                "name": names.get(approval.assignee_id, "Участник пространства"),
                "decisions": 0, "hours": 0.0, "overdue": 0, "pending": 0,
            })
            if approval.status == "pending":
                person["pending"] += 1
                if approval.due_at and approval.due_at < now:
                    person["overdue"] += 1
            elif approval.decided_at:
                person["decisions"] += 1
                person["hours"] += max(
                    0.0, (approval.decided_at - approval.created_at).total_seconds() / 3600)

    kind_groups: dict[str, list[float]] = {}
    completed = 0
    first_pass = 0
    pending = 0
    for group in by_doc.values():
        if group["pending"]:
            pending += 1
            continue
        if group["doc"].approval_status != "approved" or group["decided"] is None:
            continue
        hours = max(0.0, (group["decided"] - group["created"]).total_seconds() / 3600)
        kind_groups.setdefault(group["kind"], []).append(hours)
        completed += 1
        if group["round"] == 1:
            first_pass += 1

    by_kind = [{
        "kind": name, "documents": len(values),
        "average_hours": round(sum(values) / len(values), 1),
    } for name, values in kind_groups.items()]
    by_kind.sort(key=lambda value: value["average_hours"], reverse=True)
    people = [{
        "user_id": str(user_id), "name": value["name"],
        "decisions": value["decisions"], "pending": value["pending"],
        "overdue": value["overdue"],
        "average_hours": round(value["hours"] / value["decisions"], 1)
        if value["decisions"] else 0,
    } for user_id, value in by_person.items()]
    people.sort(key=lambda value: (value["overdue"], value["average_hours"]), reverse=True)
    return {
        "summary": {
            "documents": len(by_doc), "completed": completed, "pending": pending,
            "first_pass_rate": round(first_pass * 100 / completed, 1) if completed else 0,
        },
        "by_kind": by_kind,
        "people": people,
    }


# ── Обмен с корпоративными системами головной компании ───────────────────────


class TargetIn(BaseModel):
    company_id: str
    code: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=160)
    system: str = Field("other", pattern="^(sedo|naumen|other)$")
    outbox_path: str = Field("", max_length=500)
    inbox_path: str = Field("", max_length=500)
    as_archive: bool = True
    is_active: bool = True
    scan_enabled: bool = False
    scan_interval_min: int = Field(30, ge=5, le=1440)
    note: str | None = None


@router.get("/exchange/targets")
async def list_targets(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid).order_by(
        DocExchangeTarget.name))).scalars().all()
    return {"targets": [{
        "id": str(t.id), "code": t.code, "name": t.name, "system": t.system,
        "outbox_path": t.outbox_path, "inbox_path": t.inbox_path,
        "as_archive": t.as_archive, "is_active": t.is_active, "note": t.note,
        "scan_enabled": t.scan_enabled, "scan_interval_min": t.scan_interval_min,
        "last_export_at": t.last_export_at.isoformat() if t.last_export_at else None,
        "last_scan_at": t.last_scan_at.isoformat() if t.last_scan_at else None,
        "last_error": t.last_error,
    } for t in rows]}


@router.post("/exchange/targets", status_code=status.HTTP_201_CREATED)
async def create_target(
    payload: TargetIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести точку обмена. Правит администратор: путь к папке головной компании
    это настройка пространства, а не личное предпочтение."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    if payload.scan_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала проверьте папку вручную")
    dup = (await db.execute(select(DocExchangeTarget.id).where(
        DocExchangeTarget.company_id == cid,
        DocExchangeTarget.code == payload.code))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Точка с таким кодом уже есть")
    t = DocExchangeTarget(
        company_id=cid, code=payload.code, name=payload.name, system=payload.system,
        outbox_path=payload.outbox_path.strip(), inbox_path=payload.inbox_path.strip(),
        as_archive=payload.as_archive, is_active=payload.is_active,
        scan_enabled=payload.scan_enabled, scan_interval_min=payload.scan_interval_min,
        note=payload.note)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return {"id": str(t.id), "code": t.code, "name": t.name}


class TargetScheduleIn(BaseModel):
    company_id: str
    enabled: bool
    interval_min: int = Field(30, ge=5, le=1440)


@router.put("/exchange/targets/{target_id}/schedule")
async def update_target_schedule(
    target_id: str,
    payload: TargetScheduleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Включить расписание только после ручной проверки папки обмена."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    target = (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid,
        DocExchangeTarget.id == _uuid_or_400(target_id, "target_id")))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка обмена не найдена")
    if payload.enabled and not target.inbox_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не указана папка приёма")
    if payload.enabled and target.last_scan_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала проверьте папку вручную кнопкой «Проверить папку»")
    target.scan_enabled = payload.enabled
    target.scan_interval_min = payload.interval_min
    await db.commit()
    return {"enabled": target.scan_enabled, "interval_min": target.scan_interval_min}


@router.post("/{doc_id}/export", status_code=status.HTTP_201_CREATED)
async def export_doc(
    doc_id: str,
    company_id: str = Query(...),
    target_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Выгрузить документ в папку головной компании.

    Только зарегистрированный: наружу уходит номер, по нему принимающая сторона
    и опознаёт документ. Повторная выгрузка разрешена — версия могла измениться,
    и прежний пакет при этом не затирается.
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ: наружу уходит номер")

    target = (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid,
        DocExchangeTarget.id == _uuid_or_400(target_id, "target_id")))).scalar_one_or_none()
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка обмена не найдена")
    if not target.outbox_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У точки обмена не указана папка выгрузки")

    data, content = await doc_exchange.build_package(db, d)
    name = doc_exchange.package_name(d)
    row = DocExport(
        company_id=cid, doc_id=d.id, target_id=target.id, package_name=f"{name}.zip",
        package_sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
        content=content, created_by=current_user.id)
    try:
        row.package_path = doc_exchange.place_package(target, name, data)
        row.status = "placed"
        target.last_export_at = datetime.now(timezone.utc)
        target.last_error = None
    except OSError as e:
        # Папка недоступна — не молчим и не теряем пакет: пишем отказ в журнал,
        # человек скачает архив кнопкой рядом.
        row.status = "failed"
        row.error = str(e)[:500]
        target.last_error = str(e)[:500]
    db.add(row)
    db.add(DocEvent(doc_id=d.id, kind="dispatch", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=target.name,
                    note=("выгружен в папку" if row.status == "placed"
                          else f"папка недоступна: {row.error}")))
    await db.commit()
    if row.status == "failed":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Папка недоступна: {row.error}")
    return {"id": str(row.id), "package": row.package_name, "path": row.package_path,
            "files": len(content.get("files", []))}


@router.get("/{doc_id}/export/download")
async def download_package(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Скачать тот же пакет файлом — когда папка недоступна или нужен разовый обмен."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    data, content = await doc_exchange.build_package(db, d)
    name = doc_exchange.package_name(d)
    db.add(DocExport(
        company_id=cid, doc_id=d.id, status="downloaded",
        package_name=f"{name}.zip", package_sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), content=content, created_by=current_user.id))
    db.add(DocEvent(doc_id=d.id, kind="dispatch", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value="скачан пакет", note="выгрузка файлом"))
    await db.commit()
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''" + quote(f"{name}.zip")})


@router.get("/{doc_id}/exports")
async def list_exports(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Что и когда уходило по этому документу. Вопрос сверки «отдавали ли» имеет
    ответ строкой журнала, а не памятью."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "read")
    rows = (await db.execute(select(DocExport).where(
        DocExport.doc_id == d.id).order_by(DocExport.created_at.desc()))).scalars().all()
    names = {str(t.id): t.name for t in (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid))).scalars().all()}
    return {"exports": [{
        "id": str(r.id), "status": r.status, "package": r.package_name,
        "path": r.package_path, "size": r.size_bytes,
        "target": names.get(str(r.target_id), "файлом"),
        "files": len((r.content or {}).get("files", [])),
        "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@router.post("/exchange/scan")
async def scan_targets(
    company_id: str = Query(...),
    target_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Посмотреть, что головная компания положила нам в папку.

    Файлы не удаляются и не перекладываются: папка чужая. Найденное становится
    кандидатом, решение о заведении карточки принимает человек.
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid,
        DocExchangeTarget.is_active.is_(True))
    if target_id:
        stmt = stmt.where(DocExchangeTarget.id == _uuid_or_400(target_id, "target_id"))
    targets = [t for t in (await db.execute(stmt)).scalars().all() if t.inbox_path]

    added = 0
    errors: list[dict[str, str]] = []
    for t in targets:
        try:
            added += await doc_exchange.collect_inbox(db, t)
        except OSError as e:
            t.last_error = str(e)[:500]
            errors.append({"target": t.name, "error": t.last_error})
            continue
    await db.commit()
    return {"targets": len(targets), "added": added, "errors": errors}


@router.get("/exchange/inbox")
async def list_inbox(
    company_id: str = Query(...),
    status_: str = Query("new", alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocInboxItem).where(DocInboxItem.company_id == cid)
    if status_ != "all":
        stmt = stmt.where(DocInboxItem.status == status_)
    rows = (await db.execute(stmt.order_by(
        DocInboxItem.found_at.desc()).limit(_LIST_LIMIT))).scalars().all()
    names = {str(t.id): t.name for t in (await db.execute(select(DocExchangeTarget).where(
        DocExchangeTarget.company_id == cid))).scalars().all()}
    return {"items": [{
        "id": str(r.id), "file_name": r.file_name, "size": r.size_bytes,
        "file_id": str(r.file_id) if r.file_id else None,
        "target": names.get(str(r.target_id), ""),
        "parsed": r.parsed or {}, "status": r.status,
        "doc_id": str(r.doc_id) if r.doc_id else None,
        "found_at": r.found_at.isoformat() if r.found_at else None,
    } for r in rows]}


class InboxDecisionIn(BaseModel):
    company_id: str
    accept: bool = True
    kind_id: str | None = None
    title: str | None = None
    counterparty_name: str | None = None
    note: str | None = None


@router.post("/exchange/inbox/{item_id}")
async def decide_inbox(
    item_id: str,
    payload: InboxDecisionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Принять файл из папки документом или отклонить.

    Принятый заводится карточкой-черновиком: номер ему присвоит человек при
    регистрации, потому что чужой регистрационный номер нашим журналом не
    управляет.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    item = (await db.execute(select(DocInboxItem).where(
        DocInboxItem.company_id == cid,
        DocInboxItem.id == _uuid_or_400(item_id, "item_id")))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кандидат не найден")
    if item.status != "new":
        raise HTTPException(status.HTTP_409_CONFLICT, "По кандидату уже решили")

    item.decided_by = current_user.id
    item.decided_at = datetime.now(timezone.utc)
    item.note = payload.note

    if not payload.accept:
        item.status = "rejected"
        await db.commit()
        return {"status": "rejected"}

    parsed = item.parsed or {}
    kind = await _kind_or_404(db, cid, payload.kind_id) if payload.kind_id else None
    if kind is None:
        kind = (await db.execute(select(DocKind).where(
            DocKind.company_id == cid, DocKind.family == "incoming",
            DocKind.is_active.is_(True)).order_by(DocKind.sort_order))).scalars().first()
    if kind is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Не выбран вид документа, а входящих видов в справочнике нет")

    d = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction,
        title=(payload.title or parsed.get("title") or item.file_name)[:500],
        summary=parsed.get("summary"),
        counterparty_name=(payload.counterparty_name
                           or parsed.get("counterparty_name") or "")[:500],
        external_number=parsed.get("reg_number"),
        author_id=current_user.id, source="edo",
        source_ref=f"inbox:{item.id}")
    db.add(d)
    await db.flush()
    db.add(DocEvent(doc_id=d.id, kind="created", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=kind.name, note=f"принят из папки: {item.file_name}"))

    if item.file_id:
        sf = await db.get(SourceFile, item.file_id)
        if sf is not None:
            try:
                source_content = file_store.read(sf)
                content_text = await doc_text.extract(
                    source_content, sf.mime_type or "application/octet-stream", sf.file_name)
            except OSError:
                content_text = None
            db.add(DocVersion(
                company_id=cid, doc_id=d.id, revision=1, role="body",
                file_id=sf.id, file_name=sf.file_name, mime=sf.mime_type,
                size_bytes=sf.size or 0, sha256=item.sha256,
                author_id=current_user.id, content_text=content_text or ""))
            d.has_files = True
            d.current_revision = 1

    item.status = "accepted"
    item.doc_id = d.id
    await db.commit()
    return {"status": "accepted", "doc_id": str(d.id)}


# ── Ознакомление и замещение ─────────────────────────────────────────────────


class AcquaintIn(BaseModel):
    company_id: str
    user_ids: list[str] = []
    department_id: str | None = None
    due_at: datetime | None = None


@router.post("/{doc_id}/acquaint", status_code=status.HTTP_201_CREATED)
async def add_acquaint(
    doc_id: str,
    payload: AcquaintIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Направить документ на ознакомление.

    Отдельно от согласования: виза это «не возражаю» до подписания, ознакомление
    — «прочитал» после. Приказ, с которым никого не ознакомили, не работает, и
    вопрос «а он знал» должен решаться списком, а не памятью.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")

    people: set[uuid.UUID] = {_uuid_or_400(u, "user_id") for u in payload.user_ids}
    department_people: set[uuid.UUID] = set()
    if payload.department_id:
        dep = _uuid_or_400(payload.department_id, "department_id")
        department = await db.get(Department, dep)
        if department is None or department.company_id != cid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Подразделение не найдено")
        department_people = set((await db.execute(select(UserCompany.user_id).where(
            UserCompany.company_id == cid,
            UserCompany.department_id == dep))).scalars().all())
        people.update(department_people)
    if not people:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некого знакомить")
    members = set((await db.execute(select(UserCompany.user_id).where(
        UserCompany.company_id == cid,
        UserCompany.user_id.in_(people),
    ))).scalars().all())
    if members != people:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Один из получателей не состоит в компании")

    have = set((await db.execute(select(DocAcquaint.user_id).where(
        DocAcquaint.doc_id == d.id))).scalars().all())
    added = 0
    for uid in people - have:
        db.add(DocAcquaint(
            company_id=cid, doc_id=d.id, user_id=uid,
            reason="department" if uid in department_people else "manual",
            due_at=payload.due_at, created_by=current_user.id,
        ))
        added += 1
    if added:
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=current_user.name or current_user.email,
                        to_value=f"ознакомление: {added} чел.", note="лист ознакомления"))
    await db.commit()
    return {"added": added, "total": len(have) + added}


class AcquaintReadIn(BaseModel):
    company_id: str
    note: str | None = None


@router.post("/{doc_id}/acquaint/read")
async def mark_acquainted(
    doc_id: str,
    payload: AcquaintReadIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отметиться ознакомленным. Только за себя: отметка за другого — это ровно
    та подделка, от которой лист ознакомления и должен защищать."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    row = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == d.id,
        DocAcquaint.user_id == current_user.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Вас не направляли на ознакомление с этим документом")
    if row.status == "done":
        return {"status": "done", "read_at": row.read_at.isoformat()
                if row.read_at else None, "repeated": True}
    row.status = "done"
    row.read_at = datetime.now(timezone.utc)
    row.note = (payload.note or "").strip() or None
    db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value="ознакомлен", note=row.note))
    await db.commit()
    return {"status": "done", "read_at": row.read_at.isoformat()}


@router.get("/acquaints/mine")
async def my_acquaints(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """С чем мне нужно ознакомиться."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.company_id == cid, DocAcquaint.user_id == current_user.id,
        DocAcquaint.status == "pending").order_by(
        DocAcquaint.due_at.asc().nullslast()))).scalars().all()
    if not rows:
        return {"acquaints": []}
    docs = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.id.in_({r.doc_id for r in rows})))).scalars().all()}
    return {"acquaints": [{
        "id": str(r.id), "doc_id": str(r.doc_id),
        "doc_title": docs[r.doc_id].title if r.doc_id in docs else "",
        "doc_number": docs[r.doc_id].reg_number if r.doc_id in docs else None,
        "due_at": r.due_at.isoformat() if r.due_at else None,
    } for r in rows if r.doc_id in docs]}


class SubstitutionIn(BaseModel):
    company_id: str
    user_id: str
    deputy_id: str
    starts_on: date_type
    ends_on: date_type
    basis: str | None = None


@router.get("/substitutions")
async def list_substitutions(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "docs")
    rows = (await db.execute(select(UserSubstitution).where(
        UserSubstitution.company_id == cid).order_by(
        UserSubstitution.starts_on.desc()))).scalars().all()
    ids = {r.user_id for r in rows} | {r.deputy_id for r in rows}
    names = {str(u.id): (u.name or u.email) for u in (await db.execute(
        select(User).where(User.id.in_(ids)))).scalars().all()} if ids else {}
    today = datetime.now(timezone.utc).date()
    return {"substitutions": [{
        "id": str(r.id),
        "user": names.get(str(r.user_id), ""), "user_id": str(r.user_id),
        "deputy": names.get(str(r.deputy_id), ""), "deputy_id": str(r.deputy_id),
        "starts_on": r.starts_on.isoformat(), "ends_on": r.ends_on.isoformat(),
        "basis": r.basis, "is_active": r.is_active,
        "now": r.is_active and r.starts_on <= today <= r.ends_on,
    } for r in rows]}


@router.post("/substitutions", status_code=status.HTTP_201_CREATED)
async def create_substitution(
    payload: SubstitutionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Назначить замещение на время отсутствия.

    Заводит администратор пространства: замещение это полномочие, а не личная
    настройка, и основанием обычно служит приказ о возложении обязанностей.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    if payload.ends_on < payload.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Дата окончания раньше даты начала")
    uid = _uuid_or_400(payload.user_id, "user_id")
    did = _uuid_or_400(payload.deputy_id, "deputy_id")
    if uid == did:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Человек не может замещать сам себя")
    row = UserSubstitution(
        company_id=cid, user_id=uid, deputy_id=did,
        starts_on=payload.starts_on, ends_on=payload.ends_on,
        basis=payload.basis, created_by=current_user.id)
    db.add(row)
    await log_audit(db, actor=current_user, company_id=cid, action="doc.substitution",
                    target=str(row.id),
                    details={"from": payload.starts_on.isoformat(),
                             "to": payload.ends_on.isoformat()})
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id)}


@router.delete("/substitutions/{sub_id}")
async def stop_substitution(
    sub_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Прекратить замещение. Запись остаётся: по ней объясняется, кто и на каком
    основании расписывался в прошлом."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    await _assert_admin(db, cid, current_user)
    row = (await db.execute(select(UserSubstitution).where(
        UserSubstitution.company_id == cid,
        UserSubstitution.id == _uuid_or_400(sub_id, "sub_id")))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Замещение не найдено")
    row.is_active = False
    await db.commit()
    return {"stopped": str(row.id)}


@router.get("/{doc_id}")
async def get_doc(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка целиком: реквизиты, редакции файлов, связи и след."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "read")
    kind = await db.get(DocKind, d.kind_id)
    organization = (await db.get(Organization, d.organization_id)
                    if d.organization_id else None)

    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == d.id, DocVersion.tombstoned_at.is_(None))
        .order_by(DocVersion.role, DocVersion.revision.desc()))).scalars().all()
    events = (await db.execute(select(DocEvent).where(DocEvent.doc_id == d.id)
                               .order_by(DocEvent.created_at.desc()).limit(200))).scalars().all()
    relations = (await db.execute(select(DocRelation).where(
        DocRelation.doc_id == d.id))).scalars().all()
    acquaints = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == d.id))).scalars().all()
    approvals = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == d.id).order_by(
        DocApproval.round.desc(), DocApproval.step_no))).scalars().all()
    live = [a for a in approvals if a.round == d.approval_round]
    snapshot = live[0].document_snapshot if live else None
    snapshot_sha256 = live[0].snapshot_sha256 if live else None
    decidable = {
        a.id for a in live
        if a.status == "pending"
        and await doc_approvals.may_decide(db, cid, a, current_user)
    }
    approval_user_ids = {
        user_id for a in approvals
        for user_id in (a.assignee_id, a.decided_by)
        if user_id is not None
    }
    approval_people = {}
    if approval_user_ids:
        approval_people = {
            row.id: row.name or row.email
            for row in (await db.execute(select(User).where(
                User.id.in_(approval_user_ids)))).scalars()
        }

    return {
        **_card_out(d, {str(kind.id): kind.name} if kind else None,
                    {str(organization.id): organization.name} if organization else None),
        "kind": _kind_out(kind) if kind else None,
        "available_actions": await _available_actions(db, cid, d, kind, current_user),
        "versions": [{
            "id": str(v.id), "revision": v.revision, "role": v.role,
            "file_id": str(v.file_id), "file_name": v.file_name, "mime": v.mime,
            "size": v.size_bytes, "sha256": v.sha256, "title": v.title,
            "is_current": v.is_current,
            "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
        } for v in versions],
        "events": [{
            "id": str(e.id), "kind": e.kind, "actor": e.actor_name,
            "from": e.from_value, "to": e.to_value, "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
        "relations": [{
            "id": str(r.id), "kind": r.kind, "target_ref": r.target_ref,
            "target_doc_id": str(r.target_doc_id) if r.target_doc_id else None,
        } for r in relations],
        # Лист ознакомления: приказ, с которым никого не ознакомили, не работает.
        "acquaints": [{
            "id": str(a.id), "user_id": str(a.user_id), "status": a.status,
            "reason": a.reason,
            "read_at": a.read_at.isoformat() if a.read_at else None,
            "due_at": a.due_at.isoformat() if a.due_at else None,
            "reminded_at": a.reminded_at.isoformat() if a.reminded_at else None,
            "note": a.note,
        } for a in acquaints],
        # Кого именно ждут — то, чего не показывают гибриды рынка: там видно
        # «идёт согласование», но не видно, на ком оно стоит.
        "approval": {
            "status": d.approval_status, "round": d.approval_round,
            "snapshot": snapshot,
            "snapshot_sha256": snapshot_sha256,
            "steps": doc_approvals.progress(live),
            "rows": [{
                "id": str(a.id), "round": a.round, "step_no": a.step_no,
                "step_name": a.step_name, "status": a.status,
                "assignee_id": str(a.assignee_id) if a.assignee_id else None,
                "assignee_name": approval_people.get(a.assignee_id),
                "decided_by_id": str(a.decided_by) if a.decided_by else None,
                "decided_by_name": approval_people.get(a.decided_by),
                "can_decide": a.id in decidable,
                "snapshot_sha256": a.snapshot_sha256,
                "comment": a.comment,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "due_at": a.due_at.isoformat() if a.due_at else None,
            } for a in approvals],
        },
    }


# ── Файлы документа ──────────────────────────────────────────────────────────


@router.post("/{doc_id}/versions", status_code=status.HTTP_201_CREATED)
async def upload_version(
    doc_id: str,
    company_id: str = Query(...),
    role: str = Query("body", pattern="^(body|appendix|signed_scan|attachment)$"),
    title: str | None = Query(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Приложить файл новой редакцией.

    Тот же файл, залитый повторно, новой редакции не создаёт: содержимое
    опознаётся хешем. Иначе история редакций набивается копиями, и вопрос «что
    именно согласовали» снова становится неразрешимым.
    """
    cid = await assert_company_product(company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    d = (await db.execute(select(DocCard).where(
        DocCard.id == d.id).execution_options(
            populate_existing=True).with_for_update())).scalar_one()
    if d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Во время согласования набор файлов зафиксирован. "
                            "Сначала отмените круг")
    if d.status not in ("draft", "registered") and not (
            d.status == "in_force" and role == "signed_scan"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Для действующего или закрытого документа заведите новую редакцию")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Файл больше {_MAX_FILE_BYTES // 1024 // 1024} МБ")
    mime = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if mime not in _MIME_ALLOWED:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Тип {mime} не принимается")

    digest = hashlib.sha256(content).hexdigest()
    same = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == d.id, DocVersion.role == role,
        DocVersion.sha256 == digest,
        DocVersion.tombstoned_at.is_(None)))).scalars().first()
    if same is not None:
        return {"id": str(same.id), "revision": same.revision, "duplicate": True}

    last = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == d.id, DocVersion.role == role,
        DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None)))).scalars().first()
    latest_revision = (await db.execute(select(func.max(DocVersion.revision)).where(
        DocVersion.doc_id == d.id, DocVersion.role == role))).scalar_one() or 0

    sf = file_store.put(db, cid, content, file_name=file.filename or "файл", mime=mime)
    await db.flush()
    v = DocVersion(
        company_id=cid, doc_id=d.id, revision=latest_revision + 1,
        role=role, file_id=sf.id, file_name=sf.file_name, mime=mime,
        size_bytes=len(content), sha256=digest, title=title,
        supersedes_id=last.id if last else None, author_id=current_user.id)
    v.content_text = await doc_text.extract(content, mime, sf.file_name) or ""
    if last is not None:
        last.is_current = False
        await db.flush()
    db.add(v)
    d.has_files = True
    if role == "body":
        d.current_revision = v.revision
    if d.approval_status in ("approved", "rejected"):
        d.approval_status = "none"
        db.add(DocEvent(doc_id=d.id, kind="approval", user_id=current_user.id,
                        actor_name=current_user.name or current_user.email,
                        to_value="нужно согласовать заново",
                        note="изменён набор файлов документа"))
    db.add(DocEvent(doc_id=d.id, kind="version", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=f"{role} ред. {v.revision}", note=sf.file_name))
    await db.commit()
    await db.refresh(v)
    return {"id": str(v.id), "revision": v.revision, "file_id": str(sf.id),
            "file_name": sf.file_name, "size": len(content)}


class TombstoneIn(BaseModel):
    company_id: str
    reason: str = Field(..., min_length=3, max_length=300)


@router.post("/versions/{version_id}/tombstone")
async def tombstone_version(
    version_id: str,
    payload: TombstoneIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Убрать редакцию из работы. Не удаление: строка остаётся с причиной, потому
    что исчезнувший без следа файл документа — это дыра в истории."""
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    v = (await db.execute(select(DocVersion).where(
        DocVersion.company_id == cid,
        DocVersion.id == _uuid_or_400(version_id, "version_id")))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Редакция не найдена")
    d = await _doc_or_404(db, cid, v.doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    d = (await db.execute(select(DocCard).where(
        DocCard.id == d.id).execution_options(
            populate_existing=True).with_for_update())).scalar_one()
    v = (await db.execute(select(DocVersion).where(
        DocVersion.id == v.id).execution_options(
            populate_existing=True))).scalar_one()
    if v.tombstoned_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Редакция уже выведена из работы")
    if d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Во время согласования набор файлов зафиксирован. "
                            "Сначала отмените круг")
    if d.status not in ("draft", "registered"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Файлы действующего или закрытого документа неизменяемы")
    was_current = v.is_current
    v.tombstoned_at = datetime.now(timezone.utc)
    v.tombstoned_by = current_user.id
    v.tombstone_reason = payload.reason
    v.is_current = False
    await db.flush()
    if was_current:
        previous = (await db.execute(select(DocVersion).where(
            DocVersion.doc_id == d.id, DocVersion.role == v.role,
            DocVersion.id != v.id, DocVersion.tombstoned_at.is_(None),
        ).order_by(DocVersion.revision.desc()).limit(1))).scalar_one_or_none()
        if previous:
            previous.is_current = True
        if v.role == "body":
            d.current_revision = previous.revision if previous else 0
    d.has_files = (await db.execute(select(DocVersion.id).where(
        DocVersion.doc_id == d.id, DocVersion.id != v.id,
        DocVersion.tombstoned_at.is_(None)).limit(1))).scalar_one_or_none() is not None
    if d.approval_status in ("approved", "rejected"):
        d.approval_status = "none"
        db.add(DocEvent(doc_id=d.id, kind="approval", user_id=current_user.id,
                        actor_name=current_user.name or current_user.email,
                        to_value="нужно согласовать заново",
                        note="изменён набор файлов документа"))
    db.add(DocEvent(doc_id=d.id, kind="version", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    from_value=f"{v.role} ред. {v.revision}", note=payload.reason))
    await db.commit()
    return {"tombstoned": str(v.id)}


# ── Связи и поручение ────────────────────────────────────────────────────────


class ErrandIn(BaseModel):
    company_id: str
    title: str = Field(..., min_length=1, max_length=300)
    assignee_id: str
    due_at: datetime | None = None
    description: str | None = None


@router.post("/{doc_id}/errand", status_code=status.HTTP_201_CREATED)
async def create_errand(
    doc_id: str,
    payload: ErrandIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Поручение по документу — обычная задача со связью.

    Резолюция руководителя это работа человека, а работу в пространстве ведут
    «Задачи»: там срок, напоминание, эскалация и участие внешних сторон уже
    написаны. Здесь только заводится связь, чтобы из документа было видно, что по
    нему поручено, а из задачи — на основании чего.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    kind = await db.get(DocKind, d.kind_id)

    label = d.reg_number or d.title[:60]
    t = Task(company_id=cid, title=payload.title.strip(),
             description=payload.description or f"Поручение по документу {label}",
             author_id=current_user.id,
             assignee_id=_uuid_or_400(payload.assignee_id, "assignee_id"),
             type_id=kind.errand_type_id if kind else None,
             due_at=payload.due_at, object_id=d.object_id, status="open")
    db.add(t)
    await db.flush()
    db.add(TaskEvent(task_id=t.id, kind="created", user_id=current_user.id,
                     note=f"Поручение по документу {label}"))
    db.add(DocRelation(company_id=cid, doc_id=d.id, kind="errand",
                       target_ref=f"task:{t.id}", created_by=current_user.id))
    db.add(DocEvent(doc_id=d.id, kind="errand", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=f"task:{t.id}", note=payload.title.strip()))
    await db.commit()
    await db.refresh(t)
    return {"task_id": str(t.id), "number": t.number}


class RelationIn(BaseModel):
    company_id: str
    kind: str = Field("related",
                      pattern="^(reply_to|annex_of|amends|cancels|basis|errand|related)$")
    target_ref: str = Field(..., min_length=3, max_length=200)


@router.post("/{doc_id}/relations", status_code=status.HTTP_201_CREATED)
async def add_relation(
    doc_id: str,
    payload: RelationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "docs")
    d = await _doc_or_404(db, cid, doc_id)
    await _assert_doc_permission(db, cid, d, current_user, "edit")
    target_doc = None
    if payload.target_ref.startswith("doc:"):
        target_doc = _uuid_or_400(payload.target_ref.split(":", 1)[1], "target_ref")
    dup = (await db.execute(select(DocRelation.id).where(
        DocRelation.company_id == cid, DocRelation.doc_id == d.id,
        DocRelation.kind == payload.kind,
        DocRelation.target_ref == payload.target_ref))).scalar_one_or_none()
    if dup is not None:
        return {"id": str(dup), "duplicate": True}
    r = DocRelation(company_id=cid, doc_id=d.id, kind=payload.kind,
                    target_ref=payload.target_ref, target_doc_id=target_doc,
                    created_by=current_user.id)
    db.add(r)
    db.add(DocEvent(doc_id=d.id, kind="relation", user_id=current_user.id,
                    actor_name=current_user.name or current_user.email,
                    to_value=payload.target_ref, note=payload.kind))
    await db.commit()
    await db.refresh(r)
    return {"id": str(r.id), "kind": r.kind, "target_ref": r.target_ref}


async def authorize_docs_file_download(db: AsyncSession, user: User,
                                       file_id: uuid.UUID) -> None:
    """Проверка доступа к файлу документа при скачивании по прямой ссылке.

    Членства в компании мало: закрытый документ виден только автору,
    ответственному и подписанту, а адрес файла легко переслать. Файлы вне «Дела»
    сюда не попадают — у них нет строки в `doc_versions`, и проверка их не
    касается.
    """
    rows = (await db.execute(select(DocVersion.doc_id).where(
        DocVersion.file_id == file_id))).scalars().all()
    if not rows:
        return
    docs = (await db.execute(select(DocCard).where(
        DocCard.id.in_(set(rows))))).scalars().all()
    if any([await _can_doc(db, d.company_id, d, user, "read") for d in docs]):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
