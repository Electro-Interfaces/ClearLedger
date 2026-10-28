"""Приложение «Бухгалтерия» пространства — чтение сопряжений (energy, РусГидро).

Отвечает на вопрос менеджера: что бухгалтерия знает об этом контрагенте, договоре и
объекте, что знаем мы, как это связано и что нужно разобрать. Источник сведений —
выгруженные отчёты, уже принятые в пространство строками `DataEntry` слоя `raw`.

Только чтение: ни импорта, ни правок карточек здесь нет. Доступ — тот же, что у
реестра договоров (`references_router`): членство в компании плюс необязательный
отбор по своему юрлицу. Новый экран прав не расширяет.

Отбор один на все ответы: плитки, список, карточка и выгрузка считаются из одного
среза (`services/accounting_space.load_slice`), поэтому число в плитке и длина
списка не могут разойтись.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import User
from app.services import accounting_space as acct

router = APIRouter(prefix="/accounting/space", tags=["Бухгалтерия · сопряжение"])

# Страница по умолчанию и максимум за один запрос. Полный отбор доступен страницами:
# `total` считается по всему отбору, а не по видимой порции.
PAGE = 100
PAGE_MAX = 1000


def _matches(row: dict, needle: str) -> bool:
    if not needle:
        return True
    hay = " ".join(str(row.get(k) or "") for k in (
        "counterparty_name", "contract_label", "kind", "reason", "source_file",
        "station_hint", "candidates", "status_label", "verification_label",
    )) + " " + " ".join(row.get("card_labels") or [])
    return needle.casefold() in hay.casefold()


async def _slice(company_id: str, organization_id: str | None,
                 current_user: User, db: AsyncSession) -> acct.Slice:
    cid = await assert_company_member(company_id, current_user, db)
    return await acct.load_slice(db, cid, organization_id)


@router.get("/summary")
async def get_summary(
    company_id: str = Query(...),
    organization_id: str | None = Query(None, description="Своё юрлицо; по умолчанию все"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обзор: что загружено, за какой период, сколько разобрано и что требует внимания."""
    return acct.summary(await _slice(company_id, organization_id, current_user, db))


@router.get("/records")
async def list_records(
    company_id: str = Query(...),
    organization_id: str | None = Query(None),
    status: str | None = Query(None, description="matched|related|unmatched|candidate, через запятую"),
    verification: str | None = Query(None, description="verified|partial|differences|not_checked|stale"),
    location_id: str | None = Query(None, description="Строки, легшие на договоры этой площадки"),
    search: str | None = Query(None),
    limit: int = Query(PAGE, ge=1, le=PAGE_MAX),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Строки бухгалтерского источника с их сопряжениями, страницами по всему отбору."""
    sl = await _slice(company_id, organization_id, current_user, db)
    statuses = {s.strip() for s in (status or "").split(",") if s.strip()}
    verifications = {v.strip() for v in (verification or "").split(",") if v.strip()}
    rows = [acct.record_row(r, sl) for r in sl.records]
    if statuses:
        rows = [r for r in rows if r["status"] in statuses]
    if verifications:
        rows = [r for r in rows if r["verification"] in verifications]
    if location_id:
        rows = [r for r in rows if location_id in (r["location_ids"] or [])]
    needle = (search or "").strip()
    if needle:
        rows = [r for r in rows if _matches(r, needle)]
    return {"total": len(rows), "items": rows[offset:offset + limit]}


@router.get("/records/{entry_id}")
async def get_record(
    entry_id: str,
    company_id: str = Query(...),
    organization_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Карточка строки: сторона бухгалтерии, сторона пространства, сверенные поля."""
    try:
        uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID записи")
    sl = await _slice(company_id, organization_id, current_user, db)
    for rec in sl.records:
        if rec.id == entry_id:
            return acct.record_card(rec, sl)
    raise HTTPException(status_code=404, detail="Запись источника не найдена")


@router.get("/objects")
async def list_objects(
    company_id: str = Query(...),
    organization_id: str | None = Query(None),
    search: str | None = Query(None),
    only_gaps: bool = Query(False, description="Только площадки с непроверенными основаниями"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отчёт по объекту: аренда земли, получение электроэнергии и что об этом знает учёт."""
    sl = await _slice(company_id, organization_id, current_user, db)
    rows = acct.objects_report(sl)
    needle = (search or "").strip().casefold()
    if needle:
        rows = [r for r in rows if needle in (
            f"{r['code']} {r['name']} {r['address']}".casefold())]
    if only_gaps:
        rows = [r for r in rows if r["unchecked"] or r["without_source"]]
    return {"total": len(rows), "items": rows}


@router.get("/sources")
async def list_sources(
    company_id: str = Query(...),
    organization_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Журнал источников: файлы, партии, периоды, SHA-256 и что из них разобрано."""
    sl = await _slice(company_id, organization_id, current_user, db)
    return {"items": acct.sources(sl), "scope": acct.summary(sl)["scope"]}


@router.get("/links")
async def list_links(
    company_id: str = Query(...),
    entity_type: str = Query(..., description="contract (пока единственный тип в данных)"),
    entity_id: str = Query(...),
    organization_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сопряжения одной карточки — для бейджа в её собственном экране."""
    sl = await _slice(company_id, organization_id, current_user, db)
    return {"items": acct.entity_links(sl, entity_type, entity_id)}
