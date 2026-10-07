"""Журнал безопасности пространства и ловушка для сканеров (`app/guard.py`).

Журнал и блокировки видит только суперадминистратор: события идут до всякой
аутентификации, у них нет компании, и смотреть их — дело того, кто отвечает за весь
контейнер, а не за одну организацию.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import guard
from app.auth import get_current_user
from app.database import get_db
from app.models import SecurityBlock, SecurityEvent, User

router = APIRouter(prefix="/security", tags=["Безопасность"])


def _require_super(user: User) -> None:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права суперадминистратора экосистемы")


@router.api_route("/trap", methods=["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS", "PATCH"],
                  include_in_schema=False)
async def trap(request: Request):
    """Сюда nginx стека отдаёт пути сканеров (`/.env`, `wp-*`…) и инструменты взлома.
    Исходный путь — в X-Original-URI. Ответ — обычный 404: сканер не должен понять,
    что его заметили."""
    original = (request.headers.get("x-original-uri") or request.url.path)[:200]
    kind = "bad_ua" if request.headers.get("x-trap-reason") == "1" else "trap"
    await guard.record(kind, request, path=original, block=True)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@router.get("/events")
async def events(
    days: int = Query(7, ge=1, le=90), kind: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Эпизоды за период и сводка по видам и адресам."""
    _require_super(user)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(SecurityEvent).where(SecurityEvent.at >= since)
    if kind:
        q = q.where(SecurityEvent.kind == kind)
    rows = (await db.execute(q.order_by(SecurityEvent.at.desc()).limit(500))).scalars().all()
    by_kind = (await db.execute(select(SecurityEvent.kind, func.count()).where(SecurityEvent.at >= since)
                                .group_by(SecurityEvent.kind))).all()
    by_ip = (await db.execute(select(SecurityEvent.ip, func.count(), func.max(SecurityEvent.at))
                              .where(SecurityEvent.at >= since).group_by(SecurityEvent.ip)
                              .order_by(func.count().desc()).limit(20))).all()
    return {
        "events": [{"id": str(e.id), "at": e.at.isoformat(), "kind": e.kind, "label": guard.KIND_LABEL.get(e.kind, e.kind),
                    "ip": e.ip, "path": e.path, "userAgent": e.user_agent, "hits": e.hits,
                    "detail": e.detail or (e.scope if e.scope != "guard" else None)} for e in rows],
        "byKind": [{"kind": k, "label": guard.KIND_LABEL.get(k, k), "count": n} for k, n in by_kind],
        "byIp": [{"ip": ip, "count": n, "last": last.isoformat()} for ip, n, last in by_ip],
    }


@router.get("/blocks")
async def blocks(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Блокировки: действующие и снятые/истёкшие за неделю."""
    _require_super(user)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (await db.execute(select(SecurityBlock).where(SecurityBlock.created_at >= since)
                             .order_by(SecurityBlock.created_at.desc()).limit(200))).scalars().all()
    now = datetime.now(timezone.utc)
    return {"blocks": [{"id": str(b.id), "ip": b.ip, "until": b.until.isoformat(), "reason": b.reason,
                        "createdAt": b.created_at.isoformat(), "active": b.lifted_at is None and b.until > now,
                        "liftedAt": b.lifted_at.isoformat() if b.lifted_at else None,
                        "liftedBy": b.lifted_by_name} for b in rows]}


@router.post("/blocks/{block_id}/lift")
async def lift(block_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Снять блокировку: адрес снова пускается. Действует в течение 30 секунд на всех воркерах."""
    _require_super(user)
    b = await db.get(SecurityBlock, block_id)
    if b is None:
        raise HTTPException(404, "Блокировка не найдена")
    b.lifted_at = datetime.now(timezone.utc)
    b.lifted_by_name = user.name or user.email
    await db.commit()
    guard.forget_block(b.ip)
    return {"ok": True}
