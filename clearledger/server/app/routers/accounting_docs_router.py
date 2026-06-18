"""
CRUD для учётных документов 1С (AccountingDoc).
Импорт, фильтрация, связь с DataEntry.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AccountingDoc, User
from app.schemas import (
    AccountingDocCreate,
    AccountingDocImportRequest,
    AccountingDocImportResponse,
    AccountingDocResponse,
    AccountingDocsPage,
    AccountingDocsStats,
    AccountingDocUpdate,
)
from app.auth import assert_company_member, get_current_user

router = APIRouter(prefix="/accounting-docs", tags=["Учётные документы 1С"])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _ts(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    return dt.isoformat()


def _parse_uuid(val: str, label: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Невалидный {label}")


def _doc_resp(d: AccountingDoc) -> AccountingDocResponse:
    return AccountingDocResponse(
        id=str(d.id),
        companyId=str(d.company_id),
        externalId=d.external_id,
        docType=d.doc_type,
        number=d.number,
        date=d.date,
        counterpartyName=d.counterparty_name,
        counterpartyInn=d.counterparty_inn,
        organizationName=d.organization_name,
        amount=d.amount,
        vatAmount=d.vat_amount,
        status1c=d.status_1c,
        lines=d.lines or [],
        matchedEntryId=str(d.matched_entry_id) if d.matched_entry_id else None,
        matchStatus=d.match_status,
        matchDetails=d.match_details,
        warehouseCode=d.warehouse_code,
        externalNumber=d.external_number,
        externalDate=d.external_date,
        operationType=d.operation_type,
        periodStatus=d.period_status,
        discrepancyStatus=d.discrepancy_status,
        discrepancySummary=d.discrepancy_summary,
        discrepancyDetails=d.discrepancy_details,
        createdAt=_ts(d.created_at),
        updatedAt=_ts(d.updated_at),
    )


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AccountingDocResponse])
async def list_accounting_docs(
    company_id: str = Query(...),
    doc_type: str | None = Query(None),
    counterparty: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    match_status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    q = select(AccountingDoc).where(AccountingDoc.company_id == cid)

    if doc_type:
        q = q.where(AccountingDoc.doc_type == doc_type)
    if counterparty:
        q = q.where(AccountingDoc.counterparty_name.ilike(f"%{counterparty}%"))
    if date_from:
        q = q.where(AccountingDoc.date >= date_from)
    if date_to:
        q = q.where(AccountingDoc.date <= date_to)
    if match_status:
        q = q.where(AccountingDoc.match_status == match_status)

    q = q.order_by(AccountingDoc.date.desc())
    result = await db.execute(q)
    return [_doc_resp(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# SEARCH (с пагинацией)
# ---------------------------------------------------------------------------

@router.get("/search", response_model=AccountingDocsPage)
async def search_accounting_docs(
    company_id: str = Query(...),
    q: str | None = Query(None, description="Поиск по номеру/контрагенту/организации"),
    doc_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    match_status: str | None = Query(None),
    period_status: str | None = Query(None, description="open | closed"),
    discrepancy_status: str | None = Query(None, description="pending | none | rounding | minor | material | critical | unmatched"),
    sort: str = Query("date_desc", pattern="^(date_desc|date_asc|amount_desc|amount_asc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    base = select(AccountingDoc).where(AccountingDoc.company_id == cid)

    if doc_type:
        base = base.where(AccountingDoc.doc_type == doc_type)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(
            AccountingDoc.number.ilike(like),
            AccountingDoc.counterparty_name.ilike(like),
            AccountingDoc.counterparty_inn.ilike(like),
            AccountingDoc.organization_name.ilike(like),
            AccountingDoc.external_id.ilike(like),
            AccountingDoc.external_number.ilike(like),
        ))
    if date_from:
        base = base.where(AccountingDoc.date >= date_from)
    if date_to:
        base = base.where(AccountingDoc.date <= date_to)
    if match_status:
        base = base.where(AccountingDoc.match_status == match_status)
    if period_status:
        base = base.where(AccountingDoc.period_status == period_status)
    if discrepancy_status:
        base = base.where(AccountingDoc.discrepancy_status == discrepancy_status)

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    order = {
        "date_desc":   AccountingDoc.date.desc(),
        "date_asc":    AccountingDoc.date.asc(),
        "amount_desc": AccountingDoc.amount.desc(),
        "amount_asc":  AccountingDoc.amount.asc(),
    }[sort]
    result = await db.execute(base.order_by(order).limit(limit).offset(offset))
    return AccountingDocsPage(
        items=[_doc_resp(d) for d in result.scalars().all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=AccountingDocsStats)
async def accounting_docs_stats(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(company_id, current_user, db)
    total = (await db.execute(
        select(func.count(AccountingDoc.id)).where(AccountingDoc.company_id == cid)
    )).scalar_one()
    by_type_rows = (await db.execute(
        select(AccountingDoc.doc_type, func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == cid)
        .group_by(AccountingDoc.doc_type)
    )).all()
    by_status_rows = (await db.execute(
        select(AccountingDoc.match_status, func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == cid)
        .group_by(AccountingDoc.match_status)
    )).all()
    return AccountingDocsStats(
        total=int(total or 0),
        byType={t or "—": int(c) for t, c in by_type_rows},
        bySource={s or "—": int(c) for s, c in by_status_rows},
    )


# ---------------------------------------------------------------------------
# GET ONE
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/related", response_model=list[AccountingDocResponse])
async def get_related_docs(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Связанные документы для ОРП: ПеремещениеТоваров (на виртуальные склады
    Талоны/Карты/Ведомости/Яндекс) и СписаниеТоваров (по прочим) за тот же
    день со склада-источника. Не регистраторы ОРП, но фактически
    бухгалтерская цепочка одной смены."""
    uid = _parse_uuid(doc_id)
    cid = await assert_company_member(company_id, current_user, db)
    doc = (await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == uid, AccountingDoc.company_id == cid)
    )).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if doc.doc_type != "ОРП":
        return []
    # Ищем перемещения и списания за ту же дату с тем же warehouse_code.
    # date в AccountingDoc хранится как YYYY-MM-DD, warehouse_code — код 1С.
    candidates = (await db.execute(
        select(AccountingDoc).where(
            AccountingDoc.company_id == cid,
            AccountingDoc.date == doc.date,
            AccountingDoc.warehouse_code == doc.warehouse_code,
            AccountingDoc.doc_type.in_(["ПеремещениеТоваров", "СписаниеТоваров"]),
        )
    )).scalars().all()
    return [_doc_resp(d) for d in candidates]


@router.get("/{doc_id}", response_model=AccountingDocResponse)
async def get_accounting_doc(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == uid, AccountingDoc.company_id == cid)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return _doc_resp(doc)


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=AccountingDocResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_accounting_doc(
    body: AccountingDocCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(body.company_id, current_user, db)
    doc = AccountingDoc(
        company_id=cid,
        external_id=body.external_id,
        doc_type=body.doc_type,
        number=body.number,
        date=body.date,
        counterparty_name=body.counterparty_name,
        counterparty_inn=body.counterparty_inn,
        organization_name=body.organization_name,
        amount=body.amount,
        vat_amount=body.vat_amount,
        status_1c=body.status_1c,
        lines=[line.model_dump() for line in body.lines],
        warehouse_code=body.warehouse_code,
    )
    db.add(doc)
    await db.flush()
    return _doc_resp(doc)


# ---------------------------------------------------------------------------
# IMPORT (массовый)
# ---------------------------------------------------------------------------

@router.post("/import", response_model=AccountingDocImportResponse)
async def import_accounting_docs(
    body: AccountingDocImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(body.company_id, current_user, db)
    errors: list[str] = []
    created = 0
    updated = 0

    # Загружаем существующие external_id для upsert
    result = await db.execute(
        select(AccountingDoc.external_id, AccountingDoc.id)
        .where(AccountingDoc.company_id == cid)
    )
    existing = {row[0]: row[1] for row in result.all()}

    for item in body.docs:
        try:
            if item.external_id in existing:
                # Обновляем
                doc_id = existing[item.external_id]
                res = await db.execute(
                    select(AccountingDoc).where(AccountingDoc.id == doc_id)
                )
                doc = res.scalar_one()
                doc.number = item.number
                doc.date = item.date
                doc.counterparty_name = item.counterparty_name
                doc.counterparty_inn = item.counterparty_inn
                doc.organization_name = item.organization_name
                doc.amount = item.amount
                doc.vat_amount = item.vat_amount
                doc.status_1c = item.status_1c
                doc.lines = [line.model_dump() for line in item.lines]
                doc.warehouse_code = item.warehouse_code
                updated += 1
            else:
                doc = AccountingDoc(
                    company_id=cid,
                    external_id=item.external_id,
                    doc_type=item.doc_type,
                    number=item.number,
                    date=item.date,
                    counterparty_name=item.counterparty_name,
                    counterparty_inn=item.counterparty_inn,
                    organization_name=item.organization_name,
                    amount=item.amount,
                    vat_amount=item.vat_amount,
                    status_1c=item.status_1c,
                    lines=[line.model_dump() for line in item.lines],
                    warehouse_code=item.warehouse_code,
                )
                db.add(doc)
                existing[item.external_id] = doc.id
                created += 1
        except Exception as e:
            errors.append(f"Документ {item.number}: {str(e)}")

    await db.flush()
    return AccountingDocImportResponse(
        total=len(body.docs),
        created=created,
        updated=updated,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------

@router.patch("/{doc_id}", response_model=AccountingDocResponse)
async def update_accounting_doc(
    doc_id: str,
    body: AccountingDocUpdate,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == uid, AccountingDoc.company_id == cid)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    if body.match_status is not None:
        doc.match_status = body.match_status
    if body.matched_entry_id is not None:
        doc.matched_entry_id = uuid.UUID(body.matched_entry_id)
    if body.match_details is not None:
        doc.match_details = body.match_details

    await db.flush()
    return _doc_resp(doc)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_accounting_doc(
    doc_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    cid = await assert_company_member(company_id, current_user, db)
    result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == uid, AccountingDoc.company_id == cid)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    await db.delete(doc)
