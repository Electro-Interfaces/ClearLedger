"""
Роутер аудит-лога: история действий по записям и компаниям.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import AuditEvent, DataEntry, User, UserCompany
from app.schemas import AuditActionType, AuditEventResponse


class AuditEventCreate(BaseModel):
    """Неавторитетная UI-телеметрия (camelCase от фронтенда)."""
    companyId: str
    entryId: str | None = None
    action: AuditActionType
    details: str | None = Field(None, max_length=2000)
    # Старые клиенты присылают эти поля. Сервер намеренно их игнорирует.
    userId: str | None = None
    userName: str | None = None

router = APIRouter(prefix="/audit", tags=["Аудит"])


def _audit_response(event: AuditEvent) -> AuditEventResponse:
    """Конвертирует ORM AuditEvent в схему ответа."""
    return AuditEventResponse(
        id=str(event.id),
        entry_id=str(event.entry_id) if event.entry_id else None,
        company_id=str(event.company_id),
        user_id=event.user_id,
        user_name=event.user_name,
        action=event.action,
        details=event.details,
        timestamp=event.timestamp,
    )


@router.post("", response_model=AuditEventResponse, status_code=201)
async def create_audit_event(
    body: AuditEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Записать UI-телеметрию без права подделать системное действие или автора."""
    cid = await assert_company_member(body.companyId, current_user, db)

    entry_id = None
    if body.entryId:
        try:
            entry_id = uuid.UUID(body.entryId)
        except ValueError:
            raise HTTPException(status_code=400, detail="Невалидный ID записи")
        belongs = await db.scalar(select(DataEntry.id).where(
            DataEntry.id == entry_id, DataEntry.company_id == cid))
        if belongs is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")

    event = AuditEvent(
        company_id=cid,
        entry_id=entry_id,
        user_id=str(current_user.id),
        user_name=current_user.name or current_user.email,
        action=f"client.{body.action}",
        details=body.details,
    )
    db.add(event)
    await db.flush()
    return _audit_response(event)


@router.get("", response_model=list[AuditEventResponse])
async def list_audit_events(
    company_id: str | None = Query(None),
    action: str | None = Query(None),
    user_id: str | None = Query(None, description="события конкретного человека"),
    entry_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список событий аудита с фильтрами. Возвращает плоский массив."""
    query = select(AuditEvent)

    # Изоляция данных по компании
    if company_id:
        cid = await assert_company_member(company_id, current_user, db)
    else:
        cid = current_user.company_id
        if cid is None:
            raise HTTPException(status_code=400, detail="Укажите company_id")
    query = query.where(AuditEvent.company_id == cid)

    if action:
        query = query.where(AuditEvent.action == action)

    if user_id:
        query = query.where(AuditEvent.user_id == user_id)

    if entry_id:
        try:
            eid = uuid.UUID(entry_id)
            query = query.where(AuditEvent.entry_id == eid)
        except ValueError:
            pass

    if date_from:
        query = query.where(AuditEvent.timestamp >= date_from)

    if date_to:
        query = query.where(AuditEvent.timestamp <= date_to)

    by_time = AuditEvent.timestamp.asc() if order == "asc" else AuditEvent.timestamp.desc()
    query = query.order_by(by_time).offset(offset).limit(limit)
    result = await db.execute(query)
    events = result.scalars().all()

    return [_audit_response(e) for e in events]


@router.get("/activity")
async def activity_summary(
    company_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Динамика доступа и активность людей — для «Обзора» и «Сотрудников».

    Отвечает на вопросы МАГа 31.07: кто когда заходил, кого подключали и
    отключали, ждут ли приглашения, и какой процент активности у каждого
    человека (доля дней с действиями за окно)."""
    from sqlalchemy import text as _sql
    cid = await assert_company_member(company_id, current_user, db)
    p = {"cid": str(cid), "days": days}
    totals = (await db.execute(_sql("""
        select count(*) filter (where action='auth.login') as logins,
               count(*) filter (where action='auth.login'
                                and timestamp >= now() - interval '7 days') as logins_7d,
               count(*) filter (where action='auth.login_failed') as failed,
               count(*) filter (where action='user.create') as connected,
               count(*) filter (where action='user.remove') as removed,
               count(distinct user_id) filter (where action='auth.login') as unique_people
        from audit_events
        where company_id = :cid and timestamp >= now() - make_interval(days => :days)
    """), p)).one()
    people = (await db.execute(_sql("""
        select ae.user_id, max(ae.user_name) as name,
               count(distinct date(ae.timestamp)) as active_days,
               count(*) filter (where ae.action='auth.login') as logins,
               max(ae.timestamp) as last_at
        from audit_events ae
        where ae.company_id = :cid and ae.timestamp >= now() - make_interval(days => :days)
          and ae.user_id is not null
        group by ae.user_id
        order by active_days desc, logins desc
        limit 30
    """), p)).all()
    inv = (await db.execute(_sql("""
        select count(*) filter (where status='pending' and expires_at >= now()) as pending,
               count(*) filter (where status='pending' and expires_at < now()) as expired,
               count(*) filter (where status='accepted'
                                and accepted_at >= now() - make_interval(days => :days)) as accepted
        from invitations where company_id = :cid
    """), p)).one()
    return {
        "days": days,
        "totals": {
            "logins": totals.logins, "logins_7d": totals.logins_7d,
            "failed": totals.failed, "connected": totals.connected,
            "removed": totals.removed, "unique_people": totals.unique_people,
        },
        "invitations": {"pending": inv.pending, "expired": inv.expired, "accepted": inv.accepted},
        "people": [{
            "user_id": r.user_id, "name": r.name,
            "active_days": r.active_days, "logins": r.logins,
            "last_at": r.last_at.isoformat() if r.last_at else None,
            # Процент активности: доля дней окна, когда человек что-то делал.
            "share": round(r.active_days / days * 100),
        } for r in people],
    }


@router.get("/entry/{entry_id}", response_model=list[AuditEventResponse])
async def get_entry_audit(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """История аудита для конкретной записи."""
    try:
        eid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID записи")

    stmt = select(AuditEvent).where(AuditEvent.entry_id == eid)
    # Изоляция: обычный юзер видит аудит только доступных компаний (иначе утечка
    # журнала чужой записи по её id).
    if not current_user.is_superadmin:
        stmt = stmt.where(AuditEvent.company_id.in_(
            select(UserCompany.company_id).where(UserCompany.user_id == current_user.id)
        ))
    result = await db.execute(stmt.order_by(AuditEvent.timestamp.desc()))
    events = result.scalars().all()
    return [_audit_response(e) for e in events]
