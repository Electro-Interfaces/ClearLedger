"""API «Банк ЗУ» — площадки под установку ЭЗС (девелоперский пайплайн).

Раздел energy/РусГидро. Авторизация — членство в компании (как equipment_router).
НЕ путать с /equipment (склад железа): здесь учёт МЕСТ на стадиях
проработка → работа → архив. Источник данных — сводный Excel «Банк данных ЗУ».
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import EzsSite, User
from app.services import ezs_site_analysis, ezs_site_work, ezs_sites

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
    search: str | None = Query(None), owner_id: uuid.UUID | None = Query(None),
    overdue: bool = Query(False),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=2000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Список площадок с фильтрами (стадия/регион/поиск/ответственный/просрочка)."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_sites.list_sites(db, cid, stage=stage, region=region, search=search,
                                      owner_id=owner_id, overdue=overdue,
                                      page=page, page_size=page_size)


@router.get("/meta/members")
async def list_members(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Кого можно назначить ответственным за площадку (члены компании)."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_site_work.company_members(db, cid)


@router.get("/meta/gates")
async def list_gates(user: User = Depends(get_current_user)):
    """Чек-листы гейтов по стадиям — чтобы UI показывал требования до перехода."""
    return {
        "stages": [{"stage": s, "label": ezs_sites.STAGE_LABELS[s],
                    "hint": ezs_sites.STAGE_HINTS[s],
                    "items": ezs_site_work.GATES.get(s, [])}
                   for s in ezs_sites.ALL_STAGES],
    }


@router.post("", status_code=201)
async def create_site(
    payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Завести площадку руками — лид, который пришёл не из файла."""
    cid = await assert_company_member(company_id, user, db)
    site = await ezs_site_work.create_site(db, cid, payload, user)
    await db.commit()
    return await ezs_sites.site_detail(db, cid, site.id)


@router.get("/analysis/matrix")
async def analysis_matrix(
    company_id: str = Query(...), stage: str | None = Query(None),
    region: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Приоритеты: привлекательность × исполнимость по активным площадкам."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_site_analysis.priority_matrix(db, cid, stage=stage, region=region)


@router.get("/analysis/gaps")
async def analysis_gaps(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Разрывы покрытия: где сеть без пайплайна, где пайплайн без сети, каннибализация."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_site_analysis.coverage_gaps(db, cid)


@router.get("/analysis/map")
async def analysis_map(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Точки для карты: площадки со стадией и скорингом (станции сети — из /api/locations)."""
    cid = await assert_company_member(company_id, user, db)
    m = await ezs_site_analysis.priority_matrix(db, cid)
    sites = (await db.execute(
        select(EzsSite.id, EzsSite.lat, EzsSite.lon).where(
            EzsSite.company_id == cid, EzsSite.lat.is_not(None)))).all()
    coords = {str(i): (la, lo) for i, la, lo in sites}
    pts = []
    for it in m["items"]:
        c = coords.get(it["id"])
        if c:
            pts.append({**it, "lat": c[0], "lon": c[1]})
    return {"points": pts, "thresholds": m["thresholds"]}


@router.get("/{site_id}/economics")
async def site_economics(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Оценка экономики площадки по фактическим сессиям сети + допущения расчёта."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    bench = await ezs_site_analysis.region_benchmarks(db, cid)
    near = await ezs_site_analysis.nearest_station_km(db, cid)
    return {
        "economics": ezs_site_analysis.economics(site, bench),
        "score": ezs_site_analysis.score_site(site, near_km=near.get(str(site_id)), bench=bench),
        "quadrants": ezs_site_analysis.QUADRANTS,
    }


@router.get("/{site_id}")
async def get_site(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Карточка площадки: поля ведения, чек-лист гейта и все исходные поля (raw)."""
    cid = await assert_company_member(company_id, user, db)
    out = await ezs_sites.site_detail(db, cid, site_id)
    if out is None:
        raise HTTPException(404, "Площадка не найдена")
    return out


@router.patch("/{site_id}")
async def patch_site(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Правка карточки. Изменённые поля помечаются ручными — импорт их не трогает."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_site_work.update_site(db, site, payload, user)
    await db.commit()
    out = await ezs_sites.site_detail(db, cid, site_id)
    return {**res, "site": out}


@router.post("/{site_id}/stage")
async def move_stage(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Перевод по воронке. Незакрытый гейт не блокирует, но попадает в историю."""
    stage = str(payload.get("stage") or "")
    if stage not in ezs_sites.ALL_STAGES:
        raise HTTPException(400, f"Неизвестная стадия: {stage}")
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_site_work.set_stage(db, site, stage,
                                        reason=payload.get("reason"), user=user)
    await db.commit()
    return {**res, "site": await ezs_sites.site_detail(db, cid, site_id)}


@router.post("/{site_id}/gate")
async def mark_gate(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Отметить пункт гейта, который проверяется глазами (право, согласие, СМР)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_site_work.set_gate_item(db, site, str(payload.get("key") or ""),
                                            bool(payload.get("done")), user)
    await db.commit()
    return res


@router.get("/{site_id}/events")
async def get_events(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """История площадки: стадии, касания, заметки, правки, импорт."""
    cid = await assert_company_member(company_id, user, db)
    await _owned(db, cid, site_id)
    return await ezs_site_work.site_events(db, cid, site_id)


@router.post("/{site_id}/events", status_code=201)
async def add_event(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Записать касание (звонок, письмо, встреча) или заметку."""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Пустая запись")
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_site_work.add_touch(db, site, text,
                                        str(payload.get("kind") or "touch"), user)
    await db.commit()
    return res


@router.delete("/{site_id}")
async def delete_site(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Удалить площадку. Для отказа есть архив с причиной — удаление только для
    ошибочно заведённых записей, поэтому история уходит вместе с ними (каскад)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    await db.delete(site)
    await db.commit()
    return {"deleted": str(site_id)}


async def _owned(db: AsyncSession, cid, site_id: uuid.UUID) -> EzsSite:
    """Площадка строго своей компании — иначе чужой банк можно править по id."""
    site = (await db.execute(
        select(EzsSite).where(EzsSite.company_id == cid, EzsSite.id == site_id)
    )).scalar_one_or_none()
    if site is None:
        raise HTTPException(404, "Площадка не найдена")
    return site
