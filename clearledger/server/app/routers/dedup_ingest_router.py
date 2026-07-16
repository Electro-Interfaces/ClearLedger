"""
Приём среза дублей 208 по API-ключу (X-Cloud-API-Key) — для авто-обновления
среза с ноды 208 по расписанию (Task Scheduler + probe + curl), без юзер-JWT.

Нода 208 в overlay гоняет probe локально против D:\208 и POST-ит дамп сюда;
компания резолвится по cloud_api_key. Скоуп «Магазин» здесь НЕ применяется —
это машинный приём под ключ конкретной компании.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import Company
from app.services import dedup_service

router = APIRouter(prefix="/dedup-ingest", tags=["Dedup ingest (внешний)"])


@router.post("/reload")
async def dedup_reload_by_key(
    file: UploadFile,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Загрузить свежий дамп 208 (probe с ноды) под компанию ключа. Дамп с
    ошибкой соединения (нет #CARDS) отклоняется ДО очистки кеша — срез цел."""
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Дамп слишком большой")
    text = raw.decode("utf-8", "replace")
    if "#CARDS" not in text:
        raise HTTPException(400, "Не похоже на дамп 208 (нет секции #CARDS)")
    return await dedup_service.load_dump(db, company.id, text)


@router.get("/jobs/claim")
async def claim_job(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Нода забирает следующий pending-перецеп (помечает running). null — нет заданий."""
    return await dedup_service.claim_pending_job(db, company.id)


class JobResultBody(BaseModel):
    ok: bool = True
    result: dict = {}


@router.post("/jobs/{job_id}/result")
async def report_job_result(
    job_id: str, body: JobResultBody,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Нода отчитывается по выполненному заданию (отчёт → status done/error)."""
    try:
        jid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Невалидный ID")
    ok = await dedup_service.report_job(db, company.id, jid, ok=body.ok, result=body.result)
    if not ok:
        raise HTTPException(404, "Задание не найдено")
    return {"ok": True}
