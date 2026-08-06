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
from app.models import EzsSite, EzsSiteParticipant, User
from app.services import (
    ezs_changes, ezs_checklist, ezs_lifecycle, ezs_park_plan, ezs_project,
    ezs_site_analysis, ezs_site_work, ezs_sites, projects_process,
)
from app.services.space_projection import ProjectionError

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


@router.post("/import-park-plan")
async def import_park_plan(
    company_id: str = Query(...), dry_run: bool = Query(False),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Импорт рабочего реестра работ по парку (переносы, замены, демонтажи).

    Отдельная ручка, а не режим импорта банка ЗУ: тот файл описывает МЕСТА под
    новую стройку, этот — РАБОТЫ на действующих станциях. Общего в них только
    расширение файла.
    """
    cid = await assert_company_member(company_id, user, db)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    return await ezs_park_plan.import_park_plan_xlsx(db, cid, content, dry_run)


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
    overdue: bool = Query(False), risk: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=2000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Список площадок с фильтрами. `risk` раскрывает цифры обзора портфеля
    (без ответственного, без шага, просрочки ТП и поставок, застрявшие)."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_sites.list_sites(db, cid, stage=stage, region=region, search=search,
                                      owner_id=owner_id, overdue=overdue, risk=risk,
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


@router.get("/meta/project-kinds")
async def project_kinds(user: User = Depends(get_current_user)):
    """Типы проектов и режимы закрытия — для форм заведения и остановки."""
    return {"kinds": ezs_lifecycle.PROJECT_KINDS, "closeModes": ezs_lifecycle.CLOSE_MODES}


@router.get("/projects")
async def list_projects(
    company_id: str = Query(...),
    site_id: uuid.UUID | None = Query(None, description="проекты одной площадки"),
    location_id: str | None = Query(None, description="проекты одного объекта сети"),
    kind: str | None = Query(None),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """История места или актива: сколько проектов на нём было и чем кончились."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_lifecycle.list_projects(
        db, cid, site_id=site_id, location_id=location_id, kind=kind)


@router.post("/{site_id}/projects", status_code=201)
async def start_project(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Завести на площадке новый проект (вторая очередь, модернизация, демонтаж)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_lifecycle.start_project(
        db, cid, site=site, kind=str(payload.get("kind") or "new_build"),
        title=payload.get("title"), location_id=payload.get("location_id"),
        reason=payload.get("reason"), user=user)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось завести проект"))
    await db.commit()
    return res["project"]


@router.post("/{site_id}/successor", status_code=201)
async def start_successor(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Завести новую работу на действующем объекте: модернизация, перенос, демонтаж.

    Возвращает id нового ПРОЕКТА — у него своё рабочее место, свой бюджет и своя
    дата ввода. Прежний проект не трогаем: его дата ввода остаётся фактом.
    """
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_lifecycle.start_successor(
        db, cid, source=site, kind=str(payload.get("kind") or "retrofit"),
        reason=payload.get("reason"), user=user)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось завести работу"))
    await db.commit()
    return res


@router.get("/locations/{location_id}/works")
async def works_on_location(
    location_id: str, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Что делали с этим объектом: стройка, модернизации, переносы — по порядку."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_lifecycle.works_on_location(db, cid, location_id)


@router.post("/projects/{project_id}/close")
async def close_project(
    project_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Приостановить или отменить проект.

    Разные вещи: приостановка держит капвложения на счёте 08, отмена без
    перспектив возобновления — основание списать их в периоде решения.
    """
    cid = await assert_company_member(company_id, user, db)
    from app.models import EzsProject
    p = (await db.execute(select(EzsProject).where(
        EzsProject.company_id == cid, EzsProject.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Проект не найден")
    res = await ezs_lifecycle.close_project(
        db, cid, p, mode=str(payload.get("mode") or ""), reason=str(payload.get("reason") or ""),
        user=user)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось закрыть проект"))
    await db.commit()
    return res["project"]


@router.post("/projects/reopen")
async def reopen_from_operation(
    payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Вернуть объект из эксплуатации в проектный контур новым проектом."""
    cid = await assert_company_member(company_id, user, db)
    res = await ezs_lifecycle.reopen_from_operation(
        db, cid, str(payload.get("location_id") or ""),
        kind=str(payload.get("kind") or "retrofit"),
        reason=str(payload.get("reason") or ""), user=user)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message", "Не удалось вернуть объект в проекты"))
    await db.commit()
    return res["project"]


@router.get("/meta/checklist")
async def checklist_meta(user: User = Depends(get_current_user)):
    """Регламент согласования ЗУ целиком: 8 этапов, задачи, ответственные.

    Гейты стадий — тот же чек-лист, разложенный по воронке; здесь он в порядке
    документа, чтобы сверять работу с бумагой отдела развития.
    """
    return ezs_checklist.checklist_meta()


@router.post("/bulk/assign")
async def bulk_assign(
    payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Назначить ответственного сразу нескольким проектам.

    `owner_user_id: null` снимает ответственного. Раздача трёхсот проектов по
    одному — не работа, а повод не начинать вести их вовсе.
    """
    cid = await assert_company_member(company_id, user, db)
    ids = [uuid.UUID(str(i)) for i in (payload.get("site_ids") or [])]
    res = await ezs_site_work.bulk_assign(db, cid, ids, payload.get("owner_user_id"), user)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    await db.commit()
    return res


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


@router.get("/portfolio")
async def portfolio(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Обзор портфеля проектов: этапы, бюджет, присоединения, реализация."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.portfolio(db, cid)


@router.get("/portfolio/overview")
async def portfolio_overview(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Рабочий обзор портфеля: что горит, где затык, когда ждать станции, что изменилось."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.portfolio_overview(db, cid)


@router.get("/changes/overview")
async def changes_overview(
    company_id: str = Query(...),
    days: int = Query(30),
    category: str | None = Query(None),
    source: str | None = Query(None),
    cursor: uuid.UUID | None = Query(None),
    limit: int = Query(60),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Проверяемая история изменений проекта: прежнее и новое значение рядом."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_changes.changes_overview(
        db, cid, days=days, category=category, source=source,
        cursor=cursor, limit=limit,
    )


@router.get("/tech-connections")
async def tech_connections(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Реестр техприсоединений по всем проектам: статусы, сроки, просрочки."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.tech_connections_report(db, cid)


@router.get("/phase-durations")
async def phase_durations(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Сколько проекты реально стоят на каждой стадии (медиана по истории)."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.phase_durations(db, cid)


@router.get("/export/portfolio")
async def export_portfolio(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Выгрузка портфеля проектов в xlsx — то, что уходит на совещание."""
    from fastapi.responses import Response

    cid = await assert_company_member(company_id, user, db)
    data = await ezs_project.export_portfolio_xlsx(db, cid)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="projects_portfolio.xlsx"'},
    )


# Выгрузка любого экрана раздела: совещание идёт по Excel, и если таблицы нет,
# цифры переписывают руками в свой файл — а он назавтра расходится с системой.
_EXPORTS = {
    "funnel": ("Воронка", "funnel"),
    "matrix": ("Приоритеты", "priorities"),
    "budget": ("Бюджет", "budget"),
    "accounting": ("Ждёт учёта", "awaiting_accounting"),
    "tech-connections": ("Присоединение", "tech_connections"),
    "equipment": ("Оборудование", "equipment"),
}


@router.get("/export/{report}")
async def export_report(
    report: str, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Выгрузка экрана в xlsx: воронка, приоритеты, бюджет, учёт, ТП, оборудование."""
    from fastapi.responses import Response

    if report not in _EXPORTS:
        raise HTTPException(404, "Неизвестный отчёт")
    cid = await assert_company_member(company_id, user, db)
    _, fname = _EXPORTS[report]
    fn = getattr(ezs_project, f"export_{report.replace('-', '_')}_xlsx")
    data = await fn(db, cid)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
    )


@router.get("/equipment")
async def equipment_report(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Сводный реестр потребности в оборудовании по всем проектам."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.equipment_report(db, cid)


@router.get("/tech-connections/by-operator")
async def tech_connections_by_operator(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Присоединения по сетевым организациям: сроки, стоимость, отказы.

    Сроки и цены у разных сетевых различаются в разы, поэтому «сколько ждать ТУ»
    без ответа «у кого» — бесполезная средняя по больнице.
    """
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.tech_connections_by_operator(db, cid)


@router.get("/costs/report")
async def costs_report(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Бюджет портфеля по статьям: план, факт, отклонение.

    Капвложения и расходы периода разделены: у них разная судьба при отмене
    проекта, и складывать их в одну сумму нельзя.
    """
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.costs_report(db, cid)


@router.get("/awaiting-accounting")
async def awaiting_accounting(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """«Ждёт учёта»: проект ушёл вперёд, а в бухгалтерии записи нет."""
    cid = await assert_company_member(company_id, user, db)
    return await ezs_project.awaiting_accounting(db, cid)


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
    # Факт капвложений точнее плана: пока стройка не закрыта, берём план.
    costs = await ezs_project.list_costs(db, cid, site.id)
    capex_budget = costs["capitalFact"] or costs["capitalPlan"] or None
    return {
        "economics": ezs_site_analysis.economics(site, bench, capex_budget=capex_budget),
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
    """Перевод по воронке.

    Обязательные пункты гейта блокируют движение вперёд; обход — только с
    обоснованием и правами админа компании, и он попадает в историю.
    """
    stage = str(payload.get("stage") or "")
    if stage not in ezs_sites.ALL_STAGES:
        raise HTTPException(400, f"Неизвестная стадия: {stage}")
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    may_override = await _is_company_admin(db, cid, user)
    res = await ezs_site_work.set_stage(
        db, site, stage, reason=payload.get("reason"), user=user,
        may_override=may_override, override=bool(payload.get("override")))
    if not res.get("moved") and res.get("blocked"):
        await db.rollback()
        return {**res, "mayOverride": may_override}
    await db.commit()
    return {**res, "mayOverride": may_override,
            "site": await ezs_sites.site_detail(db, cid, site_id)}


async def _is_company_admin(db: AsyncSession, cid, user: User) -> bool:
    """Право обхода гейта: суперадмин или админ этой компании."""
    if getattr(user, "is_superadmin", False):
        return True
    from app.models import UserCompany
    row = (await db.execute(select(UserCompany).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    return bool(row is not None and getattr(row, "role", None) == "admin")


# ── Документы проекта ──────────────────────────────────────────────────────
@router.get("/{site_id}/docs")
async def list_site_docs(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Документы проекта: ЕГРН, ТУ, договор, схемы, фото, акты."""
    cid = await assert_company_member(company_id, user, db)
    await _owned(db, cid, site_id)
    return await ezs_project.list_docs(db, cid, site_id)


@router.post("/{site_id}/docs", status_code=201)
async def upload_site_doc(
    site_id: uuid.UUID, company_id: str = Query(...),
    kind: str = Query("other"), title: str | None = Query(None),
    note: str | None = Query(None), file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Загрузить документ к проекту. Файл ложится в общее хранилище."""
    import hashlib
    import os
    from pathlib import Path

    from app.models import SourceFile

    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")

    file_id = uuid.uuid4()
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "file").suffix
    path = upload_dir / f"{file_id}{ext}"
    with open(path, "wb") as fh:
        fh.write(content)
    db.add(SourceFile(
        id=file_id, company_id=cid, file_name=file.filename or "документ",
        mime_type=file.content_type or "application/octet-stream", size=len(content),
        storage_path=str(path), fingerprint=hashlib.sha256(content).hexdigest()))
    await db.flush()

    res = await ezs_project.add_doc(db, cid, site, file_id=file_id, kind=kind,
                                    title=title, note=note, user=user)
    await db.commit()
    return res


@router.delete("/{site_id}/docs/{doc_id}")
async def delete_site_doc(
    site_id: uuid.UUID, doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    ok = await ezs_project.delete_doc(db, cid, site, doc_id, user)
    if not ok:
        raise HTTPException(404, "Документ не найден")
    await db.commit()
    return {"deleted": str(doc_id)}


# ── Проект: контекст, техприсоединение, бюджет, учёт ───────────────────────
@router.get("/{site_id}/project")
async def project_context(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Всё, что карточка проекта показывает сверх паспорта: этапы, ТП, бюджет,
    субсидия, договор и объект сети."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    return await ezs_project.project_context(db, cid, site)


@router.get("/{site_id}/roadmap")
async def project_roadmap(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Схема реализации проекта: путь от участка до эксплуатации одной лентой."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    return await ezs_project.project_roadmap(db, cid, site)


@router.put("/{site_id}/tech-connection")
async def put_tech_connection(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Завести или обновить техприсоединение проекта (заявка → ТУ → договор → факт)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_project.upsert_tech_connection(db, cid, site, payload, user)
    await db.commit()
    return res


@router.put("/{site_id}/equipment")
async def put_equipment(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Позиция оборудования проекта: план → заказ → поставка → монтаж."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_project.upsert_equipment(db, cid, site, payload, user)
    await db.commit()
    return res


@router.delete("/{site_id}/equipment/{eq_id}")
async def del_equipment(
    site_id: uuid.UUID, eq_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    ok = await ezs_project.delete_equipment(
        db, cid, site_id, eq_id, site=site, user=user)
    if not ok:
        raise HTTPException(404, "Позиция не найдена")
    await db.commit()
    return {"deleted": str(eq_id)}


@router.put("/{site_id}/costs")
async def put_cost(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Статья бюджета проекта (план/факт)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_project.upsert_cost(db, cid, site, payload, user)
    await db.commit()
    return res


@router.delete("/{site_id}/costs/{cost_id}")
async def del_cost(
    site_id: uuid.UUID, cost_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    ok = await ezs_project.delete_cost(db, cid, site_id, cost_id, site=site, user=user)
    if not ok:
        raise HTTPException(404, "Статья не найдена")
    await db.commit()
    return {"deleted": str(cost_id)}


@router.post("/{site_id}/link-contract")
async def link_contract(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Привязать договор учёта к проекту (аренда, сервитут, разрешение)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_project.link_contract(db, cid, site, payload.get("contract_id"), user)
    if not res.get("ok"):
        raise HTTPException(404, res.get("message", "Договор не найден"))
    await db.commit()
    return res


@router.post("/{site_id}/link-location")
async def link_location(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Связать проект с объектом сети — цикл замкнут."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    res = await ezs_project.link_location(db, cid, site, payload.get("location_id"), user)
    if not res.get("ok"):
        raise HTTPException(404, res.get("message", "Объект не найден"))
    await db.commit()
    return res


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


@router.get("/{site_id}/case")
async def project_case(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Ход проекта: стадия маршрута, доступные действия, вехи, сколько стоим.

    Гейты отвечают на «что заполнено», ход — на «что делать дальше и чья очередь».
    """
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    try:
        return await projects_process.case_state(db, cid, site, user)
    except ProjectionError as e:
        # Мост не настроен или Координатор недоступен — карточка должна открыться
        # и показать причину, а не упасть целиком из-за необязательной панели.
        return {"ok": False, "exists": False, "error": str(e)}


@router.post("/{site_id}/case")
async def open_project_case(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Начать вести проект по маршруту (или обновить сводку у заведённого кейса)."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    try:
        return await projects_process.sync_case(db, cid, site, user)
    except ProjectionError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/{site_id}/case/transition")
async def apply_project_step(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Выполнить шаг маршрута: тело — { linkId, payload, branchCaseId? }."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    link_id = str(payload.get("linkId") or "")
    if not link_id:
        raise HTTPException(400, "Не указано действие (linkId)")
    branch = payload.get("branchCaseId")
    try:
        res = await projects_process.apply_step(
            db, cid, site, link_id, payload.get("payload") or {}, user,
            branch_case_id=str(branch) if branch else None)
    except ProjectionError as e:
        raise HTTPException(400, str(e)) from e
    await db.commit()
    return res


@router.post("/{site_id}/case/undo")
async def undo_project_step(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Отменить последний шаг маршрута (нажали не ту кнопку).

    Правила — на стороне Координатора: свой последний шаг и не позже суток.
    """
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    try:
        res = await projects_process.undo_step(db, cid, site, user)
    except ProjectionError as e:
        raise HTTPException(400, str(e)) from e
    await db.commit()
    return res


@router.get("/{site_id}/participants")
async def project_participants(
    site_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Кто ведёт проект и в какой роли регламента. Заодно — словарь ролей для формы."""
    cid = await assert_company_member(company_id, user, db)
    await _owned(db, cid, site_id)
    rows = (await db.execute(
        select(EzsSiteParticipant, User)
        .join(User, User.id == EzsSiteParticipant.user_id)
        .where(EzsSiteParticipant.site_id == site_id)
        .order_by(EzsSiteParticipant.role_code, User.name)
    )).all()
    return {
        "roles": [{"code": c, "label": l} for c, l in ezs_checklist.ROLES.items()],
        "participants": [
            {"id": str(p.id), "userId": str(p.user_id), "roleCode": p.role_code,
             "name": u.name or u.email, "email": u.email, "note": p.note}
            for p, u in rows
        ],
    }


@router.post("/{site_id}/participants")
async def add_project_participant(
    site_id: uuid.UUID, payload: dict, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Назначить человека на роль в проекте. Тело: { userId, roleCode, note }."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    user_id = payload.get("userId")
    role_code = (payload.get("roleCode") or "").strip()
    if not user_id or not role_code:
        raise HTTPException(400, "Нужны человек и роль")
    if role_code not in ezs_checklist.ROLES:
        raise HTTPException(400, f"Неизвестная роль регламента: {role_code}")
    # Человек должен быть в этой же компании: состав проекта не место для чужих.
    # Проверка именно членства, а не просто существования: id людей отдают разные
    # ручки, и без join сотрудник соседнего пространства получал бы роль в чужом
    # проекте — вместе с правом нажимать её кнопки и видимостью почты в составе.
    from app.models import UserCompany
    try:
        target_id = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(400, "Неизвестный человек")
    target = (await db.execute(
        select(User).join(UserCompany, UserCompany.user_id == User.id)
        .where(User.id == target_id, UserCompany.company_id == cid))).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "Человек не найден в этой компании")

    exists = (await db.execute(select(EzsSiteParticipant).where(
        EzsSiteParticipant.site_id == site_id,
        EzsSiteParticipant.user_id == target.id,
        EzsSiteParticipant.role_code == role_code))).scalar_one_or_none()
    if exists is None:
        db.add(EzsSiteParticipant(company_id=cid, site_id=site_id, user_id=target.id,
                                  role_code=role_code, note=payload.get("note")))
        await db.commit()

    # Состав — часть полномочий маршрута, поэтому уезжает в кейс сразу, а не при
    # следующем шаге: иначе назначенный человек не увидит своей кнопки.
    await _push_participants(db, cid, site, user)
    return {"ok": True}


@router.delete("/{site_id}/participants/{participant_id}")
async def drop_project_participant(
    site_id: uuid.UUID, participant_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Снять человека с роли в проекте."""
    cid = await assert_company_member(company_id, user, db)
    site = await _owned(db, cid, site_id)
    row = (await db.execute(select(EzsSiteParticipant).where(
        EzsSiteParticipant.id == participant_id,
        EzsSiteParticipant.site_id == site_id))).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    await _push_participants(db, cid, site, user)
    return {"ok": True}


async def _push_participants(db: AsyncSession, cid, site: EzsSite, user: User) -> None:
    """Отправить состав в кейс. Кейса ещё нет — это норма, состав уедет при заведении."""
    try:
        await projects_process.sync_case(db, cid, site, user)
    except ProjectionError:
        pass


async def _owned(db: AsyncSession, cid, site_id: uuid.UUID) -> EzsSite:
    """Площадка строго своей компании — иначе чужой банк можно править по id."""
    site = (await db.execute(
        select(EzsSite).where(EzsSite.company_id == cid, EzsSite.id == site_id)
    )).scalar_one_or_none()
    if site is None:
        raise HTTPException(404, "Площадка не найдена")
    return site
