"""/api/charge-sessions — импорт и данные зарядных сессий ЭЗС (energy, РусГидро).

Источник — Excel-выгрузка ChargeTransactions (26 колонок). Импорт парсит файл,
нормализует поля, дедуплицирует по «ID сессии» и сохраняет в charge_sessions.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import ChargeSession, User

router = APIRouter(prefix="/charge-sessions", tags=["Зарядные сессии"])


@router.post("/import")
async def import_sessions(
    company_id: str,
    file: UploadFile = File(...),
    mode: str = "append",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Импорт Excel-выгрузки зарядных сессий.

    mode:
      • 'append'  — подгрузить только новые (дедуп по «ID сессии»);
      • 'replace' — переписать: удалить все сессии компании и загрузить заново.

    Парсинг и нормализация (коннектор/тип клиента, регион, дедуп, режим) — через
    общий сервис ingest_charge_sessions (тот же путь, что и у канала ЭЗС)."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.charge_sessions_normalize import ingest_charge_sessions, parse_sessions_xlsx

    data = await file.read()
    try:
        rows = parse_sessions_xlsx(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {exc}") from exc

    result = await ingest_charge_sessions(db, cid, rows, channel_id=None, mode=mode)
    await db.commit()
    return {"created": result["created"], "skipped": result["skipped"],
            "errors": result["errors"], "deleted": result.get("deleted", 0),
            "mode": result.get("mode", mode)}


@router.post("/enrich")
async def enrich_sessions(
    company_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Обогащение сессий справочником «Организации» (xlsx): проставить
    наименование корпоративного клиента (client_name) ЮЛ-сессиям по телефону
    (user_id = телефон организации). Идемпотентно, отдельно от загрузки сессий."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.charge_sessions_normalize import enrich_sessions_with_orgs, parse_orgs_xlsx

    data = await file.read()
    try:
        parsed = parse_orgs_xlsx(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {exc}") from exc
    if not parsed.get("orgs"):
        raise HTTPException(400, "В справочнике не найдено строк «телефон + название»")

    result = await enrich_sessions_with_orgs(db, cid, parsed)
    await db.commit()
    return result


@router.post("/reenrich")
async def reenrich_sessions(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Переприменить обогащение из сохранённого реестра corporate_clients (без файла).
    Нужно после перезагрузки таблицы сессий — восстанавливает распределение по ЮЛ."""
    cid = await assert_company_member(company_id, current_user, db)
    from app.services.charge_sessions_normalize import enrich_from_registry
    result = await enrich_from_registry(db, cid)
    await db.commit()
    return result


@router.get("/count")
async def count_sessions(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    cid = await assert_company_member(company_id, current_user, db)
    n = (await db.execute(
        select(func.count()).select_from(ChargeSession).where(ChargeSession.company_id == cid)
    )).scalar_one()
    return {"count": int(n)}


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/export")
async def export_sessions(
    company_id: str,
    date_from: str,
    date_to: str,
    user_type: str | None = None,
    client: str | None = None,
    limit: int = Query(60000, ge=1, le=200000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Построчная выгрузка сессий в xlsx с ОБЕИМИ ценами: тариф станции (розница)
    и договорной тариф ЮЛ + обе выручки + разница. Фильтры: период (обяз.),
    опц. тип клиента (ФЛ/ЮЛ) и конкретный клиент (client_name)."""
    cid = await assert_company_member(company_id, current_user, db)
    try:
        df = date.fromisoformat(date_from[:10])
        dt = date.fromisoformat(date_to[:10])
    except ValueError as exc:
        raise HTTPException(400, "Неверный формат даты (YYYY-MM-DD)") from exc
    lo = datetime.combine(df, datetime.min.time())
    hi = datetime.combine(dt, datetime.max.time())

    S = ChargeSession
    q = select(S).where(S.company_id == cid, S.started_at.is_not(None),
                        S.started_at >= lo, S.started_at <= hi)
    if user_type:
        q = q.where(S.user_type == user_type)
    if client:
        q = q.where(S.client_name == client)
    rows = (await db.execute(q.order_by(S.started_at).limit(limit))).scalars().all()

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sessions"
    ws.append(["ID сессии", "Станция", "Регион", "Коннектор", "Начало", "Энергия кВтч",
               "Тип клиента", "Клиент (ЮЛ)",
               "Тариф станции ₽/кВтч", "Выручка по рознице ₽",
               "Тариф ЮЛ ₽/кВтч", "Выручка ЮЛ ₽", "Разница ЮЛ−розница ₽"])
    for s in rows:
        energy = float(s.energy_kwh or 0)
        retail_tariff = float(s.tariff or 0)
        retail_rev = round(energy * retail_tariff, 2)   # розница-эквивалент (что было бы по станции)
        corp_amount = float(s.client_amount) if s.client_amount is not None else None
        diff = round(corp_amount - retail_rev, 2) if corp_amount is not None else None
        ws.append([
            s.session_ext_id, s.station_code, s.region, s.connector_type,
            s.started_at.strftime("%d.%m.%Y %H:%M") if s.started_at else "",
            round(energy, 3), s.user_type, s.client_name,
            retail_tariff, retail_rev,
            float(s.client_tariff) if s.client_tariff is not None else None,
            corp_amount, diff,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    fname = f"sessions_{company_id}_{date_from[:10]}_{date_to[:10]}.xlsx"
    return Response(content=buf.getvalue(), media_type=_XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
