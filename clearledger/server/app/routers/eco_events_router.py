"""Приём событий от приложений пространства: /api/eco/events.

Обратный канал к тому, что уже есть в прямую сторону. Ядро ходит в приложения
служебным токеном, приложения к Ядру — ключом интеграции (`X-Cloud-API-Key`), тем
же, которым к нам стучится почтовый мост.

Ручка намеренно тупая: приняли, записали, ответили. Разбор — фоновым проходом,
потому что отправитель ретраит по коду ответа, и наша внутренняя ошибка не должна
превращаться в бесконечную повторную доставку.
"""
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import Company
from app.services import inbound_events

router = APIRouter(prefix="/eco", tags=["Экосистема: события приложений"])


@router.post("/events")
async def accept_event(
    request: Request,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять одно событие приложения.

    Ответы: `accepted` — приняли, `duplicate` — уже было (тоже успех: повторная
    доставка штатна), `rejected` — событию нечем себя опознать. Ретраить имеет
    смысл только на 5xx, и именно поэтому дубль не считается ошибкой.
    """
    event = await request.json()
    provider = str(event.get("source") or request.headers.get("X-Eco-App") or "support")
    status, note = await inbound_events.accept(db, provider, event, company.id)
    return {"status": status, "note": note}
