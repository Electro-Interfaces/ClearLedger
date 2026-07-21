"""API «Банк ЗУ» — площадки под установку ЭЗС (девелоперский пайплайн).

Раздел energy/РусГидро. Авторизация — членство в компании (как equipment_router).
НЕ путать с /equipment (склад железа): здесь учёт МЕСТ на стадиях
проработка → работа → архив. Источник данных — сводный Excel «Банк данных ЗУ».
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services import ezs_sites

router = APIRouter(prefix="/sites", tags=["Площадки ЭЗС (Банк ЗУ)"])


@router.post("/import")
async def import_sites(
    company_id: str = Query(...), dry_run: bool = Query(False),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Импорт сводного «Банк данных ЗУ» (xlsx, 3 листа → стадии). REPLACE-ALL."""
    cid = await assert_company_member(company_id, user, db)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    return await ezs_sites.import_sites_xlsx(db, cid, content, dry_run)


@router.get("/overview")
async def sites_overview(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Сводка пайплайна: по стадиям, топ-регионы, план ЭЗС/мощности."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_sites.sites_overview(db, cid)


@router.get("")
async def list_sites(
    company_id: str = Query(...),
    stage: str | None = Query(None), region: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=2000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Список площадок с фильтрами (стадия/регион/поиск) и пагинацией."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_sites.list_sites(db, cid, stage=stage, region=region,
                                      search=search, page=page, page_size=page_size)


@router.get("/{site_id}")
async def get_site(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Карточка площадки — все исходные поля (raw)."""
    cid = await assert_company_member(company_id, user, db)
    out = await ezs_sites.site_detail(db, cid, site_id)
    if out is None:
        raise HTTPException(404, "Площадка не найдена")
    return out
