"""/api/charge-sessions — импорт и данные зарядных сессий ЭЗС (energy, РусГидро).

Источник — Excel-выгрузка ChargeTransactions (26 колонок). Импорт парсит файл,
нормализует поля, дедуплицирует по «ID сессии» и сохраняет в charge_sessions.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import ChargeSession, User

router = APIRouter(prefix="/charge-sessions", tags=["Зарядные сессии"])

_DT_FORMATS = ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M")


def _num(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0


def _dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v).strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _s(v, maxlen: int | None = None) -> str | None:
    if v is None:
        return None
    out = str(v).strip()
    if not out:
        return None
    return out[:maxlen] if maxlen else out


@router.post("/import")
async def import_sessions(
    company_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Импорт Excel-выгрузки зарядных сессий. Дедуп по «ID сессии»."""
    cid = await assert_company_member(company_id, current_user, db)
    try:
        import openpyxl
    except ImportError as exc:
        raise HTTPException(500, "openpyxl не установлен на сервере") from exc

    data = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {exc}") from exc
    ws = wb[wb.sheetnames[0]]

    existing: set[str] = set((await db.execute(
        select(ChargeSession.session_ext_id).where(ChargeSession.company_id == cid)
    )).scalars().all())

    created = skipped = errors = 0
    seen: set[str] = set()
    batch: list[ChargeSession] = []

    for r in ws.iter_rows(min_row=2, values_only=True):
        try:
            if not r or r[0] is None:
                continue
            sid = str(r[0]).strip()
            if not sid:
                errors += 1
                continue
            if sid in existing or sid in seen:
                skipped += 1
                continue
            seen.add(sid)

            started = _dt(r[5]) if len(r) > 5 else None
            finished = _dt(r[6]) if len(r) > 6 else None
            dur = round((finished - started).total_seconds() / 60, 2) if started and finished and finished >= started else 0.0

            batch.append(ChargeSession(
                company_id=cid,
                session_ext_id=sid[:64],
                station_code=_s(r[1] if len(r) > 1 else None, 40),
                address=_s(r[2] if len(r) > 2 else None, 300),
                connector_no=_s(r[3] if len(r) > 3 else None, 20),
                connector_type=(_s(r[4], 40).upper() if len(r) > 4 and _s(r[4]) else None),
                started_at=started, finished_at=finished, duration_min=dur,
                result=_s(r[7] if len(r) > 7 else None, 40),
                charge_type=_s(r[9] if len(r) > 9 else None, 40),
                rfid=_s((r[10] if len(r) > 10 else None) or (r[23] if len(r) > 23 else None), 120),
                user_id=_s(r[11] if len(r) > 11 else None, 160),
                energy_kwh=_num(r[12]) if len(r) > 12 else 0.0,
                amount=_num(r[13]) if len(r) > 13 else 0.0,
                tariff=_num(r[14]) if len(r) > 14 else 0.0,
                paid_at=_dt(r[16]) if len(r) > 16 else None,
                station_name=_s(r[17] if len(r) > 17 else None, 160),
                region=_s(r[18] if len(r) > 18 else None, 120),
                user_type=_s(r[21] if len(r) > 21 else None, 20),
                payment_id=_s(r[24] if len(r) > 24 else None, 64),
            ))
            created += 1
            if len(batch) >= 1000:
                db.add_all(batch)
                await db.flush()
                batch = []
        except Exception:  # noqa: BLE001
            errors += 1

    if batch:
        db.add_all(batch)
        await db.flush()
    await db.commit()

    return {"created": created, "skipped": skipped, "errors": errors}


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
