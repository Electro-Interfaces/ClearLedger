"""API приложения «Инфо» (/api/info/*) — знание пространства.

Одно приложение на всё пространство, три входа (стол, кнопка в шапке, правая
панель рабочей области) и один источник данных. Контекстная подсказка — та же
база с фильтром по продукту и разделу, а не отдельная копия текстов.
Модель и решения — `docs/INFO.md`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services import info_center

router = APIRouter(prefix="/info", tags=["Инфо (знание пространства)"])


@router.get("/meta")
async def meta(user: User = Depends(get_current_user)):
    """Пласты знания — для фильтров и форм."""
    return {"kinds": info_center.KINDS}


@router.get("/tree")
async def tree(
    company_id: str = Query(...),
    app_code: str | None = Query(None, description="только знание этого продукта"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Всё дерево: разделы и статьи по пластам. `app_code` — свод одного продукта."""
    cid = await assert_company_member(company_id, user, db)
    return await info_center.tree(db, cid, app_code=app_code)


@router.get("/context")
async def context(
    app_code: str = Query(..., description="код продукта, например projects"),
    section_key: str | None = Query(None, description="ключ раздела рабочей области"),
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Что показать в правой панели для открытой рабочей области."""
    cid = await assert_company_member(company_id, user, db)
    return await info_center.context(db, cid, app_code=app_code, section_key=section_key)


@router.get("/search")
async def search(
    q: str = Query("", description="запрос"),
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await info_center.search(db, cid, q)


@router.get("/stats")
async def stats(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await info_center.stats(db, cid)


@router.get("/articles/{article_id}")
async def get_article(
    article_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    a = await info_center.article(db, cid, article_id)
    if a is None:
        raise HTTPException(404, "Статья не найдена")
    return a


@router.put("/articles")
async def upsert_article(
    payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Завести или поправить статью пространства (платформенные — только у поставщика)."""
    cid = await assert_company_member(company_id, user, db)
    res = await info_center.upsert_article(db, cid, payload, user)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось сохранить"))
    await db.commit()
    return res


@router.delete("/articles/{article_id}")
async def delete_article(
    article_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    if not await info_center.delete_article(db, cid, article_id):
        raise HTTPException(404, "Статья не найдена или принадлежит платформе")
    await db.commit()
    return {"deleted": str(article_id)}


@router.put("/categories")
async def upsert_category(
    payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    res = await info_center.upsert_category(db, cid, payload)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось сохранить"))
    await db.commit()
    return res
