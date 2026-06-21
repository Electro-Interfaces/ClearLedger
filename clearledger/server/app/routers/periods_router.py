"""
/api/periods/* — учётные периоды.

Идеология v3: TradeLedger не управляет периодами — она их РЕПЛИЦИРУЕТ из
БП (через дату запрета изменений) или строит сводку на основе
импортированных AccountingDoc. UI показывает: какие месяцы есть в данных,
сколько в них документов и закрыт ли период в эталоне.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import AccountingDoc, Period, User

router = APIRouter(prefix="/periods", tags=["Учётные периоды"])


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


# ─── Схемы ───────────────────────────────────────────────────

class PeriodRow(BaseModel):
    id: str | None = None        # null, если ещё нет записи в таблице periods
    year: int
    month: int
    status: str                  # open | closed
    closedAt: str | None = None
    closureSource: str           # from_bp | manual | derived
    docsCount: int
    minDate: str | None = None
    maxDate: str | None = None


class PeriodsSummary(BaseModel):
    items: list[PeriodRow]
    totalDocs: int
    openCount: int
    closedCount: int


class PeriodToggleRequest(BaseModel):
    company_id: str
    year: int
    month: int
    closed: bool                 # true → закрыть, false → открыть


# ─── GET /periods/summary ────────────────────────────────────

@router.get("/summary", response_model=PeriodsSummary)
async def periods_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сводка по периодам компании.

    Источник:
    - docsCount, minDate, maxDate берутся из AccountingDoc.date (строка
      "YYYY-MM-DD"), агрегируем по (year, month).
    - status, closedAt, closureSource берутся из таблицы Period — если
      записи нет, статус "open", источник "derived".
    """
    cid = await assert_company_member(company_id, current_user, db)

    # 1) Агрегат из документов. SUBSTR(date, 1, 4)/(6,2) — у нас даты строкой.
    year_col = func.substring(AccountingDoc.date, 1, 4)
    month_col = func.substring(AccountingDoc.date, 6, 2)
    docs_stmt = (
        select(
            year_col.label("y"),
            month_col.label("m"),
            func.count(AccountingDoc.id).label("c"),
            func.min(AccountingDoc.date).label("mn"),
            func.max(AccountingDoc.date).label("mx"),
        )
        .where(AccountingDoc.company_id == cid, AccountingDoc.date.is_not(None))
        .group_by(year_col, month_col)
    )
    docs_rows = (await db.execute(docs_stmt)).all()
    doc_buckets: dict[tuple[int, int], dict] = {}
    for y, m, c, mn, mx in docs_rows:
        try:
            yi, mi = int(y), int(m)
        except (TypeError, ValueError):
            continue
        if not (1 <= mi <= 12):
            continue
        doc_buckets[(yi, mi)] = {"count": int(c or 0), "min": mn, "max": mx}

    # 2) Period-записи (имеют статус и closed_at)
    period_rows = (await db.execute(
        select(Period).where(Period.company_id == cid)
    )).scalars().all()
    period_map: dict[tuple[int, int], Period] = {(p.year, p.month): p for p in period_rows}

    # 3) Объединяем — берём все ключи из периодов и доков
    all_keys = set(doc_buckets.keys()) | set(period_map.keys())
    items: list[PeriodRow] = []
    for y, m in sorted(all_keys, reverse=True):
        b = doc_buckets.get((y, m), {})
        p = period_map.get((y, m))
        items.append(PeriodRow(
            id=str(p.id) if p else None,
            year=y,
            month=m,
            status=p.status if p else "open",
            closedAt=_ts(p.closed_at) if p and p.closed_at else None,
            closureSource=p.closure_source if p else "derived",
            docsCount=b.get("count", 0),
            minDate=b.get("min"),
            maxDate=b.get("max"),
        ))

    return PeriodsSummary(
        items=items,
        totalDocs=sum(b["count"] for b in doc_buckets.values()),
        openCount=sum(1 for it in items if it.status == "open"),
        closedCount=sum(1 for it in items if it.status == "closed"),
    )


# ─── POST /periods/toggle ────────────────────────────────────

@router.post("/toggle", response_model=PeriodRow)
async def toggle_period(
    body: PeriodToggleRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Открыть или закрыть период вручную (closure_source='manual').

    В производстве закрытие должно прилетать из БП ГИГ; этот эндпоинт —
    оперативный инструмент пока репликация ДатыЗапретаИзменения
    не реализована.
    """
    cid = await assert_company_member(body.company_id, current_user, db)
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1..12")

    existing = (await db.execute(
        select(Period).where(
            Period.company_id == cid,
            Period.year == body.year,
            Period.month == body.month,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        period = Period(
            company_id=cid,
            year=body.year,
            month=body.month,
            status="closed" if body.closed else "open",
            closed_at=now if body.closed else None,
            closed_by=current_user.email,
            closure_source="manual",
        )
        db.add(period)
        await db.flush()
    else:
        existing.status = "closed" if body.closed else "open"
        existing.closed_at = now if body.closed else None
        existing.closed_by = current_user.email if body.closed else None
        existing.closure_source = "manual"
        period = existing
        await db.flush()

    # docsCount считаем отдельно
    docs_count = (await db.execute(
        select(func.count(AccountingDoc.id)).where(
            AccountingDoc.company_id == cid,
            func.substring(AccountingDoc.date, 1, 4) == str(body.year),
            func.substring(AccountingDoc.date, 6, 2) == f"{body.month:02d}",
        )
    )).scalar_one()

    return PeriodRow(
        id=str(period.id),
        year=period.year,
        month=period.month,
        status=period.status,
        closedAt=_ts(period.closed_at),
        closureSource=period.closure_source,
        docsCount=int(docs_count or 0),
    )
