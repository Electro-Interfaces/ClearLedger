"""Настройки связей «Телефонии»: только метаданные и проверка API без звонков."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.routers.voice_router import _voice_admin
from app.services.support_scope import support_company_id
from app.services.voice_support_context import _support_target
from app.services.space_projection import _internal_base_url


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(prefix="/voice/connections", tags=["Телефония: подключения"],
                   dependencies=[Depends(no_store)])


class Direction(BaseModel):
    configured: bool
    enabled: bool


class Readiness(BaseModel):
    history: Direction | None = None
    events: Direction | None = None


Source = Literal["connector", "config", "env", "environment", "missing"]


class Sources(BaseModel):
    endpoint: Source | None = None
    api_key: Source | None = None
    crm_token: Source | None = None
    webhook_secret: Source | None = None


class Connection(BaseModel):
    id: uuid.UUID | None
    provider: Literal["megafon", "asterisk"]
    enabled: bool
    status: Literal["active", "paused", "error", "planned", "inactive", "disabled", "unknown"]
    configured: bool
    endpoint: str | None = Field(None, max_length=2048)
    sources: Sources
    readiness: Readiness
    webhook_path: str | None = Field(None, max_length=250)
    last_sync_at: datetime | None = None
    last_error: str | None = None

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value):
        if not value:
            return None
        try:
            url = urlsplit(value)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                return None
            # Адрес здесь нужен для ориентации. Параметры запроса не публикуем.
            return urlunsplit((url.scheme, url.netloc, url.path, "", ""))
        except ValueError:
            return None

    @field_validator("webhook_path")
    @classmethod
    def safe_webhook(cls, value):
        if not value:
            return None
        import re
        return value if re.fullmatch(r"/api/v1/telephony/(megafon/event|voice/[0-9a-f-]{36})", value) else None

    @field_validator("last_error", mode="before")
    @classmethod
    def generic_error(cls, value):
        return "Последний обмен завершился ошибкой. Проверьте подключение." if value else None


class SupportConnections(BaseModel):
    company_id: uuid.UUID
    connections: list[Connection] = Field(max_length=100)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: uuid.UUID | None = Field(...)


async def scope(header, user, db):
    ref = header or (str(user.company_id) if user.company_id else None)
    if not ref:
        raise HTTPException(400, "Выберите компанию")
    return await _voice_admin(ref, user, db)


async def support_request(db, cid, *, connector_id=None, check=False):
    target, miss = await _support_target(db, cid, "voice.connections")
    if target is None:
        # Причина названа: администратор видит этот текст на экране «Подключения»,
        # и «не подключена ИЛИ не настроена» не говорит ему, что чинить.
        raise HTTPException(503, {
            "support_not_enabled": "«Поддержка» не подключена этой компании",
            "support_not_linked": "Для компании не задано соответствие компании "
                                  "в «Поддержке» (Центр управления → Приложения)",
            "sso_not_configured": "Служебный обмен не настроен: нет ключа подписи",
        }.get(miss, "Поддержка недоступна"))
    app, token = target
    method = "POST" if check else "GET"
    suffix = "/check" if check else ""
    payload = {"connector_id": str(connector_id) if connector_id else None} if check else None
    try:
        async with httpx.AsyncClient(timeout=12.0 if payload else 4.0, follow_redirects=False) as client:
            async with client.stream(method, f"{_internal_base_url(app, 'support')}/api/v1/eco/voice/connections{suffix}",
                                     headers={"Authorization": f"Bearer {token}"}, json=payload) as response:
                if response.status_code == 404 and payload:
                    raise HTTPException(404, "Подключение не найдено в выбранной компании")
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 128_000:
                        raise ValueError("oversized")
                    chunks.append(chunk)
        return json.loads(b"".join(chunks))
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(503, "Не удалось прочитать настройки Поддержки. Повторите проверку.") from None


@router.get("")
async def connections(company_header: str | None = Header(None, alias="X-Company-Id"),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await scope(company_header, user, db)
    try:
        body = SupportConnections.model_validate(await support_request(db, cid))
        mapped = await support_company_id(db, cid)
        if str(body.company_id) != str(mapped):
            raise ValueError("company mismatch")
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(503, "Поддержка вернула неподтверждённые настройки компании") from None
    return {"company_id": str(cid), "connections": [c.model_dump(mode="json") for c in body.connections]}


@router.post("/check")
async def check(payload: CheckIn, company_header: str | None = Header(None, alias="X-Company-Id"),
                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid = await scope(company_header, user, db)
    body = await support_request(db, cid, connector_id=payload.connector_id, check=True)
    if not isinstance(body, dict) or type(body.get("ok")) is not bool:
        raise HTTPException(503, "Поддержка не подтвердила результат проверки")
    # Ответ провайдера и его текст не пересылаются: в них могут быть ключи и номера.
    try:
        at = datetime.fromisoformat(str(body.get("at", "")).replace("Z", "+00:00"))
        if at.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError:
        raise HTTPException(503, "Поддержка не подтвердила время проверки") from None
    return {"company_id": str(cid), "ok": body["ok"], "at": at.isoformat(),
            "message": "API истории отвечает. Данные звонков не сохранялись." if body["ok"]
            else "API истории не прошёл проверку. Проверьте адрес, ключ API и доступность ВАТС."}
