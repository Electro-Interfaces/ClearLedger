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
from app.services.export_audit import log_export
from app.services.export_files import xlsx_response

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

    # След выгрузки: в файле — персональные данные клиентов и обе выручки.
    scope = f"{date_from[:10]}…{date_to[:10]}"
    if user_type:
        scope += f", тип {user_type}"
    if client:
        scope += f", клиент «{client}»"
    log_export(db, cid, current_user,
               f"Реестр сессий ЭЗС (xlsx): {len(rows)} строк, период {scope}")

    fname = f"Реестр сессий ЭЗС {date_from[:10]} — {date_to[:10]}"
    if client:
        fname += f" · {client}"
    return xlsx_response(wb, f"{fname}.xlsx")


@router.get("/export/monthly-matrix")
async def export_monthly_matrix(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Матрица «станция × месяц» (кВт·ч) в формате привычного свода «ОБЩАЯ»:
    паспортные колонки + месяцы за весь горизонт. Отпуск = сводная контрагента
    (station_dispense_periods) до точки склейки, далее — зарядные сессии (то же
    правило, что в «Динамике 2024+»). Прямая замена ручного Excel-свода."""
    from sqlalchemy import text as sa_text

    from app.models import ServiceLocation
    cid = await assert_company_member(company_id, current_user, db)

    file_rows = (await db.execute(sa_text(
        "SELECT location_id, period, SUM(dispense_kwh) AS kwh "
        "FROM station_dispense_periods "
        "WHERE company_id = :cid AND dispense_kwh IS NOT NULL "
        "GROUP BY location_id, period"), {"cid": str(cid)})).all()
    sess_rows = (await db.execute(sa_text(
        "SELECT location_id, to_char(date_trunc('month', started_at), 'YYYY-MM-01') AS period, "
        "       SUM(energy_kwh) AS kwh "
        "FROM charge_sessions "
        "WHERE company_id = :cid AND location_id IS NOT NULL AND energy_kwh IS NOT NULL "
        "GROUP BY location_id, 2"), {"cid": str(cid)})).all()

    # точка склейки: первый месяц, где сессии дают ≥80% сводной (см. long-trend)
    f_tot: dict[str, float] = {}
    for r in file_rows:
        f_tot[r.period] = f_tot.get(r.period, 0.0) + float(r.kwh or 0)
    s_tot: dict[str, float] = {}
    for r in sess_rows:
        s_tot[r.period] = s_tot.get(r.period, 0.0) + float(r.kwh or 0)
    cutoff = None
    for p in sorted(set(f_tot) | set(s_tot)):
        sk, fk = s_tot.get(p, 0.0), f_tot.get(p)
        if sk > 0 and (fk is None or sk >= fk * 0.8):
            cutoff = p
            break
    cutoff = cutoff or "9999-99"

    cell: dict[tuple[str, str], float] = {}
    for r in file_rows:
        if r.period < cutoff:
            cell[(r.location_id, r.period)] = cell.get((r.location_id, r.period), 0.0) + float(r.kwh or 0)
    for r in sess_rows:
        if r.period >= cutoff:
            cell[(r.location_id, r.period)] = cell.get((r.location_id, r.period), 0.0) + float(r.kwh or 0)
    months = sorted({p for (_, p) in cell})
    loc_ids = {lid for (lid, _) in cell}

    locs = {l.id: l for l in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == cid)
    )).scalars().all() if l.id in loc_ids}

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Станция × месяц"
    loc_cls = {"city": "город", "highway": "трасса"}
    spd_cls = {"fast": "Быстрая", "slow": "Медленная"}
    ws.append(["Б/У", "№ ZOI-1", "Регион", "Город", "Адрес", "трасса/город",
               "Быстрая/медленная", "Марка", "Мощность", "Инвентарный номер",
               "Дата установки", "Дата вывода"]
              + [f"{m[5:7]}.{m[:4]}" for m in months] + ["Итого, кВт·ч"])
    order = sorted(loc_ids, key=lambda lid: (
        (locs.get(lid).extra_metadata or {}).get("federalSubject") or "" if locs.get(lid) else "",
        locs.get(lid).name if locs.get(lid) else ""))
    for lid in order:
        l = locs.get(lid)
        md = (l.extra_metadata or {}) if l else {}
        row_vals = [round(cell.get((lid, m), 0.0), 1) or None for m in months]
        ws.append([
            md.get("buNumber") or md.get("number") or (l.station_number if l else None),
            md.get("zoi1"),
            md.get("federalSubject") or (l.city if l else None),
            (l.city if l else None) or md.get("cityName"),
            (l.address if l else None),
            loc_cls.get(getattr(l, "location_class", None) or ""),
            spd_cls.get(getattr(l, "speed_class", None) or ""),
            getattr(l, "brand", None),
            getattr(l, "power_kwt", None),
            getattr(l, "inventory_number", None),
            getattr(l, "installed_on", None),
            getattr(l, "decommissioned_on", None),
        ] + row_vals + [round(sum(v for v in (cell.get((lid, m), 0.0) for m in months)), 1)])
    # итоговая строка сети
    ws.append(["", "", "ИТОГО по сети", "", "", "", "", "", "", "", "", ""]
              + [round(sum(cell.get((lid, m), 0.0) for lid in loc_ids), 1) for m in months]
              + [round(sum(cell.values()), 1)])

    buf = io.BytesIO()
    wb.save(buf)

    # След выгрузки: свод по всей сети — заменяет ручной Excel и уходит наружу.
    span = f"{months[0]}…{months[-1]}" if months else "нет данных"
    log_export(db, cid, current_user,
               f"Матрица «станция × месяц» (xlsx): {len(order)} станций, "
               f"{len(months)} мес. ({span}), склейка с {cutoff}")

    period = f" {months[0][:7]} — {months[-1][:7]}" if months else ""
    return xlsx_response(wb, f"Матрица станция-месяц{period}.xlsx")
