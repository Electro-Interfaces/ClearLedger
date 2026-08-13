"""/api/intake-docs — приём первичных документов в пространство.

Один экран разбора на все источники: файл с диска, выгрузка 1С, ЭДО, почта.
Меняется способ доставки, а не работа с документом — поэтому ручки принимают
пакет и дальше говорят на языке кандидатов, а не файлов.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import IntakeBatch, IntakeItem, User
from app.services import intake_docs

router = APIRouter(prefix="/intake-docs", tags=["Приём первички"])


def _item(it: IntakeItem) -> dict[str, Any]:
    return {
        "id": str(it.id), "rowNo": it.row_no, "docType": it.doc_type,
        "number": it.number, "date": it.date,
        "counterpartyName": it.counterparty_name, "counterpartyInn": it.counterparty_inn,
        "counterpartyId": str(it.counterparty_id) if it.counterparty_id else None,
        "contractName": it.contract_name,
        "contractId": str(it.contract_id) if it.contract_id else None,
        "amount": float(it.amount or 0), "vat": float(it.vat_amount or 0),
        "lines": it.lines or [], "raw": it.raw,
        "status": it.status, "checks": it.checks or [],
        "docId": str(it.accounting_doc_id) if it.accounting_doc_id else None,
    }


@router.post("/upload")
async def upload(
    company_id: str = Form(...),
    declared_type: str | None = Form(None),
    source: str = Form("file"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Загрузить файл: разобрать, сопоставить, проверить. В учёт НИЧЕГО не пишет.

    Приём — отдельное действие человека: система показывает, что поняла и что её
    смущает, и только потом документы попадают в учёт.
    """
    cid = await assert_company_member(company_id, current_user, db)
    content = await file.read()

    rows, columns = intake_docs.parse_table(content, file.filename or "")
    batch = IntakeBatch(
        company_id=cid, source=source, file_name=file.filename,
        declared_type=declared_type, uploaded_by=current_user.email,
        status="parsed" if rows else "empty",
        stats={"rows": len(rows), "columns": columns},
    )
    db.add(batch)
    await db.flush()

    if not rows:
        await db.commit()
        return {"batchId": str(batch.id), "items": [], "columns": columns,
                "error": "Не удалось распознать таблицу: не найдены колонки "
                         "с номером, датой, контрагентом или суммой"}

    items = await intake_docs.build_items(db, cid, batch.id, rows, declared_type)
    await intake_docs.match_and_verify(db, cid, items)
    for it in items:
        db.add(it)
    batch.stats = {**(batch.stats or {}), "items": len(items),
                   "ready": sum(1 for i in items if i.status == "ready"),
                   "warning": sum(1 for i in items if i.status == "warning"),
                   "blocked": sum(1 for i in items if i.status == "blocked"),
                   "duplicate": sum(1 for i in items if i.status == "duplicate")}
    await db.commit()

    return {"batchId": str(batch.id), "columns": columns,
            "stats": batch.stats, "items": [_item(i) for i in items]}


@router.get("/batches")
async def batches(
    company_id: str,
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """История загрузок: что, когда и чем закончилось."""
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(select(IntakeBatch).where(
        IntakeBatch.company_id == cid)
        .order_by(IntakeBatch.created_at.desc()).limit(limit))).scalars().all()
    accepted = dict((str(r[0]), r[1]) for r in (await db.execute(
        select(IntakeItem.batch_id, func.count())
        .where(IntakeItem.company_id == cid, IntakeItem.status == "accepted")
        .group_by(IntakeItem.batch_id))).all())
    return {"rows": [{
        "id": str(b.id), "source": b.source, "fileName": b.file_name,
        "declaredType": b.declared_type, "uploadedBy": b.uploaded_by,
        "status": b.status, "stats": b.stats or {},
        "accepted": accepted.get(str(b.id), 0),
        "createdAt": b.created_at.isoformat() if b.created_at else None,
    } for b in rows]}


@router.get("/items")
async def items(
    company_id: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Кандидаты пакета с проверками."""
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(select(IntakeItem).where(
        IntakeItem.company_id == cid, IntakeItem.batch_id == batch_id)
        .order_by(IntakeItem.row_no))).scalars().all()
    return {"rows": [_item(i) for i in rows]}


@router.post("/accept")
async def accept(
    company_id: str,
    batch_id: str | None = None,
    item_ids: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Принять кандидатов в учёт: весь пакет или отмеченные строки."""
    cid = await assert_company_member(company_id, current_user, db)
    q = select(IntakeItem).where(IntakeItem.company_id == cid)
    if item_ids:
        q = q.where(IntakeItem.id.in_(item_ids))
    elif batch_id:
        q = q.where(IntakeItem.batch_id == batch_id)
    else:
        return {"created": 0, "skipped": 0}
    rows = (await db.execute(q)).scalars().all()
    return await intake_docs.accept_items(db, cid, rows, current_user.email)


@router.post("/reject")
async def reject(
    company_id: str,
    item_ids: list[str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Отклонить кандидатов: строка остаётся в истории, но в учёт не идёт."""
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(select(IntakeItem).where(
        IntakeItem.company_id == cid, IntakeItem.id.in_(item_ids)))).scalars().all()
    for it in rows:
        if it.status != "accepted":
            it.status = "rejected"
    await db.commit()
    return {"rejected": len(rows)}
