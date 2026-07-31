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

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.space_projection import ProjectionError, create_object_ticket

router = APIRouter(prefix="/tickets", tags=["Заявки"])

# Верхний предел списка: экран листает клиентом, заявки лёгкие.
_LIST_LIMIT = 500


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Заявки пространства. scope: open — активные, mine — мои (автор или исполнитель),
    closed — завершённые, all — всё."""
    await assert_company_member(company_id, current_user, db)
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
          and {cond}
        order by t.created_at desc
        limit :lim
    """), {"email": current_user.email, "lim": _LIST_LIMIT})).all()
    return {"tickets": [_row(r) for r in rows], "total": len(rows)}


@router.get("/summary")
async def tickets_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Срез руководителя: сколько и где стоит работа. Одним запросом на блок."""
    await assert_company_member(company_id, current_user, db)
    base = ("from public.tickets t where coalesce(t.is_deleted,false)=false "
            "and coalesce(t.is_archived,false)=false")
    totals = (await db.execute(text(f"""
        select count(*) filter (where t.status not in ('closed','cancelled')) as open,
               count(*) filter (where t.status not in ('closed','cancelled')
                                and coalesce(t.sla_breached,false)) as sla_breached,
               count(*) filter (where t.created_at >= now() - interval '7 days') as created_7d,
               count(*) filter (where t.closed_at >= now() - interval '7 days') as closed_7d,
               count(*) filter (where t.created_at >= now() - interval '30 days') as created_30d,
               count(*) filter (where t.closed_at >= now() - interval '30 days') as closed_30d
        {base}
    """))).one()
    by = {}
    for key, expr in (("responsibility", "coalesce(t.responsibility,'—')"),
                      ("status", "t.status"),
                      ("category", "coalesce(t.category,'—')")):
        rows = (await db.execute(text(f"""
            select {expr} as k, count(*) as n {base}
              and t.status not in ('closed','cancelled')
            group by 1 order by 2 desc limit 12
        """))).all()
        by[key] = [{"key": r.k, "count": r.n} for r in rows]
    assignees = (await db.execute(text("""
        select coalesce(au.name, '— не назначен') as k, count(*) as n
        from public.tickets t
        left join public.users au on au.id = coalesce(t.current_assignee_id, t.assigned_to)
        where coalesce(t.is_deleted,false)=false and coalesce(t.is_archived,false)=false
          and t.status not in ('closed','cancelled')
        group by 1 order by 2 desc limit 10
    """))).all()
    by["assignee"] = [{"key": r.k, "count": r.n} for r in assignees]
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
    await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(text("""
        select m.id, m.name, m.description, m.interval_days, m.lead_days,
               m.category, m.priority, m.next_due_date, m.is_active,
               so.name as object_name
        from public.maintenance_schedules m
        left join public.service_objects so on so.id = m.service_object_id
        order by m.is_active desc, m.next_due_date nulls last
        limit 200
    """))).all()
    return {"schedules": [{
        "id": str(r.id), "name": r.name, "description": r.description,
        "interval_days": r.interval_days, "lead_days": r.lead_days,
        "category": r.category, "priority": r.priority,
        "next_due_date": r.next_due_date.isoformat() if r.next_due_date else None,
        "is_active": bool(r.is_active), "object": r.object_name,
    } for r in rows]}


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
