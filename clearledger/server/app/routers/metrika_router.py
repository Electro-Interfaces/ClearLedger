"""/api/metrika/* — коннектор Яндекс.Метрики: подключение (счётчик + OAuth-токен)
и отчёты (сводка / динамика / источники). Токен хранится шифрованным на бэке и
наружу не отдаётся — фронт получает только статус и агрегаты."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services.metrika.client import MetrikaError
from app.services.metrika.service import MetrikaService


async def _report(coro):
    """Обёртка отчётных вызовов: ошибку Метрики → 409 (чистое сообщение фронту)."""
    try:
        return await coro
    except MetrikaError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e)) from e

router = APIRouter(prefix="/metrika", tags=["Яндекс.Метрика"])


class MetrikaConnBody(BaseModel):
    counter_id: str = Field(min_length=1, max_length=40)
    token: str = Field(min_length=10, max_length=2048)


def _d(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field}: {s}") from exc


# Даты для Метрики: date1/date2 в формате YYYY-MM-DD или today/yesterday/NdaysAgo.
def _md(s: str) -> str:
    return s if (s in ("today", "yesterday") or s.endswith("daysAgo")) else _d(s, "date").isoformat()


@router.get("/status")
async def metrika_status(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Статус подключения (без токена)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await MetrikaService(db).status(cid)


@router.put("/connection")
async def metrika_save(
    company_id: str, body: MetrikaConnBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сохранить/обновить подключение (счётчик + токен) + провалидировать."""
    cid = await assert_company_member(company_id, current_user, db)
    return await MetrikaService(db).save(cid, body.counter_id.strip(), body.token.strip())


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def metrika_delete(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    cid = await assert_company_member(company_id, current_user, db)
    await MetrikaService(db).delete(cid)


@router.post("/test")
async def metrika_test(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Проверить подключение (обращение к API Метрики)."""
    cid = await assert_company_member(company_id, current_user, db)
    return await MetrikaService(db).test(cid)


@router.get("/summary")
async def metrika_summary(
    company_id: str, date1: str = "7daysAgo", date2: str = "today",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сводка: визиты / посетители / просмотры / отказы / время / глубина / новые."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _report(MetrikaService(db).summary(cid, _md(date1), _md(date2)))


@router.get("/timeseries")
async def metrika_timeseries(
    company_id: str, date1: str = "30daysAgo", date2: str = "today",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Динамика по дням: визиты / посетители / просмотры."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _report(MetrikaService(db).timeseries(cid, _md(date1), _md(date2)))


@router.get("/sources")
async def metrika_sources(
    company_id: str, date1: str = "30daysAgo", date2: str = "today",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Источники трафика по визитам."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _report(MetrikaService(db).sources(cid, _md(date1), _md(date2)))
