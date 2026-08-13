"""API оповещений пространства: на что подписана организация и куда это доставлять.

Читать может администратор организации (это раздел «Управления»), править — он же.
Каталог категорий — из кода (`notify_catalog`), поэтому подписка не может ссылаться на
событие, которого система не порождает.

Проверка доставки (`/test`) идёт тем же путём, что и настоящее оповещение, — иначе
«работает у меня» и «дойдёт до людей» оказались бы разными вещами.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import NotificationRule, User
from app.notify_catalog import probe_action, is_known, list_categories
from app.routers.users_router import require_company_admin
from app.services import notify

router = APIRouter(prefix="/notifications", tags=["Оповещения пространства"])


class RuleIn(BaseModel):
    category: str
    enabled: bool = True
    via_chat: bool = True
    via_email: bool = False
    recipients: list[str] | None = None   # None/[] — администраторы организации


class RuleOut(RuleIn):
    id: str


@router.get("/catalog")
async def catalog(_: User = Depends(get_current_user)) -> list[dict]:
    """Категории событий, на которые можно подписаться."""
    return list_categories()


@router.get("", response_model=list[RuleOut])
async def list_rules(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(company_id, current_user, db)
    rules = await notify.rules_for(db, cid)
    return [RuleOut(
        id=str(r.id), category=r.category, enabled=r.enabled,
        via_chat=r.via_chat, via_email=r.via_email,
        recipients=[str(x) for x in (r.recipients or [])] or None,
    ) for r in rules]


@router.put("", response_model=list[RuleOut])
async def save_rules(
    company_id: str = Query(...),
    payload: list[RuleIn] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сохранить подписки пачкой: в интерфейсе это одна таблица, а не набор форм."""
    cid = await require_company_admin(company_id, current_user, db)
    existing = {r.category: r for r in (await db.execute(select(NotificationRule).where(
        NotificationRule.company_id == cid))).scalars().all()}

    for item in payload:
        if not is_known(item.category):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Неизвестная категория: {item.category}")
        # Пустой список получателей = «администраторы организации», храним как NULL:
        # так состав получателей следует за составом админов, а не устаревает.
        recipients = [str(uuid.UUID(x)) for x in (item.recipients or [])] or None
        rule = existing.get(item.category)
        if rule is None:
            db.add(NotificationRule(
                company_id=cid, category=item.category, enabled=item.enabled,
                via_chat=item.via_chat, via_email=item.via_email, recipients=recipients))
        else:
            rule.enabled = item.enabled
            rule.via_chat = item.via_chat
            rule.via_email = item.via_email
            rule.recipients = recipients
    await db.commit()
    return await list_rules(company_id=company_id, db=db, current_user=current_user)


@router.post("/test")
async def test_delivery(
    company_id: str = Query(...),
    category: str = Query("people"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отправить проверочное оповещение тем же путём, каким пойдёт настоящее."""
    cid = await require_company_admin(company_id, current_user, db)
    if not is_known(category):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная категория")
    # Действие берётся из префиксов самой категории (`notify_catalog.probe_action`):
    # ручная карта покрывала три категории из семи, а остальные проверялись действием
    # из «Прочих событий» — кнопка отвечала «доставлено» про чужую подписку.
    probe = probe_action(category)
    result = await notify.dispatch(
        db, cid, probe, who=current_user.name,
        details="Проверка доставки оповещений из «Управления»")
    return result
