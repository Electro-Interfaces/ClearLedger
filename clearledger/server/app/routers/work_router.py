"""Единый список работы: документы и поручения одной лентой.

Этап 13б трекерного контура. До сих пор «вся работа компании» была двумя
экранами с разными отборами, и вопрос «что у нас в работе по площадке 208»
требовал посмотреть в обоих. Человек приходит с одним вопросом — «что в работе»
— и не должен знать, какой движок за предметом стоит.

Объединяется выдача, а не модель: `doc_cards` и `tasks` остаются раздельными
(`docs/TRACK.md`, раздел 2). Здесь UNION по общей проекции — ключ, род, тип,
заголовок, ответственный, срок, состояние, объект, проект.

Три вещи, из-за которых это не сводится к двум запросам подряд:

1. **Права спрашиваются обе.** У документов свой ACL (`_readable_doc_clause` —
   закрытые карточки, гранты, визы), у поручений своя видимость (`_visible_to`).
   Единый список обязан применить оба правила, иначе объединение станет дырой в
   правах, а не удобством. Правила зовутся из своих роутеров: скопировать их
   сюда значило бы завести вторую версию, которая разойдётся с первой.

2. **Постраничность в базе.** Слить две выборки в приложении можно ровно до
   второй страницы: чтобы отдать строки 100–200 общего порядка, пришлось бы
   тянуть по 200 из каждой таблицы, а дальше только хуже.

3. **Состояние общее.** Колонка считается `work_state` — тем же правилом, что в
   карточке и на доске (этап 13а).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Integer, String, Uuid, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_current_user
from app.database import get_db
from app.models import (
    DocCard, DocKind, DocLabelLink, ServiceLocation, Task, TaskLabel,
    TaskLabelLink, TaskProject, TaskType, User,
)
from app.services import work_query, work_state

router = APIRouter(prefix="/work", tags=["Трек"])

_LIST_LIMIT = 200


async def _assert_work(company_ref: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Право на работу компании — то же, что у обоих контуров по отдельности."""
    try:
        return await assert_company_product(company_ref, user, db, "docs")
    except HTTPException:
        return await assert_company_product(company_ref, user, db, "plan")


def _uuid_or_400(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Неверный {field}") from exc


def _key(row: Any, project_code: str | None) -> str:
    """Как предмет называют вслух: «TF-42», «№17», «Вх-88», «черновик».

    Ключ собирается здесь, а не в SQL: у поручения он зависит от проекта, у
    документа — от того, зарегистрирован ли он. Незарегистрированный документ
    честно называется черновиком: выдуманный номер увёл бы человека искать его
    в журнале.
    """
    if row.kind == "task":
        if project_code and row.project_number:
            return f"{project_code}-{row.project_number}"
        return f"№{row.number}"
    return row.reg_number or "черновик"


@router.get("")
async def list_work(
    company_id: str = Query(...),
    kind: str | None = Query(None, pattern="^(doc|task)$"),
    scope: str = Query("open", pattern="^(open|mine|assigned|done|all)$"),
    state: str | None = Query(None),
    type_id: str | None = Query(None),
    project_id: str | None = Query(None),
    assignee_id: str | None = Query(None),
    object_id: str | None = Query(None),
    label_id: str | None = Query(None),
    author_id: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    # Тот же язык, что в реестре поручений (этап 12): «тип: входящее #мои
    # состояние: на согласовании». Разбирает `work_query` — один разбор на оба
    # списка, иначе «исполнитель: я» значило бы в них разное.
    query: str | None = Query(None, max_length=500),
    due_to: datetime | None = Query(None),
    sort: str = Query("updated", pattern="^-?(updated|created|due)$"),
    limit: int = Query(50, ge=1, le=_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Работа компании одной лентой: документы и поручения вперемешку.

    `kind` — фильтр, а не раздел: «входящие» это отбор по виду документа, а не
    отдельный экран со своей веткой кода.
    """
    cid = await _assert_work(company_id, current_user, db)
    now = datetime.now(timezone.utc)

    query_out: dict[str, Any] | None = None
    if query and query.strip():
        parsed, unknown, free_text = await work_query.parse(db, cid, current_user, query)
        # Разрезы реестра поручений переводятся в разрезы общей ленты: часть из
        # них у документов не существует (наблюдатель, спринт), и молчать об
        # этом нельзя — человек решит, что отобрал, а отбора не было.
        scope_map = {"open": "open", "closed": "done", "mine": "mine",
                     "assigned": "assigned", "all": "all"}
        parsed_scope = parsed.get("scope")
        if parsed_scope in scope_map:
            scope = scope_map[parsed_scope]
        elif parsed_scope == "overdue":
            scope, due_to = "open", due_to or now
        elif parsed_scope == "today":
            scope, due_to = "open", due_to or now + timedelta(days=1)
        elif parsed_scope == "waiting":
            scope, state = "open", "external"
        elif parsed_scope is not None:
            unknown.append("#" + parsed_scope)
        for name in ("backlog", "sprint_id", "fix_version_id", "found_version_id",
                     "stage", "priority"):
            if parsed.get(name) is not None:
                unknown.append(f"{name}: только у поручений")
        kind = parsed.get("kind", kind)
        state = parsed.get("state", state)
        project_id = parsed.get("project_id", project_id)
        assignee_id = parsed.get("assignee_id", assignee_id)
        author_id = parsed.get("author_id", author_id)
        label_id = parsed.get("label_id", label_id)
        type_id = parsed.get("type_id", type_id)
        object_id = parsed.get("object_id", object_id)
        due_to = parsed.get("due_to", due_to)
        q = free_text or q
        query_out = {"parsed": {k: str(v) for k, v in parsed.items()},
                     "unknown": unknown, "text": free_text or None}

    # Правила видимости берём у их хозяев — второй версии этих правил быть не
    # должно, они разойдутся на первой же правке прав.
    from app.routers.docs_router import _readable_doc_clause
    from app.routers.tasks_router import _is_admin, _visible_to

    admin = await _is_admin(db, cid, current_user)
    doc_clause = await _readable_doc_clause(db, cid, current_user)

    task_sel = select(
        Task.id.label("id"),
        literal("task", String).label("kind"),
        Task.title.label("title"),
        work_state.task_state_sql(Task).label("state"),
        Task.status.label("status"),
        Task.stage_code.label("stage_code"),
        Task.type_id.label("type_id"),
        Task.assignee_id.label("responsible_id"),
        Task.author_id.label("author_id"),
        Task.due_at.label("due_at"),
        Task.object_id.label("object_id"),
        Task.project_id.label("project_id"),
        Task.number.label("number"),
        Task.project_number.label("project_number"),
        literal(None, String).label("reg_number"),
        literal(None, String).label("kind_code"),
        Task.priority.label("priority"),
        Task.created_at.label("created_at"),
        Task.updated_at.label("updated_at"),
    ).where(Task.company_id == cid, _visible_to(current_user, admin))

    # Имена колонок задаются явно у обеих половин: UNION берёт их у первой, и
    # при отборе только по документам подзапрос назывался бы `kind_id` вместо
    # `type_id` — фильтры молча промахивались бы мимо колонки.
    doc_sel = select(
        DocCard.id.label("id"),
        literal("doc", String).label("kind"),
        DocCard.title.label("title"),
        work_state.doc_state_sql(DocCard).label("state"),
        DocCard.status.label("status"),
        literal(None, String).label("stage_code"),
        DocCard.kind_id.label("type_id"),
        DocCard.responsible_id.label("responsible_id"),
        DocCard.author_id.label("author_id"),
        DocCard.due_at.label("due_at"),
        DocCard.object_id.label("object_id"),
        literal(None, Uuid).label("project_id"),
        literal(None, Integer).label("number"),
        literal(None, Integer).label("project_number"),
        DocCard.reg_number.label("reg_number"),
        DocCard.kind_code.label("kind_code"),
        literal(None, String).label("priority"),
        DocCard.created_at.label("created_at"),
        DocCard.updated_at.label("updated_at"),
    ).where(DocCard.company_id == cid, doc_clause)

    if kind == "task":
        parts = [task_sel]
    elif kind == "doc":
        parts = [doc_sel]
    else:
        parts = [task_sel, doc_sel]
    union = parts[0].union_all(*parts[1:]).subquery("work") if len(parts) > 1 \
        else parts[0].subquery("work")

    sel = select(union)

    # Разрез — тот же вопрос, что в реестре поручений: что живо, что моё, что
    # закрыто. «Моё» одинаково читается в обоих контурах: я исполнитель работы
    # или ответственный за документ.
    if scope == "open":
        sel = sel.where(union.c.state != "done")
    elif scope == "done":
        sel = sel.where(union.c.state == "done")
    elif scope == "mine":
        sel = sel.where(union.c.state != "done",
                        union.c.responsible_id == current_user.id)
    elif scope == "assigned":
        sel = sel.where(union.c.state != "done",
                        union.c.author_id == current_user.id,
                        or_(union.c.responsible_id.is_(None),
                            union.c.responsible_id != current_user.id))

    if state:
        codes = [c for c in state.split(",") if c in work_state.COLUMNS]
        if not codes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестное состояние")
        sel = sel.where(union.c.state.in_(codes))
    if type_id:
        sel = sel.where(union.c.type_id == _uuid_or_400(type_id, "type_id"))
    if project_id:
        sel = sel.where(union.c.project_id == _uuid_or_400(project_id, "project_id"))
    if assignee_id:
        sel = sel.where(union.c.responsible_id == _uuid_or_400(assignee_id, "assignee_id"))
    if author_id:
        sel = sel.where(union.c.author_id == _uuid_or_400(author_id, "author_id"))
    if object_id:
        sel = sel.where(union.c.object_id == object_id)
    if due_to:
        sel = sel.where(union.c.due_at <= due_to)
    if label_id:
        # Справочник меток общий на оба контура, а связи свои у каждого.
        lid = _uuid_or_400(label_id, "label_id")
        sel = sel.where(or_(
            union.c.id.in_(select(TaskLabelLink.task_id).where(TaskLabelLink.label_id == lid)),
            union.c.id.in_(select(DocLabelLink.doc_id).where(DocLabelLink.label_id == lid)),
        ))
    if q and (text := q.strip()):
        like = f"%{text}%"
        digits = text.lstrip("№#").strip()
        conds = [union.c.title.ilike(like), union.c.reg_number.ilike(like)]
        if digits.isdigit():
            conds.append(union.c.number == int(digits))
        sel = sel.where(or_(*conds))

    total = (await db.execute(
        select(func.count()).select_from(sel.subquery()))).scalar_one()

    desc = sort.startswith("-")
    key = sort.lstrip("-")
    col = {"updated": union.c.updated_at, "created": union.c.created_at,
           "due": union.c.due_at}[key]
    # Срок по возрастанию — сначала ближайшие; без срока уезжает в конец в обоих
    # порядках, иначе голову списка занимает то, что никого не ждёт.
    sel = sel.order_by(col.desc().nullslast() if desc or key != "due"
                       else col.asc().nullslast())

    rows = (await db.execute(sel.limit(limit).offset(offset))).all()
    return {
        "work": await _decorate(db, cid, rows, now),
        "total": total, "limit": limit, "offset": offset,
        "columns": [{"code": c, "name": work_state.COLUMN_NAMES[c]}
                    for c in work_state.COLUMNS],
        **({"query": query_out} if query_out is not None else {}),
    }


async def _decorate(db: AsyncSession, cid: uuid.UUID, rows: list[Any],
                    now: datetime) -> list[dict[str, Any]]:
    """Доклеить имена пачкой: страница списка не ходит в базу построчно."""
    if not rows:
        return []
    people = {i for r in rows for i in (r.responsible_id, r.author_id) if i}
    types = {r.type_id for r in rows if r.type_id}
    projects = {r.project_id for r in rows if r.project_id}
    objects = {r.object_id for r in rows if r.object_id}

    names = {u.id: u.name for u in (await db.execute(
        select(User).where(User.id.in_(people)))).scalars()} if people else {}
    task_types = {t.id: (t.name, t.route) for t in (await db.execute(
        select(TaskType).where(TaskType.id.in_(types)))).scalars()} if types else {}
    doc_kinds = {k.id: k.name for k in (await db.execute(
        select(DocKind).where(DocKind.id.in_(types)))).scalars()} if types else {}
    prjs = {p.id: p.code for p in (await db.execute(
        select(TaskProject).where(TaskProject.id.in_(projects)))).scalars()} if projects else {}
    objs = {o.id: o.name for o in (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.id.in_(objects)))).scalars()} if objects else {}

    ids = [r.id for r in rows]
    labels: dict[uuid.UUID, list[dict[str, str]]] = {i: [] for i in ids}
    for link_model, link_col in ((TaskLabelLink, TaskLabelLink.task_id),
                                 (DocLabelLink, DocLabelLink.doc_id)):
        for owner, lid, name, color in (await db.execute(
            select(link_col, TaskLabel.id, TaskLabel.name, TaskLabel.color)
            .join(TaskLabel, TaskLabel.id == link_model.label_id)
            .where(link_col.in_(ids))
        )).all():
            labels[owner].append({"id": str(lid), "name": name, "color": color})

    out = []
    for r in rows:
        route = task_types.get(r.type_id, (None, None))[1] if r.kind == "task" else None
        stage = next((s.get("name") for s in (route or [])
                      if s.get("code") == r.stage_code), None)
        out.append({
            "id": str(r.id),
            "kind": r.kind,
            "key": _key(r, prjs.get(r.project_id)),
            "title": r.title,
            "type": (task_types.get(r.type_id, (None, None))[0] if r.kind == "task"
                     else doc_kinds.get(r.type_id)),
            "stage": stage,
            **work_state.state_out(r.state),
            "status": r.status,
            "responsible": names.get(r.responsible_id),
            "responsible_id": str(r.responsible_id) if r.responsible_id else None,
            "author": names.get(r.author_id),
            "due_at": r.due_at.isoformat() if r.due_at else None,
            # Просрочка — свойство живой работы: у завершённой срок уже не сигнал.
            "overdue": bool(r.due_at and r.state != "done" and r.due_at < now),
            "object_id": r.object_id,
            "object": objs.get(r.object_id),
            "project": prjs.get(r.project_id),
            "project_id": str(r.project_id) if r.project_id else None,
            "priority": r.priority,
            "labels": labels.get(r.id, []),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


# ── Очередь «На мне» ────────────────────────────────────────────────────────
# Личное разложено по четырём спискам: визы, поручения, ознакомления, свои
# документы. Человек утром хочет знать не «сколько у меня виз», а «что горит», —
# и здесь это один список, сгруппированный по сроку.
#
# Род действия остаётся в строке (`reason`), потому что от него зависит, что с
# предметом делать: расписаться, отметить прочтение или закрыть работу.

# Что человек должен сделать с предметом. Порядок — приоритет показа, когда один
# предмет попадает в очередь дважды: расписаться важнее, чем «мой документ».
_REASONS: tuple[tuple[str, str], ...] = (
    ("approve", "виза"),
    ("acquaint", "ознакомиться"),
    ("do", "работа"),
    ("own", "мой документ"),
)


@router.get("/mine")
async def work_mine(
    company_id: str = Query(...),
    limit: int = Query(200, ge=1, le=_LIST_LIMIT),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Всё, что ждёт лично меня, одной очередью.

    Четыре источника сводятся здесь, а не на экране: иначе клиент собирал бы
    очередь четырьмя запросами и сам решал, что важнее, — а «что горит» это
    вопрос к данным, а не к вёрстке.
    """
    cid = await _assert_work(company_id, current_user, db)
    now = datetime.now(timezone.utc)

    from app.routers.docs_router import approvals_mine, my_acquaints
    from app.routers.tasks_router import _is_admin, _visible_to

    admin = await _is_admin(db, cid, current_user)
    items: dict[tuple[str, str], dict[str, Any]] = {}

    def put(kind: str, item_id: str, reason: str, data: dict[str, Any]) -> None:
        """Один предмет — одна строка. Приоритет рода действия задан `_REASONS`:
        документ, который я и подписываю, и веду, ждёт от меня подписи."""
        key = (kind, item_id)
        order = [r for r, _ in _REASONS]
        if key in items and order.index(items[key]["reason"]) <= order.index(reason):
            return
        items[key] = {"kind": kind, "id": item_id, "reason": reason,
                      "reason_name": dict(_REASONS)[reason], **data}

    # Визы и ознакомления берём у их хозяина: правила замещения, кругов и
    # break-glass живут там, и повторять их здесь значит завести вторую версию.
    approvals = (await approvals_mine(company_id, db, current_user))["approvals"]
    for row in approvals:
        put("doc", row["doc_id"], "approve", {
            "title": row["doc_title"], "key": row["doc_number"] or "черновик",
            "due_at": row["due_at"], "note": row["step_name"],
            "acting_for": row.get("acting_for"),
        })
    acquaints = (await my_acquaints(company_id, db, current_user))["acquaints"]
    for row in acquaints:
        put("doc", row["doc_id"], "acquaint", {
            "title": row["doc_title"], "key": row["doc_number"] or "черновик",
            "due_at": row["due_at"], "note": None, "acquaint_id": row["id"],
        })

    # Поручения на мне и мои документы — из общей проекции: состояние и ключ
    # считаются тем же правилом, что в ленте.
    task_rows = (await db.execute(
        select(Task).where(
            Task.company_id == cid, _visible_to(current_user, admin),
            Task.status == "open", Task.assignee_id == current_user.id)
        .order_by(Task.due_at.asc().nullslast()).limit(limit))).scalars().all()
    projects = {p.id: p.code for p in (await db.execute(select(TaskProject).where(
        TaskProject.id.in_({t.project_id for t in task_rows if t.project_id}))
    )).scalars()} if task_rows else {}
    types = {t.id: t for t in (await db.execute(select(TaskType).where(
        TaskType.id.in_({t.type_id for t in task_rows if t.type_id}))
    )).scalars()} if task_rows else {}
    for t in task_rows:
        code = projects.get(t.project_id)
        route = (types[t.type_id].route if t.type_id in types else None) or []
        put("task", str(t.id), "do", {
            "title": t.title,
            "key": (f"{code}-{t.project_number}" if code and t.project_number
                    else f"№{t.number}"),
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "note": next((s.get("name") for s in route
                          if s.get("code") == t.stage_code), None),
            "state": work_state.task_state(t, route),
        })

    doc_rows = (await db.execute(
        select(DocCard).where(
            DocCard.company_id == cid,
            DocCard.status.in_(("draft", "registered", "in_force")),
            or_(DocCard.responsible_id == current_user.id,
                DocCard.author_id == current_user.id))
        .order_by(DocCard.due_at.asc().nullslast()).limit(limit))).scalars().all()
    for d in doc_rows:
        put("doc", str(d.id), "own", {
            "title": d.title, "key": d.reg_number or "черновик",
            "due_at": d.due_at.isoformat() if d.due_at else None,
            "note": None, "state": work_state.doc_state(d),
        })

    # Группа по сроку — то, ради чего очередь и собрана: человек спрашивает
    # «что горит», а не «сколько у меня виз».
    def bucket(due: str | None) -> str:
        if not due:
            return "later"
        at = datetime.fromisoformat(due)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at < now:
            return "overdue"
        if at < now + timedelta(days=1):
            return "today"
        if at < now + timedelta(days=7):
            return "week"
        return "later"

    rows = []
    for item in items.values():
        rows.append({**item, "bucket": bucket(item.get("due_at")),
                     "overdue": bucket(item.get("due_at")) == "overdue"})
    order = {"overdue": 0, "today": 1, "week": 2, "later": 3}
    rows.sort(key=lambda r: (order[r["bucket"]], r.get("due_at") or "9999"))
    return {
        "mine": rows,
        "buckets": [
            {"code": "overdue", "name": "Горит"},
            {"code": "today", "name": "Сегодня"},
            {"code": "week", "name": "На неделе"},
            {"code": "later", "name": "Без срока"},
        ],
    }


# ── Перенос по доске ────────────────────────────────────────────────────────
# Карточку тянут мышью, а делает это движок предмета: поручение идёт по маршруту
# своего типа, документ — через круг виз. Единая доска не заводит третьего
# способа менять состояние, иначе след работы разошёлся бы с самой работой.


class MoveIn(BaseModel):
    company_id: str
    state: str


@router.post("/{kind}/{item_id}/move")
async def move_work(
    kind: str,
    item_id: str,
    payload: MoveIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Перенести предмет в колонку общей доски.

    Отказ всегда называет причину: карточка, молча прыгнувшая обратно, — загадка,
    а «этот документ не зарегистрирован, а вид этого требует» — ответ.
    """
    cid = await _assert_work(payload.company_id, current_user, db)
    if payload.state not in work_state.COLUMNS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная колонка")
    if payload.state == "external":
        # Внешняя сторона появляется не переносом карточки: работа уезжает
        # наружу вместе с адресатом и возвращается его ответом.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "В «Ждём внешних» работа попадает, когда её отдают наружу — "
            "письмом или заявкой у подрядчика, а не переносом карточки")

    if kind == "task":
        from app.routers.tasks_router import TaskAction, task_action

        task = await db.get(Task, _uuid_or_400(item_id, "item_id"))
        if task is None or task.company_id != cid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Поручение не найдено")
        if payload.state == "done":
            return await task_action(item_id, TaskAction(
                company_id=str(cid), status="done"), db, current_user)
        ttype = await db.get(TaskType, task.type_id) if task.type_id else None
        route = (ttype.route if ttype else None) or []
        target = next((s.get("code") for i, s in enumerate(route)
                       if work_state.stage_column(s, i, len(route)) == payload.state), None)
        if target is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"У типа «{ttype.name if ttype else 'поручение'}» нет стадии в колонке "
                f"«{work_state.COLUMN_NAMES[payload.state]}» — добавьте её в маршрут")
        if task.status != "open":
            return await task_action(item_id, TaskAction(
                company_id=str(cid), status="open", stage_code=target), db, current_user)
        return await task_action(item_id, TaskAction(
            company_id=str(cid), stage_code=target), db, current_user)

    if kind == "doc":
        from app.routers.docs_router import (
            ActionIn, ApprovalStartIn, approval_start, doc_action,
        )

        doc = await db.get(DocCard, _uuid_or_400(item_id, "item_id"))
        if doc is None or doc.company_id != cid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
        if payload.state == "approval":
            # Круг виз стартует своей ручкой: там проверки вида, регистрации и
            # обязательных реквизитов, и обойти их доской нельзя.
            return await approval_start(item_id, ApprovalStartIn(
                company_id=str(cid)), db, current_user)
        if payload.state == "done":
            return await doc_action(item_id, ActionIn(
                company_id=str(cid), status="executed"), db, current_user)
        if payload.state == "in_work" and doc.approval_status == "pending":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Документ на согласовании: круг отменяют в карточке, "
                "чтобы отказ был с причиной и остался в листе")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Документ переводит в это состояние регистрация или подпись — "
            "их делают в карточке")

    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестный род предмета")


@router.get("/summary")
async def work_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сколько работы в каждой колонке — заголовки доски и счётчики разделов."""
    cid = await _assert_work(company_id, current_user, db)
    from app.routers.docs_router import _readable_doc_clause
    from app.routers.tasks_router import _is_admin, _visible_to

    admin = await _is_admin(db, cid, current_user)
    doc_clause = await _readable_doc_clause(db, cid, current_user)
    counts: dict[str, dict[str, int]] = {
        c: {"doc": 0, "task": 0} for c in work_state.COLUMNS}

    for model, clause, state_expr, key in (
        (Task, _visible_to(current_user, admin), work_state.task_state_sql(Task), "task"),
        (DocCard, doc_clause, work_state.doc_state_sql(DocCard), "doc"),
    ):
        for value, count in (await db.execute(
            select(state_expr.label("state"), func.count())
            .where(model.company_id == cid, clause)
            .group_by(state_expr)
        )).all():
            if value in counts:
                counts[value][key] = count

    return {"columns": [{
        "code": c, "name": work_state.COLUMN_NAMES[c],
        "docs": counts[c]["doc"], "tasks": counts[c]["task"],
        "total": counts[c]["doc"] + counts[c]["task"],
    } for c in work_state.COLUMNS]}
