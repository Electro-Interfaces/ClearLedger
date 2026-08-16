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
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    Counterparty, DocApproval, DocCard, DocCase, DocEvent, DocKind, DocRelation,
    DocExchangeTarget, DocExport, DocInboxItem, DocLabelLink, DocShareLink,
    DocVersion, Organization, SourceFile, Task, TaskEvent, TaskLabel,
    TaskType, TaskWorkItem, User, UserCompany,
)
from app.routers import doc_share_router
from app.services import doc_approvals, doc_exchange, doc_print, file_store, mail_send
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


def _visible(d: DocCard, user: User) -> bool:
    """Закрытый документ виден автору, ответственному и подписанту.

    Полноценных прав уровня записи пока нет; это отсечка того же рода, что
    `visibility` у задачи, и на ней держится единственная защита от чужих глаз.
    """
    if d.confidentiality != "private":
        return True
    return user.is_superadmin or user.id in {d.author_id, d.responsible_id, d.signatory_id}


def _assert_visible(d: DocCard, user: User) -> None:
    if not _visible(d, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Документ закрыт")


def _card_out(d: DocCard, names: dict[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
    return {
        "id": str(d.id), "kind_id": str(d.kind_id), "kind_code": d.kind_code,
        "kind_name": names.get(str(d.kind_id), ""),
        "family": d.family, "direction": d.direction,
        "title": d.title, "summary": d.summary, "status": d.status,
        "reg_number": d.reg_number,
        "reg_date": d.reg_date.isoformat() if d.reg_date else None,
        "number_manual": d.number_manual,
        "organization_id": str(d.organization_id) if d.organization_id else None,
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
    fields: list[dict] = []
    # Маршрут согласования вида. Санитайзер оставляет только известные ключи:
    # иначе в JSONB копится то, что никто не читает, но все боятся удалить.
    route: list[dict] = []
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
        fields=payload.fields or None,
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
    k.fields = payload.fields or None
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
    limit: int = Query(200, ge=1, le=_LIST_LIMIT),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Реестр документов. Период считается по дате регистрации, а для
    незарегистрированных — по дате создания карточки: иначе черновики выпадают
    из любого отбора и теряются."""
    cid = await assert_company_product(company_id, current_user, db, "docs")
    stmt = select(DocCard).where(DocCard.company_id == cid)
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
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(DocCard.title.ilike(like),
                              DocCard.reg_number.ilike(like),
                              DocCard.external_number.ilike(like),
                              DocCard.counterparty_name.ilike(like)))
    stmt = stmt.order_by(DocCard.reg_date.desc().nullslast(),
                         DocCard.created_at.desc()).limit(limit)
    rows = [d for d in (await db.execute(stmt)).scalars().all()
            if _visible(d, current_user)]
    names = dict((await db.execute(select(DocKind.id, DocKind.name).where(
        DocKind.company_id == cid))).all())
    names = {str(k): v for k, v in names.items()}
    return {"docs": [_card_out(d, names) for d in rows], "count": len(rows)}


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
    attrs: dict = {}
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

    name = payload.counterparty_name.strip()
    if payload.counterparty_id and not name:
        name = (await db.execute(select(Counterparty.name).where(
            Counterparty.id == _uuid_or_400(payload.counterparty_id, "counterparty_id")
        ))).scalar_one_or_none() or ""

    d = DocCard(
        company_id=cid, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title=payload.title.strip(), summary=payload.summary,
        organization_id=_uuid_or_400(payload.organization_id, "organization_id")
        if payload.organization_id else None,
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
        attrs=payload.attrs or None, source=payload.source, source_ref=payload.source_ref)
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
    # Номер чужого документа вводят руками: он пришёл со своим, и выдавать ему наш
    # из счётчика нельзя — счётчик описывает наши документы.
    reg_number: str | None = None
    reg_date: date_type | None = None


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
    _assert_visible(d, current_user)
    if d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Документ уже зарегистрирован под номером {d.reg_number}")

    kind = await _kind_or_404(db, cid, d.kind_id)
    on_date = payload.reg_date or datetime.now(timezone.utc).date()

    if payload.reg_number:
        number = payload.reg_number.strip()
        d.number_manual = True
    else:
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
    d.registered_by = current_user.id
    if d.status == "draft":
        d.status = "registered"

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
                    to_value=number))
    await log_audit(db, actor=current_user, company_id=cid, action="doc.register",
                    target=number, details={"title": d.title[:200], "kind": kind.code})
    try:
        await db.commit()
    except Exception:
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
    _assert_visible(d, current_user)
    who = current_user.name or current_user.email

    if payload.status and payload.status != d.status:
        if d.status == "cancelled":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Отменённый документ не оживает: заведите новый")
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
    for field, value in simple.items():
        if value is None:
            continue
        old = getattr(d, field)
        if str(old or "") == str(value):
            continue
        setattr(d, field, value)
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
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=who, to_value=str(value or ""), note=field))

    # Объект сети опознаётся строковым ключом, поэтому идёт отдельно от полей-UUID.
    if payload.object_id is not None and d.object_id != (payload.object_id or None):
        d.object_id = payload.object_id or None
        db.add(DocEvent(doc_id=d.id, kind="field", user_id=current_user.id,
                        actor_name=who, to_value=payload.object_id or "", note="object_id"))

    if payload.due_at is not None:
        d.due_at = payload.due_at
    if payload.external_date is not None:
        d.external_date = payload.external_date
    if payload.attrs is not None:
        d.attrs = payload.attrs
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
    _assert_visible(d, current_user)
    if d.approval_status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Согласование уже идёт: дождитесь виз или отмените круг")

    kind = await db.get(DocKind, d.kind_id)
    route = payload.route if payload.route is not None else (kind.route if kind else None)
    res = await doc_approvals.start(db, cid, d, route or [], current_user)
    if "error" in res:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, res["error"])
    await db.commit()
    return res


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
    if row.assignee_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Визу ставит тот, кому она адресована")
    d = await _doc_or_404(db, cid, row.doc_id)
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
    rows = (await db.execute(select(DocApproval).where(
        DocApproval.company_id == cid, DocApproval.assignee_id == current_user.id,
        DocApproval.status == "pending").order_by(DocApproval.due_at.asc().nullslast())
    )).scalars().all()
    if not rows:
        return {"approvals": []}
    docs = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.id.in_({r.doc_id for r in rows})))).scalars().all()}
    return {"approvals": [{
        "id": str(r.id), "doc_id": str(r.doc_id),
        "step_name": r.step_name, "mode": r.mode,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "doc_title": docs[r.doc_id].title if r.doc_id in docs else "",
        "doc_number": docs[r.doc_id].reg_number if r.doc_id in docs else None,
    } for r in rows if r.doc_id in docs and _visible(docs[r.doc_id], current_user)]}


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
    _assert_visible(d, current_user)
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ: наружу уходит номер")

    link = DocShareLink(
        company_id=cid, doc_id=d.id, token=doc_share_router.new_token(),
        recipient_name=(payload.recipient_name or "").strip() or None,
        recipient_email=(payload.recipient_email or "").strip() or None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.days),
        created_by=current_user.id)
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
    _assert_visible(d, current_user)
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
    _assert_visible(d, current_user)
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
    if d.status == "registered":
        d.status = "in_force"
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
    _assert_visible(d, current_user)
    return HTMLResponse(await doc_print.render_card(db, d))


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
    _assert_visible(d, current_user)
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
    _assert_visible(d, current_user)
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
    docs = [d for d in (await db.execute(stmt.limit(_LIST_LIMIT))).scalars().all()
            if _visible(d, current_user)]
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
    dup = (await db.execute(select(DocExchangeTarget.id).where(
        DocExchangeTarget.company_id == cid,
        DocExchangeTarget.code == payload.code))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Точка с таким кодом уже есть")
    t = DocExchangeTarget(
        company_id=cid, code=payload.code, name=payload.name, system=payload.system,
        outbox_path=payload.outbox_path.strip(), inbox_path=payload.inbox_path.strip(),
        as_archive=payload.as_archive, is_active=payload.is_active, note=payload.note)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return {"id": str(t.id), "code": t.code, "name": t.name}


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
    _assert_visible(d, current_user)
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
    _assert_visible(d, current_user)
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
    _assert_visible(d, current_user)
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
    for t in targets:
        try:
            found = doc_exchange.scan_inbox(t)
            t.last_error = None
        except OSError as e:
            t.last_error = str(e)[:500]
            continue
        t.last_scan_at = datetime.now(timezone.utc)
        for item in found:
            dup = (await db.execute(select(DocInboxItem.id).where(
                DocInboxItem.company_id == cid,
                DocInboxItem.sha256 == item["sha256"]))).scalar_one_or_none()
            if dup is not None:
                continue
            sf = file_store.put(db, cid, item["data"],
                                file_name=item["file_name"], mime=None)
            await db.flush()
            db.add(DocInboxItem(
                company_id=cid, target_id=t.id, file_name=item["file_name"],
                source_path=item["source_path"], size_bytes=item["size"],
                sha256=item["sha256"], file_id=sf.id,
                parsed=item["parsed"] or None))
            added += 1
    await db.commit()
    return {"targets": len(targets), "added": added}


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
            db.add(DocVersion(
                company_id=cid, doc_id=d.id, revision=1, role="body",
                file_id=sf.id, file_name=sf.file_name, mime=sf.mime_type,
                size_bytes=sf.size or 0, sha256=item.sha256,
                author_id=current_user.id))
            d.has_files = True
            d.current_revision = 1

    item.status = "accepted"
    item.doc_id = d.id
    await db.commit()
    return {"status": "accepted", "doc_id": str(d.id)}


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
    _assert_visible(d, current_user)
    kind = await db.get(DocKind, d.kind_id)

    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == d.id, DocVersion.tombstoned_at.is_(None))
        .order_by(DocVersion.role, DocVersion.revision.desc()))).scalars().all()
    events = (await db.execute(select(DocEvent).where(DocEvent.doc_id == d.id)
                               .order_by(DocEvent.created_at.desc()).limit(200))).scalars().all()
    relations = (await db.execute(select(DocRelation).where(
        DocRelation.doc_id == d.id))).scalars().all()
    approvals = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == d.id).order_by(
        DocApproval.round.desc(), DocApproval.step_no))).scalars().all()
    live = [a for a in approvals if a.round == d.approval_round]

    return {
        **_card_out(d, {str(kind.id): kind.name} if kind else None),
        "kind": _kind_out(kind) if kind else None,
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
        # Кого именно ждут — то, чего не показывают гибриды рынка: там видно
        # «идёт согласование», но не видно, на ком оно стоит.
        "approval": {
            "status": d.approval_status, "round": d.approval_round,
            "steps": doc_approvals.progress(live),
            "rows": [{
                "id": str(a.id), "round": a.round, "step_no": a.step_no,
                "step_name": a.step_name, "status": a.status,
                "assignee_id": str(a.assignee_id) if a.assignee_id else None,
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
    _assert_visible(d, current_user)

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

    sf = file_store.put(db, cid, content, file_name=file.filename or "файл", mime=mime)
    await db.flush()
    v = DocVersion(
        company_id=cid, doc_id=d.id, revision=(last.revision + 1) if last else 1,
        role=role, file_id=sf.id, file_name=sf.file_name, mime=mime,
        size_bytes=len(content), sha256=digest, title=title,
        supersedes_id=last.id if last else None, author_id=current_user.id)
    if last is not None:
        last.is_current = False
    db.add(v)
    d.has_files = True
    if role == "body":
        d.current_revision = v.revision
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
    _assert_visible(d, current_user)
    v.tombstoned_at = datetime.now(timezone.utc)
    v.tombstoned_by = current_user.id
    v.tombstone_reason = payload.reason
    v.is_current = False
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
    _assert_visible(d, current_user)
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
    _assert_visible(d, current_user)
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
    if any(_visible(d, user) for d in docs):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")
