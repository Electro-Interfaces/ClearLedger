"""
API сверки документов: авто-сверка, сводка, ручное сопоставление.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AccountingDoc, DataEntry, User
from app.schemas import (
    AccountingDocResponse,
    DataEntryResponse,
    ManualMatchRequest,
    ReconciliationSummaryResponse,
    UnmatchRequest,
)
from app.services.reconciliation_service import run_reconciliation
from app.utils import resolve_company_id

router = APIRouter(prefix="/reconciliation", tags=["Сверка"])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _ts(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    return dt.isoformat()


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


def _entry_resp(e: DataEntry) -> DataEntryResponse:
    return DataEntryResponse(
        id=str(e.id),
        title=e.title,
        category_id=e.category_id,
        subcategory_id=e.subcategory_id,
        doc_type_id=e.doc_type_id,
        company_id=str(e.company_id),
        status=e.status,
        source=e.source,
        source_label=e.source_label,
        file_url=e.file_url,
        file_type=e.file_type,
        file_size=e.file_size,
        metadata=e.meta or {},
        ocr_data=e.ocr_data,
        source_id=e.source_id,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


# ---------------------------------------------------------------------------
# POST /reconciliation/run — запуск авто-сверки
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_reconciliation_endpoint(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await run_reconciliation(db, cid)
    return result


# ---------------------------------------------------------------------------
# GET /reconciliation/summary — сводка
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=ReconciliationSummaryResponse)
async def get_summary(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)

    # Считаем статусы документов 1С (один запрос, без N+1)
    docs_result = await db.execute(
        select(AccountingDoc.match_status, AccountingDoc.matched_entry_id)
        .where(AccountingDoc.company_id == cid)
    )
    docs = docs_result.all()

    matched = 0
    unmatched_acc = 0
    discrepancy = 0
    matched_entry_ids: set = set()

    for status, entry_id in docs:
        if status == "matched":
            matched += 1
            if entry_id:
                matched_entry_ids.add(entry_id)
        elif status in ("unmatched", "pending"):
            unmatched_acc += 1
        elif status == "discrepancy":
            discrepancy += 1

    entries_result = await db.execute(
        select(func.count(DataEntry.id)).where(DataEntry.company_id == cid)
    )
    total_entries = entries_result.scalar() or 0
    unmatched_entry = total_entries - len(matched_entry_ids)

    return ReconciliationSummaryResponse(
        matched=matched,
        unmatchedAcc=unmatched_acc,
        unmatchedEntry=unmatched_entry,
        discrepancy=discrepancy,
        totalAccDocs=len(docs),
        totalEntries=total_entries,
    )


# ---------------------------------------------------------------------------
# GET /reconciliation/unmatched-1c — документы 1С без оригинала
# ---------------------------------------------------------------------------

@router.get("/unmatched-1c", response_model=list[AccountingDocResponse])
async def get_unmatched_1c(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(AccountingDoc)
        .where(
            AccountingDoc.company_id == cid,
            AccountingDoc.match_status.in_(["unmatched", "pending"]),
        )
        .order_by(AccountingDoc.date.desc())
    )
    return [_doc_resp(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# GET /reconciliation/unmatched-cl — записи CL без пары в 1С
# ---------------------------------------------------------------------------

@router.get("/unmatched-cl", response_model=list[DataEntryResponse])
async def get_unmatched_cl(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)

    # ID всех сопоставленных entries
    matched_result = await db.execute(
        select(AccountingDoc.matched_entry_id)
        .where(
            AccountingDoc.company_id == cid,
            AccountingDoc.matched_entry_id.is_not(None),
        )
    )
    matched_ids = {row[0] for row in matched_result.all() if row[0]}

    # Все entries компании
    entries_result = await db.execute(
        select(DataEntry)
        .where(DataEntry.company_id == cid)
        .order_by(DataEntry.created_at.desc())
    )
    entries = entries_result.scalars().all()

    return [_entry_resp(e) for e in entries if e.id not in matched_ids]


# ---------------------------------------------------------------------------
# GET /reconciliation/discrepancies — расхождения
# ---------------------------------------------------------------------------

@router.get("/discrepancies", response_model=list[AccountingDocResponse])
async def get_discrepancies(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(company_id, db)
    result = await db.execute(
        select(AccountingDoc)
        .where(
            AccountingDoc.company_id == cid,
            AccountingDoc.match_status == "discrepancy",
        )
        .order_by(AccountingDoc.date.desc())
    )
    return [_doc_resp(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# POST /reconciliation/match — ручное сопоставление
# ---------------------------------------------------------------------------

@router.post("/match")
async def manual_match(
    body: ManualMatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    doc_uuid = uuid.UUID(body.doc_id)
    entry_uuid = uuid.UUID(body.entry_id)

    doc_result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == doc_uuid, AccountingDoc.company_id == cid)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ 1С не найден")

    entry_result = await db.execute(
        select(DataEntry).where(DataEntry.id == entry_uuid, DataEntry.company_id == cid)
    )
    entry = entry_result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    doc.matched_entry_id = entry_uuid
    doc.match_status = "matched"
    doc.match_details = {"manual": True, "score": 100, "confidence": 100, "missingLines": [], "extraLines": []}
    await db.flush()
    return {"status": "ok", "docId": str(doc.id), "entryId": str(entry.id)}


# ---------------------------------------------------------------------------
# POST /reconciliation/unmatch — разорвать связь
# ---------------------------------------------------------------------------

@router.post("/unmatch")
async def unmatch(
    body: UnmatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await resolve_company_id(body.company_id, db)
    doc_uuid = uuid.UUID(body.doc_id)
    doc_result = await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == doc_uuid, AccountingDoc.company_id == cid)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ 1С не найден")

    doc.matched_entry_id = None
    doc.match_status = "pending"
    doc.match_details = None
    await db.flush()
    return {"status": "ok", "docId": str(doc.id)}
