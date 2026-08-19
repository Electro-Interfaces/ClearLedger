"""
Приложение «Заявки» — трекер пространства (docs/TICKETS.md репозитория ecosystem-deploy).

Движок заявок — контур Поддержки: стадии, SLA, эскалации, внешние стороны живут там.
Здесь — витрина для сотрудников пространства: список, срез руководителя, регламентные
задачи. Базы Ядра и Поддержки сведены в одну (схемы core и public), поэтому ЧТЕНИЕ идёт
прямым SQL по public-витрине — вторая правда о заявках в Ядре не заводится. ЗАПИСЬ
(создание) — только через эко-канал приложения (space_projection.create_object_ticket):
там начисляются стадия, SLA и аудит; писать в public.tickets напрямую нельзя.
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.support_scope import support_company_id
from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.space_projection import ProjectionError, create_object_ticket

router = APIRouter(prefix="/tickets", tags=["Заявки"])

# Верхний предел списка: экран листает клиентом, заявки лёгкие.
_LIST_LIMIT = 500


def _uuid_or_400(v: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Невалидный {what}")


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "number": r.display_number or (str(r.number) if r.number is not None else None),
        "title": r.title,
        "status": r.status,
        "stage": r.stage_name,
        "stage_color": r.stage_color,
        "priority": r.priority,
        "type": r.type,
        "category": r.category,
        "responsibility": r.responsibility,
        "assignee": r.assignee_name,
        "object": r.object_name,
        "external_system": r.external_system,
        "sla_deadline": r.sla_deadline.isoformat() if r.sla_deadline else None,
        "sla_breached": bool(r.sla_breached),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
async def list_tickets(
    company_id: str = Query(...),
    scope: str = Query("open", pattern="^(open|mine|closed|all)$"),
    object_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Заявки пространства. scope: open — активные, mine — мои (автор или исполнитель),
    closed — завершённые, all — всё. object_id — объект ПРОСТРАНСТВА (core-id):
    карточка объекта и «Офис» ссылаются на свои заявки; матчим через проекцию
    (service_objects.eco_object_id), на всякий случай принимаем и public-id."""
    cid = await assert_company_member(company_id, current_user, db)
    # Заявки лежат в схеме Поддержки, и company_id там СВОЙ. Без фильтра по карте
    # соответствия компания видела бы чужие заявки (в контейнере их бывает
    # несколько). Нет карты — нет выдачи: пусто честнее, чем чужое.
    support_cid = await support_company_id(db, cid)
    if not support_cid:
        return {"tickets": [], "total": 0}
    cond = "true"
    if scope == "open":
        cond = "t.status not in ('closed','cancelled')"
    elif scope == "closed":
        cond = "t.status in ('closed','cancelled')"
    elif scope == "mine":
        # Автор и исполнитель в Поддержке — её пользователи; матчим по email через
        # public.users: id людей в двух схемах разные, email — общий ключ.
        cond = ("(t.customer_user_id = pu.id or t.assigned_to = pu.id "
                "or t.current_assignee_id = pu.id)")
    if object_id:
        _uuid_or_400(object_id, "object_id")
        cond += " and (so.eco_object_id::text = :oid or t.service_object_id::text = :oid)"
    rows = (await db.execute(text(f"""
        select t.id, t.number, t.display_number, t.title, t.status, t.priority,
               t.type, t.category, t.responsibility, t.external_system,
               t.sla_deadline, t.sla_breached, t.created_at, t.updated_at,
               st.name as stage_name, st.color as stage_color,
               so.name as object_name,
               au.name as assignee_name
        from public.tickets t
        left join public.ticket_stages st on st.id = t.stage_id
        left join public.service_objects so on so.id = t.service_object_id
        left join public.users au on au.id = coalesce(t.current_assignee_id, t.assigned_to)
        left join public.users pu on lower(pu.email) = lower(:email)
        where coalesce(t.is_deleted, false) = false
          and coalesce(t.is_archived, false) = false
          and t.company_id::text = :support_cid
          and {cond}
        order by t.created_at desc
        limit :lim
    """), {"email": current_user.email, "lim": _LIST_LIMIT,
           "support_cid": support_cid,
           **({"oid": object_id} if object_id else {})})).all()
    return {"tickets": [_row(r) for r in rows], "total": len(rows)}


@router.get("/summary")
async def tickets_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Срез руководителя: сколько и где стоит работа. Одним запросом на блок."""
    cid = await assert_company_member(company_id, current_user, db)
    support_cid = await support_company_id(db, cid)
    if not support_cid:
        return {"totals": {}, "by": {}}
    base = ("from public.tickets t where coalesce(t.is_deleted,false)=false "
            "and coalesce(t.is_archived,false)=false "
            "and t.company_id::text = :support_cid")
    totals = (await db.execute(text(f"""
        select count(*) filter (where t.status not in ('closed','cancelled')) as open,
               count(*) filter (where t.status not in ('closed','cancelled')
                                and coalesce(t.sla_breached,false)
                                -- SLA-сигнал — только по СВОИМ заявкам: у зеркал
                                -- внешних систем (HubEx) свой SLA и своя история,
                                -- их просрочка засоряла сигнал тысячами.
                                and coalesce(t.external_system,'') = '') as sla_breached,
               count(*) filter (where t.created_at >= now() - interval '7 days') as created_7d,
               count(*) filter (where t.closed_at >= now() - interval '7 days') as closed_7d,
               count(*) filter (where t.created_at >= now() - interval '30 days') as created_30d,
               count(*) filter (where t.closed_at >= now() - interval '30 days') as closed_30d
        {base}
    """), {"support_cid": support_cid})).one()
    by = {}
    for key, expr in (("responsibility", "coalesce(t.responsibility,'—')"),
                      ("status", "t.status"),
                      ("category", "coalesce(t.category,'—')")):
        rows = (await db.execute(text(f"""
            select {expr} as k, count(*) as n {base}
              and t.status not in ('closed','cancelled')
            group by 1 order by 2 desc limit 12
        """), {"support_cid": support_cid})).all()
        by[key] = [{"key": r.k, "count": r.n} for r in rows]
    assignees = (await db.execute(text("""
        select coalesce(au.name, '— не назначен') as k, count(*) as n
        from public.tickets t
        left join public.users au on au.id = coalesce(t.current_assignee_id, t.assigned_to)
        where coalesce(t.is_deleted,false)=false and coalesce(t.is_archived,false)=false
          and t.company_id::text = :support_cid
          and t.status not in ('closed','cancelled')
        group by 1 order by 2 desc limit 10
    """), {"support_cid": support_cid})).all()
    by["assignee"] = [{"key": r.k, "count": r.n} for r in assignees]
    # Разрез по подразделениям штатной структуры: исполнитель Поддержки → человек
    # Ядра по email → его подразделение. Руководитель видит нагрузку своих отделов.
    departments = (await db.execute(text("""
        select coalesce(od.name, '— без подразделения') as k, count(*) as n
        from public.tickets t
        left join public.users au on au.id = coalesce(t.current_assignee_id, t.assigned_to)
        left join core.users cu on lower(cu.email) = lower(au.email)
        left join core.user_companies uc on uc.user_id = cu.id
        left join core.org_departments od on od.id = uc.department_id
        where coalesce(t.is_deleted,false)=false and coalesce(t.is_archived,false)=false
          and t.status not in ('closed','cancelled')
        group by 1 order by 2 desc limit 12
    """), {"support_cid": support_cid})).all()
    by["department"] = [{"key": r.k, "count": r.n} for r in departments]
    return {
        "open": totals.open, "sla_breached": totals.sla_breached,
        "created_7d": totals.created_7d, "closed_7d": totals.closed_7d,
        "created_30d": totals.created_30d, "closed_30d": totals.closed_30d,
        "by": by,
    }


@router.get("/schedules")
async def list_schedules(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Регламентные (периодические) задачи: движок Поддержки сам порождает заявки
    по interval_days. Здесь — витрина «что и когда должно выполняться»."""
    cid = await assert_company_member(company_id, current_user, db)
    support_cid = await support_company_id(db, cid)
    if not support_cid:
        return {"schedules": []}
    rows = (await db.execute(text("""
        select m.id, m.name, m.description, m.interval_days, m.lead_days,
               m.category, m.priority, m.next_due_date, m.is_active,
               so.name as object_name
        from public.maintenance_schedules m
        left join public.service_objects so on so.id = m.service_object_id
        where m.company_id::text = :support_cid
        order by m.is_active desc, m.next_due_date nulls last
        limit 200
    """), {"support_cid": support_cid})).all()
    return {"schedules": [{
        "id": str(r.id), "name": r.name, "description": r.description,
        "interval_days": r.interval_days, "lead_days": r.lead_days,
        "category": r.category, "priority": r.priority,
        "next_due_date": r.next_due_date.isoformat() if r.next_due_date else None,
        "is_active": bool(r.is_active), "object": r.object_name,
    } for r in rows]}


@router.get("/{ticket_id}")
async def ticket_details(
    ticket_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка заявки: детали + связь с обсуждением + точка эскалации.

    «Из обсуждения» — комната, где заявку родили кнопкой «В заявку»
    (core.chat_ticket_links); скрытый чат самой заявки открывается отдельной
    ручкой чата (ensure), здесь его не трогаем. Эскалация — руководитель
    подразделения исполнителя по штатной структуре; если исполнитель сам
    руководитель — руководитель родительского подразделения.
    """
    cid = await assert_company_member(company_id, current_user, db)
    tid = _uuid_or_400(ticket_id, "ticket_id")
    # Карточка по прямой ссылке — тоже только своей компании: без фильтра
    # идентификатор чужой заявки открывал её целиком.
    support_cid = await support_company_id(db, cid)
    if not support_cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    r = (await db.execute(text("""
        select t.id, t.number, t.display_number, t.title, t.description, t.status,
               t.priority, t.type, t.category, t.responsibility, t.external_system,
               t.sla_deadline, t.sla_breached, t.created_at, t.updated_at,
               st.name as stage_name, st.color as stage_color,
               so.name as object_name, so.eco_object_id,
               au.name as assignee_name, au.email as assignee_email,
               cu.name as author_name
        from public.tickets t
        left join public.ticket_stages st on st.id = t.stage_id
        left join public.service_objects so on so.id = t.service_object_id
        left join public.users au on au.id = coalesce(t.current_assignee_id, t.assigned_to)
        left join public.users cu on cu.id = t.customer_user_id
        where t.id = :tid and coalesce(t.is_deleted, false) = false
          and t.company_id::text = :support_cid
    """), {"tid": str(tid), "support_cid": support_cid})).one_or_none()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")

    # Родившее обсуждение (может не быть: заявка поставлена формой или каналом).
    origin = (await db.execute(text("""
        select l.room_id, cr.name as room_name
        from core.chat_ticket_links l
        join core.chat_rooms cr on cr.id = l.room_id
        where l.ticket_id = :tid
        order by l.created_at
        limit 1
    """), {"tid": str(tid)})).one_or_none()

    # Точка эскалации по штатной структуре (от исполнителя вверх).
    escalation = None
    if r.assignee_email:
        esc = (await db.execute(text("""
            select od.name as dep_name, h.name as head_name, h.id as head_id,
                   cu.id as person_id,
                   pod.name as parent_dep, ph.name as parent_head
            from core.users cu
            join core.user_companies uc on uc.user_id = cu.id
            join core.org_departments od on od.id = uc.department_id
            left join core.users h on h.id = od.head_user_id
            left join core.org_departments pod on pod.id = od.parent_id
            left join core.users ph on ph.id = pod.head_user_id
            where lower(cu.email) = lower(:email)
            limit 1
        """), {"email": r.assignee_email})).one_or_none()
        if esc is not None:
            if esc.head_name and esc.head_id != esc.person_id:
                escalation = {"department": esc.dep_name, "to": esc.head_name}
            elif esc.parent_head:
                # Исполнитель сам руководитель — эскалация уровнем выше.
                escalation = {"department": esc.parent_dep, "to": esc.parent_head}

    return {
        **_row(r),
        "description": r.description,
        "author": r.author_name,
        "eco_object_id": str(r.eco_object_id) if r.eco_object_id else None,
        "origin_room": ({"room_id": str(origin.room_id), "room_name": origin.room_name}
                        if origin else None),
        "escalation": escalation,
    }


class TicketCreate(BaseModel):
    company_id: str
    object_id: str            # объект пространства (core.service_locations.id)
    description: str = Field(min_length=3, max_length=4000)
    title: str | None = Field(None, max_length=300)
    priority: str = Field("medium", pattern="^(low|medium|high|critical)$")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать заявку по объекту. Пишем ТОЛЬКО через эко-канал приложения: там
    стадия, SLA и аудит. Заявки без объекта — этап В2 (docs/TICKETS.md §9)."""
    cid = await assert_company_member(payload.company_id, current_user, db)
    try:
        res = await create_object_ticket(
            db, cid, payload.object_id,
            description=payload.description, title=payload.title,
            priority=payload.priority, author_email=current_user.email,
        )
    except ProjectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return res
