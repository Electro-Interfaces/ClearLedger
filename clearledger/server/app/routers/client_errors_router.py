"""Сбои интерфейса у пользователя: журнал того, что упало в браузере.

«Периодически возникает ошибка» — это всё, что мы знали о падениях экрана: текст
минифицированной ошибки React без места и без повторяемости (МАГ, 18.09.2026).
Здесь падение записывается с маршрутом, версией и стеком компонентов, поэтому
следующий разбор начинается не с угадывания, а с записи.

Дисциплина записи:
- **Одна строка на отпечаток в час.** Цикл перерисовки способен послать сотни
  сообщений в секунду; без свёртки журнал ошибок сам станет отказом.
- **Ручка открыта без токена.** Экран входа падает до аутентификации, и такое
  падение нужно видеть особенно. Пользователь подписывается, если токен есть.
- **Сохраняем только текст.** Ни снимка экрана, ни содержимого полей: журнал
  сбоев не должен становиться вторым местом хранения рабочих данных.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ClientError, User

router = APIRouter(prefix="/client-errors", tags=["Сбои интерфейса"])

settings = get_settings()

# Окно свёртки: повтор того же сбоя в течение часа увеличивает счётчик.
ОКНО = timedelta(hours=1)


class СбойIn(BaseModel):
    message: str = Field(default="", max_length=2000)
    stack: str | None = Field(default=None, max_length=8000)
    componentStack: str | None = Field(default=None, max_length=8000)
    path: str = Field(default="", max_length=500)
    version: str | None = Field(default=None, max_length=40)
    # Что человек делал перед падением: экран раздела, если интерфейс его знает.
    screen: str | None = Field(default=None, max_length=120)


def отпечаток(message: str, path: str, component_stack: str | None) -> str:
    """Ключ свёртки: один и тот же сбой на одном экране — одна строка журнала.

    В ключ идут пять верхних кадров стека компонентов, а не весь стек: ниже по нему
    у одного и того же падения оказываются разные строки таблицы и списки, и полный
    стек развалил бы свёртку на сотни «разных» ошибок. Верхние кадры — это и есть
    место падения.
    """
    кадры = [x.strip() for x in (component_stack or "").splitlines() if x.strip()][:5]
    сырьё = f"{message}|{path}|{' / '.join(кадры)}"
    return hashlib.sha256(сырьё.encode()).hexdigest()[:32]


async def _пользователь(request: Request, db: AsyncSession) -> User | None:
    """Кто упал, если он вошёл. Без токена — тоже запись, просто без имени."""
    заголовок = request.headers.get("authorization") or ""
    if not заголовок.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(заголовок[7:], settings.secret_key,
                             algorithms=[settings.algorithm])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return (await db.execute(select(User).where(User.id == sub))).scalar_one_or_none()
    except Exception:
        return None


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def записать_сбой(
    body: СбойIn, request: Request, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Принять сбой интерфейса. Ответ всегда 202: журнал не мешает работе."""
    ключ = отпечаток(body.message, body.path, body.componentStack)

    сейчас = datetime.now(timezone.utc)
    прежний = (await db.execute(
        select(ClientError).where(ClientError.fingerprint == ключ,
                                  ClientError.last_at >= сейчас - ОКНО)
        .order_by(ClientError.last_at.desc()).limit(1))).scalar_one_or_none()

    user = await _пользователь(request, db)
    if прежний is not None:
        прежний.hits += 1
        прежний.last_at = сейчас
        if user is not None and not прежний.user_email:
            прежний.user_email = user.email
        await db.commit()
        return {"accepted": True, "hits": прежний.hits}

    запись = ClientError(
        fingerprint=ключ,
        message=(body.message or "")[:2000],
        stack=(body.stack or None),
        component_stack=(body.componentStack or None),
        path=(body.path or "")[:500],
        screen=(body.screen or None),
        version=(body.version or None),
        user_email=user.email if user is not None else None,
        company_id=user.company_id if user is not None else None,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        hits=1,
        last_at=сейчас,
    )
    db.add(запись)
    await db.commit()
    return {"accepted": True, "hits": 1}
