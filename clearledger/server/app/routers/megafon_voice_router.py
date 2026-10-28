"""Чтение внешней ВАТС в приложении «Телефония». Управляющих команд здесь нет."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import AuditEvent, User
from app.services import megafon_voice
from app.services.app_registry import company_apps
from app.services.app_roles import app_roles
from app.services.support_scope import support_company_id


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(tags=["Телефония: АТС"], dependencies=[Depends(no_store)])
CallSource = Literal["node", "mango", "megafon"]


def requested_source(request: Request, source: CallSource | None) -> CallSource:
    return source or ("megafon" if "/voice/megafon" in request.url.path else "node")


async def _scope(user: User, db: AsyncSession, company_header: str | None) -> tuple[uuid.UUID, str]:
    ref = company_header or (str(user.company_id) if user.company_id else None)
    if not ref:
        raise HTTPException(400, "Выберите компанию")
    cid = await assert_company_member(ref, user, db)
    if not any(a["code"] == "voice" and a["enabled"] for a in await company_apps(db, cid)):
        raise HTTPException(403, "«Телефония» не подключена компании")
    if "admin" not in await app_roles(db, user, cid, "voice"):
        raise HTTPException(403, "Нужна роль администратора «Телефонии»")
    mapped = await support_company_id(db, cid)
    try:
        support_cid = str(uuid.UUID(str(mapped)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(404, "Компания пространства не сопоставлена с Поддержкой") from None
    return cid, support_cid


async def _audit(db: AsyncSession, user: User, cid: uuid.UUID, action: str, details: dict):
    # Аудит чтения номеров без номера, поисковой строки и ссылок на записи в журнале.
    # Событие чтения не рассылает оповещения о действиях администраторов.
    db.add(AuditEvent(company_id=cid, user_id=str(user.id), user_name=user.name,
                      action=action, details=json.dumps(details, ensure_ascii=False)))
    await db.commit()


@router.get("/voice/megafon")
@router.get("/voice/pbx")
async def overview(
    request: Request,
    source: CallSource | None = Query(None),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    operator: str | None = Query(None, max_length=200),
    group: str | None = Query(None, max_length=200),
    line: str | None = Query(None, max_length=50),
    missed: bool | None = None,
    direction: Literal["inbound", "outbound"] | None = None,
    search: str | None = Query(None, max_length=40),
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(25, ge=1, le=100),
    company_header: str | None = Header(None, alias="X-Company-Id"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid, support_cid = await _scope(user, db, company_header)
    start, end = megafon_voice.period(start, end)
    selected = requested_source(request, source)
    result = await megafon_voice.overview(db, support_cid, cid, source=selected, start=start, end=end,
        operator=operator, group=group, line=line, missed=missed, direction=direction,
        search=search, page=page, page_size=page_size)
    await _audit(db, user, cid, f"voice.{selected}.read", {"count": len(result["calls"]["items"]), "search": bool(search)})
    return result


@router.get("/voice/megafon/calls/{call_id}")
@router.get("/voice/pbx/calls/{call_id}")
async def call_detail(
    request: Request,
    call_id: uuid.UUID,
    source: CallSource | None = Query(None),
    company_header: str | None = Header(None, alias="X-Company-Id"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid, support_cid = await _scope(user, db, company_header)
    selected = requested_source(request, source)
    call = await megafon_voice.call_detail(db, support_cid, call_id, source=selected)
    await _audit(db, user, cid, f"voice.{selected}.detail", {"call_id": str(call_id)})
    return {"provider": selected, "company_id": str(cid), "call": call}


@router.get("/voice/pbx/sources")
async def sources(company_header: str | None = Header(None, alias="X-Company-Id"),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid, support_cid = await _scope(user, db, company_header)
    result = await megafon_voice.source_connections(db, support_cid)
    return {"company_id": str(cid), **result}
