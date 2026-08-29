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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import (
    Integer, String, Uuid, and_, delete, func, literal, or_, select)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_product, get_current_user
from app.audit import log_audit
from app.database import get_db
from app.models import (
    DocCard, DocKind, DocLabelLink, DocRelation, ServiceLocation, Task, TaskLabel,
    TaskLabelLink, TaskProject, TaskType, User, UserCompany,
)
from app.services import placement, space_time, work_query, work_state

router = APIRouter(prefix="/work", tags=["Трек"])

_LIST_LIMIT = 200
# Занятость режется отдельным пределом и заведомо большим: обрыв здесь
# означает не «показали не всё», а «предложили занятое время как
# свободное». Пара «встреча — участник» на месяц у активного человека —
# сотни строк, и общий предел списка тут мал.
_BUSY_LIMIT = 2000


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
    # Предмет работы: `site:<uuid>`, `contract:<uuid>`, `object:<ключ>`. Реестр
    # документов такой отбор умел с самого начала, лента — нет, и переход
    # «показать всю работу по проекту» приводил на список без единого поручения.
    ref: str | None = Query(None, max_length=120),
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
        # Предмета в языке запросов нет намеренно: его значение само содержит
        # двоеточие (`site:<uuid>`), а разбор строит пары «поле: значение» —
        # первое же двоеточие развалило бы ссылку. Предмет приходит параметром.
        due_to = parsed.get("due_to", due_to)
        q = free_text or q
        query_out = {"parsed": {k: str(v) for k, v in parsed.items()},
                     "unknown": unknown, "text": free_text or None}

    # Правила видимости берём у их хозяев — второй версии этих правил быть не
    # должно, они разойдутся на первой же правке прав.
    from app.routers.docs_router import _readable_doc_clause
    from app.routers.tasks_router import _is_admin, _not_personal, _visible_to

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
        Task.subject_ref.label("subject_ref"),
        Task.project_id.label("project_id"),
        Task.number.label("number"),
        Task.project_number.label("project_number"),
        literal(None, String).label("reg_number"),
        literal(None, String).label("kind_code"),
        Task.priority.label("priority"),
        Task.created_at.label("created_at"),
        Task.updated_at.label("updated_at"),
    # Личные записи в ленту компании не входят: здесь работа, а не чья-то
    # записная книжка. Право видеть своё у автора остаётся (`_visible_to`) —
    # это отбор, а не запрет.
    ).where(Task.company_id == cid, _visible_to(current_user, admin), _not_personal())

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
        DocCard.subject_ref.label("subject_ref"),
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
    if ref:
        # Документ помнит предмет двумя способами — своим полем и явной связью;
        # оба одинаково законны, как и в реестре документов. У поручения связь
        # одна. Ссылка вида `object:<ключ>` понимается и как объект: человек,
        # пришедший «показать работу по объекту», не обязан знать, что внутри
        # это разные колонки.
        related = select(DocRelation.doc_id).where(
            DocRelation.company_id == cid,
            DocRelation.doc_id == union.c.id,
            DocRelation.target_ref == ref).exists()
        clauses = [union.c.subject_ref == ref, related]
        if ref.startswith("object:"):
            clauses.append(union.c.object_id == ref.split(":", 1)[1])
        sel = sel.where(or_(*clauses))
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
        "work": await _decorate(db, cid, rows, now, current_user.id),
        "total": total, "limit": limit, "offset": offset,
        "columns": [{"code": c, "name": work_state.COLUMN_NAMES[c]}
                    for c in work_state.COLUMNS],
        **({"query": query_out} if query_out is not None else {}),
    }


async def _decorate(db: AsyncSession, cid: uuid.UUID, rows: list[Any],
                    now: datetime, user_id: uuid.UUID) -> list[dict[str, Any]]:
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

    # Личная отметка приезжает вместе со строкой, одним запросом на всю
    # страницу. Без неё действия раскладки в списках работали вслепую: солнце не
    # залито у взятого в день, «убрать из подборки» не появляется никогда — и
    # по этой причине их пришлось из строк убрать. По ней же строится ось
    # раскладки на доске: колонки считаются из уже полученных данных, второй
    # выдачи для той же доски не заводим.
    marks = await placement.marks_for(
        db, cid, user_id, [f"{o['kind']}:{o['id']}" for o in out])
    for o in out:
        o["mark"] = placement.out(marks.get(f"{o['kind']}:{o['id']}"))
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
    ("own_note", "моя запись"),
    ("unassigned", "никому не поручено"),
    ("own", "мой документ"),
)


@router.get("/mine")
async def work_mine(
    company_id: str = Query(...),
    limit: int = Query(200, ge=1, le=_LIST_LIMIT),
    # Местная дата человека. Пространство растянуто от Владивостока до Москвы, и
    # единого «сегодня» у него нет: во Владивостоке рабочее утро наступает,
    # когда по UTC ещё вчера. Пусто — считаем по UTC, как раньше.
    today: date | None = Query(None),
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
    from app.routers.tasks_router import (
        _is_admin, _my_dated_personal, _not_personal, _visible_to)

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
    # Второе условие — своя работа без исполнителя. Человек, заведший поручение и
    # никому не отдавший его, увидит строку у себя: иначе работа существует, но
    # не показывается никому, и «что на мне» отвечает неправду.
    task_rows = (await db.execute(
        select(Task).where(
            Task.company_id == cid, _visible_to(current_user, admin),
            # Записная книжка целиком в очередь не входит: «личное» в названии
            # раздела должно оставаться правдой, а условие «своё без исполнителя»
            # без этого фильтра втянуло бы её всю. Но запись, которой человек
            # ПОСТАВИЛ СРОК, входит: правило «без срока — заметка, со сроком —
            # дело» держится именно на этом. Личной она не перестаёт быть —
            # очередь своя, её видит только хозяин.
            or_(_not_personal(), _my_dated_personal(current_user)),
            Task.status == "open",
            or_(Task.assignee_id == current_user.id,
                and_(Task.assignee_id.is_(None),
                     Task.author_id == current_user.id)))
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
        # Своя запись со сроком — не «никому не поручено»: поручать её некому,
        # она уже у того, кто её завёл. Отдельное слово, чтобы строка не читалась
        # как забытая работа компании.
        повод = ("own_note" if t.visibility == "personal"
                 else "do" if t.assignee_id else "unassigned")
        put("task", str(t.id), повод, {
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

    # Личная раскладка кладётся поверх очереди одним запросом (этап 14).
    # Отложенное человеком не выбрасывается из выдачи, а помечается: экран
    # решает, показать его в «Отложено» или спрятать из сегодняшнего списка.
    # Выбросить здесь значило бы, что отложенное нельзя ни увидеть, ни вернуть.
    from app.services import placement

    marks = await placement.marks_for(
        db, cid, current_user.id,
        [f"{i['kind']}:{i['id']}" for i in items.values()])
    сегодня = today or space_time.local_date(now, current_user.tz)

    rows = []
    for item in items.values():
        mark = marks.get(f"{item['kind']}:{item['id']}")
        rows.append({**item, "bucket": bucket(item.get("due_at")),
                     "overdue": bucket(item.get("due_at")) == "overdue",
                     "mark": placement.out(mark),
                     "in_day": bool(mark and mark.taken_for == сегодня),
                     "hidden": placement.hidden(mark, сегодня)})
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
    from app.routers.tasks_router import _is_admin, _not_personal, _visible_to

    admin = await _is_admin(db, cid, current_user)
    doc_clause = await _readable_doc_clause(db, cid, current_user)
    counts: dict[str, dict[str, int]] = {
        c: {"doc": 0, "task": 0} for c in work_state.COLUMNS}

    for model, clause, state_expr, key in (
        (Task, and_(_visible_to(current_user, admin), _not_personal()),
         work_state.task_state_sql(Task), "task"),
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


# ---------------------------------------------------------------------------
# Личные напоминания
# ---------------------------------------------------------------------------
class ReminderIn(BaseModel):
    """Своё напоминание о предмете пространства."""
    company_id: str
    target_ref: str
    remind_at: datetime
    note: str | None = None


class ReminderAction(BaseModel):
    """Отложить на N минут, перенести на время или погасить."""
    company_id: str
    snooze_minutes: int | None = None
    remind_at: datetime | None = None
    done: bool | None = None


def _reminder_out(row) -> dict[str, Any]:
    return {
        "id": str(row.id), "target_ref": row.target_ref, "note": row.note,
        "remind_at": row.remind_at, "fired_at": row.fired_at,
        "snooze_count": row.snooze_count,
    }


@router.get("/reminders")
async def reminders_list(
    company_id: str = Query(...),
    pending: bool = Query(False, description="только сработавшие и не погашенные"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Свои напоминания. Чужих не бывает: отбор по `user_id` жёсткий, без
    исключения для администратора — иначе слово «личное» неправда."""
    from app.models import PersonalReminder

    cid = await _assert_work(company_id, current_user, db)
    sel = select(PersonalReminder).where(
        PersonalReminder.company_id == cid,
        PersonalReminder.user_id == current_user.id,
        PersonalReminder.done_at.is_(None))
    if pending:
        sel = sel.where(PersonalReminder.fired_at.is_not(None))
    rows = list((await db.execute(
        sel.order_by(PersonalReminder.remind_at).limit(_LIST_LIMIT))).scalars())
    return {"items": [_reminder_out(r) for r in rows], "total": len(rows)}


@router.post("/reminders", status_code=status.HTTP_201_CREATED)
async def reminder_create(
    payload: ReminderIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Поставить напоминание себе.

    Право на предмет здесь не проверяется намеренно: напоминание не открывает
    ничего — оно хранит ссылку и текст, которые человек написал сам. Проверка
    случится там, где он по ссылке пойдёт.
    """
    from app.services import reminders

    cid = await _assert_work(payload.company_id, current_user, db)
    try:
        row = await reminders.put(db, cid, current_user.id, payload.target_ref,
                                  payload.remind_at, payload.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Время напоминания уже прошло")
    await db.commit()
    return _reminder_out(row)


@router.post("/reminders/{reminder_id}")
async def reminder_action(
    reminder_id: str,
    payload: ReminderAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отложить, перенести или погасить своё напоминание."""
    from app.models import PersonalReminder
    from app.services import reminders

    cid = await _assert_work(payload.company_id, current_user, db)
    row = await db.get(PersonalReminder, _uuid_or_400(reminder_id, "reminder_id"))
    if row is None or row.company_id != cid or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Напоминание не найдено")
    if payload.done:
        row.done_at = datetime.now(timezone.utc)
    elif payload.remind_at is not None:
        await reminders.reschedule(db, row, payload.remind_at)
    elif payload.snooze_minutes is not None:
        await reminders.snooze(db, row, payload.snooze_minutes)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Нечего делать: ни отложить, ни перенести, ни погасить")
    await db.commit()
    return _reminder_out(row)


# ---------------------------------------------------------------------------
# Календарь
# ---------------------------------------------------------------------------
class EventIn(BaseModel):
    """Встреча: время, место, кого зовём."""
    company_id: str
    title: str = Field(min_length=1, max_length=300)
    starts_at: datetime
    ends_at: datetime
    description: str | None = None
    all_day: bool = False
    tz: str = "Europe/Moscow"
    location: str | None = None
    conference_url: str | None = None
    visibility: str = Field("company", pattern="^(company|private|personal)$")
    subject_ref: str | None = None
    # Кого зовём. Пара «идентификатор — обязательность»: необязательный участник
    # не должен блокировать подбор времени, иначе встречу на пятерых не собрать
    # никогда. Простой список идентификаторов принимается тоже — все считаются
    # обязательными.
    attendee_ids: list[str] = Field(default_factory=list)
    optional_ids: list[str] = Field(default_factory=list)
    # От чьего имени собираем: помощник ведёт календарь владельца.
    on_behalf_of: str | None = None
    # Повторение: {"mode": "weekly", "interval": 1}. Час и минута берутся у самой
    # встречи — второе место, где записано «в 10:00», разошлось бы с ней при
    # первом переносе. Пусто — разовая встреча.
    recurrence: dict | None = None
    recurrence_until: date | None = None


class EventAction(BaseModel):
    """Одно действие над встречей: правка, отмена или свой ответ.

    Ответ участника и правка организатора живут в одной ручке намеренно: и то,
    и другое — «что случилось со встречей», а два места обязаны были бы
    одинаково пересчитывать согласия и разошлись бы на первой правке.
    """
    company_id: str
    title: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    conference_url: str | None = None
    attendee_ids: list[str] | None = None
    cancel: bool | None = None
    cancel_reason: str | None = None
    # Правка серии: пустой словарь снимает повторение (созданные встречи
    # остаются — они уже стоят в чужих календарях).
    recurrence: dict | None = None
    recurrence_until: date | None = None
    response: str | None = Field(None, pattern="^(accepted|declined|tentative)$")
    comment: str | None = None
    # Встречное предложение участника. Само по себе ничего не двигает: перенос —
    # решение организатора. Отказ без предложения оставляет его гадать, когда
    # человеку удобно, и переписка уходит в чат, где её потом не найти.
    propose_starts_at: datetime | None = None
    propose_ends_at: datetime | None = None


def _event_out(ev, attendees: list, me: uuid.UUID) -> dict[str, Any]:
    mine = next((a for a in attendees if a.user_id == me), None)
    return {
        "id": str(ev.id), "title": ev.title, "description": ev.description,
        "starts_at": ev.starts_at, "ends_at": ev.ends_at, "all_day": ev.all_day,
        "tz": ev.tz, "location": ev.location, "conference_url": ev.conference_url,
        "visibility": ev.visibility, "status": ev.status,
        "recurrence": ev.recurrence,
        "recurrence_until": (ev.recurrence_until.isoformat()
                             if ev.recurrence_until else None),
        "series_id": str(ev.series_id) if ev.series_id else None,
        "cancel_reason": ev.cancel_reason, "subject_ref": ev.subject_ref,
        "organizer_id": str(ev.organizer_id),
        "is_organizer": ev.organizer_id == me,
        "my_response": mine.response if mine else None,
        "attendees": [{
            "user_id": str(a.user_id), "name": getattr(a, "name", None), "role": a.role,
            "response": a.response, "comment": a.comment,
            "proposed_starts_at": getattr(a, "proposed_starts_at", None),
            "proposed_ends_at": getattr(a, "proposed_ends_at", None),
        } for a in attendees],
    }


async def _attendees(db: AsyncSession, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    """Участники пачкой: иначе на месяце выходит запрос на каждую встречу."""
    from app.models import CalendarAttendee

    if not event_ids:
        return {}
    rows = (await db.execute(
        select(CalendarAttendee, User.name)
        .join(User, User.id == CalendarAttendee.user_id)
        .where(CalendarAttendee.event_id.in_(event_ids)))).all()
    out: dict[uuid.UUID, list] = {}
    for att, name in rows:
        att.name = name  # имя нужно выдаче; в базе оно живёт у пользователя
        out.setdefault(att.event_id, []).append(att)
    return out


def _my_events_clause(user_id: uuid.UUID):
    """Мои встречи: те, что я собрал, и те, куда меня позвали.

    Общий календарь компании сюда не входит намеренно: «все встречи всех» —
    другой экран с другим вопросом, и подмешивать его значит утопить свои три
    встречи в сотне чужих.
    """
    from app.models import CalendarAttendee, CalendarEvent

    return or_(
        CalendarEvent.organizer_id == user_id,
        CalendarEvent.id.in_(select(CalendarAttendee.event_id).where(
            CalendarAttendee.user_id == user_id)),
    )


@router.get("/calendar")
async def calendar_list(
    company_id: str = Query(...),
    date_from: datetime = Query(..., alias="from"),
    date_to: datetime = Query(..., alias="to"),
    # Поиск словами: «когда была планёрка по экосистеме» без него решается перебором
    # месяцев глазами — и человеком, и агентом.
    q: str | None = Query(None, max_length=200),
    # `mine` — мой календарь; `company` — общий календарь компании.
    scope: str = Query("mine", pattern="^(mine|company)$"),
    # Обсуждения ПО ПРЕДМЕТУ: `doc:<uuid>`, `task:<uuid>`.
    subject_ref: str | None = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Встречи периода — пересекающиеся с окном, а не начинающиеся в нём:
    иначе командировка с прошлой недели пропадёт из этой.

    Три вопроса, и у каждого свой круг.

    `mine` — мой календарь: что я собрал и куда меня позвали. Всё остальное сюда
    не подмешивается, иначе свои три встречи тонут в сотне чужих.

    `company` — общий календарь компании, и в нём ТОЛЬКО встречи с кругом «вся
    компания». Закрытые не появляются даже строкой «занято»: для планирования
    есть `/calendar/busy`, который отдаёт интервалы и ничего больше, а общий
    календарь — это витрина, и место в ней закрытому событию значило бы, что
    круг видимости зависит от экрана.

    `subject_ref` — обсуждения по предмету. Здесь круг шире моего: если человек
    видит документ, факт назначенного по нему совещания — часть его истории, и
    прятать его значит заставлять спрашивать в чате «мы вообще собирались?».
    Но шире ровно на встречи компании: закрытая встреча остаётся закрытой.
    """
    from app.models import CalendarEvent

    cid = await _assert_work(company_id, current_user, db)
    if scope == "company":
        круг = CalendarEvent.visibility == "company"
    elif subject_ref:
        круг = or_(_my_events_clause(current_user.id),
                   CalendarEvent.visibility == "company")
    else:
        круг = _my_events_clause(current_user.id)
    sel = select(CalendarEvent).where(
        CalendarEvent.company_id == cid,
        круг,
        CalendarEvent.starts_at < date_to,
        CalendarEvent.ends_at > date_from)
    if subject_ref:
        sel = sel.where(CalendarEvent.subject_ref == subject_ref)
    if q and q.strip():
        игла = f"%{q.strip()}%"
        sel = sel.where(or_(CalendarEvent.title.ilike(игла),
                            CalendarEvent.description.ilike(игла),
                            CalendarEvent.location.ilike(игла)))
    # `total` — сколько встреч ЕСТЬ, а не сколько поместилось. Считать длину
    # обрезанного списка значит уверять человека, что за двухсотой строкой
    # ничего нет: календарь молча терял хвост месяца.
    всего = (await db.execute(
        select(func.count()).select_from(sel.subquery()))).scalar_one()
    rows = list((await db.execute(
        sel.order_by(CalendarEvent.starts_at).limit(_LIST_LIMIT))).scalars())
    parts = await _attendees(db, [r.id for r in rows])
    return {"events": [_event_out(r, parts.get(r.id, []), current_user.id) for r in rows],
            "total": всего,
            # Признак усечения: без него экран не может честно сказать «показаны
            # не все» и выглядит полным.
            "truncated": всего > len(rows)}


@router.get("/calendar/busy")
async def calendar_busy(
    company_id: str = Query(...),
    date_from: datetime = Query(..., alias="from"),
    date_to: datetime = Query(..., alias="to"),
    # Кого проверяем: список id через запятую. Пусто — только себя.
    user_ids: str | None = Query(None, max_length=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кто когда занят в окне — «свободно/занято», а не чужой календарь.

    Отдаём ТОЛЬКО интервалы: начало, конец, признак «весь день». Ни названий, ни
    участников, ни места. Это принципиально: чтобы предложить время, знать предмет
    чужой встречи не нужно, а показать его значило бы открыть чужой календарь тому,
    кого туда не звали.

    Отменённые встречи занятостью не считаются: место освободилось.
    """
    from app.models import CalendarAttendee, CalendarEvent

    cid = await _assert_work(company_id, current_user, db)
    ids = {current_user.id}
    for chunk in (user_ids or "").split(","):
        if chunk.strip():
            ids.add(_uuid_or_400(chunk.strip(), "user_ids"))
    # Только люди этой организации: чужую занятость не отдаём даже интервалами.
    свои = set((await db.execute(select(UserCompany.user_id).where(
        UserCompany.company_id == cid, UserCompany.user_id.in_(ids)))).scalars())

    rows = (await db.execute(
        select(CalendarEvent, CalendarAttendee.user_id)
        .join(CalendarAttendee, CalendarAttendee.event_id == CalendarEvent.id)
        .where(CalendarEvent.company_id == cid,
               # Только назначенные: пока идёт опрос, времени у встречи нет, и
               # шесть предложенных вариантов заняли бы всем участникам
               # полнедели — то есть подбор перестал бы находить что-либо.
               CalendarEvent.status == "planned",
               CalendarAttendee.user_id.in_(свои),
               CalendarAttendee.response != "declined",
               CalendarEvent.starts_at < date_to,
               CalendarEvent.ends_at > date_from)
        .order_by(CalendarEvent.starts_at).limit(_BUSY_LIMIT))).all()

    # Усечение занятости опаснее усечения списка: подбор времени объявил бы
    # занятый интервал свободным. Предел поднят и о его достижении говорится
    # вслух — молчаливое «свободно» тут хуже отказа.
    обрезано = len(rows) >= _BUSY_LIMIT
    занято: dict[str, list] = {str(u): [] for u in свои}
    for ev, uid in rows:
        занято[str(uid)].append({
            "starts_at": ev.starts_at, "ends_at": ev.ends_at, "all_day": ev.all_day,
        })
    # Рабочее окно каждого — вместе с занятостью, одним ответом. Подбор времени
    # без него предлагает восемь утра тому, кто начинает в десять, и полночь
    # тому, кто во Владивостоке: свободно ≠ можно.
    люди = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(свои)))).scalars()}
    return {
        "from": date_from, "to": date_to,
        "truncated": обрезано,
        "people": [{
            "user_id": uid,
            "name": (люди[uuid.UUID(uid)].name if uuid.UUID(uid) in люди else "—"),
            "tz": (люди[uuid.UUID(uid)].tz if uuid.UUID(uid) in люди else None),
            "work_start": (люди[uuid.UUID(uid)].work_start.strftime("%H:%M")
                           if uuid.UUID(uid) in люди else None),
            "work_end": (люди[uuid.UUID(uid)].work_end.strftime("%H:%M")
                         if uuid.UUID(uid) in люди else None),
            "busy": ivs,
        } for uid, ivs in занято.items()],
    }


@router.get("/calendar/{event_id}/ics")
async def calendar_ics(
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Встреча файлом для внешнего календаря.

    Нужна и своим: человек живёт в Outlook или в телефоне, и «есть в Треке» не
    значит «не занят» для того, кто зовёт его туда.
    """
    from app.services import ics

    cid = await _assert_work(company_id, current_user, db)
    # Право участника, а не просто членство в компании. Соседняя карточка
    # встречи это спрашивала, а файл отдавался всякому, кто знает UUID, — вместе
    # с темой, описанием, местом и ссылкой на конференцию. Закрытые переговоры
    # так утекали внутри компании.
    ev = await _event_participant(db, cid, event_id, current_user)
    organizer = await db.get(User, ev.organizer_id)
    текст = ics.event_ics(
        uid=f"{ev.id}@trek.elsyplus", title=ev.title,
        starts_at=ev.starts_at, ends_at=ev.ends_at,
        description=ev.description, location=ev.location,
        url=ev.conference_url,
        organizer_email=organizer.email if organizer else None,
        organizer_name=organizer.name if organizer else None,
        cancelled=ev.status == "cancelled",
        sequence=1 if ev.status == "cancelled" else 0)
    return Response(
        content=текст, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="meeting.ics"'})


@router.get("/calendar/{event_id}")
async def calendar_card(
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Одна встреча целиком: состав, ответы участников, место, ссылка на конференцию.

    Без неё карточку приходилось выуживать из выборки периода — то есть знать
    заранее, в каком месяце искать.
    """
    from app.models import CalendarAttendee, CalendarEvent

    cid = await _assert_work(company_id, current_user, db)
    ev = await db.get(CalendarEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    parts = (await _attendees(db, [ev.id])).get(ev.id, [])
    # Видеть встречу вправе организатор и приглашённые. Правило то же, что у выборки
    # (`_my_events_clause`): прямая ссылка не должна обходить то, что закрывает список.
    if ev.organizer_id != current_user.id and not any(
            a.user_id == current_user.id for a in parts):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")
    return _event_out(ev, parts, current_user.id)


@router.post("/calendar", status_code=status.HTTP_201_CREATED)
async def calendar_create(
    payload: EventIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Собрать встречу. Организатор — участник по определению: иначе в
    собственном календаре он свою же встречу не увидит."""
    from app.models import CalendarAttendee, CalendarEvent

    cid = await _assert_work(payload.company_id, current_user, db)
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Встреча не может кончаться раньше, чем начинается")
    # Помощник собирает встречу ОТ ИМЕНИ владельца календаря: организатором
    # становится владелец, иначе выданное полномочие бесполезно — секретарь
    # заводил бы встречи на себя. Кто именно нажал, видно в журнале.
    организатор = current_user.id
    if payload.on_behalf_of:
        владелец = _uuid_or_400(payload.on_behalf_of, "on_behalf_of")
        if not await can_manage_calendar(db, cid, владелец, current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Вам не доверяли вести этот календарь")
        организатор = владелец
        await log_audit(db, actor=current_user, company_id=cid,
                        action="calendar.on_behalf", target=str(владелец))
    ev = CalendarEvent(
        company_id=cid, organizer_id=организатор, title=payload.title.strip(),
        description=payload.description or None,
        starts_at=payload.starts_at, ends_at=payload.ends_at,
        all_day=payload.all_day, tz=payload.tz, location=payload.location or None,
        conference_url=payload.conference_url or None,
        visibility=payload.visibility, subject_ref=payload.subject_ref or None,
        recurrence=(payload.recurrence or None),
        recurrence_until=payload.recurrence_until)
    db.add(ev)
    await db.flush()

    необязательные = {_uuid_or_400(i, "optional_ids") for i in payload.optional_ids}
    ids = ({организатор, current_user.id}
           | {_uuid_or_400(i, "attendee_ids") for i in payload.attendee_ids}
           | необязательные)
    # Зовём только людей этой компании: приглашение постороннему открыло бы ему
    # карточку встречи вместе с предметом и составом участников.
    свои = set((await db.execute(select(UserCompany.user_id).where(
        UserCompany.company_id == cid, UserCompany.user_id.in_(ids)))).scalars())
    for uid in ids & свои:
        db.add(CalendarAttendee(
            event_id=ev.id, user_id=uid,
            # Необязательный участник не блокирует подбор времени: иначе
            # приглашённый «для сведения» руководитель закрывает все слоты, хотя
            # встреча может пройти без него.
            role="optional" if uid in необязательные else "required",
            response="accepted" if uid == организатор else "pending"))
    await db.flush()
    parts = await _attendees(db, [ev.id])
    await db.commit()
    return _event_out(ev, parts.get(ev.id, []), current_user.id)


@router.post("/calendar/{event_id}")
async def calendar_action(
    event_id: str,
    payload: EventAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Изменить встречу, отменить её или ответить на приглашение."""
    from app.models import CalendarAttendee, CalendarEvent
    from app.services import reminders

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await db.get(CalendarEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    parts = (await _attendees(db, [ev.id])).get(ev.id, [])
    приглашён = any(a.user_id == current_user.id for a in parts)
    if ev.organizer_id != current_user.id and not приглашён:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")

    # Встречное предложение — второе (и последнее), что участник может сделать
    # со встречей помимо ответа. Время оно не двигает: перенос остаётся решением
    # организатора, иначе любой приглашённый переставлял бы чужие календари.
    if payload.propose_starts_at is not None and payload.propose_ends_at is not None:
        mine = next((a for a in parts if a.user_id == current_user.id), None)
        if mine is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Предлагать время может только приглашённый")
        if payload.propose_ends_at <= payload.propose_starts_at:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Конец не может быть раньше начала")
        mine.proposed_starts_at = payload.propose_starts_at
        mine.proposed_ends_at = payload.propose_ends_at
        # Предложивший другое время считается отказавшимся от нынешнего: иначе в
        # составе он выглядит согласившимся на час, который сам просит поменять.
        mine.response = "declined"
        mine.responded_at = datetime.now(timezone.utc)
        mine.comment = payload.comment or None
        await db.commit()
        return _event_out(ev, parts, current_user.id)

    # Свой ответ — единственное, что участник может сделать со встречей.
    if payload.response is not None:
        mine = next((a for a in parts if a.user_id == current_user.id), None)
        if mine is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Отвечать может только приглашённый")
        mine.response = payload.response
        mine.responded_at = datetime.now(timezone.utc)
        mine.comment = payload.comment or None
        await db.commit()
        return _event_out(ev, parts, current_user.id)

    # Помощник ведёт календарь владельца: перенести и отменить встречу — ровно
    # та работа, ради которой полномочие и выдают. Проверка та же, что у гостей и
    # материалов, — второй способ спросить «вправе ли он» разошёлся бы с первым.
    if not await can_manage_calendar(db, cid, ev.organizer_id, current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Менять встречу может тот, кто её собрал, или его помощник")

    if payload.cancel:
        # Не удаляем: встреча уже стоит в чужих календарях, и молча исчезнувшая
        # означает, что кто-то придёт в пустую переговорную.
        ev.status = "cancelled"
        ev.cancel_reason = (payload.cancel_reason or "").strip() or None
        await reminders.drop_for(db, f"event:{ev.id}")
        if ev.recurrence:
            # Отменяя голову серии, гасим и продолжение: иначе завтра проход
            # материализации заведёт следующую планёрку отменённой встречи.
            # Уже созданные будущие отменяем тоже — они стоят в чужих календарях
            # и должны показаться зачёркнутыми, а не пропасть.
            ev.recurrence = None
            for future in (await db.execute(select(CalendarEvent).where(
                    CalendarEvent.series_id == ev.id,
                    CalendarEvent.starts_at >= datetime.now(timezone.utc),
                    CalendarEvent.status != "cancelled"))).scalars():
                future.status = "cancelled"
                future.cancel_reason = ev.cancel_reason
                await reminders.drop_for(db, f"event:{future.id}")
        await db.commit()
        return _event_out(ev, parts, current_user.id)

    if payload.recurrence is not None and ev.series_id is not None:
        # Повторение живёт только у ГОЛОВЫ. Иначе порождённая встреча начинает
        # порождать своё продолжение, и серия ветвится. Интерфейс это знает и
        # поля не показывает, но правило обязано стоять на сервере: клиент у
        # ручки не один.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Это встреча из серии. Повторение задаётся у первой встречи серии")
    if payload.recurrence is not None:
        # Пустой словарь снимает повторение. Уже созданные встречи остаются: они
        # стоят в чужих календарях, и «выключил серию — исчезли три планёрки»
        # означает, что люди придут в пустую переговорную.
        ev.recurrence = payload.recurrence or None
    if payload.recurrence_until is not None:
        ev.recurrence_until = payload.recurrence_until

    время_сдвинулось = False
    if payload.starts_at is not None or payload.ends_at is not None:
        starts = payload.starts_at or ev.starts_at
        ends = payload.ends_at or ev.ends_at
        if ends <= starts:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Встреча не может кончаться раньше, чем начинается")
        время_сдвинулось = starts != ev.starts_at or ends != ev.ends_at
        ev.starts_at, ev.ends_at = starts, ends
    if payload.title is not None and payload.title.strip():
        ev.title = payload.title.strip()
    for поле in ("description", "location", "conference_url"):
        значение = getattr(payload, поле)
        if значение is not None:
            setattr(ev, поле, значение.strip() or None)

    if payload.attendee_ids is not None:
        хотим = {current_user.id} | {_uuid_or_400(i, "attendee_ids") for i in payload.attendee_ids}
        свои = set((await db.execute(select(UserCompany.user_id).where(
            UserCompany.company_id == cid, UserCompany.user_id.in_(хотим)))).scalars())
        хотим &= свои
        есть = {a.user_id: a for a in parts}
        for uid in хотим - set(есть):
            db.add(CalendarAttendee(event_id=ev.id, user_id=uid, response="pending"))
        for uid, att in есть.items():
            if uid not in хотим:
                await db.delete(att)

    if время_сдвинулось:
        # «Буду в 10» не равно «буду в 18»: перенос обнуляет согласия, иначе
        # организатор считает, что кворум есть, а половина не придёт.
        for att in parts:
            if att.user_id != current_user.id:
                att.response = "pending"
                att.responded_at = None
    await db.flush()
    parts = (await _attendees(db, [ev.id])).get(ev.id, [])
    await db.commit()
    return _event_out(ev, parts, current_user.id)


# ---------------------------------------------------------------------------
# Личная раскладка (этап 14 «Трека»)
# ---------------------------------------------------------------------------
# Очередь отвечает «что от меня ждут». Раскладка — «что я с этим решил»: взял в
# день, отложил до даты, положил в свою подборку, пометил важным. Ничего в предмете
# при этом не меняется и никому, кроме хозяина, не видно; наружу видно
# объективное — срок, состояние, просрочка.
#
# Подборка эксклюзивна: предмет лежит в одной или ни в одной. Иначе доска по подборкам
# перестаёт быть доской — карточка висит в трёх колонках, и перенос становится
# загадкой «переместить или добавить».


class ListIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=60)


class ListAction(BaseModel):
    company_id: str
    name: str | None = Field(None, min_length=1, max_length=60)
    # Место в списке: человек раскладывает свои подборки по важности, и порядок
    # хранится, а не пересчитывается по имени или дате.
    position: int | None = Field(None, ge=0, le=999)
    delete: bool = False
    reviewed: bool = False


class PlaceIn(BaseModel):
    """Одно движение раскладки. Переданное меняется, остальное стоит."""
    company_id: str
    target_ref: str = Field(min_length=3, max_length=120)
    list_id: str | None = None
    drop_list: bool = False
    taken_for: date | None = None
    drop_day: bool = False
    defer_until: date | None = None
    undefer: bool = False
    starred: bool | None = None
    position: int | None = None
    clear: bool = False


async def _my_lists(db: AsyncSession, cid: uuid.UUID, user: User):
    from app.models import PersonalList

    return list((await db.execute(select(PersonalList).where(
        PersonalList.company_id == cid, PersonalList.user_id == user.id)
        .order_by(PersonalList.position, PersonalList.created_at))).scalars())


# ---------------------------------------------------------------------------
# Партнёрский контур встречи: гость без учётной записи и открытые ему материалы
# ---------------------------------------------------------------------------
class GuestIn(BaseModel):
    company_id: str
    email: str = Field(min_length=3, max_length=255)
    name: str | None = Field(None, max_length=255)
    # Сколько дней живёт ссылка. Тридцать по умолчанию: встречу назначают
    # заранее, но не на полгода, а вечная ссылка раскрывает встречу и материалы
    # ровно столько, сколько живёт чужой почтовый ящик.
    days: int = Field(30, ge=1, le=180)


class GuestAction(BaseModel):
    company_id: str
    revoke: bool = False


class MaterialIn(BaseModel):
    company_id: str
    # Пока только документ: у него есть редакция, номер и снимок — то есть через
    # месяц можно ответить, что именно человек видел. У задачи и записи такого
    # нет, и открывать их наружу нечем.
    target_ref: str = Field(pattern="^doc:[0-9a-fA-F-]{36}$")
    days: int = Field(30, ge=1, le=180)


async def can_manage_calendar(db: AsyncSession, cid: uuid.UUID,
                              owner_id: uuid.UUID, user: User) -> bool:
    """Вправе ли человек вести календарь этого владельца.

    Сам владелец — всегда. Помощник — если ему выдали полномочие: он действует
    от СВОЕГО имени с пометкой «от имени N», и в журнале видно обоих. Общий
    доступ к учётной записи решал бы ту же задачу и терял ответ на вопрос
    «кто перенёс».
    """
    from app.models import CalendarDelegate

    if owner_id == user.id:
        return True
    строка = (await db.execute(select(CalendarDelegate.id).where(
        CalendarDelegate.company_id == cid,
        CalendarDelegate.owner_id == owner_id,
        CalendarDelegate.delegate_id == user.id,
        CalendarDelegate.revoked_at.is_(None)))).scalar_one_or_none()
    return строка is not None


async def _event_of_organizer(db: AsyncSession, cid: uuid.UUID, event_id: str,
                              user: User):
    """Встреча, которой этот человек распоряжается: собранная им или та, чей
    организатор выдал ему полномочие вести свой календарь."""
    from app.models import CalendarEvent

    ev = await db.get(CalendarEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    if not await can_manage_calendar(db, cid, ev.organizer_id, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Звать и открывать материалы может тот, кто собрал "
                            "встречу, или его помощник")
    return ev


@router.post("/calendar/{event_id}/guests", status_code=status.HTTP_201_CREATED)
async def guest_invite(
    event_id: str,
    payload: GuestIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Позвать внешнего участника.

    Учётной записи ему не заводим: она дала бы место в составе компании ради
    одной встречи. Гость опознаётся одноразовой ссылкой, как получатель
    документа, и токен виден ровно один раз — в этом ответе.
    """
    from app.models import CalendarGuest
    from app.routers import invite_router

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    почта = payload.email.strip().lower()
    if "@" not in почта:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен адрес почты")
    есть = (await db.execute(select(CalendarGuest).where(
        CalendarGuest.event_id == ev.id,
        func.lower(CalendarGuest.email) == почта,
        CalendarGuest.revoked_at.is_(None)))).scalar_one_or_none()
    if есть is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Этот адрес уже приглашён. Отзовите прежнюю ссылку, "
                            "если нужна новая")
    сырой = invite_router.new_token()
    guest = CalendarGuest(
        event_id=ev.id, email=почта,
        name=(payload.name or "").strip() or None,
        token_hash=invite_router.token_hash(сырой), token_prefix=сырой[:8],
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.days))
    db.add(guest)
    await db.commit()
    return {"id": str(guest.id), "email": guest.email, "name": guest.name,
            "response": guest.response,
            # Единственное место, где токен виден: дальше он живёт у гостя.
            "token": сырой}


@router.get("/calendar/{event_id}/guests")
async def guest_list(
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кого позвали снаружи и что они ответили. Токенов здесь нет и не будет."""
    from app.models import CalendarGuest, CalendarMaterial

    cid = await _assert_work(company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    guests = list((await db.execute(select(CalendarGuest).where(
        CalendarGuest.event_id == ev.id,
        CalendarGuest.revoked_at.is_(None))
        .order_by(CalendarGuest.created_at))).scalars())
    materials = list((await db.execute(select(CalendarMaterial).where(
        CalendarMaterial.event_id == ev.id)
        .order_by(CalendarMaterial.created_at))).scalars())
    return {
        "guests": [{
            "id": str(g.id), "email": g.email, "name": g.name,
            "response": g.response, "comment": g.comment,
            "opened_at": g.opened_at,
            "proposed_starts_at": g.proposed_starts_at,
            "proposed_ends_at": g.proposed_ends_at,
        } for g in guests],
        "materials": [{
            "id": str(m.id), "target_ref": m.target_ref, "title": m.title,
            "url": m.share_url,
        } for m in materials],
    }


@router.post("/calendar/{event_id}/guests/{guest_id}")
async def guest_action(
    event_id: str,
    guest_id: str,
    payload: GuestAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отозвать приглашение. Строку не удаляем: ответ гостя — часть истории
    встречи, а отозванная ссылка отвечает так же, как несуществующая."""
    from app.models import CalendarGuest

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    guest = await db.get(CalendarGuest, _uuid_or_400(guest_id, "guest_id"))
    if guest is None or guest.event_id != ev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Приглашение не найдено")
    if payload.revoke:
        guest.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(guest.id), "revoked": guest.revoked_at is not None}


@router.post("/calendar/{event_id}/materials", status_code=status.HTTP_201_CREATED)
async def material_open(
    event_id: str,
    payload: MaterialIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Открыть гостям материал встречи.

    Приглашение само по себе не открывает ничего: позвать человека обсудить
    договор и дать ему договор — разные решения. Каждый материал открывается
    поимённо и СОХРАНЯЕТ СОБСТВЕННЫЕ ПРАВА: для документа заводится обычная
    гостевая ссылка, отзыв которой не отменяет встречу, а отмена встречи не
    отзывает её.
    """
    from app.models import CalendarMaterial, DocShareLink
    from app.routers import doc_share_router, docs_router

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    doc_id = payload.target_ref.split(":", 1)[1]
    d = await docs_router._doc_or_404(db, cid, doc_id)
    # Право открыть наружу — право отправлять, а не читать: показать документ
    # партнёру и прочитать его самому это разные полномочия.
    await docs_router._assert_doc_permission(db, cid, d, current_user, "send")
    if not d.reg_number:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Сначала зарегистрируйте документ: наружу уходит номер")

    сырой = doc_share_router.new_token()
    link = DocShareLink(
        company_id=cid, doc_id=d.id,
        token_hash=doc_share_router.token_hash(сырой),
        token_prefix=сырой[:8],
        recipient_name=None, recipient_email=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.days),
        created_by=current_user.id)
    link.version_snapshot, link.card_snapshot = await docs_router._share_snapshots(db, d)
    db.add(link)
    await db.flush()

    row = CalendarMaterial(
        event_id=ev.id, target_ref=payload.target_ref, title=d.title,
        share_id=link.id, share_url="/doc-share/" + сырой,
        created_by=current_user.id)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "target_ref": row.target_ref,
            "title": row.title, "url": row.share_url}


@router.post("/calendar/{event_id}/materials/{material_id}/close")
async def material_close(
    event_id: str,
    material_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Закрыть материал: снять его со встречи и отозвать его ссылку.

    Отзываем именно ту ссылку, которую сами и завели, — не трогая прочие: у
    документа их бывает несколько, и закрытие материала встречи не должно
    отбирать документ у того, кому его отправляли отдельно.
    """
    from app.models import CalendarMaterial, DocShareLink

    cid = await _assert_work(company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    row = await db.get(CalendarMaterial, _uuid_or_400(material_id, "material_id"))
    if row is None or row.event_id != ev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")
    if row.share_id:
        link = await db.get(DocShareLink, row.share_id)
        if link is not None and link.revoked_at is None:
            link.revoked_at = datetime.now(timezone.utc)
    await db.delete(row)
    await db.commit()
    return {"closed": True}


class PollIn(BaseModel):
    company_id: str
    # Варианты времени. Три-шесть — то, что человек способен сравнить; двадцать
    # означают, что организатор не выбирал, а свалил выбор на других.
    options: list[dict] = Field(min_length=2, max_length=8)


class VoteIn(BaseModel):
    company_id: str
    option_id: str
    vote: str = Field(pattern="^(yes|maybe|no)$")


class PickIn(BaseModel):
    company_id: str
    option_id: str


@router.post("/calendar/{event_id}/poll", status_code=status.HTTP_201_CREATED)
async def poll_open(
    event_id: str,
    payload: PollIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Превратить встречу в опрос времени.

    Опрос — состояние встречи, а не отдельная сущность: гости, материалы, файл
    для чужого календаря и отмена продолжают работать тем же кодом. Пока идёт
    опрос, встреча занятостью не считается — иначе шесть предложенных вариантов
    заняли бы всем участникам полнедели.
    """
    from app.models import CalendarPollOption

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    if ev.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Встреча отменена")
    await db.execute(delete(CalendarPollOption).where(
        CalendarPollOption.event_id == ev.id))
    for o in payload.options:
        начало = o.get("starts_at")
        конец = o.get("ends_at")
        if not начало or not конец:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "У варианта нужны начало и конец")
        н = datetime.fromisoformat(str(начало))
        к = datetime.fromisoformat(str(конец))
        if к <= н:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Конец варианта не может быть раньше начала")
        db.add(CalendarPollOption(event_id=ev.id, starts_at=н, ends_at=к))
    ev.status = "poll"
    await db.commit()
    return {"status": ev.status, "options": len(payload.options)}


@router.get("/calendar/{event_id}/poll")
async def poll_read(
    event_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Варианты и голоса. Видит всякий, кого позвали: голосование и есть их дело."""
    from app.models import CalendarAttendee, CalendarEvent, CalendarPollOption, CalendarPollVote

    cid = await _assert_work(company_id, current_user, db)
    ev = await db.get(CalendarEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    свой = ev.organizer_id == current_user.id or (await db.execute(
        select(CalendarAttendee.id).where(
            CalendarAttendee.event_id == ev.id,
            CalendarAttendee.user_id == current_user.id))).scalar_one_or_none()
    if not свой:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")
    options = list((await db.execute(select(CalendarPollOption).where(
        CalendarPollOption.event_id == ev.id)
        .order_by(CalendarPollOption.starts_at))).scalars())
    голоса = (await db.execute(select(CalendarPollVote).where(
        CalendarPollVote.option_id.in_([o.id for o in options])))).scalars().all() \
        if options else []
    свод: dict[uuid.UUID, dict[str, int]] = {
        o.id: {"yes": 0, "maybe": 0, "no": 0} for o in options}
    мой: dict[str, str] = {}
    for v in голоса:
        свод[v.option_id][v.vote] = свод[v.option_id].get(v.vote, 0) + 1
        if v.user_id == current_user.id:
            мой[str(v.option_id)] = v.vote
    return {
        "status": ev.status,
        "options": [{
            "id": str(o.id), "starts_at": o.starts_at, "ends_at": o.ends_at,
            "votes": свод[o.id], "my_vote": мой.get(str(o.id)),
        } for o in options],
    }


@router.post("/calendar/{event_id}/poll/vote")
async def poll_vote(
    event_id: str,
    payload: VoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Свой голос за вариант. Повторное нажатие меняет его, а не добавляет
    второй: «за вторник шестеро» должно означать шестерых."""
    from app.models import CalendarPollOption, CalendarPollVote

    cid = await _assert_work(payload.company_id, current_user, db)
    opt = await db.get(CalendarPollOption, _uuid_or_400(payload.option_id, "option_id"))
    if opt is None or str(opt.event_id) != event_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вариант не найден")
    await _event_participant(db, cid, event_id, current_user)
    строка = (await db.execute(select(CalendarPollVote).where(
        CalendarPollVote.option_id == opt.id,
        CalendarPollVote.user_id == current_user.id))).scalar_one_or_none()
    if строка is None:
        строка = CalendarPollVote(option_id=opt.id, user_id=current_user.id)
        db.add(строка)
    строка.vote = payload.vote
    await db.commit()
    return {"option_id": str(opt.id), "vote": строка.vote}


@router.post("/calendar/{event_id}/poll/pick")
async def poll_pick(
    event_id: str,
    payload: PickIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Выбрать вариант: опрос кончился, встреча получила время.

    Варианты снимаются, а согласия обнуляются: голос «подходит» это готовность
    рассмотреть, а не обещание прийти. Оставить их значило бы записать людей на
    встречу, о которой они ещё не знают.
    """
    from app.models import CalendarAttendee, CalendarPollOption

    cid = await _assert_work(payload.company_id, current_user, db)
    ev = await _event_of_organizer(db, cid, event_id, current_user)
    opt = await db.get(CalendarPollOption, _uuid_or_400(payload.option_id, "option_id"))
    if opt is None or opt.event_id != ev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вариант не найден")
    ev.starts_at, ev.ends_at = opt.starts_at, opt.ends_at
    ev.status = "planned"
    await db.execute(delete(CalendarPollOption).where(
        CalendarPollOption.event_id == ev.id))
    for a in (await db.execute(select(CalendarAttendee).where(
            CalendarAttendee.event_id == ev.id))).scalars():
        a.response = "pending"
        a.responded_at = None
    await db.commit()
    return {"starts_at": ev.starts_at, "ends_at": ev.ends_at, "status": ev.status}


async def _event_participant(db: AsyncSession, cid: uuid.UUID, event_id: str,
                             user: User):
    """Встреча, к которой человек имеет отношение: организатор или приглашённый."""
    from app.models import CalendarAttendee, CalendarEvent

    ev = await db.get(CalendarEvent, _uuid_or_400(event_id, "event_id"))
    if ev is None or ev.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Встреча не найдена")
    if ev.organizer_id == user.id:
        return ev
    есть = (await db.execute(select(CalendarAttendee.id).where(
        CalendarAttendee.event_id == ev.id,
        CalendarAttendee.user_id == user.id))).scalar_one_or_none()
    if есть is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Это не ваша встреча")
    return ev


# ── Делегирование ──────────────────────────────────────────────────────────
class DelegateIn(BaseModel):
    company_id: str
    delegate_id: str


@router.get("/calendar-delegates")
async def delegates_list(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кому я доверил вести свой календарь и чьи календари веду я."""
    from app.models import CalendarDelegate

    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(select(CalendarDelegate).where(
        CalendarDelegate.company_id == cid,
        CalendarDelegate.revoked_at.is_(None),
        or_(CalendarDelegate.owner_id == current_user.id,
            CalendarDelegate.delegate_id == current_user.id)))).scalars().all()
    имена = {u.id: u.name for u in (await db.execute(select(User).where(
        User.id.in_({r.owner_id for r in rows} | {r.delegate_id for r in rows}))
    )).scalars()} if rows else {}
    return {
        "mine": [{"id": str(r.id), "user_id": str(r.delegate_id),
                  "name": имена.get(r.delegate_id, "—")}
                 for r in rows if r.owner_id == current_user.id],
        "for_others": [{"id": str(r.id), "user_id": str(r.owner_id),
                        "name": имена.get(r.owner_id, "—")}
                       for r in rows if r.delegate_id == current_user.id],
    }


@router.post("/calendar-delegates", status_code=status.HTTP_201_CREATED)
async def delegate_add(
    payload: DelegateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Доверить помощнику вести свой календарь.

    Полномочие выдаёт ТОЛЬКО владелец календаря — ни администратор, ни сам
    помощник: иначе «ведение календаря» становится способом получить доступ
    без ведома того, чей он.
    """
    from app.models import CalendarDelegate

    cid = await _assert_work(payload.company_id, current_user, db)
    кому = _uuid_or_400(payload.delegate_id, "delegate_id")
    if кому == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Свой календарь вы и так ведёте")
    if await db.get(UserCompany, (кому, cid)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Человек не в этой компании")
    строка = (await db.execute(select(CalendarDelegate).where(
        CalendarDelegate.company_id == cid,
        CalendarDelegate.owner_id == current_user.id,
        CalendarDelegate.delegate_id == кому))).scalar_one_or_none()
    if строка is None:
        строка = CalendarDelegate(company_id=cid, owner_id=current_user.id,
                                  delegate_id=кому, created_by=current_user.id)
        db.add(строка)
    строка.revoked_at = None
    await log_audit(db, actor=current_user, company_id=cid,
                    action="calendar.delegate", target=str(кому))
    await db.commit()
    return {"id": str(строка.id)}


@router.post("/calendar-delegates/{delegate_id}/revoke")
async def delegate_revoke(
    delegate_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Забрать полномочие. Отзывает владелец календаря."""
    from app.models import CalendarDelegate

    cid = await _assert_work(company_id, current_user, db)
    строка = await db.get(CalendarDelegate, _uuid_or_400(delegate_id, "delegate_id"))
    if строка is None or строка.company_id != cid or строка.owner_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Полномочие не найдено")
    строка.revoked_at = datetime.now(timezone.utc)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="calendar.delegate.revoke", target=str(строка.delegate_id))
    await db.commit()
    return {"revoked": True}


# ── Заготовки встреч ───────────────────────────────────────────────────────
class TemplateIn(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    duration_minutes: int = Field(60, ge=5, le=8 * 60)
    location: str | None = None
    attendee_ids: list[str] = Field(default_factory=list)
    recurrence: dict | None = None


@router.get("/calendar-templates")
async def templates_list(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Заготовки встреч компании: планёрка, приёмка, разбор."""
    from app.models import CalendarTemplate

    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(select(CalendarTemplate).where(
        CalendarTemplate.company_id == cid)
        .order_by(CalendarTemplate.name))).scalars().all()
    return {"templates": [{
        "id": str(t.id), "name": t.name, "title": t.title,
        "description": t.description, "duration_minutes": t.duration_minutes,
        "location": t.location,
        "attendee_ids": (t.attendee_ids or {}).get("ids", []),
        "recurrence": t.recurrence,
    } for t in rows]}


@router.post("/calendar-templates", status_code=status.HTTP_201_CREATED)
async def template_add(
    payload: TemplateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сохранить заготовку. Состав хранится списком идентификаторов: заготовка —
    черновик, и ссылочная целостность на уволившегося мешала бы больше, чем
    помогала."""
    from app.models import CalendarTemplate

    cid = await _assert_work(payload.company_id, current_user, db)
    есть = (await db.execute(select(CalendarTemplate).where(
        CalendarTemplate.company_id == cid,
        func.lower(CalendarTemplate.name) == payload.name.strip().lower()
    ))).scalar_one_or_none()
    if есть is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Заготовка с таким именем есть")
    row = CalendarTemplate(
        company_id=cid, name=payload.name.strip(), title=payload.title.strip(),
        description=payload.description or None,
        duration_minutes=payload.duration_minutes,
        location=payload.location or None,
        attendee_ids={"ids": payload.attendee_ids},
        recurrence=payload.recurrence or None,
        created_by=current_user.id)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "name": row.name}


@router.post("/calendar-templates/{template_id}/delete")
async def template_delete(
    template_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Убрать заготовку. Встречи, собранные по ней, не трогаются: они уже живут
    сами по себе."""
    from app.models import CalendarTemplate

    cid = await _assert_work(company_id, current_user, db)
    row = await db.get(CalendarTemplate, _uuid_or_400(template_id, "template_id"))
    if row is None or row.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заготовка не найдена")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.get("/lists")
async def lists_mine(
    company_id: str = Query(...),
    today: date | None = Query(None, description="местная дата человека"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Мои подборки со счётчиком и давностью обзора.

    Давность считается здесь, а не на экране: «не открывали 12 дней» — это
    единственная механика, из-за которой подборка «потом» не превращается в
    кладбище, и она обязана быть свойством продукта, а не привычки человека.
    """
    from app.models import PersonalMark

    cid = await _assert_work(company_id, current_user, db)
    rows = await _my_lists(db, cid, current_user)
    counts = dict((await db.execute(
        select(PersonalMark.list_id, func.count()).where(
            PersonalMark.company_id == cid,
            PersonalMark.user_id == current_user.id,
            PersonalMark.list_id.is_not(None)).group_by(PersonalMark.list_id))).all())
    now = datetime.now(timezone.utc)
    сегодня = today or space_time.local_date(now, current_user.tz)
    # Числа для пунктов навигации считаются здесь же, одним проходом: пункт,
    # считающий себя сам, означает пять запросов на каждое открытие «Трека».
    day, starred, deferred, loose = (await db.execute(select(
        func.count().filter(PersonalMark.taken_for == сегодня),
        func.count().filter(PersonalMark.starred.is_(True)),
        func.count().filter(PersonalMark.deferred_until > сегодня),
        func.count().filter(PersonalMark.list_id.is_(None)),
    ).where(PersonalMark.company_id == cid,
            PersonalMark.user_id == current_user.id))).one()
    return {
        "lists": [{
            "id": str(r.id), "name": r.name, "position": r.position,
            "count": counts.get(r.id, 0),
            "stale_days": ((now - r.reviewed_at).days if r.reviewed_at else None),
        } for r in rows],
        "counts": {"day": day, "starred": starred,
                   "deferred": deferred, "loose": loose},
    }


@router.post("/lists", status_code=status.HTTP_201_CREATED)
async def list_create(
    payload: ListIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Завести подборку. Имени достаточно: цвет и описание превратили бы движение
    руки в заполнение формы."""
    from app.models import PersonalList

    cid = await _assert_work(payload.company_id, current_user, db)
    rows = await _my_lists(db, cid, current_user)
    if any(r.name.lower() == payload.name.strip().lower() for r in rows):
        raise HTTPException(status.HTTP_409_CONFLICT, "Такая подборка уже есть")
    row = PersonalList(company_id=cid, user_id=current_user.id,
                       name=payload.name.strip(), position=len(rows))
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "name": row.name, "position": row.position,
            "count": 0, "stale_days": None}


@router.post("/lists/{list_id}")
async def list_action(
    list_id: str,
    payload: ListAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Переименовать, отметить обзор или удалить подборку.

    Удаление подборки не трогает предметы: у отметок обнуляется `list_id`, и работа
    возвращается в «Не разложено». Личная раскладка не вправе ничего удалять из
    работы компании — это её главное свойство.
    """
    from app.models import PersonalList

    cid = await _assert_work(payload.company_id, current_user, db)
    row = await db.get(PersonalList, _uuid_or_400(list_id, "list_id"))
    if row is None or row.company_id != cid or row.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подборка не найдена")
    if payload.delete:
        await db.delete(row)
        await db.commit()
        return {"deleted": True}
    if payload.name:
        row.name = payload.name.strip()
    if payload.position is not None:
        row.position = payload.position
    if payload.reviewed:
        row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    # Давность обзора считается так же, как в списке: `None` тут означало бы «ни
    # разу не открывали» у подборки, которую вчера просмотрели.
    now = datetime.now(timezone.utc)
    return {"id": str(row.id), "name": row.name, "position": row.position,
            "stale_days": (now - row.reviewed_at).days if row.reviewed_at else None}


async def _due_of(db: AsyncSession, cid: uuid.UUID, target_ref: str):
    """Срок предмета — он ограничивает отложение. Личное сокрытие не вправе
    уносить работу за её собственный срок."""
    kind, _, key = target_ref.partition(":")
    try:
        oid = uuid.UUID(key)
    except ValueError:
        return None
    if kind == "task":
        row = await db.get(Task, oid)
    elif kind == "doc":
        row = await db.get(DocCard, oid)
    else:
        return None
    return row.due_at if row is not None and row.company_id == cid else None


@router.post("/place")
async def place(
    payload: PlaceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Разложить предмет у себя: в день, в подборку, под звезду или до даты."""
    from app.services import placement

    cid = await _assert_work(payload.company_id, current_user, db)
    list_id = None
    if payload.list_id:
        from app.models import PersonalList

        lst = await db.get(PersonalList, _uuid_or_400(payload.list_id, "list_id"))
        if lst is None or lst.company_id != cid or lst.user_id != current_user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Подборка не найдена")
        list_id = lst.id

    try:
        row = await placement.put(
            db, cid, current_user.id, payload.target_ref,
            list_id=list_id, taken_for=payload.taken_for,
            deferred_until=payload.defer_until, starred=payload.starred,
            position=payload.position, clear=payload.clear,
            drop_day=payload.drop_day, undefer=payload.undefer,
            today=space_time.local_date(datetime.now(timezone.utc),
                                        current_user.tz),
            due_at=(await _due_of(db, cid, payload.target_ref)
                    if payload.defer_until else None))
    except placement.DeferRefused as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if row is not None and payload.drop_list:
        row.list_id = None
    await db.commit()
    return {"target_ref": payload.target_ref,
            "mark": placement.out(row) if row is not None else None}


@router.get("/frequent")
async def frequent_assignees(
    company_id: str = Query(...),
    limit: int = Query(6, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Кому этот человек чаще всего поручает работу.

    Считается по его же постановкам за три месяца, а не по справочнику: список
    «кому кинуть» должен состоять из тех, кому кидают, и у кладовщика он другой,
    чем у главного бухгалтера. Пусто у новичка — это нормальное состояние, а не
    ошибка: тогда рядом просто нет быстрых плашек.
    """
    since = datetime.now(timezone.utc) - timedelta(days=90)
    cid = await _assert_work(company_id, current_user, db)
    rows = (await db.execute(
        select(Task.assignee_id, func.count().label("n")).where(
            Task.company_id == cid, Task.author_id == current_user.id,
            Task.assignee_id.is_not(None),
            Task.assignee_id != current_user.id,
            Task.created_at >= since)
        .group_by(Task.assignee_id).order_by(func.count().desc()).limit(limit))).all()
    ids = [r[0] for r in rows]
    if not ids:
        return {"people": []}
    people = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(ids)))).scalars()}
    return {"people": [{
        "id": str(i), "name": (people[i].name or people[i].email or "—"),
        "count": n,
    } for i, n in rows if i in people]}


@router.get("/placed")
async def placed(
    company_id: str = Query(...),
    list_id: str | None = Query(None, alias="list"),
    scope: str = Query("list", pattern="^(list|day|carry|deferred|starred|loose)$"),
    on: date | None = Query(None, description="день для scope=day; пусто — сегодня"),
    today: date | None = Query(None, description="местная дата человека"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Что лежит в подборке, в дне, в отложенном или под звездой.

    Строка уходит отсюда сама, по факту действия: закрытое поручение и
    выведенный документ не показываются. Убирать руками нечего — необходимость
    уборки и есть то, из-за чего личные списки зарастают.
    """
    from app.models import PersonalMark
    from app.routers.docs_router import _readable_doc_clause
    from app.routers.tasks_router import _is_admin, _visible_to
    from app.services import placement

    cid = await _assert_work(company_id, current_user, db)
    # `on` называет день, о котором спрашивают (календарь), `today` — какой день
    # сейчас у человека. Разные вопросы: первый про экран, второй про часовой
    # пояс, и подменять один другим нельзя.
    сегодня = today or space_time.local_date(
        datetime.now(timezone.utc), current_user.tz)
    sel = select(PersonalMark).where(PersonalMark.company_id == cid,
                                     PersonalMark.user_id == current_user.id)
    if scope == "list":
        if not list_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не сказано, какая подборка")
        sel = sel.where(PersonalMark.list_id == _uuid_or_400(list_id, "list"))
    elif scope == "day":
        # Календарь спрашивает про конкретный день, «Сегодня» — про сегодняшний:
        # это один и тот же вопрос с разной датой, и второго разреза не нужно.
        sel = sel.where(PersonalMark.taken_for == (on or сегодня))
    elif scope == "carry":
        # Вчерашнее, взятое и не закрытое. Само в новый день не переезжает:
        # сброс работает только там, где рядом стоит утренний вопрос «вчера
        # осталось столько — переносим?», иначе человек молча теряет невзятое.
        sel = sel.where(PersonalMark.taken_for.is_not(None),
                        PersonalMark.taken_for < сегодня)
    elif scope == "deferred":
        sel = sel.where(PersonalMark.deferred_until > сегодня)
    elif scope == "starred":
        sel = sel.where(PersonalMark.starred.is_(True))
    else:
        sel = sel.where(PersonalMark.list_id.is_(None))
    marks = list((await db.execute(sel.order_by(
        PersonalMark.position, PersonalMark.created_at).limit(_LIST_LIMIT))).scalars())
    if not marks:
        return {"items": []}

    by_kind: dict[str, dict[uuid.UUID, PersonalMark]] = {"task": {}, "doc": {}}
    for m in marks:
        kind, _, key = m.target_ref.partition(":")
        if kind in by_kind:
            try:
                by_kind[kind][uuid.UUID(key)] = m
            except ValueError:
                continue

    items: list[dict[str, Any]] = []
    if by_kind["task"]:
        admin = await _is_admin(db, cid, current_user)
        for t in (await db.execute(select(Task).where(
                Task.company_id == cid, Task.id.in_(by_kind["task"]),
                Task.status == "open", _visible_to(current_user, admin)))).scalars():
            items.append({
                "kind": "task", "id": str(t.id), "title": t.title,
                "key": f"№{t.number}",
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "personal": t.visibility == "personal",
                "mark": placement.out(by_kind["task"][t.id]),
            })
    if by_kind["doc"]:
        clause = await _readable_doc_clause(db, cid, current_user)
        for d in (await db.execute(select(DocCard).where(
                DocCard.company_id == cid, DocCard.id.in_(by_kind["doc"]),
                DocCard.status.in_(("draft", "registered", "in_force")),
                clause))).scalars():
            items.append({
                "kind": "doc", "id": str(d.id), "title": d.title,
                "key": d.reg_number or "черновик",
                "due_at": d.due_at.isoformat() if d.due_at else None,
                "personal": False,
                "mark": placement.out(by_kind["doc"][d.id]),
            })
    items.sort(key=lambda r: ((r["mark"] or {}).get("position", 0),
                              r.get("due_at") or "9999"))
    return {"items": items}
