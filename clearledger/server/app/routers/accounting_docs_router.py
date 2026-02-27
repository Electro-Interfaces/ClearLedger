"""
CRUD для учётных документов 1С (AccountingDoc).
Импорт, фильтрация, связь с DataEntry.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AccountingDoc, User
from app.schemas import (
    AccountingDocCreate,
    AccountingDocImportRequest,
    AccountingDocImportResponse,
    AccountingDocResponse,
    AccountingDocUpdate,
)
from app.utils import resolve_company_id

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
    cid = await resolve_company_id(company_id, db)
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
# GET ONE
# ---------------------------------------------------------------------------

@router.get("/{doc_id}", response_model=AccountingDocResponse)
async def get_accounting_doc(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    result = await db.execute(select(AccountingDoc).where(AccountingDoc.id == uid))
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
    cid = await resolve_company_id(body.company_id, db)
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
    cid = await resolve_company_id(body.company_id, db)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    result = await db.execute(select(AccountingDoc).where(AccountingDoc.id == uid))
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = _parse_uuid(doc_id)
    result = await db.execute(select(AccountingDoc).where(AccountingDoc.id == uid))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    await db.delete(doc)
