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
from datetime import date as date_type, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    case, delete as sa_delete, func, or_, select, true as sa_true,
    update as sa_update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_company_by_api_key, get_current_user
from app.database import get_db
from app.models import (
    Company, ServiceLocation, SourceFile, Task, TaskAttachment, TaskChecklistItem,
    TaskEvent, TaskExternalRef, TaskLabel, TaskLabelLink, TaskLink, TaskParticipant,
    TaskProject, TaskRecurrence, TaskSprint, TaskTemplate, TaskType, TaskVersion,
    TaskView, TaskWatcher, TaskWorkItem,
    User, UserCompany,
)
from app.services import (
    process_templates, space_connectors, task_mail, task_scheduler, work_query,
    work_state,
)

router = APIRouter(prefix="/tasks", tags=["Задачи"])

async def _assert_work(company_ref: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Право на работу компании: «Трек» либо, для старых пространств, «Задачи».

    Поручения переехали в «Трек» (решение МАГа 16.08.2026), и продукт `plan` с
    лаунчера снят. Но ручки остались теми же: их зовёт и карточка документа, и
    экран поручений внутри «Трека». Гейт проверяет сначала новый продукт, потом
    старый — иначе после переименования у людей закрылась бы их же работа.
    """
    try:
        return await assert_company_product(company_ref, user, db, "docs")
    except HTTPException:
        return await assert_company_product(company_ref, user, db, "plan")



# Чем человек называет возврат задачи из спринта в очередь — в командной строке.
_BACKLOG_WORDS = ("бэклог", "backlog", "-")
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
    # Привычный набор из любого трекера: работа копится в беклоге, забирается
    # в план, делается, проверяется. Нужен тем, кто ведёт поток задач доской, —
    # у остальных заготовок маршрут короче и без «накопителя».
    {"code": "flow", "name": "Поток работ", "sort_order": 40,
     "description": "Беклог и доска: копим, берём в работу, проверяем",
     "route": [{"code": "backlog", "name": "Беклог"},
               {"code": "todo", "name": "К выполнению"},
               {"code": "doing", "name": "В работе"},
               {"code": "review", "name": "На проверке"}]},
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
        "reaction_hours": t.reaction_hours,
        "escalate_to_id": str(t.escalate_to_id) if t.escalate_to_id else None,
        # NULL — тип общий для компании; иначе он свой у проекта.
        "project_id": str(t.project_id) if t.project_id else None,
    }


def _task_out(t: Task, route: list[dict], names: dict[str, str | None],
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        **(extra or {}),
        "id": str(t.id),
        "number": t.number,
        # Как задачу называют вслух и пишут в коммите: `TF-42`. Сквозной номер
        # остаётся рядом — на него ссылаются уже написанные интеграции.
        "key": (f"{names.get('project_code')}-{t.project_number}"
                if names.get("project_code") and t.project_number else str(t.number)),
        "project": names.get("project"),
        "project_id": str(t.project_id) if t.project_id else None,
        "project_number": t.project_number,
        # «Исправлено в 1.4.2» — ответ заявителю, «обнаружено в» — с чего
        # разбираться, если сломали давно.
        "fix_version": names.get("fix_version"),
        "fix_version_id": str(t.fix_version_id) if t.fix_version_id else None,
        "found_version": names.get("found_version"),
        "found_version_id": str(t.found_version_id) if t.found_version_id else None,
        # Пусто — задача в бэклоге: решили делать, не решили когда.
        "sprint": names.get("sprint"),
        "sprint_id": str(t.sprint_id) if t.sprint_id else None,
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
        # Общая ось пространства (этап 13а): одна колонка на документ и на
        # поручение. Считается в `work_state` и больше нигде.
        **work_state.state_out(work_state.task_state(t, route)),
        "visibility": t.visibility,
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
    prj_ids = {t.project_id for t in tasks if t.project_id}
    ver_ids = {i for t in tasks for i in (t.fix_version_id, t.found_version_id) if i}
    spr_ids = {t.sprint_id for t in tasks if t.sprint_id}
    prjs = {r.id: r for r in (await db.execute(
        select(TaskProject).where(TaskProject.id.in_(prj_ids)))).scalars()} if prj_ids else {}
    vers = {r.id: r.name for r in (await db.execute(
        select(TaskVersion).where(TaskVersion.id.in_(ver_ids)))).scalars()} if ver_ids else {}
    sprs = {r.id: r.name for r in (await db.execute(
        select(TaskSprint).where(TaskSprint.id.in_(spr_ids)))).scalars()} if spr_ids else {}
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
        "project": prjs[t.project_id].name if t.project_id in prjs else None,
        "project_code": prjs[t.project_id].code if t.project_id in prjs else None,
        "fix_version": vers.get(t.fix_version_id),
        "found_version": vers.get(t.found_version_id),
        "sprint": sprs.get(t.sprint_id),
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

    spent: dict[uuid.UUID, int] = {}
    for tid, total in (await db.execute(
        select(TaskWorkItem.task_id, func.coalesce(func.sum(TaskWorkItem.minutes), 0))
        .where(TaskWorkItem.task_id.in_(ids))
        .group_by(TaskWorkItem.task_id))).all():
        spent[tid] = int(total or 0)

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
        "time": {
            "estimate": t.estimate_minutes,
            "spent": spent.get(t.id, 0),
            "estimate_text": human_duration(t.estimate_minutes),
            "spent_text": human_duration(spent.get(t.id, 0)),
        },
    } for t in tasks}


def _visible_to(user: User, is_admin: bool):
    """Условие видимости для выборок: приватную задачу видят только причастные.

    Собрано одним местом намеренно: стоит забыть его в поиске или в обзоре — и
    закрытая задача утечёт хотя бы заголовком, а это ровно то, ради чего её
    закрывали.
    """
    if is_admin:
        return sa_true()
    return or_(
        Task.visibility != "private",
        Task.author_id == user.id,
        Task.assignee_id == user.id,
        Task.id.in_(select(TaskWatcher.task_id).where(TaskWatcher.user_id == user.id)),
        Task.id.in_(select(TaskParticipant.task_id).where(
            TaskParticipant.user_id == user.id)),
    )


async def _is_admin(db: AsyncSession, cid: uuid.UUID, user: User) -> bool:
    if user.is_superadmin:
        return True
    m = await db.get(UserCompany, (user.id, cid))
    return m is not None and m.role == "admin"


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


async def _can_view_task(db: AsyncSession, cid: uuid.UUID, user: User, t: Task) -> bool:
    if t.visibility != "private" or await _is_admin(db, cid, user):
        return True
    return user.id in (t.author_id, t.assignee_id) or bool(
        await db.get(TaskWatcher, (t.id, user.id))
        or await db.get(TaskParticipant, (t.id, user.id)))


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



# ── Язык запросов ───────────────────────────────────────────────────────────
# Разбор живёт в `services/work_query.py`: тем же языком спрашивают и реестр
# поручений, и общую ленту работы (этап 13в). Вторая реализация разошлась бы с
# первой, и «исполнитель: я» значил бы в двух списках разное.


async def _parse_query(db: AsyncSession, cid: uuid.UUID, user: User,
                       text: str) -> tuple[dict[str, Any], list[str], str]:
    return await work_query.parse(db, cid, user, text)


@router.get("")
async def list_tasks(
    company_id: str = Query(...),
    scope: str = Query("open", pattern="^(open|mine|assigned|watching|overdue|today|waiting|closed|all)$"),
    object_id: str | None = Query(None),
    project_id: str | None = Query(None),
    fix_version_id: str | None = Query(None),
    found_version_id: str | None = Query(None),
    sprint_id: str | None = Query(None),
    # Бэклог — это отсутствие спринта, а не отдельный список. Отдельный
    # параметр нужен потому, что «пусто» через `sprint_id` не передать.
    backlog: bool = Query(False),
    type_id: str | None = Query(None),
    assignee_id: str | None = Query(None),
    author_id: str | None = Query(None),
    stage: str | None = Query(None),
    priority: str | None = Query(None, pattern=_PRIORITY),
    label_id: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    # Строка запроса: «проект: TF #нерешённые исполнитель: я». Что разобрано, а
    # что нет, возвращается в ответе — иначе опечатка молча сужает список.
    query: str | None = Query(None, max_length=500),
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
    cid = await _assert_work(company_id, current_user, db)
    now = datetime.now(timezone.utc)

    # Строка запроса перекрывает поля формы: человек, дописавший «исполнитель:
    # я», ждёт своих задач, а не пересечения с тем, что осталось в отборе сбоку.
    query_out: dict[str, Any] | None = None
    if query and query.strip():
        parsed, unknown, free_text = await _parse_query(db, cid, current_user, query)
        scope = parsed.get("scope", scope)
        backlog = parsed.get("backlog", backlog)
        project_id = parsed.get("project_id", project_id)
        fix_version_id = parsed.get("fix_version_id", fix_version_id)
        found_version_id = parsed.get("found_version_id", found_version_id)
        sprint_id = parsed.get("sprint_id", sprint_id)
        assignee_id = parsed.get("assignee_id", assignee_id)
        author_id = parsed.get("author_id", author_id)
        label_id = parsed.get("label_id", label_id)
        type_id = parsed.get("type_id", type_id)
        object_id = parsed.get("object_id", object_id)
        stage = parsed.get("stage", stage)
        priority = parsed.get("priority", priority)
        due_from = parsed.get("due_from", due_from)
        due_to = parsed.get("due_to", due_to)
        q = free_text or q
        query_out = {"parsed": {k: str(v) for k, v in parsed.items()},
                     "unknown": unknown, "text": free_text or None}

    sel = select(Task).where(Task.company_id == cid,
                             _visible_to(current_user, await _is_admin(db, cid, current_user)))

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
    if project_id:
        sel = sel.where(Task.project_id == _uuid_or_400(project_id, "project_id"))
    if sprint_id:
        sel = sel.where(Task.sprint_id == _uuid_or_400(sprint_id, "sprint_id"))
    if backlog:
        sel = sel.where(Task.sprint_id.is_(None))
    if fix_version_id:
        sel = sel.where(Task.fix_version_id == _uuid_or_400(fix_version_id, "fix_version_id"))
    if found_version_id:
        sel = sel.where(
            Task.found_version_id == _uuid_or_400(found_version_id, "found_version_id"))
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
        **({"query": query_out} if query_out is not None else {}),
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
    cid = await _assert_work(company_id, current_user, db)
    # Принадлежность отдаём вместе с именем: поручая работу, надо видеть, свой это
    # человек или подрядчик, — задача внешнему участнику раскрывает ему внутреннее.
    rows = (await db.execute(
        select(User.id, User.name, User.email, UserCompany.party_type, User.avatar_url)
        .join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == cid)
        .order_by(User.name))).all()
    return {"people": [{"id": str(i), "name": n or (e or "—"),
                        "partyType": p or "internal", "avatarUrl": a}
                       for i, n, e, p, a in rows]}


# ── Типы задач и маршруты ────────────────────────────────────────────────


# ── Проекты ─────────────────────────────────────────────────────────────────
# Контейнер работы: свой номер (`TF-42`), свои типы задач, свой состав. Заведён
# 22.08.2026 под трекерный контур: без проекта не собирается ни бэклог, ни релиз.


def _project_out(p: TaskProject, tasks: int = 0, open_tasks: int = 0) -> dict[str, Any]:
    return {
        "id": str(p.id), "code": p.code, "name": p.name,
        "description": p.description,
        "lead_id": str(p.lead_id) if p.lead_id else None,
        "counter": p.counter, "is_archived": p.is_archived,
        "sort_order": p.sort_order,
        "tasks": tasks, "open": open_tasks,
    }


@router.get("/projects")
async def list_projects(
    company_id: str = Query(...),
    archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Проекты компании со счётчиками работы: пустой проект видно сразу."""
    cid = await _assert_work(company_id, current_user, db)
    q = select(TaskProject).where(TaskProject.company_id == cid)
    if not archived:
        q = q.where(TaskProject.is_archived.is_(False))
    rows = (await db.execute(q.order_by(TaskProject.sort_order, TaskProject.code))).scalars().all()
    counts = dict((pid, (n, o)) for pid, n, o in (await db.execute(
        select(Task.project_id, func.count(Task.id),
               func.count(Task.id).filter(Task.status == "open"))
        .where(Task.company_id == cid, Task.project_id.is_not(None))
        .group_by(Task.project_id))).all())
    return {"projects": [_project_out(p, *counts.get(p.id, (0, 0))) for p in rows]}


class ProjectIn(BaseModel):
    company_id: str
    # Код идёт в номер задачи и в разговор, поэтому только латиница в верхнем
    # регистре и цифры: `TF-42` читается, `тф-42` в коммите — нет.
    code: str = Field(min_length=2, max_length=10, pattern="^[A-Z][A-Z0-9]*$")
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    lead_id: str | None = None
    sort_order: int = 100


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    exists = (await db.execute(select(TaskProject).where(
        TaskProject.company_id == cid,
        TaskProject.code == payload.code))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Проект с таким кодом уже есть")
    p = TaskProject(
        company_id=cid, code=payload.code, name=payload.name.strip(),
        description=payload.description, sort_order=payload.sort_order,
        lead_id=_uuid_or_400(payload.lead_id, "руководитель") if payload.lead_id else None)
    db.add(p)
    await db.flush()
    await db.commit()
    return _project_out(p)


class ProjectPatch(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    lead_id: str | None = None
    sort_order: int | None = None
    is_archived: bool | None = None


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: ProjectPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Правка проекта. Код не меняется: он уже в номерах задач и в переписке."""
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    p = await db.get(TaskProject, _uuid_or_400(project_id, "проект"))
    if p is None or p.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    if payload.name is not None:
        p.name = payload.name.strip()
    if payload.description is not None:
        p.description = payload.description
    if payload.lead_id is not None:
        p.lead_id = _uuid_or_400(payload.lead_id, "руководитель") if payload.lead_id else None
    if payload.sort_order is not None:
        p.sort_order = payload.sort_order
    if payload.is_archived is not None:
        p.is_archived = payload.is_archived
    await db.commit()
    return _project_out(p)


# ── Версии проекта ────────────────────────────────────────────
# «Исправлено в 1.4.2» — то, чего ждёт заявитель. Версия принадлежит проекту:
# «1.4» у фронта и «1.4» у бэкенда — разные вещи, и общий справочник заставил
# бы придумывать им разные имена.


def _version_out(v: TaskVersion, fixed: int = 0, open_tasks: int = 0) -> dict[str, Any]:
    return {
        "id": str(v.id), "project_id": str(v.project_id),
        "name": v.name, "description": v.description, "state": v.state,
        "released_on": v.released_on.isoformat() if v.released_on else None,
        "sort_order": v.sort_order,
        # Состав виден прямо в списке: «десять сделано, три висят» — это и есть
        # ответ на вопрос «можно ли выпускать».
        "fixed": fixed, "open": open_tasks,
    }


async def _version_or_400(db: AsyncSession, value: str, project_id: uuid.UUID | None,
                          field: str) -> uuid.UUID:
    """Версия существует и принадлежит проекту задачи.

    Версия чужого проекта в карточке не значит ничего: `1.4` фронта, проставленная
    задаче бэкенда, соврёт заявителю, в каком релизе искать исправление.
    """
    v = await db.get(TaskVersion, _uuid_or_400(value, field))
    if v is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная версия")
    if project_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "У задачи нет проекта: версии живут на проекте")
    if v.project_id != project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Версия принадлежит другому проекту")
    return v.id


@router.get("/versions")
async def list_versions(
    company_id: str = Query(...),
    project_id: str | None = Query(None),
    state: str | None = Query(None, pattern="^(open|released|cancelled)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Версии компании со счётчиками состава. Без `project_id` — все проекты
    разом: так карточка задачи одним запросом получает всё, что может выбрать."""
    cid = await _assert_work(company_id, current_user, db)
    q = select(TaskVersion).where(TaskVersion.company_id == cid)
    if project_id:
        q = q.where(TaskVersion.project_id == _uuid_or_400(project_id, "project_id"))
    if state:
        q = q.where(TaskVersion.state == state)
    rows = (await db.execute(q.order_by(TaskVersion.sort_order,
                                        TaskVersion.name))).scalars().all()
    counts = dict((vid, (n, o)) for vid, n, o in (await db.execute(
        select(Task.fix_version_id, func.count(Task.id),
               func.count(Task.id).filter(Task.status == "open"))
        .where(Task.company_id == cid, Task.fix_version_id.is_not(None))
        .group_by(Task.fix_version_id))).all())
    return {"versions": [_version_out(v, *counts.get(v.id, (0, 0))) for v in rows]}


class VersionIn(BaseModel):
    company_id: str
    project_id: str
    # Свободная строка: схемы нумерации у продуктов разные, и навязывать semver
    # значило бы спорить с командой о том, что не наше дело.
    name: str = Field(min_length=1, max_length=40)
    description: str | None = None
    released_on: date_type | None = None
    sort_order: int = 100


@router.post("/versions", status_code=status.HTTP_201_CREATED)
async def create_version(
    payload: VersionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    prj = await db.get(TaskProject, _uuid_or_400(payload.project_id, "project_id"))
    if prj is None or prj.company_id != cid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный проект")
    name = payload.name.strip()
    if (await db.execute(select(TaskVersion.id).where(
            TaskVersion.project_id == prj.id,
            TaskVersion.name == name))).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такая версия в проекте уже есть")
    v = TaskVersion(company_id=cid, project_id=prj.id, name=name,
                    description=payload.description, released_on=payload.released_on,
                    sort_order=payload.sort_order)
    db.add(v)
    await db.flush()
    await db.commit()
    return _version_out(v)


class VersionPatch(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=40)
    description: str | None = None
    state: str | None = Field(None, pattern="^(open|released|cancelled)$")
    released_on: date_type | None = None
    sort_order: int | None = None


@router.patch("/versions/{version_id}")
async def update_version(
    version_id: str,
    payload: VersionPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Правка версии. Проект не меняется: версия уже названа заявителю в ответе,
    и переезд в другой проект сделал бы этот ответ ложью."""
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    v = await db.get(TaskVersion, _uuid_or_400(version_id, "версия"))
    if v is None or v.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия не найдена")
    if payload.name is not None and payload.name.strip() != v.name:
        name = payload.name.strip()
        if (await db.execute(select(TaskVersion.id).where(
                TaskVersion.project_id == v.project_id, TaskVersion.name == name,
                TaskVersion.id != v.id))).scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Такая версия в проекте уже есть")
        v.name = name
    if payload.description is not None:
        v.description = payload.description
    if payload.sort_order is not None:
        v.sort_order = payload.sort_order
    if payload.released_on is not None:
        v.released_on = payload.released_on
    if payload.state is not None:
        v.state = payload.state
        # Выпуск без даты — дырка в ответе заявителю: «исправлено в 1.4.2», а
        # когда она вышла, неизвестно. Ставим день выпуска, если его не назвали.
        if payload.state == "released" and v.released_on is None:
            v.released_on = datetime.now(timezone.utc).date()
    await db.commit()
    return _version_out(v)


@router.get("/versions/{version_id}/summary")
async def version_summary(
    version_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Состав версии: что вошло, что осталось, что в ней обнаружено.

    Она же черновик списка изменений: закрытые задачи с номерами и заголовками —
    ровно то, что уходит в ответ заявителю и в описание релиза.
    """
    cid = await _assert_work(company_id, current_user, db)
    v = await db.get(TaskVersion, _uuid_or_400(version_id, "версия"))
    if v is None or v.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия не найдена")
    admin = await _is_admin(db, cid, current_user)
    rows = (await db.execute(
        select(Task).where(Task.company_id == cid, _visible_to(current_user, admin),
                           or_(Task.fix_version_id == v.id, Task.found_version_id == v.id))
        .order_by(Task.project_number, Task.number))).scalars().all()
    names = await _names(db, rows)
    fixed = [t for t in rows if t.fix_version_id == v.id]
    return {
        "version": _version_out(
            v, len([t for t in fixed if t.status != "open"]),
            len([t for t in fixed if t.status == "open"])),
        "done": [_task_out(t, names[t.id]["route"], names[t.id])
                 for t in fixed if t.status != "open"],
        "left": [_task_out(t, names[t.id]["route"], names[t.id])
                 for t in fixed if t.status == "open"],
        "found": [_task_out(t, names[t.id]["route"], names[t.id])
                  for t in rows if t.found_version_id == v.id],
    }


# ── Спринты проекта ─────────────────────────────────────────────────────────
# Доска по стадиям отвечает «где работа стоит», спринт — «что берём следующим».
# Задача без спринта и есть бэклог: отдельной сущности под него нет, иначе
# задачу пришлось бы класть куда-то дважды.


def _sprint_out(sp: TaskSprint, done: int = 0, left: int = 0) -> dict[str, Any]:
    return {
        "id": str(sp.id), "project_id": str(sp.project_id),
        "name": sp.name, "state": sp.state,
        "starts_on": sp.starts_on.isoformat() if sp.starts_on else None,
        "ends_on": sp.ends_on.isoformat() if sp.ends_on else None,
        "carried_over": sp.carried_over,
        # Итог тремя числами: взято, сделано, перенесено. Диаграмму сгорания не
        # рисуем, пока её никто не попросил.
        "taken": done + left + sp.carried_over, "done": done, "left": left,
    }


@router.get("/sprints")
async def list_sprints(
    company_id: str = Query(...),
    project_id: str | None = Query(None),
    state: str | None = Query(None, pattern="^(planned|active|closed)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Спринты компании со счётчиками: сделано и осталось видно списком."""
    cid = await _assert_work(company_id, current_user, db)
    q = select(TaskSprint).where(TaskSprint.company_id == cid)
    if project_id:
        q = q.where(TaskSprint.project_id == _uuid_or_400(project_id, "project_id"))
    if state:
        q = q.where(TaskSprint.state == state)
    rows = (await db.execute(q.order_by(TaskSprint.starts_on.desc().nullslast(),
                                        TaskSprint.name))).scalars().all()
    counts = dict((sid, (d, o)) for sid, d, o in (await db.execute(
        select(Task.sprint_id,
               func.count(Task.id).filter(Task.status != "open"),
               func.count(Task.id).filter(Task.status == "open"))
        .where(Task.company_id == cid, Task.sprint_id.is_not(None))
        .group_by(Task.sprint_id))).all())
    return {"sprints": [_sprint_out(sp, *counts.get(sp.id, (0, 0))) for sp in rows]}


class SprintIn(BaseModel):
    company_id: str
    project_id: str
    name: str = Field(min_length=1, max_length=60)
    starts_on: date_type | None = None
    ends_on: date_type | None = None


@router.post("/sprints", status_code=status.HTTP_201_CREATED)
async def create_sprint(
    payload: SprintIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    prj = await db.get(TaskProject, _uuid_or_400(payload.project_id, "project_id"))
    if prj is None or prj.company_id != cid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный проект")
    if payload.starts_on and payload.ends_on and payload.ends_on < payload.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Спринт кончается раньше, чем начинается")
    name = payload.name.strip()
    if (await db.execute(select(TaskSprint.id).where(
            TaskSprint.project_id == prj.id,
            TaskSprint.name == name))).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой спринт в проекте уже есть")
    sp = TaskSprint(company_id=cid, project_id=prj.id, name=name,
                    starts_on=payload.starts_on, ends_on=payload.ends_on)
    db.add(sp)
    await db.flush()
    await db.commit()
    return _sprint_out(sp)


class SprintPatch(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=60)
    state: str | None = Field(None, pattern="^(planned|active|closed)$")
    starts_on: date_type | None = None
    ends_on: date_type | None = None


@router.patch("/sprints/{sprint_id}")
async def update_sprint(
    sprint_id: str,
    payload: SprintPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Правка спринта, включая начало и закрытие отрезка.

    Закрытие — не просто смена слова: незакрытые задачи возвращаются в бэклог, а
    их число остаётся в спринте. Иначе итог показал бы «взято столько же, сколько
    сделано» — по такому отчёту не видно, что отрезок переоценили.
    """
    cid = await _assert_work(payload.company_id, current_user, db)
    sp = await db.get(TaskSprint, _uuid_or_400(sprint_id, "спринт"))
    if sp is None or sp.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спринт не найден")
    if payload.name is not None and payload.name.strip() != sp.name:
        name = payload.name.strip()
        if (await db.execute(select(TaskSprint.id).where(
                TaskSprint.project_id == sp.project_id, TaskSprint.name == name,
                TaskSprint.id != sp.id))).scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Такой спринт в проекте уже есть")
        sp.name = name
    if payload.starts_on is not None:
        sp.starts_on = payload.starts_on
    if payload.ends_on is not None:
        sp.ends_on = payload.ends_on
    if sp.starts_on and sp.ends_on and sp.ends_on < sp.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Спринт кончается раньше, чем начинается")

    if payload.state is not None and payload.state != sp.state:
        if payload.state == "active":
            # Активный спринт в проекте один: два «текущих» отрезка означают, что
            # плана нет, а есть два списка желаний.
            busy = (await db.execute(select(TaskSprint.name).where(
                TaskSprint.project_id == sp.project_id, TaskSprint.state == "active",
                TaskSprint.id != sp.id))).scalars().first()
            if busy:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"В проекте уже идёт спринт «{busy}» — закройте его")
            if sp.starts_on is None:
                sp.starts_on = datetime.now(timezone.utc).date()
        if payload.state == "closed":
            left = (await db.execute(select(Task).where(
                Task.sprint_id == sp.id, Task.status == "open"))).scalars().all()
            sp.carried_over = len(left)
            for t in left:
                t.sprint_id = None
                db.add(TaskEvent(task_id=t.id, kind="field", user_id=current_user.id,
                                 from_value=f"спринт: {sp.name}"[:200],
                                 to_value="бэклог"))
            if sp.ends_on is None:
                sp.ends_on = datetime.now(timezone.utc).date()
        sp.state = payload.state
    await db.commit()
    counts = (await db.execute(
        select(func.count(Task.id).filter(Task.status != "open"),
               func.count(Task.id).filter(Task.status == "open"))
        .where(Task.sprint_id == sp.id))).one()
    return _sprint_out(sp, *counts)


@router.get("/sprints/{sprint_id}/summary")
async def sprint_summary(
    sprint_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Итог спринта: что сделано и что в нём осталось.

    Перенесённое числом, а не списком: задачи к этому моменту уже в бэклоге и
    показываются там — второй список означал бы, что они в двух местах сразу.
    """
    cid = await _assert_work(company_id, current_user, db)
    sp = await db.get(TaskSprint, _uuid_or_400(sprint_id, "спринт"))
    if sp is None or sp.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Спринт не найден")
    admin = await _is_admin(db, cid, current_user)
    rows = (await db.execute(
        select(Task).where(Task.company_id == cid, _visible_to(current_user, admin),
                           Task.sprint_id == sp.id)
        .order_by(Task.project_number, Task.number))).scalars().all()
    names = await _names(db, rows)
    done = [t for t in rows if t.status != "open"]
    left = [t for t in rows if t.status == "open"]
    return {
        "sprint": _sprint_out(sp, len(done), len(left)),
        "done": [_task_out(t, names[t.id]["route"], names[t.id]) for t in done],
        "left": [_task_out(t, names[t.id]["route"], names[t.id]) for t in left],
    }


@router.get("/types")
async def list_types(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(select(TaskType).where(TaskType.company_id == cid)
                             .order_by(TaskType.sort_order, TaskType.name))).scalars().all()
    return {"types": [_type_out(t) for t in rows], "default_route": DEFAULT_ROUTE,
            "columns": [{"code": c, "name": work_state.COLUMN_NAMES[c]}
                        for c in work_state.COLUMNS]}


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
    reaction_hours: int | None = Field(None, ge=1, le=720)
    escalate_to_id: str | None = None


def _clean_route(route: list[dict]) -> list[dict]:
    """Маршрут из формы: коды уникальны, имена обязательны, колонка — по желанию.

    Колонка (`work_state.COLUMNS`) — место стадии на общей доске пространства.
    Её называет тот, кто рисует маршрут: только он знает, что «Согласование с
    юристом» — это согласование, а не работа. Пусто — колонку угадывает
    эвристика по месту стадии.
    """
    out: list[dict] = []
    for s in route:
        code = str(s.get("code") or "").strip()[:40]
        name = str(s.get("name") or "").strip()[:120]
        if code and name and code not in [x["code"] for x in out]:
            stage = {"code": code, "name": name}
            if s.get("column") in work_state.COLUMNS:
                stage["column"] = str(s["column"])
            out.append(stage)
    return out


async def _assert_admin(db: AsyncSession, cid: uuid.UUID, user: User,
                        message: str = "Типы задач правит администратор пространства") -> None:
    """Правила и оценки — админу пространства.

    Справочник типов правит тот, кто отвечает за порядок: исполнитель может двигать
    свою задачу, но не менять маршрут для всех. Отказ называет причину своими
    словами — «типы задач правит администратор» под отчётом о людях выглядит
    ошибкой системы, а не правилом.
    """
    if user.is_superadmin:
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)


@router.post("/types", status_code=status.HTTP_201_CREATED)
async def create_type(
    payload: TypeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    exists = (await db.execute(select(TaskType).where(
        TaskType.company_id == cid, TaskType.code == payload.code))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Тип с таким кодом уже есть")
    t = TaskType(
        company_id=cid, code=payload.code, name=payload.name,
        description=payload.description, route=_clean_route(payload.route),
        default_priority=payload.default_priority, due_days=payload.due_days,
        is_active=payload.is_active, sort_order=payload.sort_order,
        reaction_hours=payload.reaction_hours,
        escalate_to_id=(_uuid_or_400(payload.escalate_to_id, "escalate_to_id")
                        if payload.escalate_to_id else None))
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
    cid = await _assert_work(payload.company_id, current_user, db)
    await _assert_admin(db, cid, current_user)
    t = await db.get(TaskType, _uuid_or_400(type_id, "type_id"))
    if t is None or t.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип не найден")
    t.name, t.description = payload.name, payload.description
    t.route = _clean_route(payload.route)
    t.default_priority, t.due_days = payload.default_priority, payload.due_days
    t.is_active, t.sort_order = payload.is_active, payload.sort_order
    t.reaction_hours = payload.reaction_hours
    t.escalate_to_id = (_uuid_or_400(payload.escalate_to_id, "escalate_to_id")
                        if payload.escalate_to_id else None)
    # Маршрут переписали — задачи этого типа переезжают по колонкам сразу.
    # Без этого доска держала бы прежнюю раскладку до следующего движения каждой
    # задачи, то есть месяцами: человек поправил колонку и не увидел результата.
    # Один UPDATE на стадию: их единицы, а задач могут быть тысячи.
    for index, stage in enumerate(t.route):
        await db.execute(sa_update(Task).where(
            Task.type_id == t.id, Task.stage_code == stage["code"]).values(
            stage_column=work_state.stage_column(stage, index, len(t.route))))
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
    cid = await _assert_work(company_id, current_user, db)
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
    project_id: str | None = None
    found_version_id: str | None = None
    fix_version_id: str | None = None
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
    cid = await _assert_work(payload.company_id, current_user, db)
    ttype = None
    if payload.type_id:
        ttype = await db.get(TaskType, _uuid_or_400(payload.type_id, "type_id"))
        if ttype is None or ttype.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный тип задачи")
    # Проект: свой номер задачи (`TF-42`) выдаёт триггер базы, здесь только
    # проверяем, что проект наш и не в архиве — в закрытый проект работу не ставят.
    project = None
    if payload.project_id:
        project = await db.get(TaskProject, _uuid_or_400(payload.project_id, "project_id"))
        if project is None or project.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный проект")
        if project.is_archived:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Проект в архиве")
    if ttype is not None and ttype.project_id and (
            project is None or ttype.project_id != project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Этот тип задач принадлежит другому проекту")
    # Версии живут на проекте, поэтому и проверяются против него: задача без
    # проекта версии не получает — их некуда отнести.
    pid = project.id if project else None
    found_v = await _version_or_400(db, payload.found_version_id, pid,
                                    "found_version_id") if payload.found_version_id else None
    fix_v = await _version_or_400(db, payload.fix_version_id, pid,
                                  "fix_version_id") if payload.fix_version_id else None
    route = _route_of(ttype)
    due = payload.due_at
    if due is None and ttype is not None and ttype.due_days is not None:
        due = datetime.now(timezone.utc) + timedelta(days=ttype.due_days)
    assignee = _uuid_or_400(payload.assignee_id, "assignee_id") if payload.assignee_id else None
    if assignee is not None and await db.get(UserCompany, (assignee, cid)) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Исполнитель не состоит в пространстве")

    t = Task(
        company_id=cid, project_id=project.id if project else None,
        found_version_id=found_v, fix_version_id=fix_v,
        type_id=ttype.id if ttype else None,
        title=payload.title.strip(), description=payload.description,
        priority=payload.priority or (ttype.default_priority if ttype else "medium"),
        status="open", stage_code=route[0]["code"],
        stage_column=work_state.stage_column_of(route, route[0]["code"]),
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
    cid = await _assert_work(company_id, current_user, db)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    # Живые задачи целиком плюс закрытые за период: закрытые год назад в обзоре
    # не нужны, а «в работе» нужны все — просрочка не обязана попадать в окно.
    tasks = list((await db.execute(select(Task).where(
        Task.company_id == cid,
        _visible_to(current_user, await _is_admin(db, cid, current_user)),
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


# ── Представления: сохранённый отбор реестра ─────────────────────────────


class ViewIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=120)
    query: dict = Field(default_factory=dict)
    shared: bool = False
    position: int = 100
    # К какому списку относится отбор: реестр поручений, реестр документов или
    # общая лента работы (этап 13ж). Справочник один на все три — человек видит
    # свои отборы в одном месте, а не в трёх.
    list_scope: str = Field("task", pattern="^(task|doc|work)$")


@router.get("/views")
async def list_views(
    company_id: str = Query(...),
    list_scope: str = Query("task", pattern="^(task|doc|work)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Мои представления и общие компании — одним списком, как их видит панель."""
    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(select(TaskView).where(
        TaskView.company_id == cid,
        TaskView.list_scope == list_scope,
        or_(TaskView.user_id.is_(None), TaskView.user_id == current_user.id))
        .order_by(TaskView.position, TaskView.name))).scalars().all()
    can_manage_shared = await _is_admin(db, cid, current_user)
    return {"views": [{
        "id": str(v.id), "name": v.name, "query": v.query or {},
        "shared": v.user_id is None, "position": v.position,
        "list_scope": v.list_scope,
        "can_delete": v.user_id == current_user.id or can_manage_shared,
    } for v in rows]}


@router.post("/views", status_code=status.HTTP_201_CREATED)
async def create_view(
    payload: ViewIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сохранить отбор. Общее представление заводит администратор: иначе список
    компании зарастает чужими черновиками."""
    cid = await _assert_work(payload.company_id, current_user, db)
    if payload.shared:
        await _assert_admin(db, cid, current_user)
    v = TaskView(company_id=cid, user_id=None if payload.shared else current_user.id,
                 list_scope=payload.list_scope,
                 name=payload.name.strip(), query=payload.query or {},
                 position=payload.position)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return {"id": str(v.id), "name": v.name, "query": v.query,
            "shared": v.user_id is None, "list_scope": v.list_scope}


@router.delete("/views/{view_id}")
async def delete_view(
    view_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    v = await db.get(TaskView, _uuid_or_400(view_id, "view_id"))
    if v is None or v.company_id != cid or v.list_scope != "task":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Представление не найдено")
    # Своё снимает автор, общее — администратор.
    if v.user_id is None:
        await _assert_admin(db, cid, current_user)
    elif v.user_id != current_user.id and not current_user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это чужое представление")
    await db.delete(v)
    await db.commit()
    return {"deleted": view_id}


# ── Шаблоны и расписания ─────────────────────────────────────────────────


class TemplateIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(None, max_length=8000)
    type_id: str | None = None
    # Заполнен — шаблон порождает ДОКУМЕНТ этого вида, а не поручение: так
    # описывается «акт сверки к 5 числу». Расписание при этом одно на оба.
    doc_kind_id: str | None = None
    assignee_id: str | None = None
    object_id: str | None = None
    priority: str | None = Field(None, pattern=_PRIORITY)
    due_days: int | None = Field(None, ge=0, le=365)
    checklist: list[str] = Field(default_factory=list)


def _template_out(t: TaskTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id), "name": t.name, "title": t.title,
        "description": t.description,
        "type_id": str(t.type_id) if t.type_id else None,
        "doc_kind_id": str(t.doc_kind_id) if t.doc_kind_id else None,
        "assignee_id": str(t.assignee_id) if t.assignee_id else None,
        "object_id": t.object_id, "priority": t.priority, "due_days": t.due_days,
        "checklist": t.checklist or [],
    }


@router.get("/templates")
async def list_templates(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(select(TaskTemplate).where(TaskTemplate.company_id == cid)
                             .order_by(TaskTemplate.name))).scalars().all()
    available_process_ids = {
        item["id"] for item in await process_templates.available_templates(
            db, cid, current_user)
    }
    visible = [t for t in rows
               if not t.doc_kind_id or str(t.id) in available_process_ids]
    return {"templates": [_template_out(t) for t in visible]}


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(payload.company_id, current_user, db)
    if payload.type_id and payload.doc_kind_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Шаблон не может одновременно создавать задачу и документ")
    doc_kind_id = (_uuid_or_400(payload.doc_kind_id, "doc_kind_id")
                   if payload.doc_kind_id else None)
    if doc_kind_id:
        from app.models import DocKind

        await _assert_admin(db, cid, current_user)
        kind = await db.get(DocKind, doc_kind_id)
        if kind is None or kind.company_id != cid or not kind.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Вид документа шаблона недоступен")
        if not kind.route:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Сначала задайте маршрут у вида документа")
    type_id = _uuid_or_400(payload.type_id, "type_id") if payload.type_id else None
    if type_id:
        task_type = await db.get(TaskType, type_id)
        if task_type is None or task_type.company_id != cid:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Тип задачи не принадлежит пространству")
    assignee_id = (_uuid_or_400(payload.assignee_id, "assignee_id")
                   if payload.assignee_id else None)
    if assignee_id and await db.get(UserCompany, (assignee_id, cid)) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Исполнитель не состоит в пространстве")
    tpl = TaskTemplate(
        company_id=cid, name=payload.name.strip(), title=payload.title.strip(),
        description=payload.description,
        type_id=type_id, doc_kind_id=doc_kind_id, assignee_id=assignee_id,
        object_id=payload.object_id or None, priority=payload.priority,
        due_days=payload.due_days,
        checklist=[str(x).strip()[:500] for x in payload.checklist if str(x).strip()])
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return _template_out(tpl)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    tpl = await db.get(TaskTemplate, _uuid_or_400(template_id, "template_id"))
    if tpl is None or tpl.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не найден")
    if tpl.doc_kind_id or (tpl.assignee_id is not None
                           and tpl.assignee_id != current_user.id):
        await _assert_admin(db, cid, current_user)
    await db.delete(tpl)
    await db.commit()
    return {"deleted": template_id}


class RecurrenceIn(BaseModel):
    company_id: str
    template_id: str
    # {"mode": "daily|weekly|monthly", "at": "09:00", "weekday": 0, "day": 1, "tz": …}
    rule: dict = Field(default_factory=dict)
    enabled: bool = True


@router.get("/recurrences")
async def list_recurrences(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(
        select(TaskRecurrence, TaskTemplate.name)
        .join(TaskTemplate, TaskTemplate.id == TaskRecurrence.template_id)
        .where(TaskRecurrence.company_id == cid)
        .order_by(TaskTemplate.name))).all()
    return {"recurrences": [{
        "id": str(r.id), "template_id": str(r.template_id), "template": name,
        "rule": r.rule or {}, "enabled": r.enabled,
        "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
    } for r, name in rows]}


@router.post("/recurrences", status_code=status.HTTP_201_CREATED)
async def create_recurrence(
    payload: RecurrenceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести расписание. Первое срабатывание считаем сразу — человек должен
    видеть в списке дату, а не «когда-нибудь».

    Себе расписание заводит любой: «каждый понедельник свести отчёт» — личная
    дисциплина, а не регламент компании, и ходить за ней к администратору никто
    не станет. Регулярную работу ДРУГОМУ человеку ставит администратор
    пространства: иначе кто угодно навесит на коллегу еженедельную задачу.
    """
    cid = await _assert_work(payload.company_id, current_user, db)
    tpl = await db.get(TaskTemplate, _uuid_or_400(payload.template_id, "template_id"))
    if tpl is None or tpl.company_id != cid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Шаблон не найден")
    if tpl.assignee_id is not None and tpl.assignee_id != current_user.id:
        await _assert_admin(db, cid, current_user)
    rec = TaskRecurrence(
        company_id=cid, template_id=tpl.id, rule=payload.rule or {},
        enabled=payload.enabled, created_by=current_user.id,
        next_run_at=task_scheduler.next_run(payload.rule or {},
                                            datetime.now(timezone.utc)))
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return {"id": str(rec.id), "template": tpl.name, "rule": rec.rule,
            "enabled": rec.enabled,
            "next_run_at": rec.next_run_at.isoformat() if rec.next_run_at else None}


@router.delete("/recurrences/{rec_id}")
async def delete_recurrence(
    rec_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
    rec = await db.get(TaskRecurrence, _uuid_or_400(rec_id, "rec_id"))
    if rec is None or rec.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Расписание не найдено")
    if rec.created_by != current_user.id:
        await _assert_admin(db, cid, current_user)
    await db.delete(rec)
    await db.commit()
    return {"deleted": rec_id}


# ── Метки компании ───────────────────────────────────────────────────────
# ВНИМАНИЕ: `/labels` и `/attachments/…` объявлены ДО `/{task_id}` — иначе FastAPI
# разберёт «labels» как идентификатор задачи (та же грабля, что у `/summary`).


@router.get("/labels")
async def list_labels(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    # Ссылку на закрытую задачу могут переслать — проверяем причастность, а не
    # только знание идентификатора.
    if not await _can_view_task(db, cid, current_user, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
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
    work = (await db.execute(
        select(TaskWorkItem).where(TaskWorkItem.task_id == t.id)
        .order_by(TaskWorkItem.work_date.desc(), TaskWorkItem.created_at.desc()))).all()
    people = {u: n for u, n in (await db.execute(select(User.id, User.name).where(
        User.id.in_({w.user_id for (w,) in work if w.user_id})))).all()} if work else {}
    participants = (await db.execute(
        select(TaskParticipant, User.name, User.email)
        .join(User, User.id == TaskParticipant.user_id)
        .where(TaskParticipant.task_id == t.id)
        .order_by(TaskParticipant.created_at))).all()

    can_manage_files = (current_user.id in (t.author_id, t.assignee_id)
                        or await _is_admin(db, cid, current_user))
    return {
        **_task_out(t, names[t.id]["route"], names[t.id], extras[t.id]),
        "description": t.description,
        "events": [{
            "id": str(e.id), "kind": e.kind,
            # Имя из письма важнее имени учётки: подпись под репликой должна
            # совпадать с тем, как человек представился в почте.
            "user": e.actor_name or actors.get(e.user_id),
            "from": e.from_value, "to": e.to_value, "note": e.note,
            "pinned": e.pinned,
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
            "can_delete": can_manage_files or a.uploaded_by == current_user.id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a, sf in attachments],
        "links": await _links_out(db, t),
        "work_items": [{
            "id": str(w.id), "minutes": w.minutes, "duration": human_duration(w.minutes),
            "work_date": w.work_date.isoformat(), "description": w.description,
            "kind": w.kind, "user": people.get(w.user_id),
        } for w, in work],
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
    project_id: str | None = None          # подобрать «ничью» задачу в проект
    # "" — снять версию: «оказалось, чинить не здесь» бывает чаще, чем хотелось бы.
    fix_version_id: str | None = None
    found_version_id: str | None = None
    sprint_id: str | None = None           # "" — вернуть задачу в бэклог
    add_label_id: str | None = None
    remove_label_id: str | None = None
    estimate: str | None = Field(None, max_length=40)   # «4ч», «30м»; "" — снять
    visibility: str | None = Field(None, pattern="^(company|private)$")


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
    cid = await _assert_work(payload.company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    # Реплика — не действие над задачей. Кто задачу видит, тот может в неё
    # написать: коллега, заметивший «это уже сделано», не должен молчать
    # только потому, что работа не на нём (так же в YouTrack и Jira —
    # комментарий отделён от перехода). Всё остальное — по праву участника.
    only_note = (payload.note is not None and not any((
        payload.stage_code, payload.assignee_id, payload.status, payload.priority,
        payload.due_at, payload.title, payload.description, payload.object_id,
        payload.add_label_id, payload.remove_label_id)))
    if not only_note:
        await _assert_actor(db, cid, current_user, t)

    ttype = await db.get(TaskType, t.type_id) if t.type_id else None
    route = _route_of(ttype)
    logged = False   # записалось ли событие, к которому реплика уже прицеплена

    if payload.stage_code is not None:
        if payload.stage_code not in [s["code"] for s in route]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Стадии нет в маршруте типа")
        # Закрытая задача по маршруту не ходит. Иначе получается «выполнена, но
        # стадия ползёт»: в ленте движение есть, а работы нет, и любой отчёт по
        # стадиям начинает врать. Хочешь двигать — сначала верни в работу
        # (в YouTrack/Jira это ровно тот же порядок: переход только у живой).
        if t.status != "open":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Задача закрыта — сначала верните её в работу, потом двигайте по маршруту")
        if payload.stage_code != t.stage_code:
            db.add(TaskEvent(task_id=t.id, kind="stage", user_id=current_user.id,
                             from_value=_stage_name(route, t.stage_code),
                             to_value=_stage_name(route, payload.stage_code),
                             note=payload.note))
            # Колонка ставится вместе со стадией: код без колонки — задача,
            # которой нет на общей доске.
            work_state.apply_stage(t, route, payload.stage_code)
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
        # Работу мог поручить маршрут — тогда он ждёт исхода. Отметка ставится в
        # той же транзакции, что и закрытие: доставка пойдёт фоном, но потерять
        # исход нельзя — работа уже сделана, второй раз её никто не сделает.
        if payload.status in ("done", "cancelled"):
            from app.services import errands
            waiting = await errands.close(db, t, payload.status)
            if waiting is not None:
                db.add(TaskEvent(
                    task_id=t.id, kind="status", user_id=current_user.id,
                    actor_name="Процесс", to_value="исход уехал в процесс",
                    note=f"процесс {waiting.process_id}"))

    # Правка поля — тоже событие. Молча сдвинутый срок или снятая срочность
    # рушат доверие к следу: работа «сама» перестала гореть, и объяснить это
    # некому. В YouTrack и Jira любое изменение поля попадает в историю.
    def field_changed(name: str, was: Any, now: Any) -> None:
        nonlocal logged
        db.add(TaskEvent(task_id=t.id, kind="field", user_id=current_user.id,
                         from_value=f"{name}: {was if was not in (None, '') else '—'}"[:200],
                         to_value=str(now if now not in (None, "") else "—")[:200],
                         note=payload.note))
        logged = True

    if payload.priority is not None and payload.priority != t.priority:
        field_changed("срочность", t.priority, payload.priority)
        t.priority = payload.priority
    if payload.due_at is not None and payload.due_at != t.due_at:
        field_changed("срок",
                      t.due_at.strftime("%d.%m.%Y") if t.due_at else None,
                      payload.due_at.strftime("%d.%m.%Y"))
        t.due_at = payload.due_at
    if payload.title is not None and payload.title.strip() != t.title:
        field_changed("заголовок", t.title, payload.title.strip())
        t.title = payload.title.strip()
    if payload.description is not None and (payload.description or None) != t.description:
        # Текст описания в след не тащим — он бывает на восемь тысяч знаков;
        # важен факт правки и автор, сам текст виден в карточке.
        field_changed("описание", "правка", "правка")
        t.description = payload.description or None
    if payload.object_id is not None and (payload.object_id or None) != t.object_id:
        field_changed("объект", t.object_id, payload.object_id or None)
        t.object_id = payload.object_id or None
    # Проект назначается только задаче, у которой его не было. Перенос между
    # проектами означал бы перевыпуск номера — `TF-42` в проекте `LG` не значит
    # ничего, — а старый номер к этому времени уже разошёлся по переписке.
    # Перенос сделаем отдельно, когда понадобится, и вместе с историей номера.
    if payload.project_id and t.project_id is None:
        prj = await db.get(TaskProject, _uuid_or_400(payload.project_id, "project_id"))
        if prj is None or prj.company_id != t.company_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный проект")
        prj.counter += 1
        t.project_id, t.project_number = prj.id, prj.counter
        field_changed("проект", None, f"{prj.code} · {prj.name}")
    elif payload.project_id and t.project_id is not None             and str(t.project_id) != payload.project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Задача уже в проекте: перенос между проектами пока не делаем")
    # Версии — след для заявителя, поэтому их смена попадает в историю задачи, а
    # не меняется молча. Пустая строка снимает версию.
    for field, label in (("fix_version_id", "исправлено в версии"),
                         ("found_version_id", "обнаружено в версии")):
        value = getattr(payload, field)
        if value is None:
            continue
        new_v = await _version_or_400(db, value, t.project_id, field) if value else None
        if new_v == getattr(t, field):
            continue
        was = await db.get(TaskVersion, getattr(t, field)) if getattr(t, field) else None
        now_v = await db.get(TaskVersion, new_v) if new_v else None
        field_changed(label, was.name if was else None, now_v.name if now_v else None)
        setattr(t, field, new_v)
    # Спринт — то же правило, что у версии: он живёт на проекте, и чужой отрезок
    # задаче не подходит. Пустая строка возвращает задачу в бэклог.
    if payload.sprint_id is not None:
        new_sp = None
        if payload.sprint_id:
            sp = await db.get(TaskSprint, _uuid_or_400(payload.sprint_id, "sprint_id"))
            if sp is None or sp.company_id != t.company_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный спринт")
            if t.project_id is None or sp.project_id != t.project_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Спринт принадлежит другому проекту")
            if sp.state == "closed":
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Спринт закрыт: его итог уже подведён")
            new_sp = sp.id
        if new_sp != t.sprint_id:
            was_sp = await db.get(TaskSprint, t.sprint_id) if t.sprint_id else None
            now_sp = await db.get(TaskSprint, new_sp) if new_sp else None
            field_changed("спринт", was_sp.name if was_sp else "бэклог",
                          now_sp.name if now_sp else "бэклог")
            t.sprint_id = new_sp
    if payload.visibility is not None and payload.visibility != t.visibility:
        # Смена круга видимости — событие: «кто закрыл задачу от компании» должно
        # быть видно, иначе это тихое действие с большими последствиями.
        field_changed("видимость",
                      "вся компания" if t.visibility == "company" else "ограниченный круг",
                      "вся компания" if payload.visibility == "company" else "ограниченный круг")
        t.visibility = payload.visibility
    if payload.estimate is not None:
        est = parse_duration(payload.estimate) if payload.estimate.strip() else None
        if payload.estimate.strip() and est is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Не разобрал оценку. Пишите «4ч», «1,5ч» или «90м»")
        if est != t.estimate_minutes:
            field_changed("оценка", human_duration(t.estimate_minutes), human_duration(est))
            t.estimate_minutes = est

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
    # Отклик исполнителя: двинул стадию или написал в ленту. По этой отметке
    # считается время реакции — иначе эскалация уходит по задаче, которую уже
    # взяли в работу, и её перестают читать.
    if (t.reacted_at is None and current_user.id == t.assignee_id
            and (logged or payload.note)):
        t.reacted_at = datetime.now(timezone.utc)
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
    # Наблюдатель подписался, чтобы знать судьбу работы, а узнавал о ней последним:
    # письма уходили только упомянутым и новому исполнителю. Шлём на закрытии и на
    # передаче — на двух событиях, ради которых за задачей и следят. Реплики сюда не
    # входят намеренно: для «позовите меня в обсуждение» есть упоминание.
    await _notify_watchers(db, t, current_user, payload, mentioned,
                           handed_over=bool(new_assignee_email))
    return out


async def _notify_watchers(db: AsyncSession, t: Task, actor: User,
                          payload: TaskAction, mentioned: list[tuple[str, str]],
                          *, handed_over: bool = False) -> None:
    """Письмо наблюдателям: работа закрыта или сменила исполнителя.

    Правило «о чём уведомляем» живёт здесь, а не у вызывающего: иначе второй
    вызов из соседней ручки однажды разошёлся бы с первым, и наблюдатели начали
    бы получать письма о каждой правке срока.

    Реплики сюда не входят намеренно — для «позовите меня в обсуждение» есть
    упоминание. Того, кто действие совершил, и тех, кому письмо уже ушло другим
    поводом, из списка убираем: два письма об одном событии человек читает как
    ошибку системы.
    """
    closing = payload.status in ("done", "cancelled")
    if not closing and not handed_over:
        return
    already = {email for _, email in mentioned if email}
    already.add(actor.email)
    rows = (await db.execute(
        select(User.email).join(TaskWatcher, TaskWatcher.user_id == User.id)
        .where(TaskWatcher.task_id == t.id))).scalars().all()
    targets = sorted({email for email in rows if email and email not in already})
    if not targets:
        return
    if closing:
        verb = "выполнена" if payload.status == "done" else "отменена"
        subject = f"Задача №{t.number} {verb}: {t.title}"
        body = f"{verb.capitalize()}: {actor.name or actor.email}"
    else:
        subject = f"Задача №{t.number} передана: {t.title}"
        body = f"Передал: {actor.name or actor.email}"
    if payload.note:
        body = f"{body}\n\n{payload.note}"
    task_mail.send_notice_async(targets, subject, body)


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
    cid = await _assert_work(payload.company_id, current_user, db)
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
            work_state.apply_stage(t, route, payload.stage_code)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    if not await _can_view_task(db, cid, current_user, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
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
    cid = await _assert_work(company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    att = await db.get(TaskAttachment, _uuid_or_400(attachment_id, "attachment_id"))
    if att is None or att.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вложение не найдено")
    if att.uploaded_by != current_user.id:
        await _assert_actor(db, cid, current_user, t)
    await db.delete(att)
    await db.commit()
    return {"deleted": attachment_id}


@router.post("/{task_id}/events/{event_id}/pin")
async def pin_event(
    task_id: str,
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Закрепить или открепить реплику ленты.

    Договорённость, к которой возвращаются («решили ставить в субботу»), не
    должна тонуть в тридцати событиях. Закрепление — переключатель: повторное
    нажатие снимает.
    """
    cid = await _assert_work(company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    await _assert_actor(db, cid, current_user, t)
    ev = await db.get(TaskEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    ev.pinned = not ev.pinned
    await db.commit()
    return {"id": str(ev.id), "pinned": ev.pinned}


# ── Команды одной строкой ────────────────────────────────────────────────
#
# Как в YouTrack: «на меня срочная», «стадия диагностика», «срок завтра»,
# «метка стройка», «время 2ч». Смысл не в экзотике, а в скорости — руки не
# уходят с клавиатуры, и одну строку можно применить сразу к нескольким
# задачам. Разбор живёт на сервере: клиентов у ручки уже двое, и два парсера
# начали бы понимать команды по-разному.

# Слова срочности и разбор срока живут в языке запросов: «срочная» должна
# значить одно и то же и в отборе, и в команде над пачкой.
_CMD_PRIORITY = work_query.CMD_PRIORITY
_CMD_STATUS = {
    "выполнена": "done", "выполнено": "done", "готово": "done", "done": "done",
    "отменена": "cancelled", "отменить": "cancelled", "отмена": "cancelled",
    "открыть": "open", "вернуть": "open", "open": "open",
}


_cmd_due = work_query.cmd_due


class CommandIn(BaseModel):
    company_id: str
    task_ids: list[str] = Field(min_length=1, max_length=200)
    command: str = Field(min_length=1, max_length=300)


@router.post("/command")
async def apply_command(
    payload: CommandIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Применить команду к задачам одной строкой.

    Разбираем во что можем, а неузнанное возвращаем списком — молча проглотить
    половину команды хуже, чем сказать «этого я не понял»: человек уверен, что
    срок поставлен, а он нет.
    """
    cid = await _assert_work(payload.company_id, current_user, db)
    words = payload.command.split()
    action: dict[str, Any] = {}
    unknown: list[str] = []
    note_parts: list[str] = []
    labels: list[str] = []
    work: str | None = None
    # Версия и спринт разрешаются не здесь, а на каждой задаче: одно и то же
    # «1.4» может существовать в двух проектах, и пачка задач бывает из разных.
    version_name: str | None = None
    sprint_name: str | None = None

    people = {(n or "").lower(): u for u, n in (await db.execute(
        select(User.id, User.name).join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == cid))).all()}
    label_rows = {(n or "").lower(): i for i, n in (await db.execute(
        select(TaskLabel.id, TaskLabel.name).where(TaskLabel.company_id == cid))).all()}
    projects = {(c or "").lower(): i for i, c in (await db.execute(
        select(TaskProject.id, TaskProject.code)
        .where(TaskProject.company_id == cid,
               TaskProject.is_archived.is_(False)))).all()}
    versions = {(pid, (n or "").lower()): i for i, pid, n in (await db.execute(
        select(TaskVersion.id, TaskVersion.project_id, TaskVersion.name)
        .where(TaskVersion.company_id == cid,
               TaskVersion.state != "cancelled"))).all()}
    sprints = {(pid, (n or "").lower()): i for i, pid, n in (await db.execute(
        select(TaskSprint.id, TaskSprint.project_id, TaskSprint.name)
        .where(TaskSprint.company_id == cid, TaskSprint.state != "closed"))).all()}
    sprint_titles = {name for _pid, name in sprints}
    types = (await db.execute(select(TaskType).where(TaskType.company_id == cid))).scalars().all()
    stages = {s.get("name", "").lower(): s.get("code")
              for ty in types for s in (ty.route or []) if s.get("name")}
    stages.update({s["name"].lower(): s["code"] for s in DEFAULT_ROUTE})

    i = 0
    while i < len(words):
        w = words[i].lower()
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in ("на", "for") and nxt.lower() in ("меня", "me"):
            action["assignee_id"] = str(current_user.id)
            i += 2
            continue
        if w in ("срочность", "priority") and nxt.lower() in _CMD_PRIORITY:
            action["priority"] = _CMD_PRIORITY[nxt.lower()]
            i += 2
            continue
        if w in _CMD_PRIORITY:            # «срочная» без слова «срочность»
            action["priority"] = _CMD_PRIORITY[w]
            i += 1
            continue
        if w in _CMD_STATUS:
            action["status"] = _CMD_STATUS[w]
            i += 1
            continue
        if w in ("проект", "project") and nxt:
            pid = projects.get(nxt.lower())
            if pid:
                action["project_id"] = str(pid)
                i += 2
                continue
        if w in ("версия", "version") and nxt:
            version_name = nxt
            i += 2
            continue
        if w in ("спринт", "sprint") and nxt:
            # Имя спринта бывает из нескольких слов («Спринт 34»), поэтому берём
            # самую длинную фразу, которую знает хоть один проект, — как со сроком
            # «через 3 дня». «спринт бэклог» возвращает работу обратно: планирование
            # пачкой ходит в обе стороны.
            for take in (3, 2, 1):
                phrase = " ".join(words[i + 1:i + 1 + take])
                if phrase.lower() in sprint_titles or phrase.lower() in _BACKLOG_WORDS:
                    sprint_name = phrase
                    i += 1 + take
                    break
            else:
                unknown.append(f"спринт {nxt}")
                i += 2
            continue
        if w in ("стадия", "state", "stage") and nxt:
            code = stages.get(nxt.lower())
            if code:
                action["stage_code"] = code
                i += 2
                continue
        if w in ("срок", "due") and nxt:
            # Срок бывает из двух слов: «через 3 дня».
            for take in (3, 2, 1):
                phrase = " ".join(words[i + 1:i + 1 + take])
                if phrase and (due := _cmd_due(phrase)) is not None:
                    action["due_at"] = due.isoformat()
                    i += 1 + take
                    break
            else:
                unknown.append(f"{w} {nxt}")
                i += 2
            continue
        if w in ("метка", "тег", "tag") and nxt:
            lid = label_rows.get(nxt.lower())
            (labels.append(str(lid)) if lid else unknown.append(f"метка {nxt}"))
            i += 2
            continue
        if w in ("время", "time") and nxt:
            work = nxt
            i += 2
            continue
        if w in ("кому", "исполнитель", "assign") and nxt:
            # Фамилии хватает: «assign Петров» — люди так и говорят.
            match = next((uid for name, uid in people.items()
                          if name.startswith(nxt.lower())), None)
            (action.update({"assignee_id": str(match)}) if match
             else unknown.append(f"исполнитель {nxt}"))
            i += 2
            continue
        note_parts.append(words[i])
        i += 1

    # Свободный хвост — реплика: «на меня срочная посмотрю завтра» пишет и то,
    # и другое, как в YouTrack.
    if note_parts:
        action["note"] = " ".join(note_parts)
    if not action and not labels and not work and not version_name and not sprint_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Не понял команду. Например: «на меня срочная срок завтра»")

    done, skipped = 0, []
    for raw in payload.task_ids:
        t = await db.get(Task, _uuid_or_400(raw, "task_id"))
        if t is None or t.company_id != cid:
            skipped.append(raw)
            continue
        step = dict(action)
        if version_name:
            vid = versions.get((t.project_id, version_name.lower()))
            if vid is None:
                skipped.append(f"№{t.number}: версия {version_name} не найдена в проекте")
                continue
            step["fix_version_id"] = str(vid)
        if sprint_name:
            if sprint_name.lower() in _BACKLOG_WORDS:
                step["sprint_id"] = ""
            else:
                sid = sprints.get((t.project_id, sprint_name.lower()))
                if sid is None:
                    skipped.append(f"№{t.number}: спринт {sprint_name} не найден в проекте")
                    continue
                step["sprint_id"] = str(sid)
        try:
            await task_action(str(t.id), TaskAction(
                company_id=str(cid), **step), db, current_user)
        except HTTPException as e:
            skipped.append(f"№{t.number}: {e.detail}")
            continue
        for lid in labels:
            await task_action(str(t.id), TaskAction(
                company_id=str(cid), add_label_id=lid), db, current_user)
        if work:
            try:
                await add_work_item(str(t.id), WorkItemIn(
                    company_id=str(cid), duration=work), db, current_user)
            except HTTPException as e:
                skipped.append(f"№{t.number}: время — {e.detail}")
        done += 1

    return {"changed": done, "skipped": skipped, "unknown": unknown,
            "applied": {**{k: v for k, v in action.items() if k != "company_id"},
                        **({"версия": version_name} if version_name else {}),
                        **({"спринт": sprint_name} if sprint_name else {})}}


# ── Учёт времени: план и факт ────────────────────────────────────────────


# «2ч 30м», «1,5 ч», «90м», «45» — люди пишут длительность как придётся, и
# заставлять их вводить минуты числом значит получить учёт, которым не пользуются.
_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ч|час[а-я]*|h|м|мин[а-я]*|m)?", re.IGNORECASE)


def parse_duration(text: str) -> int | None:
    """Строка длительности → минуты. None — разобрать не удалось."""
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None
    total = 0.0
    found = False
    for value, unit in _DUR.findall(raw):
        num = float(value.replace(",", "."))
        u = (unit or "").lower()
        if u.startswith(("ч", "h")):
            total += num * 60
        elif u.startswith(("м", "m")):
            total += num
        else:
            # Голое число без единицы — часы: «поставил 2» человек имеет в виду
            # два часа, а не две минуты.
            total += num * 60
        found = True
    minutes = int(round(total))
    return minutes if found and 0 < minutes <= 60 * 24 * 30 else None


def human_duration(minutes: int | None) -> str:
    if not minutes:
        return "—"
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    return f"{hours} ч" if hours else f"{mins} мин"


class WorkItemIn(BaseModel):
    company_id: str
    # Строкой, а не числом: сервер разбирает «2ч 30м» одинаково для всех клиентов.
    duration: str = Field(min_length=1, max_length=40)
    work_date: date_type | None = None
    description: str | None = Field(None, max_length=500)
    kind: str | None = Field(None, max_length=60)
    user_id: str | None = None       # чья работа; пусто — своя


@router.post("/{task_id}/work", status_code=status.HTTP_201_CREATED)
async def add_work_item(
    task_id: str,
    payload: WorkItemIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Записать время по задаче.

    Записывать может любой, кто задачу видит: время тратит не только исполнитель
    (согласовали, съездили, помогли). За другого человека время заносит только
    участник задачи или администратор — иначе учёт становится местом, где можно
    приписать работу кому угодно.
    """
    cid = await _assert_work(payload.company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    minutes = parse_duration(payload.duration)
    if minutes is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Не разобрал длительность. Пишите «2ч 30м», «1,5ч» или «90м»")
    uid = current_user.id
    if payload.user_id:
        uid = _uuid_or_400(payload.user_id, "user_id")
        if uid != current_user.id:
            await _assert_actor(db, cid, current_user, t)
            if await db.get(UserCompany, (uid, cid)) is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Человек не состоит в пространстве")
    item = TaskWorkItem(
        task_id=t.id, user_id=uid,
        work_date=payload.work_date or datetime.now(timezone.utc).date(),
        minutes=minutes, description=payload.description, kind=payload.kind,
        created_by=current_user.id)
    db.add(item)
    # Время — часть следа работы: «делал три часа» отвечает на «почему так долго».
    db.add(TaskEvent(task_id=t.id, kind="work", user_id=current_user.id,
                     to_value=human_duration(minutes), note=payload.description))
    # Записал время — значит взялся: отдельного «отклика» ждать незачем.
    if t.reacted_at is None and uid == t.assignee_id:
        t.reacted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return {"id": str(item.id), "minutes": item.minutes,
            "duration": human_duration(item.minutes),
            "work_date": item.work_date.isoformat()}


@router.delete("/{task_id}/work/{item_id}")
async def delete_work_item(
    task_id: str,
    item_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Убрать свою запись о работе; чужую — участник задачи или администратор."""
    cid = await _assert_work(company_id, current_user, db)
    t = await _task_or_404(db, cid, task_id)
    item = await db.get(TaskWorkItem, _uuid_or_400(item_id, "item_id"))
    if item is None or item.task_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    if item.user_id != current_user.id and item.created_by != current_user.id:
        await _assert_actor(db, cid, current_user, t)
    await db.delete(item)
    await db.commit()
    return {"deleted": item_id}


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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(payload.company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
    cid = await _assert_work(company_id, current_user, db)
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
                         from_value=key, to_value=st.get("name"),
                         note=_stage_note(st)))
        added += 1
    if ref.mirror_close and result.get("closed") and t.status == "open":
        db.add(TaskEvent(task_id=t.id, kind="status", user_id=current_user.id,
                         from_value=t.status, to_value="done",
                         note="закрыто по зеркалу внешней системы"))
        t.status, t.closed_at = "done", datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ref)
    return {"ok": True, "stages_added": added, **_ref_out(ref)}


def _human_span(seconds: float) -> str:
    """«12 дн 11 ч», «3 ч 20 мин» — столько работа идёт у подрядчика."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "меньше минуты"
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ч" + (f" {minutes} мин" if minutes else "")
    days, hours = divmod(hours, 24)
    return f"{days} дн" + (f" {hours} ч" if hours else "")


def _stage_note(st: dict) -> str | None:
    """Пометка к этапу внешней системы.

    У текущего этапа (нет `date_till`) считаем, сколько он уже идёт: «идёт уже
    12 дн 11 ч» — это и есть ответ на вопрос «работа стоит или движется», ради
    которого чужие этапы вообще вливаются в нашу ленту.
    """
    note = st.get("note")
    start = st.get("date_from")
    if st.get("date_till") or not start:
        return note
    try:
        began = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return note
    if began.tzinfo is None:
        began = began.replace(tzinfo=timezone.utc)
    span = _human_span((datetime.now(timezone.utc) - began).total_seconds())
    return f"{note} · идёт уже {span}" if note else f"идёт уже {span}"


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

# ---------------------------------------------------------------------------
# Исполнительская дисциплина по поручениям
# ---------------------------------------------------------------------------

# Отчётные сутки считаем по рабочему часовому поясу компании — как в отчёте по
# визам: иначе «сделано вчера вечером» уезжало бы в соседний день.
_REPORT_TIMEZONE = ZoneInfo("Europe/Moscow")


def _discipline_percentile(values: list[float], fraction: float) -> float:
    """Перцентиль по возрастающей выборке. Пустая выборка — ноль, а не деление на ноль."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _errand_bounds(date_from: date_type | None, date_to: date_type | None):
    """Границы периода: те же правила, что у отчёта по визам, — чтобы цифры сравнивались."""
    today = datetime.now(_REPORT_TIMEZONE).date()
    selected_to = date_to or today
    selected_from = date_from or selected_to - timedelta(days=89)
    if selected_from > selected_to:
        raise HTTPException(400, "Дата начала периода позже даты окончания")
    if (selected_to - selected_from).days > 366:
        raise HTTPException(400, "Период отчёта не может превышать 367 дней")
    start_at = datetime.combine(selected_from, datetime.min.time(),
                                tzinfo=_REPORT_TIMEZONE).astimezone(timezone.utc)
    end_at = datetime.combine(selected_to + timedelta(days=1), datetime.min.time(),
                              tzinfo=_REPORT_TIMEZONE).astimezone(timezone.utc)
    return selected_from, selected_to, start_at, end_at


@router.get("/reports/discipline")
async def errand_discipline(
    company_id: str = Query(...),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Дисциплина по поручениям: сколько сделано в срок, за сколько и кем.

    Отчёт по визам отвечает на вопрос «как проходит согласование», этот — «как
    делается работа». Считаются они по-разному и смешивать их нельзя: у визы срок
    задаёт круг, у поручения — тот, кто его поставил.

    Когорта — **закрытые за период** поручения: работа попадает в отчёт тогда,
    когда она закончена, иначе долгая задача годами висела бы в знаменателе и
    портила картину месяца, в котором её только поставили.

    Текущий остаток считается отдельно и на «сейчас»: он не про период, а про то,
    что горит прямо в эту минуту.

    Паспорт метрик:

    - «в срок» — закрыто со статусом `done` не позже `due_at`; поручения без срока
      в долю не входят вовсе (их размер выборки показан отдельно): срок, которого
      не ставили, нельзя ни соблюсти, ни нарушить;
    - длительность — календарные часы от постановки до закрытия;
    - по людям — разрез по исполнителю на момент закрытия; человека без закрытых
      поручений в списке нет.
    """
    cid = await _assert_work(company_id, current_user, db)
    # Разрез по людям — не для всех: это оценка работы конкретного человека.
    await _assert_admin(db, cid, current_user,
                        "Поимённый отчёт по дисциплине доступен администратору пространства")
    selected_from, selected_to, start_at, end_at = _errand_bounds(date_from, date_to)

    closed = list((await db.execute(select(Task).where(
        Task.company_id == cid,
        Task.status.in_(("done", "cancelled")),
        Task.closed_at.is_not(None),
        Task.closed_at >= start_at,
        Task.closed_at < end_at,
    ))).scalars())
    users = {r.id: r.name for r in (await db.execute(select(User).where(
        User.id.in_({t.assignee_id for t in closed if t.assignee_id})))).scalars()}         if any(t.assignee_id for t in closed) else {}

    def hours(task: Task) -> float:
        return max(0.0, (task.closed_at - task.created_at).total_seconds() / 3600)

    done = [t for t in closed if t.status == "done"]
    with_due = [t for t in done if t.due_at is not None]
    in_time = [t for t in with_due if t.closed_at <= t.due_at]
    durations = [hours(t) for t in done]

    by_person: dict[uuid.UUID, dict[str, Any]] = {}
    for task in done:
        if task.assignee_id is None:
            continue
        row = by_person.setdefault(task.assignee_id, {
            "user_id": str(task.assignee_id),
            "name": users.get(task.assignee_id) or "—",
            "closed": 0, "with_due": 0, "in_time": 0, "_hours": [],
        })
        row["closed"] += 1
        row["_hours"].append(hours(task))
        if task.due_at is not None:
            row["with_due"] += 1
            if task.closed_at <= task.due_at:
                row["in_time"] += 1
    people = []
    for row in by_person.values():
        spent = row.pop("_hours")
        row["median_hours"] = round(_discipline_percentile(spent, 0.5), 1)
        row["in_time_share"] = (round(row["in_time"] / row["with_due"], 3)
                                if row["with_due"] else None)
        people.append(row)
    # Сначала те, у кого хуже с соблюдением срока: отчёт читают ради этого.
    people.sort(key=lambda value: (value["in_time_share"] if value["in_time_share"] is not None
                                   else 1.0, -value["closed"]))

    now = datetime.now(timezone.utc)
    open_tasks = list((await db.execute(select(Task).where(
        Task.company_id == cid, Task.status == "open"))).scalars())
    overdue = [t for t in open_tasks if t.due_at is not None and t.due_at < now]

    return {
        "date_from": selected_from.isoformat(),
        "date_to": selected_to.isoformat(),
        "cohort": "closed_in_period",
        "time_zone": "Europe/Moscow",
        "as_of": now.isoformat(),
        "closed": len(closed),
        "done": len(done),
        "cancelled": len(closed) - len(done),
        "with_due": len(with_due),
        "in_time": len(in_time),
        "in_time_share": round(len(in_time) / len(with_due), 3) if with_due else None,
        "median_hours": round(_discipline_percentile(durations, 0.5), 1),
        "p90_hours": round(_discipline_percentile(durations, 0.9), 1),
        "people": people,
        "backlog": {
            "open": len(open_tasks),
            "overdue": len(overdue),
            "oldest_overdue_days": (
                max((now - t.due_at).days for t in overdue) if overdue else 0),
        },
    }
