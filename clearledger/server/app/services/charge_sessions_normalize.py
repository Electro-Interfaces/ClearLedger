"""Нормализация зарядных сессий ЭЗС (energy): L1 RAW (Excel) → L2 CLEAN.

Вызывается оркестратором канала (source_type='charge_sessions_excel'):
  parse_sessions_xlsx(content) → сырые строки (L1)
  ingest_charge_sessions(db, company, rows, channel_id) → нормализация + сохранение

Нормализация коннектора/типа пользователя — через справочники mapping (kind
'connector'/'user_type'), с channel-override поверх company-default и канон-сида.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.mapping import apply, canon_region, load_kind_map

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


def parse_sessions_xlsx(content: bytes) -> list[dict[str, Any]]:
    """Excel ChargeTransactions → список сырых сессий (L1 RAW), по индексам колонок."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows: list[dict[str, Any]] = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or r[0] is None:
            continue
        started = _dt(r[5]) if len(r) > 5 else None
        finished = _dt(r[6]) if len(r) > 6 else None
        dur = round((finished - started).total_seconds() / 60, 2) if started and finished and finished >= started else 0.0
        rows.append({
            "session_ext_id": _s(r[0], 64),
            "station_code": _s(r[1] if len(r) > 1 else None, 40),
            "address": _s(r[2] if len(r) > 2 else None, 300),
            "connector_no": _s(r[3] if len(r) > 3 else None, 20),
            "connector_type": _s(r[4] if len(r) > 4 else None, 40),
            "started_at": started, "finished_at": finished, "duration_min": dur,
            "result": _s(r[7] if len(r) > 7 else None, 40),
            "charge_type": _s(r[9] if len(r) > 9 else None, 40),
            "rfid": _s((r[10] if len(r) > 10 else None) or (r[23] if len(r) > 23 else None), 120),
            "user_id": _s(r[11] if len(r) > 11 else None, 160),
            "energy_kwh": _num(r[12]) if len(r) > 12 else 0.0,
            "amount": _num(r[13]) if len(r) > 13 else 0.0,
            "tariff": _num(r[14]) if len(r) > 14 else 0.0,
            "paid_at": _dt(r[16]) if len(r) > 16 else None,
            "station_name": _s(r[17] if len(r) > 17 else None, 160),
            "region": _s(r[18] if len(r) > 18 else None, 120),
            "user_type": _s(r[21] if len(r) > 21 else None, 20),
            "payment_id": _s(r[24] if len(r) > 24 else None, 64),
        })
    return rows


async def ingest_charge_sessions(
    db: AsyncSession, company_id, rows: list[dict[str, Any]], channel_id=None,
) -> dict[str, Any]:
    """L1 RAW → нормализация (connector/user_type) → дедуп → сохранение (L2)."""
    connector_map = await load_kind_map(db, company_id, "connector", channel_id)
    user_type_map = await load_kind_map(db, company_id, "user_type", channel_id)

    existing: set[str] = set((await db.execute(
        select(ChargeSession.session_ext_id).where(ChargeSession.company_id == company_id)
    )).scalars().all())

    created = skipped = errors = 0
    seen: set[str] = set()
    batch: list[ChargeSession] = []

    for row in rows:
        try:
            sid = row.get("session_ext_id")
            if not sid:
                errors += 1
                continue
            if sid in existing or sid in seen:
                skipped += 1
                continue
            seen.add(sid)

            raw_conn = (row.get("connector_type") or "").upper() or None
            connector = apply("connector", raw_conn, connector_map) if raw_conn else None
            user_type = apply("user_type", row.get("user_type"), user_type_map) if row.get("user_type") else None

            batch.append(ChargeSession(
                company_id=company_id,
                channel_id=channel_id,
                session_ext_id=sid,
                station_code=row.get("station_code"),
                station_name=row.get("station_name"),
                region=canon_region(row.get("region")),
                address=row.get("address"),
                connector_no=row.get("connector_no"),
                connector_type=connector,
                started_at=row.get("started_at"), finished_at=row.get("finished_at"),
                duration_min=row.get("duration_min") or 0.0,
                result=row.get("result"), charge_type=row.get("charge_type"),
                user_type=user_type, user_id=row.get("user_id"), rfid=row.get("rfid"),
                energy_kwh=row.get("energy_kwh") or 0.0, amount=row.get("amount") or 0.0,
                tariff=row.get("tariff") or 0.0,
                paid_at=row.get("paid_at"), payment_id=row.get("payment_id"),
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

    return {"status": "success", "created": created, "skipped": skipped, "errors": errors,
            "message": f"загружено {created}, пропущено {skipped}"}
