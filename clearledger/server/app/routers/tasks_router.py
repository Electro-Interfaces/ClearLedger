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
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import ServiceLocation, Task, TaskEvent, TaskType, User, UserCompany

router = APIRouter(prefix="/tasks", tags=["Задачи"])

_LIST_LIMIT = 500
_PRIORITY = "^(low|medium|high|critical)$"

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


def _task_out(t: Task, route: list[dict], names: dict[str, str | None]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
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


@router.get("")
async def list_tasks(
    company_id: str = Query(...),
    scope: str = Query("open", pattern="^(open|mine|overdue|closed|all)$"),
    object_id: str | None = Query(None),
    type_id: str | None = Query(None),
    assignee_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Задачи пространства. scope: open — активные, mine — где я исполнитель или
    автор, overdue — активные с прошедшим сроком, closed — завершённые, all — всё."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    q = select(Task).where(Task.company_id == cid)
    if scope == "open":
        q = q.where(Task.status == "open")
    elif scope == "closed":
        q = q.where(Task.status != "open")
    elif scope == "mine":
        q = q.where(or_(Task.assignee_id == current_user.id, Task.author_id == current_user.id))
    elif scope == "overdue":
        # Тот же смысл, что у флага `overdue` в выдаче: срок прошёл у ЖИВОЙ задачи.
        q = q.where(Task.status == "open", Task.due_at < datetime.now(timezone.utc))
    if object_id:
        q = q.where(Task.object_id == object_id)
    if assignee_id:
        q = q.where(Task.assignee_id == _uuid_or_400(assignee_id, "assignee_id"))
    if type_id:
        q = q.where(Task.type_id == _uuid_or_400(type_id, "type_id"))
    tasks = list((await db.execute(
        q.order_by(Task.created_at.desc()).limit(_LIST_LIMIT))).scalars())
    names = await _names(db, tasks)
    return {"tasks": [_task_out(t, names[t.id]["route"], names[t.id]) for t in tasks],
            "total": len(tasks)}


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
    if assignee is not None:
        db.add(TaskEvent(task_id=t.id, kind="assign", user_id=current_user.id,
                         to_value=(await db.get(User, assignee)).name))
    await db.commit()
    await db.refresh(t)
    names = await _names(db, [t])
    return _task_out(t, route, names[t.id])


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


@router.get("/{task_id}")
async def task_details(
    task_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка задачи: поля, маршрут и след — кто что сделал и почему стоит."""
    cid = await assert_company_product(company_id, current_user, db, "plan")
    t = await db.get(Task, _uuid_or_400(task_id, "task_id"))
    if t is None or t.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    names = await _names(db, [t])
    events = (await db.execute(
        select(TaskEvent).where(TaskEvent.task_id == t.id)
        .order_by(TaskEvent.created_at))).scalars().all()
    actors = {r.id: r.name for r in (await db.execute(select(User).where(
        User.id.in_({e.user_id for e in events if e.user_id})))).scalars()} if events else {}
    return {
        **_task_out(t, names[t.id]["route"], names[t.id]),
        "description": t.description,
        "events": [{
            "id": str(e.id), "kind": e.kind, "user": actors.get(e.user_id),
            "from": e.from_value, "to": e.to_value, "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events],
    }


class TaskAction(BaseModel):
    company_id: str
    stage_code: str | None = None          # перевести на стадию маршрута
    assignee_id: str | None = None         # переадресовать (пустая строка — снять)
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    priority: str | None = Field(None, pattern=_PRIORITY)
    due_at: datetime | None = None
    note: str | None = Field(None, max_length=2000)   # реплика в след задачи


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
    t = await db.get(Task, _uuid_or_400(task_id, "task_id"))
    if t is None or t.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    m = await db.get(UserCompany, (current_user.id, cid))
    if not (current_user.is_superadmin or (m is not None and m.role == "admin")
            or current_user.id in (t.assignee_id, t.author_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Задача не ваша")

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

    if payload.assignee_id is not None:
        new_id = _uuid_or_400(payload.assignee_id, "assignee_id") if payload.assignee_id else None
        if new_id is not None and await db.get(UserCompany, (new_id, cid)) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Исполнитель не состоит в пространстве")
        if new_id != t.assignee_id:
            was = (await db.get(User, t.assignee_id)).name if t.assignee_id else None
            now_name = (await db.get(User, new_id)).name if new_id else None
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

    # Реплика без других изменений — комментарий; вместе с ними она уже записана
    # примечанием к событию и второй раз в ленту не идёт. Считаем по факту записи,
    # а не по составу запроса: перевод на ТЕКУЩУЮ стадию событием не становится, и
    # реплика при нём иначе пропала бы молча.
    if payload.note and not logged:
        db.add(TaskEvent(task_id=t.id, kind="comment", user_id=current_user.id,
                         note=payload.note))

    await db.commit()
    await db.refresh(t)
    names = await _names(db, [t])
    return _task_out(t, route, names[t.id])
