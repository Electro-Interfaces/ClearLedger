"""/api/books — бухгалтерия-эталон офисного пространства и её разрезы.

Первоисток концепции: у компании без объектов главный источник данных — её
БУХГАЛТЕРИЯ. Закрытый период в ней неизменяем и служит эталоном, с которым
сверяется всё остальное; открытый период — оперативные данные, которые ещё
поедут. Отсюда и разрезы: «Продажи» и «Услуги» не заводят своих чисел, а
читают тот же регистр под своим углом.

Один роутер на три приложения сознательно: данные одни (`gl_entries`,
`accounting_docs`), разные только вопросы к ним. Отдельные файлы означали бы
три копии одних и тех же выборок.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import AccountingDoc, GlAccount, GlEntry, Period, User

router = APIRouter(prefix="/books", tags=["Бухгалтерия пространства"])

# Счета выручки, НДС с продаж и себестоимости. Вынесены константами: у другой
# организации пространства план счетов тот же типовой, но если разойдётся —
# правится здесь, а не в пяти выборках.
REVENUE_KT = "90.01.1"
VAT_DT, VAT_KT = "90.03", "68.02"
COST_DT = "90.02.1"


def _num(v: Any) -> float:
    return float(v or 0)


async def _turnover(db: AsyncSession, cid, dt: str | None = None, kt: str | None = None,
                    year: int | None = None) -> float:
    q = select(func.coalesce(func.sum(GlEntry.amount), 0)).where(GlEntry.company_id == cid)
    if dt:
        q = q.where(GlEntry.account_dt == dt)
    if kt:
        q = q.where(GlEntry.account_kt == kt)
    if year:
        q = q.where(GlEntry.period_year == year)
    return _num((await db.execute(q)).scalar_one())


@router.get("/overview")
async def overview(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Сводка бухгалтерии: выручка, НДС, себестоимость, прибыль и годы."""
    cid = await assert_company_member(company_id, current_user, db)

    revenue = await _turnover(db, cid, kt=REVENUE_KT)
    vat = await _turnover(db, cid, dt=VAT_DT, kt=VAT_KT)
    cost = await _turnover(db, cid, dt=COST_DT)

    years = [
        {"year": y, "revenue": _num(a)}
        for y, a in (await db.execute(
            select(GlEntry.period_year, func.sum(GlEntry.amount))
            .where(GlEntry.company_id == cid, GlEntry.account_kt == REVENUE_KT)
            .group_by(GlEntry.period_year).order_by(GlEntry.period_year)
        )).all()
    ]

    entries, first, last = (await db.execute(
        select(func.count(), func.min(GlEntry.entry_date), func.max(GlEntry.entry_date))
        .where(GlEntry.company_id == cid)
    )).one()

    periods_total, periods_closed = (await db.execute(
        select(func.count(),
               func.count().filter(Period.status == "closed"))
        .where(Period.company_id == cid)
    )).one()

    return {
        "revenue": revenue,
        "vat": vat,
        "revenueNet": revenue - vat,
        "cost": cost,
        "grossProfit": revenue - vat - cost,
        "entries": entries,
        "firstEntry": first.isoformat() if first else None,
        "lastEntry": last.isoformat() if last else None,
        "periodsTotal": periods_total,
        "periodsClosed": periods_closed,
        "years": years,
    }


@router.get("/turnover")
async def turnover(
    company_id: str,
    year: int | None = None,
    limit: int = Query(60, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Оборотка: обороты по счетам (дебет и кредит отдельно)."""
    cid = await assert_company_member(company_id, current_user, db)

    names = {a.code: a.name for a in (await db.execute(
        select(GlAccount).where(GlAccount.company_id == cid))).scalars()}

    acc: dict[str, dict[str, float]] = {}
    for field, side in ((GlEntry.account_dt, "debit"), (GlEntry.account_kt, "credit")):
        q = (select(field, func.sum(GlEntry.amount), func.count())
             .where(GlEntry.company_id == cid, field.is_not(None))
             .group_by(field))
        if year:
            q = q.where(GlEntry.period_year == year)
        for code, amount, n in (await db.execute(q)).all():
            row = acc.setdefault(code, {"debit": 0.0, "credit": 0.0, "entries": 0})
            row[side] = _num(amount)
            row["entries"] += n

    rows = [{"code": c, "name": names.get(c, ""), **v} for c, v in acc.items()]
    rows.sort(key=lambda r: -(r["debit"] + r["credit"]))
    return {"rows": rows[:limit], "total": len(rows)}


@router.get("/entries")
async def entries(
    company_id: str,
    year: int | None = None,
    account: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Журнал проводок с фильтрами по году и счёту (в дебете или кредите)."""
    cid = await assert_company_member(company_id, current_user, db)

    q = select(GlEntry).where(GlEntry.company_id == cid)
    if year:
        q = q.where(GlEntry.period_year == year)
    if account:
        q = q.where((GlEntry.account_dt == account) | (GlEntry.account_kt == account))

    total = (await db.execute(
        select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(
        q.order_by(GlEntry.entry_date.desc()).limit(limit).offset(offset))).scalars().all()

    return {
        "total": total,
        "rows": [{
            "date": e.entry_date.isoformat(),
            "docKind": e.doc_kind,
            "docTitle": e.doc_title,
            "accountDt": e.account_dt,
            "accountKt": e.account_kt,
            "amount": _num(e.amount),
            "content": e.content,
        } for e in rows],
    }


@router.get("/periods")
async def periods(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Периоды: закрытый месяц — эталон, открытый ещё поедет.

    Обороты по месяцу считаются здесь же: закрытие без цифры ничего не говорит.
    """
    cid = await assert_company_member(company_id, current_user, db)

    by_month = {
        (y, m): {"entries": n, "revenue": 0.0}
        for y, m, n in (await db.execute(
            select(GlEntry.period_year, GlEntry.period_month, func.count())
            .where(GlEntry.company_id == cid)
            .group_by(GlEntry.period_year, GlEntry.period_month))).all()
    }
    for y, m, amount in (await db.execute(
        select(GlEntry.period_year, GlEntry.period_month, func.sum(GlEntry.amount))
        .where(GlEntry.company_id == cid, GlEntry.account_kt == REVENUE_KT)
        .group_by(GlEntry.period_year, GlEntry.period_month))).all():
        if (y, m) in by_month:
            by_month[(y, m)]["revenue"] = _num(amount)

    rows = []
    for p in (await db.execute(
        select(Period).where(Period.company_id == cid)
        .order_by(Period.year.desc(), Period.month.desc()))).scalars():
        cell = by_month.get((p.year, p.month), {"entries": 0, "revenue": 0.0})
        rows.append({"year": p.year, "month": p.month, "status": p.status,
                     "source": p.closure_source, **cell})
    return {"rows": rows}


@router.get("/docs")
async def docs(
    company_id: str,
    doc_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Первичные документы, приехавшие из бухгалтерии."""
    cid = await assert_company_member(company_id, current_user, db)

    q = select(AccountingDoc).where(AccountingDoc.company_id == cid)
    if doc_type:
        q = q.where(AccountingDoc.doc_type == doc_type)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(
        q.order_by(AccountingDoc.date.desc()).limit(limit).offset(offset))).scalars().all()

    kinds = [{"type": t, "count": n, "amount": _num(a)} for t, n, a in (await db.execute(
        select(AccountingDoc.doc_type, func.count(), func.sum(AccountingDoc.amount))
        .where(AccountingDoc.company_id == cid)
        .group_by(AccountingDoc.doc_type))).all()]

    return {
        "total": total,
        "kinds": kinds,
        "rows": [{
            "date": d.date, "number": d.number, "type": d.doc_type,
            "counterparty": d.counterparty_name, "inn": d.counterparty_inn,
            "amount": _num(d.amount), "vat": _num(d.vat_amount),
            "lines": len(d.lines or []),
        } for d in rows],
    }


# ── Разрезы: продажи и услуги ────────────────────────────────────────────────
# Своих чисел не заводят: тот же `accounting_docs`, только вопрос другой —
# кто покупает, что покупает и как это менялось по месяцам.

async def _slice(db: AsyncSession, cid, doc_type: str, top: int) -> dict[str, Any]:
    docs_q = select(AccountingDoc).where(
        AccountingDoc.company_id == cid, AccountingDoc.doc_type == doc_type)
    rows = (await db.execute(docs_q)).scalars().all()

    by_month: dict[str, dict[str, float]] = {}
    by_client: dict[str, dict[str, Any]] = {}
    by_item: dict[str, dict[str, float]] = {}
    total = vat = 0.0

    for d in rows:
        amount, dvat = _num(d.amount), _num(d.vat_amount)
        total += amount
        vat += dvat
        month = (d.date or "")[:7]
        m = by_month.setdefault(month, {"amount": 0.0, "docs": 0})
        m["amount"] += amount
        m["docs"] += 1

        c = by_client.setdefault(d.counterparty_name or "—",
                                 {"name": d.counterparty_name or "—", "inn": d.counterparty_inn,
                                  "amount": 0.0, "docs": 0})
        c["amount"] += amount
        c["docs"] += 1

        for ln in (d.lines or []):
            it = by_item.setdefault(ln.get("name") or "—",
                                    {"name": ln.get("name") or "—", "amount": 0.0, "qty": 0.0})
            it["amount"] += _num(ln.get("amount"))
            it["qty"] += _num(ln.get("qty"))

    clients = sorted(by_client.values(), key=lambda x: -x["amount"])
    items = sorted(by_item.values(), key=lambda x: -x["amount"])
    return {
        "total": total,
        "vat": vat,
        "net": total - vat,
        "docs": len(rows),
        "clients": len(clients),
        "months": [{"month": k, **v} for k, v in sorted(by_month.items())],
        "topClients": clients[:top],
        "topItems": items[:top],
    }


@router.get("/sales")
async def sales(
    company_id: str,
    top: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Продажи товаров: динамика, покупатели, товары."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _slice(db, cid, "sale_goods", top)


@router.get("/services")
async def services(
    company_id: str,
    top: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Услуги: динамика, заказчики, виды услуг."""
    cid = await assert_company_member(company_id, current_user, db)
    return await _slice(db, cid, "sale_services", top)
