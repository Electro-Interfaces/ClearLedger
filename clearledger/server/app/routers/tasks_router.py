"""
Приложение «Задачи» — работа компании внутри пространства (docs/TASKS.md
репозитория ecosystem-deploy).

Отличие от «Заявок»: заявка описывает поломку у заявителя и живёт в контуре
Поддержки со своим SLA и внешними сторонами; задача — внутренняя работа, её
ставят люди пространства друг другу. Движок здесь свой, в схеме `core`: тип
задачи несёт маршрут (упорядоченные стадии), задача идёт по нему и в любой
момент может быть переадресована.

Все действия над задачей — одной ручкой `/tasks/{id}/action`: смена стадии,
переадресация, завершение и реплика различаются только тем, какие поля
пришли. Одна точка = одна проверка прав и один способ записать след.
"""
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, delete as sa_delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_company_by_api_key, get_current_user
from app.database import get_db
from app.models import (
    Company, ServiceLocation, SourceFile, Task, TaskAttachment, TaskChecklistItem,
    TaskEvent, TaskExternalRef, TaskLabel, TaskLabelLink, TaskLink, TaskParticipant,
    TaskType, TaskWatcher, User, UserCompany,
)
from app.services import space_connectors, task_mail

router = APIRouter(prefix="/tasks", tags=["Задачи"])

_LIST_LIMIT = 500
_PRIORITY = "^(low|medium|high|critical)$"
# Виды связи. `subtask`: task_id — родитель, related_task_id — подзадача.
_LINK_KINDS = ("subtask", "blocks", "relates", "duplicates")
# Порядок срочности для сортировки: в базе это строка, а человек ждёт «сначала
# критичные». Сортировать по алфавиту (critical, high, low, medium) — бессмыслица.
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Маршрут задачи без типа — обычное поручение. Держим в коде, а не в справочнике:
# иначе продукт не работает до заведения первого типа, а первое, что делает человек
# в новом продукте, — ставит задачу, а не настраивает справочники.
DEFAULT_ROUTE: list[dict] = [
    {"code": "new", "name": "Постановка"},
    {"code": "in_progress", "name": "В работе"},
    {"code": "review", "name": "Проверка"},
]

# Заготовки типов: то, что встречается в любой компании. Заводятся кнопкой из
# раздела «Типы» — руками, а не молча при первом запросе: справочник компании
# создаёт человек и сразу видит, что появилось.
STARTER_TYPES: list[dict] = [
    {"code": "errand", "name": "Поручение", "due_days": 3, "sort_order": 10,
     "description": "Разовая работа с исполнителем и сроком",
     "route": DEFAULT_ROUTE},
    {"code": "approval", "name": "Согласование", "due_days": 5, "sort_order": 20,
     "description": "Документ или решение проходит круг согласующих",
     "route": [{"code": "draft", "name": "Подготовка"},
               {"code": "review", "name": "На согласовании"},
               {"code": "approve", "name": "Утверждение"}]},
    {"code": "incident", "name": "Инцидент", "due_days": 1, "sort_order": 30,
     "default_priority": "high",
     "description": "Что-то сломалось и мешает работе",
     "route": [{"code": "reg", "name": "Регистрация"},
               {"code": "diag", "name": "Диагностика"},
               {"code": "fix", "name": "Устранение"},
               {"code": "check", "name": "Проверка"}]},
]


def _uuid_or_400(v: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Невалидный {what}")


def _route_of(t: TaskType | None) -> list[dict]:
    """Маршрут типа; у задачи без типа — маршрут поручения."""
    if t is None or not t.route:
        return DEFAULT_ROUTE
    stages = [s for s in t.route if isinstance(s, dict) and s.get("code")]
    return stages or DEFAULT_ROUTE


def _stage_name(route: list[dict], code: str | None) -> str | None:
    if code is None:
        return None
    return next((s.get("name") for s in route if s.get("code") == code), code)


def _type_out(t: TaskType) -> dict[str, Any]:
    return {
        "id": str(t.id), "code": t.code, "name": t.name, "description": t.description,
        "route": _route_of(t), "default_priority": t.default_priority,
        "due_days": t.due_days, "is_active": t.is_active, "sort_order": t.sort_order,
    }


def _task_out(t: Task, route: list[dict], names: dict[str, str | None],
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        **(extra or {}),
        "id": str(t.id),
        "number": t.number,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "stage": _stage_name(route, t.stage_code),
        "stage_code": t.stage_code,
        "route": route,
        "type": names.get("type"),
        "type_id": str(t.type_id) if t.type_id else None,
        "assignee": names.get("assignee"),
        "assignee_id": str(t.assignee_id) if t.assignee_id else None,
        "author": names.get("author"),
        "object": names.get("object"),
        "object_id": t.object_id,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "waiting_for": t.waiting_for,
        # Просрочка — свойство живой задачи: у закрытой срок уже не сигнал.
        "overdue": bool(t.due_at and t.status == "open" and t.due_at < now),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


async def _names(db: AsyncSession, tasks: list[Task]) -> dict[uuid.UUID, dict[str, str | None]]:
    """Имена типов, людей и объектов пачкой: список задач не должен ходить в базу
    построчно."""
    type_ids = {t.type_id for t in tasks if t.type_id}
    user_ids = {i for t in tasks for i in (t.assignee_id, t.author_id) if i}
    obj_ids = {t.object_id for t in tasks if t.object_id}
    types = {r.id: r for r in (await db.execute(
        select(TaskType).where(TaskType.id.in_(type_ids)))).scalars()} if type_ids else {}
    users = {r.id: r.name for r in (await db.execute(
        select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    objs = {r.id: r.name for r in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.id.in_(obj_ids)))).scalars()} if obj_ids else {}
    return {t.id: {
        "type": types[t.type_id].name if t.type_id in types else None,
        "route": _route_of(types.get(t.type_id)),
        "assignee": users.get(t.assignee_id),
        "author": users.get(t.author_id),
        "object": objs.get(t.object_id),
    } for t in tasks}


async def _extras(db: AsyncSession, tasks: list[Task]) -> dict[uuid.UUID, dict[str, Any]]:
    """Метки, прогресс чек-листа и число подзадач — пачкой на весь список.

    Это то, что видно прямо в строке списка: по галочкам «3 из 5» человек понимает,
    жива работа или стоит, не открывая карточку. Три запроса на страницу вместо
    трёх на строку.
    """
    if not tasks:
        return {}
    ids = [t.id for t in tasks]
    labels: dict[uuid.UUID, list[dict]] = {i: [] for i in ids}
    for tid, lid, name, color in (await db.execute(
        select(TaskLabelLink.task_id, TaskLabel.id, TaskLabel.name, TaskLabel.color)
        .join(TaskLabel, TaskLabel.id == TaskLabelLink.label_id)
        .where(TaskLabelLink.task_id.in_(ids)).order_by(TaskLabel.name))).all():
        labels[tid].append({"id": str(lid), "name": name, "color": color})

    check: dict[uuid.UUID, dict[str, int]] = {}
    for tid, total, done in (await db.execute(
        select(TaskChecklistItem.task_id, func.count(),
               func.count().filter(TaskChecklistItem.done.is_(True)))
        .where(TaskChecklistItem.task_id.in_(ids))
        .group_by(TaskChecklistItem.task_id))).all():
        check[tid] = {"total": total, "done": done}

    kids: dict[uuid.UUID, dict[str, int]] = {}
    for tid, total, open_cnt in (await db.execute(
        select(TaskLink.task_id, func.count(),
               func.count().filter(Task.status == "open"))
        .join(Task, Task.id == TaskLink.related_task_id)
        .where(TaskLink.task_id.in_(ids), TaskLink.kind == "subtask")
        .group_by(TaskLink.task_id))).all():
        kids[tid] = {"total": total, "open": open_cnt}

    return {t.id: {
        "labels": labels.get(t.id, []),
        "checklist": check.get(t.id, {"total": 0, "done": 0}),
        "subtasks": kids.get(t.id, {"total": 0, "open": 0}),
    } for t in tasks}


async def _task_or_404(db: AsyncSession, cid: uuid.UUID, task_id: str) -> Task:
    t = await db.get(Task, _uuid_or_400(task_id, "task_id"))
    if t is None or t.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return t


async def _assert_actor(db: AsyncSession, cid: uuid.UUID, user: User, t: Task) -> None:
    """Право менять задачу: исполнитель, автор или администратор пространства.

    Работу двигает тот, у кого она в руках, — согласование каждого шага у
    постановщика убило бы смысл маршрута.
    """
    if user.is_superadmin or user.id in (t.assignee_id, t.author_id):
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Задача не ваша")


# Обратная сторона связи называется иначе: если А — родитель Б, то у Б это
# «родитель», а не «подзадача». Одна запись, два прочтения — вторую строку в
# таблицу не пишем, иначе связь придётся удалять в двух местах.
_LINK_MIRROR = {"subtask": "parent", "blocks": "blocked_by",
                "relates": "relates", "duplicates": "duplicated_by"}


async def _links_out(db: AsyncSession, t: Task) -> list[dict[str, Any]]:
    """Связи задачи в обе стороны — одним списком, как их видит человек."""
    out: list[dict[str, Any]] = []
    forward = (await db.execute(
        select(TaskLink, Task).join(Task, Task.id == TaskLink.related_task_id)
        .where(TaskLink.task_id == t.id))).all()
    backward = (await db.execute(
        select(TaskLink, Task).join(Task, Task.id == TaskLink.task_id)
        .where(TaskLink.related_task_id == t.id))).all()
    for link, other in forward:
        out.append({"id": str(link.id), "kind": link.kind, "task_id": str(other.id),
                    "number": other.number, "title": other.title, "status": other.status})
    for link, other in backward:
        out.append({"id": str(link.id), "kind": _LINK_MIRROR.get(link.kind, link.kind),
                    "task_id": str(other.id), "number": other.number,
                    "title": other.title, "status": other.status})
    return sorted(out, key=lambda r: (r["kind"], r["number"]))


_MENTION = re.compile(r"@([\w.-]{2,60})", re.UNICODE)


async def _watch_mentions(db: AsyncSession, cid: uuid.UUID, task: Task,
                          note: str | None, actor: User) -> list[tuple[str, str | None]]:
    """Упомянутые в реплике `@имя` попадают в наблюдатели.

    Имя ищем по началу слова: люди пишут «@Петров», а в реестре «Петров Иван».
    Не нашли — молча пропускаем: упоминание не обязано быть ссылкой, человек мог
    просто написать адрес почты.
    """
    if not note:
        return []
    handles = {h.lower() for h in _MENTION.findall(note)}
    if not handles:
        return []
    people = (await db.execute(
        select(User.id, User.name, User.email).join(
            UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == cid))).all()
    added: list[tuple[str, str | None]] = []
    for uid, name, email in people:
        hay = f"{name or ''} {email or ''}".lower()
        if not any(hay.startswith(h) or f" {h}" in hay or (email or "").lower().startswith(h)
                   for h in handles):
            continue
        if await db.get(TaskWatcher, (task.id, uid)) is not None:
            continue
        db.add(TaskWatcher(task_id=task.id, user_id=uid, reason="mention", added_by=actor.id))
        added.append((name or str(uid), email))
    return added


@router.get("")
async def list_tasks(
    company_id: str = Query(...),
    scope: str = Query("open", pattern="^(open|mine|assigned|watching|overdue|today|waiting|closed|all)$"),
    object_id: str | None = Query(None),
    type_id: str | None = Query(None),
    assignee_id: str | None = Query(None),
    author_id: str | None = Query(None),
    stage: str | None = Query(None),
    priority: str | None = Query(None, pattern=_PRIORITY),
    label_id: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    due_from: datetime | None = Query(None),
    due_to: datetime | None = Query(None),
    sort: str = Query("created", pattern="^-?(created|updated|due|priority|number)$"),
    limit: int = Query(100, ge=1, le=_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Задачи пространства.

    scope — крупный разрез рабочего места: mine — что на мне (я исполнитель),
    assigned — что я поручил другим, watching — где я наблюдатель, today — что
    горит сегодня (просрочено, срок сегодня-завтра), open/closed/all/overdue —
    состояние. Остальное — фильтры реестра; они складываются со scope.
    """
    cid = await assert_company_product(company_id, current_user, db, "plan")
    now = datetime.now(timezone.utc)
    sel = select(Task).where(Task.company_id == cid)

    if scope == "open":
        sel = sel.where(Task.status == "open")
    elif scope == "closed":
        sel = sel.where(Task.status != "open")
    elif scope == "mine":
        # «На мне» — именно исполнение. Автор своей задачи её не делает: смешав
        # их, экран исполнителя показывал бы чужую работу и терял смысл счётчика.
        # Отданное наружу тоже уходит: пока ждём подрядчика, работа не на мне —
        # иначе список «что делать» наполняется тем, что делать сейчас нельзя.
        sel = sel.where(Task.status == "open", Task.assignee_id == current_user.id,
                        or_(Task.waiting_for.is_(None), Task.waiting_for != "external"))
    elif scope == "waiting":
        sel = sel.where(Task.status == "open", Task.waiting_for == "external")
    elif scope == "assigned":
        sel = sel.where(Task.status == "open", Task.author_id == current_user.id,
                        or_(Task.assignee_id.is_(None), Task.assignee_id != current_user.id))
    elif scope == "watching":
        sel = sel.where(Task.id.in_(
            select(TaskWatcher.task_id).where(TaskWatcher.user_id == current_user.id)))
    elif scope == "overdue":
        # Тот же смысл, что у флага `overdue` в выдаче: срок прошёл у ЖИВОЙ задачи.
        sel = sel.where(Task.status == "open", Task.due_at < now)
    elif scope == "today":
        # Что горит: просрочено или срок в ближайшие сутки. Без срока — не горит,
        # такая задача попадает в «На мне», а не в «Сегодня».
        sel = sel.where(Task.status == "open", Task.due_at.is_not(None),
                        Task.due_at < now + timedelta(days=1))

    if object_id:
        sel = sel.where(Task.object_id == object_id)
    if assignee_id:
        sel = sel.where(Task.assignee_id == _uuid_or_400(assignee_id, "assignee_id"))
    if author_id:
        sel = sel.where(Task.author_id == _uuid_or_400(author_id, "author_id"))
    if type_id:
        sel = sel.where(Task.type_id == _uuid_or_400(type_id, "type_id"))
    if stage:
        sel = sel.where(Task.stage_code == stage)
    if priority:
        sel = sel.where(Task.priority == priority)
    if label_id:
        sel = sel.where(Task.id.in_(select(TaskLabelLink.task_id).where(
            TaskLabelLink.label_id == _uuid_or_400(label_id, "label_id"))))
    if due_from:
        sel = sel.where(Task.due_at >= due_from)
    if due_to:
        sel = sel.where(Task.due_at <= due_to)
    if q and (text := q.strip()):
        # Номер ищем как номер: «123» и «№123» должны открывать задачу, а не
        # искать «123» в тексте — цифру в заголовке пишут редко, а номер называют
        # постоянно. Текст ищем и в репликах: половина ответов «где это обсуждали».
        digits = text.lstrip("№#").strip()
        like = f"%{text}%"
        conds = [Task.title.ilike(like), Task.description.ilike(like),
                 Task.id.in_(select(TaskEvent.task_id).where(TaskEvent.note.ilike(like)))]
        if digits.isdigit():
            conds.append(Task.number == int(digits))
        sel = sel.where(or_(*conds))

    total = (await db.execute(
        select(func.count()).select_from(sel.subquery()))).scalar_one()

    desc = sort.startswith("-")
    key = sort.lstrip("-")
    col = {"created": Task.created_at, "updated": Task.updated_at, "due": Task.due_at,
           "number": Task.number}.get(key)
    if key == "priority":
        order = case(_PRIORITY_RANK, value=Task.priority, else_=9)
        sel = sel.order_by(order.desc() if desc else order.asc(), Task.created_at.desc())
    else:
        col = col or Task.created_at
        # Срок по возрастанию: сначала ближайшие. Задачи без срока не должны
        # занимать голову списка, поэтому NULL уезжают в конец в обоих порядках.
        sel = sel.order_by(col.desc().nullslast() if desc or key == "created"
                           else col.asc().nullslast())

    tasks = list((await db.execute(sel.limit(limit).offset(offset))).scalars())
    names = await _names(db, tasks)
    extras = await _extras(db, tasks)
    return {
        "tasks": [_task_out(t, names[t.id]["route"], names[t.id], extras[t.id])
                  for t in tasks],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/people")
async def list_people(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кому можно поручить: члены пространства. Своя ручка, а не `/users` — тот
    список админский (роли, модули, скоуп), а переадресовать задачу должен уметь
    любой исполнитель, не только администратор."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    rows = (await db.execute(
        select(User.id, User.name, User.email)
        .join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == cid)
        .order_by(User.name))).all()
    return {"people": [{"id": str(i), "name": n or (e or "—")} for i, n, e in rows]}


# ── Типы задач и маршруты ────────────────────────────────────────────────


@router.get("/types")
async def list_types(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    rows = (await db.execute(select(TaskType).where(TaskType.company_id == cid)
                             .order_by(TaskType.sort_order, TaskType.name))).scalars().all()
    return {"types": [_type_out(t) for t in rows], "default_route": DEFAULT_ROUTE}


class TypeIn(BaseModel):
    company_id: str
    code: str = Field(min_length=2, max_length=40, pattern="^[a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(None, max_length=500)
    # [{"code","name"}] — порядок стадий и есть маршрут.
    route: list[dict] = Field(default_factory=list)
    default_priority: str = Field("medium", pattern=_PRIORITY)
    due_days: int | None = Field(None, ge=0, le=365)
    is_active: bool = True
    sort_order: int = 100


def _clean_route(route: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in route:
        code = str(s.get("code") or "").strip()[:40]
        name = str(s.get("name") or "").strip()[:120]
        if code and name and code not in [x["code"] for x in out]:
            out.append({"code": code, "name": name})
    return out


async def _assert_admin(db: AsyncSession, cid: uuid.UUID, user: User) -> None:
    """Справочник типов правит тот, кто отвечает за правила: админ пространства.
    Исполнитель может двигать свою задачу, но не менять маршрут для всех."""
    if user.is_superadmin:
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Типы задач правит администратор пространства")


@router.post("/types", status_code=status.HTTP_201_CREATED)
async def create_type(
    payload: TypeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    await _assert_admin(db, cid, current_user)
    exists = (await db.execute(select(TaskType).where(
        TaskType.company_id == cid, TaskType.code == payload.code))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Тип с таким кодом уже есть")
    t = TaskType(
        company_id=cid, code=payload.code, name=payload.name,
        description=payload.description, route=_clean_route(payload.route),
        default_priority=payload.default_priority, due_days=payload.due_days,
        is_active=payload.is_active, sort_order=payload.sort_order)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _type_out(t)


@router.put("/types/{type_id}")
async def update_type(
    type_id: str,
    payload: TypeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    await _assert_admin(db, cid, current_user)
    t = await db.get(TaskType, _uuid_or_400(type_id, "type_id"))
    if t is None or t.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип не найден")
    t.name, t.description = payload.name, payload.description
    t.route = _clean_route(payload.route)
    t.default_priority, t.due_days = payload.default_priority, payload.due_days
    t.is_active, t.sort_order = payload.is_active, payload.sort_order
    await db.commit()
    await db.refresh(t)
    return _type_out(t)


@router.post("/types/starter", status_code=status.HTTP_201_CREATED)
async def create_starter_types(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести заготовки типов. Идемпотентно: уже существующие коды пропускаются,
    повторное нажатие не плодит дублей и не трогает правки компании."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    await _assert_admin(db, cid, current_user)
    have = {c for (c,) in (await db.execute(
        select(TaskType.code).where(TaskType.company_id == cid))).all()}
    added = 0
    for spec in STARTER_TYPES:
        if spec["code"] in have:
            continue
        db.add(TaskType(company_id=cid, **spec))
        added += 1
    await db.commit()
    return {"added": added}


# ── Постановка и работа ──────────────────────────────────────────────────


class TaskIn(BaseModel):
    company_id: str
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(None, max_length=8000)
    type_id: str | None = None
    assignee_id: str | None = None
    object_id: str | None = None
    priority: str | None = Field(None, pattern=_PRIORITY)
    due_at: datetime | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Поставить задачу. Тип задаёт маршрут, срочность и срок по умолчанию —
    поставивший может их перебить, но не обязан ничего знать о маршруте."""
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    ttype = None
    if payload.type_id:
        ttype = await db.get(TaskType, _uuid_or_400(payload.type_id, "type_id"))
        if ttype is None or ttype.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный тип задачи")
    route = _route_of(ttype)
    due = payload.due_at
    if due is None and ttype is not None and ttype.due_days is not None:
        due = datetime.now(timezone.utc) + timedelta(days=ttype.due_days)
    assignee = _uuid_or_400(payload.assignee_id, "assignee_id") if payload.assignee_id else None
    if assignee is not None and await db.get(UserCompany, (assignee, cid)) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Исполнитель не состоит в пространстве")

    t = Task(
        company_id=cid, type_id=ttype.id if ttype else None,
        title=payload.title.strip(), description=payload.description,
        priority=payload.priority or (ttype.default_priority if ttype else "medium"),
        status="open", stage_code=route[0]["code"],
        assignee_id=assignee, author_id=current_user.id,
        object_id=payload.object_id or None, due_at=due)
    db.add(t)
    await db.flush()
    db.add(TaskEvent(task_id=t.id, kind="created", user_id=current_user.id,
                     to_value=_stage_name(route, t.stage_code)))
    person = await db.get(User, assignee) if assignee is not None else None
    if person is not None:
        db.add(TaskEvent(task_id=t.id, kind="assign", user_id=current_user.id,
                         to_value=person.name))
    await db.commit()
    await db.refresh(t)
    # Поручение письмом: человек узнаёт о задаче, не заходя в систему. Себе не
    # пишем — тот, кто поставил задачу на себя, о ней уже знает.
    if person is not None and person.id != current_user.id and person.email:
        task_mail.send_notice_async(
            [person.email], f"Вам поручена задача №{t.number}: {t.title}",
            _errand_text(t, current_user, None))
    names = await _names(db, [t])
    extras = await _extras(db, [t])
    return _task_out(t, route, names[t.id], extras[t.id])


# ВНИМАНИЕ: `/summary` объявлен ДО `/{task_id}` — иначе FastAPI разберёт «summary»
# как идентификатор задачи и ручка ответит 400 «Невалидный task_id».
@router.get("/summary")
async def tasks_summary(
    company_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обзор работы: сколько в работе и просрочено, кто чем занят, что происходило.

    Это ответ на вопрос руководителя, а не второй список задач: разрезы по людям,
    типам и объектам плюс лента следа — кто что сделал за период.

    Считаем в Python по выборке, а не SQL-агрегатами: разрезов четыре, и каждый
    отдельным `group_by` — четыре похода в базу вместо одного. Потолок понятный —
    задач в пространстве сотни; на десятках тысяч разрезы уедут в SQL.
    """
    cid = await assert_company_product(company_id, current_user, db, "plan")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    # Живые задачи целиком плюс закрытые за период: закрытые год назад в обзоре
    # не нужны, а «в работе» нужны все — просрочка не обязана попадать в окно.
    tasks = list((await db.execute(select(Task).where(
        Task.company_id == cid,
        or_(Task.status == "open", Task.closed_at >= since),
    ))).scalars())
    names = await _names(db, tasks)

    open_t = [t for t in tasks if t.status == "open"]
    closed_t = [t for t in tasks if t.status != "open" and t.closed_at]
    overdue = [t for t in open_t if t.due_at and t.due_at < now]
    created_period = [t for t in tasks if t.created_at and t.created_at >= since]
    # Среднее время прохождения — по закрытым за период: столько работа реально идёт
    # от постановки до завершения. Медиану не берём — на десятке задач она врёт сильнее.
    durations = [(t.closed_at - t.created_at).total_seconds() / 86400
                 for t in closed_t if t.created_at]
    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    def cut(key) -> list[dict]:
        """Разрез: сколько в работе, просрочено и закрыто за период.

        `key` отдаёт пару (id, имя): по id из разреза проваливаются в список
        (`/tasks?assignee=…`), поэтому одного имени тут мало."""
        acc: dict[str, dict] = {}
        for t in tasks:
            k, label = key(t)
            row = acc.setdefault(k or "—", {
                "id": k, "name": label or "—", "open": 0, "overdue": 0, "done": 0})
            if t.status == "open":
                row["open"] += 1
                if t.due_at and t.due_at < now:
                    row["overdue"] += 1
            else:
                row["done"] += 1
        return sorted(acc.values(), key=lambda r: (-r["open"], -r["done"], r["name"]))

    events = (await db.execute(
        select(TaskEvent, Task.number, Task.title)
        .join(Task, Task.id == TaskEvent.task_id)
        .where(Task.company_id == cid, TaskEvent.created_at >= since)
        .order_by(TaskEvent.created_at.desc()).limit(60))).all()
    actors = {r.id: r.name for r in (await db.execute(select(User).where(
        User.id.in_({e.user_id for e, _, _ in events if e.user_id})))).scalars()} if events else {}

    return {
        "days": days,
        "totals": {
            "open": len(open_t),
            "overdue": len(overdue),
            "mine": sum(1 for t in open_t if current_user.id in (t.assignee_id, t.author_id)),
            "unassigned": sum(1 for t in open_t if t.assignee_id is None),
            "created": len(created_period),
            "done": len(closed_t),
            "avg_days": avg_days,
        },
        "by_assignee": cut(lambda t: (
            str(t.assignee_id) if t.assignee_id else None, names[t.id]["assignee"])),
        "by_type": cut(lambda t: (
            str(t.type_id) if t.type_id else None, names[t.id]["type"] or "без типа")),
        "by_object": [r for r in cut(lambda t: (t.object_id, names[t.id]["object"]))
                      if r["id"]],
        "activity": [{
            "id": str(e.id), "kind": e.kind, "user": actors.get(e.user_id),
            "task_id": str(e.task_id), "number": num, "title": title,
            "from": e.from_value, "to": e.to_value, "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e, num, title in events],
    }


# ── Метки компании ───────────────────────────────────────────────────────
# ВНИМАНИЕ: `/labels` и `/attachments/…` объявлены ДО `/{task_id}` — иначе FastAPI
# разберёт «labels» как идентификатор задачи (та же грабля, что у `/summary`).


@router.get("/labels")
async def list_labels(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    rows = (await db.execute(select(TaskLabel).where(TaskLabel.company_id == cid)
                             .order_by(TaskLabel.name))).scalars().all()
    return {"labels": [{"id": str(r.id), "name": r.name, "color": r.color} for r in rows]}


class LabelIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=60)
    color: str = Field("slate", pattern="^[a-z]{3,20}$")


@router.post("/labels", status_code=status.HTTP_201_CREATED)
async def create_label(
    payload: LabelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести метку. Метку заводит любой участник: ярлык — рабочий инструмент,
    а не элемент регламента, и поход к администратору за ним никто не сделает."""
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    name = payload.name.strip()
    exists = (await db.execute(select(TaskLabel).where(
        TaskLabel.company_id == cid, TaskLabel.name == name))).scalar_one_or_none()
    if exists is not None:
        return {"id": str(exists.id), "name": exists.name, "color": exists.color}
    lab = TaskLabel(company_id=cid, name=name, color=payload.color)
    db.add(lab)
    await db.commit()
    await db.refresh(lab)
    return {"id": str(lab.id), "name": lab.name, "color": lab.color}


@router.delete("/labels/{label_id}")
async def delete_label(
    label_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    await _assert_admin(db, cid, current_user)
    lab = await db.get(TaskLabel, _uuid_or_400(label_id, "label_id"))
    if lab is None or lab.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Метка не найдена")
    await db.delete(lab)
    await db.commit()
    return {"deleted": label_id}


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отдать файл вложения. Проверяем не сам файл, а задачу, к которой он привязан:
    доступ к файлу — это доступ к работе, в которой он лежит."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    att = await db.get(TaskAttachment, _uuid_or_400(attachment_id, "attachment_id"))
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение не найдено")
    task = await db.get(Task, att.task_id)
    if task is None or task.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение не найдено")
    sf = await db.get(SourceFile, att.file_id)
    if sf is None or not Path(sf.storage_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл потерян в хранилище")
    return FileResponse(sf.storage_path, media_type=sf.mime_type or "application/octet-stream",
                        filename=sf.file_name)


@router.get("/{task_id}")
async def task_details(
    task_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка задачи: поля, маршрут, лента и всё, что к работе прицеплено."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    names = await _names(db, [t])
    extras = await _extras(db, [t])
    events = (await db.execute(
        select(TaskEvent).where(TaskEvent.task_id == t.id)
        .order_by(TaskEvent.created_at))).scalars().all()
    actors = {r.id: r.name for r in (await db.execute(select(User).where(
        User.id.in_({e.user_id for e in events if e.user_id})))).scalars()} if events else {}

    checklist = (await db.execute(
        select(TaskChecklistItem).where(TaskChecklistItem.task_id == t.id)
        .order_by(TaskChecklistItem.position, TaskChecklistItem.created_at))).scalars().all()
    watchers = (await db.execute(
        select(TaskWatcher, User.name).join(User, User.id == TaskWatcher.user_id)
        .where(TaskWatcher.task_id == t.id).order_by(User.name))).all()
    attachments = (await db.execute(
        select(TaskAttachment, SourceFile)
        .join(SourceFile, SourceFile.id == TaskAttachment.file_id)
        .where(TaskAttachment.task_id == t.id)
        .order_by(TaskAttachment.created_at))).all()
    externals = (await db.execute(
        select(TaskExternalRef).where(TaskExternalRef.task_id == t.id)
        .order_by(TaskExternalRef.created_at))).scalars().all()
    participants = (await db.execute(
        select(TaskParticipant, User.name, User.email)
        .join(User, User.id == TaskParticipant.user_id)
        .where(TaskParticipant.task_id == t.id)
        .order_by(TaskParticipant.created_at))).all()

    return {
        **_task_out(t, names[t.id]["route"], names[t.id], extras[t.id]),
        "description": t.description,
        "events": [{
            "id": str(e.id), "kind": e.kind,
            # Имя из письма важнее имени учётки: подпись под репликой должна
            # совпадать с тем, как человек представился в почте.
            "user": e.actor_name or actors.get(e.user_id),
            "from": e.from_value, "to": e.to_value, "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
        "participants": [{
            "user_id": str(p.user_id), "name": n, "email": mail,
            "role": p.role, "channel": p.channel, "channel_ref": p.channel_ref,
        } for p, n, mail in participants],
        "reply_address": task_mail.reply_address(t.number) if task_mail.enabled() else None,
        "external": [_ref_out(r) for r in externals],
        # Пункты — отдельным именем: `checklist` уже занят прогрессом «3 из 5»,
        # который едет и в строку списка. Одно имя под два разных типа заставило
        # бы фронт гадать, что пришло.
        "checklist_items": [{
            "id": str(c.id), "text": c.text, "done": c.done, "position": c.position,
            "done_at": c.done_at.isoformat() if c.done_at else None,
        } for c in checklist],
        "watchers": [{"user_id": str(w.user_id), "name": n, "reason": w.reason}
                     for w, n in watchers],
        "attachments": [{
            "id": str(a.id), "event_id": str(a.event_id) if a.event_id else None,
            "file_name": sf.file_name, "mime_type": sf.mime_type, "size": sf.size,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a, sf in attachments],
        "links": await _links_out(db, t),
    }


class TaskAction(BaseModel):
    company_id: str
    stage_code: str | None = None          # перевести на стадию маршрута
    assignee_id: str | None = None         # переадресовать (пустая строка — снять)
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    priority: str | None = Field(None, pattern=_PRIORITY)
    due_at: datetime | None = None
    note: str | None = Field(None, max_length=2000)   # реплика в след задачи
    title: str | None = Field(None, min_length=3, max_length=300)
    description: str | None = Field(None, max_length=8000)
    object_id: str | None = None
    add_label_id: str | None = None
    remove_label_id: str | None = None


@router.post("/{task_id}/action")
async def task_action(
    task_id: str,
    payload: TaskAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Движение по маршруту, переадресация, завершение и реплика — одной ручкой.

    Право на действие: исполнитель, автор или администратор пространства. Работу
    двигает тот, у кого она в руках, — согласование каждого шага у постановщика
    убило бы смысл маршрута.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)

    ttype = await db.get(TaskType, t.type_id) if t.type_id else None
    route = _route_of(ttype)
    logged = False   # записалось ли событие, к которому реплика уже прицеплена

    if payload.stage_code is not None:
        if payload.stage_code not in [s["code"] for s in route]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Стадии нет в маршруте типа")
        if payload.stage_code != t.stage_code:
            db.add(TaskEvent(task_id=t.id, kind="stage", user_id=current_user.id,
                             from_value=_stage_name(route, t.stage_code),
                             to_value=_stage_name(route, payload.stage_code),
                             note=payload.note))
            t.stage_code = payload.stage_code
            logged = True

    new_assignee_email: str | None = None
    if payload.assignee_id is not None:
        new_id = _uuid_or_400(payload.assignee_id, "assignee_id") if payload.assignee_id else None
        if new_id is not None and await db.get(UserCompany, (new_id, cid)) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Исполнитель не состоит в пространстве")
        if new_id != t.assignee_id:
            was = (await db.get(User, t.assignee_id)).name if t.assignee_id else None
            new_person = await db.get(User, new_id) if new_id else None
            now_name = new_person.name if new_person else None
            # Себе письмо не шлём: человек только что нажал кнопку и всё видит.
            if new_person is not None and new_person.id != current_user.id:
                new_assignee_email = new_person.email
            db.add(TaskEvent(task_id=t.id, kind="assign", user_id=current_user.id,
                             from_value=was, to_value=now_name, note=payload.note))
            t.assignee_id = new_id
            logged = True

    if payload.status is not None and payload.status != t.status:
        db.add(TaskEvent(task_id=t.id, kind="status", user_id=current_user.id,
                         from_value=t.status, to_value=payload.status, note=payload.note))
        t.status = payload.status
        logged = True
        t.closed_at = None if payload.status == "open" else datetime.now(timezone.utc)

    if payload.priority is not None:
        t.priority = payload.priority
    if payload.due_at is not None:
        t.due_at = payload.due_at
    if payload.title is not None:
        t.title = payload.title.strip()
    if payload.description is not None:
        t.description = payload.description or None
    if payload.object_id is not None:
        t.object_id = payload.object_id or None

    if payload.add_label_id:
        lid = _uuid_or_400(payload.add_label_id, "add_label_id")
        lab = await db.get(TaskLabel, lid)
        if lab is None or lab.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Метка не найдена")
        if await db.get(TaskLabelLink, (t.id, lid)) is None:
            db.add(TaskLabelLink(task_id=t.id, label_id=lid))
    if payload.remove_label_id:
        await db.execute(sa_delete(TaskLabelLink).where(
            TaskLabelLink.task_id == t.id,
            TaskLabelLink.label_id == _uuid_or_400(payload.remove_label_id, "remove_label_id")))

    # Реплика без других изменений — комментарий; вместе с ними она уже записана
    # примечанием к событию и второй раз в ленту не идёт. Считаем по факту записи,
    # а не по составу запроса: перевод на ТЕКУЩУЮ стадию событием не становится, и
    # реплика при нём иначе пропала бы молча.
    if payload.note and not logged:
        db.add(TaskEvent(task_id=t.id, kind="comment", user_id=current_user.id,
                         note=payload.note))
    mentioned = await _watch_mentions(db, cid, t, payload.note, current_user)

    await db.commit()
    await db.refresh(t)
    names = await _names(db, [t])
    extras = await _extras(db, [t])
    out = _task_out(t, route, names[t.id], extras[t.id])
    # Закрыть родителя с живыми подзадачами можно, но человек должен об этом
    # узнать: запрет здесь мешал бы работать (подзадачу могли завести «на потом»),
    # а молчание превращало бы дерево в свалку незакрытых хвостов.
    if payload.status in ("done", "cancelled") and out["subtasks"]["open"]:
        out["warning"] = f"У задачи осталось открытых подзадач: {out['subtasks']['open']}"
    if mentioned:
        out["mentioned"] = [n for n, _ in mentioned]
        task_mail.send_notice_async(
            [e for _, e in mentioned if e],
            f"Вас упомянули в задаче №{t.number}: {t.title}",
            f"{current_user.name or 'Коллега'} написал:\n\n{payload.note or ''}")
    if new_assignee_email:
        task_mail.send_notice_async(
            [new_assignee_email], f"Вам поручена задача №{t.number}: {t.title}",
            _errand_text(t, current_user, payload.note))
    return out


def _errand_text(t: Task, author: User, note: str | None) -> str:
    """Письмо «вам поручено»: что, к какому сроку и от кого."""
    lines = [f"Задача №{t.number}: {t.title}",
             f"Поручил: {author.name or 'коллега'}"]
    if t.due_at:
        lines.append(f"Срок: {t.due_at.strftime('%d.%m.%Y')}")
    if note:
        lines += ["", note]
    if t.description:
        lines += ["", t.description]
    return "\n".join(lines)


class BulkAction(BaseModel):
    company_id: str
    task_ids: list[str] = Field(min_length=1, max_length=200)
    assignee_id: str | None = None
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    priority: str | None = Field(None, pattern=_PRIORITY)
    due_at: datetime | None = None
    stage_code: str | None = None
    note: str | None = Field(None, max_length=2000)


@router.post("/bulk")
async def bulk_action(
    payload: BulkAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """То же действие над несколькими задачами.

    Контракт тот же, что у `/action`, и след пишется каждой задаче отдельно: массовая
    правка не должна выглядеть в ленте иначе, чем ручная. Задачи, на которые нет
    права, пропускаются с перечислением — падать целиком из-за одной чужой строки
    значит заставить человека вычислять её вручную.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    done, skipped = 0, []
    for raw in payload.task_ids:
        t = await db.get(Task, _uuid_or_400(raw, "task_id"))
        if t is None or t.company_id != cid:
            skipped.append(raw)
            continue
        try:
            await _assert_actor(db, cid, current_user, t)
        except HTTPException:
            skipped.append(f"№{t.number}")
            continue
        route = _route_of(await db.get(TaskType, t.type_id) if t.type_id else None)
        if payload.stage_code and payload.stage_code in [s["code"] for s in route] \
                and payload.stage_code != t.stage_code:
            db.add(TaskEvent(task_id=t.id, kind="stage", user_id=current_user.id,
                             from_value=_stage_name(route, t.stage_code),
                             to_value=_stage_name(route, payload.stage_code),
                             note=payload.note))
            t.stage_code = payload.stage_code
        if payload.assignee_id is not None:
            new_id = _uuid_or_400(payload.assignee_id, "assignee_id") if payload.assignee_id else None
            if new_id is not None and await db.get(UserCompany, (new_id, cid)) is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Исполнитель не состоит в пространстве")
            if new_id != t.assignee_id:
                was = (await db.get(User, t.assignee_id)).name if t.assignee_id else None
                now_name = (await db.get(User, new_id)).name if new_id else None
                db.add(TaskEvent(task_id=t.id, kind="assign", user_id=current_user.id,
                                 from_value=was, to_value=now_name, note=payload.note))
                t.assignee_id = new_id
        if payload.status is not None and payload.status != t.status:
            db.add(TaskEvent(task_id=t.id, kind="status", user_id=current_user.id,
                             from_value=t.status, to_value=payload.status, note=payload.note))
            t.status = payload.status
            t.closed_at = None if payload.status == "open" else datetime.now(timezone.utc)
        if payload.priority is not None:
            t.priority = payload.priority
        if payload.due_at is not None:
            t.due_at = payload.due_at
        done += 1
    await db.commit()
    return {"changed": done, "skipped": skipped}


# ── Чек-лист ─────────────────────────────────────────────────────────────


class ChecklistIn(BaseModel):
    company_id: str
    text: str = Field(min_length=1, max_length=500)


@router.post("/{task_id}/checklist", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    task_id: str,
    payload: ChecklistIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    last = (await db.execute(select(func.coalesce(func.max(TaskChecklistItem.position), 0))
                             .where(TaskChecklistItem.task_id == t.id))).scalar_one()
    item = TaskChecklistItem(task_id=t.id, text=payload.text.strip(), position=last + 10)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": str(item.id), "text": item.text, "done": item.done, "position": item.position}


class ChecklistPatch(BaseModel):
    company_id: str
    done: bool | None = None
    text: str | None = Field(None, min_length=1, max_length=500)


@router.patch("/{task_id}/checklist/{item_id}")
async def update_checklist_item(
    task_id: str,
    item_id: str,
    payload: ChecklistPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отметить пункт или переписать его. Отметка не пишется в ленту событий:
    ход по чек-листу — это работа внутри одного шага, а не движение задачи, и
    двадцать записей «отметил пункт» утопили бы след."""
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    item = await db.get(TaskChecklistItem, _uuid_or_400(item_id, "item_id"))
    if item is None or item.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пункт не найден")
    if payload.text is not None:
        item.text = payload.text.strip()
    if payload.done is not None and payload.done != item.done:
        item.done = payload.done
        item.done_by = current_user.id if payload.done else None
        item.done_at = datetime.now(timezone.utc) if payload.done else None
    await db.commit()
    return {"id": str(item.id), "text": item.text, "done": item.done}


@router.delete("/{task_id}/checklist/{item_id}")
async def delete_checklist_item(
    task_id: str,
    item_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    item = await db.get(TaskChecklistItem, _uuid_or_400(item_id, "item_id"))
    if item is None or item.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пункт не найден")
    await db.delete(item)
    await db.commit()
    return {"deleted": item_id}


# ── Связи и подзадачи ────────────────────────────────────────────────────


class LinkIn(BaseModel):
    company_id: str
    related_task_id: str
    kind: str = Field("relates", pattern="^(subtask|blocks|relates|duplicates)$")


@router.post("/{task_id}/links", status_code=status.HTTP_201_CREATED)
async def add_link(
    task_id: str,
    payload: LinkIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Связать две задачи. Подзадача — та же связь вида `subtask`, где `task_id`
    родитель: отдельного дерева не заводим."""
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    other = await _task_or_404(db, cid, payload.related_task_id)
    if other.id == t.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Задачу нельзя связать с собой")
    # Круг из подзадач сделал бы дерево бесконечным при обходе; для остальных
    # видов связь в обе стороны законна («связана» симметрична по смыслу).
    if payload.kind == "subtask" and (await db.execute(select(TaskLink).where(
            TaskLink.task_id == other.id, TaskLink.related_task_id == t.id,
            TaskLink.kind == "subtask"))).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Эта задача уже родитель для выбранной")
    exists = (await db.execute(select(TaskLink).where(
        TaskLink.task_id == t.id, TaskLink.related_task_id == other.id,
        TaskLink.kind == payload.kind))).scalar_one_or_none()
    if exists is not None:
        return {"id": str(exists.id), "kind": exists.kind}
    link = TaskLink(task_id=t.id, related_task_id=other.id, kind=payload.kind,
                    created_by=current_user.id)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {"id": str(link.id), "kind": link.kind, "task_id": str(other.id),
            "number": other.number, "title": other.title, "status": other.status}


@router.delete("/{task_id}/links/{link_id}")
async def delete_link(
    task_id: str,
    link_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    link = await db.get(TaskLink, _uuid_or_400(link_id, "link_id"))
    # Связь снимается с любой из двух сторон: человек видит её в обеих карточках
    # и не обязан помнить, из которой её заводили.
    if link is None or t.id not in (link.task_id, link.related_task_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Связь не найдена")
    await db.delete(link)
    await db.commit()
    return {"deleted": link_id}


# ── Наблюдатели ──────────────────────────────────────────────────────────


class WatcherIn(BaseModel):
    company_id: str
    user_id: str | None = None      # пусто — подписать себя


@router.post("/{task_id}/watchers", status_code=status.HTTP_201_CREATED)
async def add_watcher(
    task_id: str,
    payload: WatcherIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Подписаться на задачу или добавить наблюдателя. Подписать себя может любой,
    кто видит задачу: следить за чужой работой — не привилегия."""
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    uid = _uuid_or_400(payload.user_id, "user_id") if payload.user_id else current_user.id
    if uid != current_user.id:
        await _assert_actor(db, cid, current_user, t)
        if await db.get(UserCompany, (uid, cid)) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Человек не состоит в пространстве")
    if await db.get(TaskWatcher, (t.id, uid)) is None:
        db.add(TaskWatcher(task_id=t.id, user_id=uid,
                           reason="manual", added_by=current_user.id))
        await db.commit()
    return {"task_id": str(t.id), "user_id": str(uid)}


@router.delete("/{task_id}/watchers/{user_id}")
async def delete_watcher(
    task_id: str,
    user_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    uid = _uuid_or_400(user_id, "user_id")
    if uid != current_user.id:
        await _assert_actor(db, cid, current_user, t)
    w = await db.get(TaskWatcher, (t.id, uid))
    if w is not None:
        await db.delete(w)
        await db.commit()
    return {"deleted": user_id}


# ── Вложения ─────────────────────────────────────────────────────────────


@router.post("/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    task_id: str,
    company_id: str = Query(...),
    event_id: str | None = Query(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Приложить файл к задаче или к реплике. Хранение общее с остальными файлами
    Ядра: запись в `source_files`, сам файл в `UPLOAD_DIR` (как у документов проекта)."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")

    file_id = uuid.uuid4()
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{file_id}{Path(file.filename or 'file').suffix}"
    with open(path, "wb") as fh:
        fh.write(content)
    db.add(SourceFile(
        id=file_id, company_id=cid, file_name=file.filename or "файл",
        mime_type=file.content_type or "application/octet-stream", size=len(content),
        storage_path=str(path), fingerprint=hashlib.sha256(content).hexdigest()))
    att = TaskAttachment(
        task_id=t.id, file_id=file_id, uploaded_by=current_user.id,
        event_id=_uuid_or_400(event_id, "event_id") if event_id else None)
    db.add(att)
    await db.commit()
    await db.refresh(att)
    return {"id": str(att.id), "file_name": file.filename, "size": len(content)}


@router.delete("/{task_id}/attachments/{attachment_id}")
async def delete_attachment(
    task_id: str,
    attachment_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отцепить файл от задачи. Сам файл в хранилище остаётся: на него может
    ссылаться другая запись, а чистка хранилища — отдельная работа."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    att = await db.get(TaskAttachment, _uuid_or_400(attachment_id, "attachment_id"))
    if att is None or att.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение не найдено")
    await db.delete(att)
    await db.commit()
    return {"deleted": attachment_id}


# ── Внешние участники: разговор почтой ───────────────────────────────────


class DelegateIn(BaseModel):
    company_id: str
    email: str = Field(min_length=5, max_length=200)
    name: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=2000)
    organization_id: str | None = None


@router.post("/{task_id}/delegate", status_code=status.HTTP_201_CREATED)
async def delegate_task(
    task_id: str,
    payload: DelegateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Поручить задачу тому, кто в пространство не заходит.

    Человек получает письмо с адресом ответа `ящик+t<номер>@домен`; его ответ
    вернётся в ленту репликой с пометкой «письмом». В пространстве он заводится
    почтовой учёткой (`users.mail_only`) — войти ею нельзя, она нужна лишь чтобы
    у его реплик был автор, а у задачи — состав.

    Мяч переходит внешней стороне: задача не брошена, но и не висит «на мне».
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    email = payload.email.strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен адрес электронной почты")
    if not task_mail.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "В пространстве не настроен ящик приёма — писать по почте некуда")

    person = (await db.execute(select(User).where(
        func.lower(User.email) == email))).scalar_one_or_none()
    if person is None:
        person = User(
            email=email, name=(payload.name or "").strip() or email.split("@")[0],
            # Пароля нет: строка-заглушка не является валидным bcrypt-хешем,
            # поэтому проверка пароля всегда отвергнет вход.
            password_hash="!", role="user", company_id=cid, mail_only=True)
        db.add(person)
        await db.flush()
        org_id = None
        if payload.organization_id:
            try:
                org_id = uuid.UUID(payload.organization_id)
            except (ValueError, TypeError):
                org_id = None
        # `party_type="partner"` — та же разметка «свой / внешний», что в чатах:
        # человек обязан выглядеть внешним везде, где он показан.
        db.add(UserCompany(user_id=person.id, company_id=cid, role="user",
                           party_type="partner", organization_id=org_id))
    elif not person.mail_only and await db.get(UserCompany, (person.id, cid)) is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Такой адрес уже занят учётной записью другого пространства")

    if await db.get(TaskParticipant, (t.id, person.id)) is None:
        db.add(TaskParticipant(task_id=t.id, user_id=person.id, role="external",
                               channel="mail", channel_ref=email, added_by=current_user.id))
    t.waiting_for = "external"
    db.add(TaskEvent(task_id=t.id, kind="delegate", user_id=current_user.id,
                     to_value=person.name or email, note=payload.note))
    await db.commit()

    task_mail.send_delegation_async(
        email=email, number=t.number, title=t.title,
        author=current_user.name or "коллега", note=payload.note,
        description=t.description,
        due=t.due_at.strftime("%d.%m.%Y") if t.due_at else None)
    return {"ok": True, "user_id": str(person.id), "email": email,
            "reply_address": task_mail.reply_address(t.number)}


@router.delete("/{task_id}/participants/{user_id}")
async def remove_participant(
    task_id: str,
    user_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Убрать внешнего участника. Мяч возвращается нам: ждать больше некого."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    uid = _uuid_or_400(user_id, "user_id")
    p = await db.get(TaskParticipant, (t.id, uid))
    if p is not None:
        await db.delete(p)
        await db.flush()
    left = (await db.execute(select(func.count()).select_from(TaskParticipant)
                             .where(TaskParticipant.task_id == t.id))).scalar_one()
    # Ждать больше некого — мяч возвращается нам.
    if not left and t.waiting_for == "external":
        t.waiting_for = None
    await db.commit()
    return {"deleted": user_id, "participants_left": left}


class ExternalRefIn(BaseModel):
    company_id: str
    connector_key: str = Field(min_length=1, max_length=120)
    connector_label: str | None = Field(None, max_length=200)
    external_number: str | None = Field(None, max_length=120)
    external_id: str | None = Field(None, max_length=200)
    external_url: str | None = Field(None, max_length=2000)
    mirror_close: bool = False
    note: str | None = Field(None, max_length=2000)


@router.post("/{task_id}/external", status_code=status.HTTP_201_CREATED)
async def link_external(
    task_id: str,
    payload: ExternalRefIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Связать задачу с работой во внешней системе.

    Зеркало, а не копия: у нас наша задача, у них своя. Мяч переходит внешней
    стороне — задача не брошена, но и не висит «на мне».

    Работу в чужой системе заводит её владелец (коннектор живёт в приложении,
    реестра в Ядре нет), поэтому здесь мы фиксируем связь с уже существующей у
    них работой. Автосоздание появится, когда приложение-владелец отдаст ручку.
    """
    cid = await assert_company_product(payload.company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)

    ref = (await db.execute(select(TaskExternalRef).where(
        TaskExternalRef.task_id == t.id,
        TaskExternalRef.connector_key == payload.connector_key))).scalar_one_or_none()
    if ref is None:
        ref = TaskExternalRef(task_id=t.id, connector_key=payload.connector_key,
                              created_by=current_user.id)
        db.add(ref)
    ref.connector_label = payload.connector_label
    ref.external_number = payload.external_number
    ref.external_id = payload.external_id
    ref.external_url = payload.external_url
    ref.mirror_close = payload.mirror_close
    t.waiting_for = "external"
    db.add(TaskEvent(task_id=t.id, kind="delegate", user_id=current_user.id,
                     from_value=payload.connector_key,
                     to_value=payload.connector_label or payload.connector_key,
                     note=payload.note))
    await db.commit()
    await db.refresh(ref)
    return _ref_out(ref)


@router.delete("/{task_id}/external/{ref_id}")
async def unlink_external(
    task_id: str,
    ref_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    ref = await db.get(TaskExternalRef, _uuid_or_400(ref_id, "ref_id"))
    if ref is None or ref.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Связь не найдена")
    await db.delete(ref)
    await db.flush()
    left = (await db.execute(select(func.count()).select_from(TaskExternalRef)
                             .where(TaskExternalRef.task_id == t.id))).scalar_one()
    parts = (await db.execute(select(func.count()).select_from(TaskParticipant)
                              .where(TaskParticipant.task_id == t.id))).scalar_one()
    if not left and not parts and t.waiting_for == "external":
        t.waiting_for = None
    await db.commit()
    return {"deleted": ref_id}


@router.post("/{task_id}/external/{ref_id}/sync")
async def sync_external(
    task_id: str,
    ref_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Подтянуть состояние работы у внешней стороны.

    Спрашиваем приложение-владельца тем же служебным каналом, что и витрина
    подключений. Если оно такой ручки не отдаёт — говорим об этом прямо, а не
    показываем выдуманный статус: неверная отметка о чужой работе хуже её
    отсутствия.
    """
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await _task_or_404(db, cid, task_id)
    ref = await db.get(TaskExternalRef, _uuid_or_400(ref_id, "ref_id"))
    if ref is None or ref.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Связь не найдена")

    result = await space_connectors.fetch_external_work(db, cid, ref.connector_key,
                                                        ref.external_id or ref.external_number)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason"), **_ref_out(ref)}

    ref.external_status = result.get("status") or ref.external_status
    ref.external_url = result.get("url") or ref.external_url
    ref.last_sync_at = datetime.now(timezone.utc)
    # Этапы чужой системы вливаются в НАШУ ленту отдельным видом события: человек
    # видит один поток, а не два окна. Уже записанные не повторяем.
    seen = {e for (e,) in (await db.execute(select(TaskEvent.from_value).where(
        TaskEvent.task_id == t.id, TaskEvent.kind == "external_stage"))).all()}
    added = 0
    for st in result.get("stages") or []:
        key = str(st.get("id") or st.get("name") or "")
        if not key or key in seen:
            continue
        db.add(TaskEvent(task_id=t.id, kind="external_stage",
                         actor_name=ref.connector_label or ref.connector_key,
                         from_value=key, to_value=st.get("name"), note=st.get("note")))
        added += 1
    if ref.mirror_close and result.get("closed") and t.status == "open":
        db.add(TaskEvent(task_id=t.id, kind="status", user_id=current_user.id,
                         from_value=t.status, to_value="done",
                         note="закрыто по зеркалу внешней системы"))
        t.status, t.closed_at = "done", datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ref)
    return {"ok": True, "stages_added": added, **_ref_out(ref)}


def _ref_out(r: TaskExternalRef) -> dict[str, Any]:
    return {
        "id": str(r.id), "connector_key": r.connector_key,
        "connector_label": r.connector_label, "external_id": r.external_id,
        "external_number": r.external_number, "external_status": r.external_status,
        "external_url": r.external_url, "direction": r.direction,
        "mirror_close": r.mirror_close,
        "last_sync_at": r.last_sync_at.isoformat() if r.last_sync_at else None,
    }


class InboundEmailIn(BaseModel):
    """Тело от почтового поллера Поддержки — camelCase, как у чатов."""
    fromAddress: str
    fromName: str | None = None
    text: str
    # Message-ID письма: ключ идемпотентности, повторная доставка дубля не создаёт.
    messageId: str | None = None
    # Ссылка на письмо-первоисточник в архиве Поддержки: из ленты должна быть
    # возможность дойти до оригинала, а не только до вычищенного текста.
    emailMessageId: str | None = None


@router.post("/{task_id}/inbound-email", status_code=status.HTTP_201_CREATED)
async def inbound_email(
    task_id: str,
    body: InboundEmailIn,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Ответ внешнего участника письмом → реплика в ленте задачи.

    `task_id` здесь — НОМЕР задачи: он приходит из плюс-адреса `+t<номер>`,
    который человек видит в письме. Пишет только тот, кого в эту задачу
    приглашали: адрес может утечь пересылкой письма, и по нему не должен
    получать слово посторонний.
    """
    if not task_id.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ожидается номер задачи")
    t = (await db.execute(select(Task).where(
        Task.number == int(task_id), Task.company_id == company.id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")

    email = (body.fromAddress or "").strip().lower()
    author = (await db.execute(
        select(User).join(TaskParticipant, TaskParticipant.user_id == User.id)
        .where(TaskParticipant.task_id == t.id, func.lower(User.email) == email)
    )).scalar_one_or_none()
    if author is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Отправитель {email or '(без адреса)'} не участник этой задачи")

    key = (body.messageId or "").strip() or None
    if key:
        dup = (await db.execute(select(TaskEvent.id).where(
            TaskEvent.task_id == t.id, TaskEvent.from_value == key))).scalar_one_or_none()
        if dup is not None:
            return {"ok": True, "eventId": str(dup), "duplicate": True}

    text = (body.text or "").strip() or "(письмо без текста)"
    ev = TaskEvent(
        task_id=t.id, kind="mail", user_id=author.id,
        actor_name=body.fromName or author.name or email,
        # `from_value` — ключ идемпотентности, `to_value` — путь к оригиналу письма
        # в архиве Поддержки: из ленты видно, чем реплика подтверждена.
        from_value=key, to_value=(body.emailMessageId or None), note=text)
    db.add(ev)
    # Ответ пришёл — мяч снова у нас.
    t.waiting_for = "us"
    await db.commit()

    # Свои узнают об ответе письмом: внешний участник пишет редко, и ждать его
    # ответа, поглядывая в карточку, никто не станет.
    people = (await db.execute(select(User.email).where(
        User.id.in_([i for i in (t.assignee_id, t.author_id) if i]),
        User.mail_only.is_(False)))).scalars().all()
    task_mail.send_notice_async(
        list(people), f"Ответ по задаче №{t.number}: {t.title}",
        f"{ev.actor_name} ответил письмом:\n\n{text}")
    return {"ok": True, "eventId": str(ev.id)}
