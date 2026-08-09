"""/api/asuim/* — приём выгрузок витрины АСУиМ ЭЗС пакетом.

Штатный путь загрузки — канал Учёта, но он берёт ОДИН файл за прогон, а
регулярное обновление витрины это десять файлов сразу. Здесь тот же разбор, но
за один заход: каждый файл опознаётся по шапке, порядок выдерживается по
связям, а в ответ приходит протокол по каждому файлу.

Загружать может только администратор пространства: операция переписывает
справочники и реестр объектов компании.
"""
from __future__ import annotations

from typing import Any

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import User, UserCompany
from app.services.asuim_normalize import ingest_asuim_batch

router = APIRouter(prefix="/asuim", tags=["Витрина АСУиМ ЭЗС"])


async def _admin(company_id: str, user: User, db: AsyncSession) -> uuid.UUID:
    """Загрузка витрины переписывает справочники компании — только администратор."""
    cid = await assert_company_member(company_id, user, db)
    if user.is_superadmin:
        return cid
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора компании")
    return cid


@router.post("/ingest-batch")
async def asuim_ingest_batch(
    company_id: str = Query(...),
    mode: str = Query("append", pattern="^(append|replace)$"),
    files: list[UploadFile] = File(..., description="Файлы выгрузки витрины (.xlsx)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Пакет выгрузок витрины: опознать, разложить по порядку, загрузить.

    Порядок внутри пакета определяется связями (станции → разъёмы → организации
    → клиенты → карты → справочники → тарифы → сессии → платежи), поэтому
    файлы можно выбирать как угодно. `admins_ru` в загрузку не берётся никогда."""
    cid = await _admin(company_id, current_user, db)

    max_size = get_settings().ocr_max_file_size
    payload: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        if len(content) > max_size:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Файл {f.filename} слишком большой ({len(content)} байт, максимум {max_size})",
            )
        payload.append((f.filename or "без имени", content))

    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Не передано ни одного файла")

    res = await ingest_asuim_batch(db, cid, payload, mode=mode)
    await db.commit()
    return {"companyId": str(cid), **res}
