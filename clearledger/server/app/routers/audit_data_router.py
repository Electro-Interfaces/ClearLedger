"""
Audit-Data API для внешних систем (TSupport аудитор).
Авторизация через X-Cloud-API-Key → company.

8 endpoint'ов:
  GET  /audit-data/quality            — документы с пропущенными полями
  GET  /audit-data/duplicates         — дубликаты документов
  GET  /audit-data/reference-integrity — целостность НСИ
  POST /audit-data/verify-batch       — пакетная верификация
  GET  /audit-data/onec-sync-status   — статус синхронизации с 1С
  GET  /audit-data/period-gaps        — пробелы в нумерации
  GET  /audit-data/compliance-check   — чек-лист закрытия периода
  POST /audit-data/webhook            — приём findings от TSupport
"""

import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_company_by_api_key
from app.database import get_db
from app.models import (
    AccountingDoc,
    Company,
    Contract,
    Connector,
    Counterparty,
    DataEntry,
)

router = APIRouter(prefix="/audit-data", tags=["Audit Data (внешний)"])


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------

REQUIRED_METADATA_FIELDS = {"counterparty", "inn", "number", "date", "amount"}


def _validate_inn(inn: str) -> bool:
    """Проверка ИНН по контрольным разрядам (10 или 12 цифр)."""
    if not inn or not inn.isdigit():
        return False
    if len(inn) == 10:
        weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        check = sum(int(inn[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(inn[9])
    if len(inn) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c1 = sum(int(inn[i]) * w1[i] for i in range(10)) % 11 % 10
        c2 = sum(int(inn[i]) * w2[i] for i in range(11)) % 11 % 10
        return c1 == int(inn[10]) and c2 == int(inn[11])
    return False


# ---------------------------------------------------------------------------
# 1. GET /audit-data/quality
# ---------------------------------------------------------------------------

@router.get("/quality")
async def get_quality_report(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
):
    """Документы с пропущенными обязательными полями."""
    result = await db.execute(
        select(DataEntry)
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status.notin_(["archived"]))
        .order_by(DataEntry.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()

    issues = []
    for e in entries:
        missing = []
        meta = e.meta or {}
        for field in REQUIRED_METADATA_FIELDS:
            if not meta.get(field):
                missing.append(field)
        if not e.title or e.title.strip() == "":
            missing.append("title")
        if missing:
            issues.append({
                "entry_id": str(e.id),
                "title": e.title,
                "status": e.status,
                "missing_fields": missing,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            })

    return {
        "total_checked": len(entries),
        "issues_found": len(issues),
        "items": issues,
    }


# ---------------------------------------------------------------------------
# 2. GET /audit-data/duplicates
# ---------------------------------------------------------------------------

@router.get("/duplicates")
async def get_duplicates(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Потенциальные дубликаты документов (по title + category)."""
    # Группируем по title + category_id, ищем count > 1
    q = (
        select(
            DataEntry.title,
            DataEntry.category_id,
            func.count(DataEntry.id).label("cnt"),
            func.array_agg(DataEntry.id).label("ids"),
        )
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status.notin_(["archived"]))
        .group_by(DataEntry.title, DataEntry.category_id)
        .having(func.count(DataEntry.id) > 1)
        .order_by(func.count(DataEntry.id).desc())
        .limit(50)
    )
    result = await db.execute(q)
    rows = result.all()

    groups = []
    for row in rows:
        groups.append({
            "title": row.title,
            "category_id": row.category_id,
            "count": row.cnt,
            "entry_ids": [str(uid) for uid in row.ids],
        })

    return {
        "duplicate_groups": len(groups),
        "total_duplicates": sum(g["count"] for g in groups),
        "items": groups,
    }


# ---------------------------------------------------------------------------
# 3. GET /audit-data/reference-integrity
# ---------------------------------------------------------------------------

@router.get("/reference-integrity")
async def get_reference_integrity(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Целостность НСИ: контрагенты без договоров, просроченные договоры."""
    # Все контрагенты
    cp_result = await db.execute(
        select(Counterparty).where(Counterparty.company_id == company.id)
    )
    counterparties = cp_result.scalars().all()

    # Все договоры
    ct_result = await db.execute(
        select(Contract).where(Contract.company_id == company.id)
    )
    contracts = ct_result.scalars().all()

    # Контрагенты, у которых есть хотя бы один договор
    cp_with_contracts = {c.counterparty_id for c in contracts}

    # Контрагенты без договоров
    no_contract = []
    for cp in counterparties:
        if str(cp.id) not in cp_with_contracts and cp.inn not in cp_with_contracts:
            no_contract.append({
                "id": str(cp.id),
                "name": cp.name,
                "inn": cp.inn,
            })

    # «Просроченные» договоры — дата > 1 года назад (эвристика)
    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    expired = []
    for c in contracts:
        if c.date and c.date < one_year_ago:
            expired.append({
                "id": str(c.id),
                "number": c.number,
                "date": c.date,
                "counterparty_id": c.counterparty_id,
                "type": c.type,
            })

    # ИНН без КПП (для ЮЛ)
    invalid_inn = []
    for cp in counterparties:
        if not _validate_inn(cp.inn):
            invalid_inn.append({
                "id": str(cp.id),
                "name": cp.name,
                "inn": cp.inn,
            })

    return {
        "counterparties_total": len(counterparties),
        "contracts_total": len(contracts),
        "counterparties_without_contracts": len(no_contract),
        "expired_contracts": len(expired),
        "invalid_inn_count": len(invalid_inn),
        "items": {
            "no_contract": no_contract[:50],
            "expired": expired[:50],
            "invalid_inn": invalid_inn[:50],
        },
    }


# ---------------------------------------------------------------------------
# 4. POST /audit-data/verify-batch
# ---------------------------------------------------------------------------

class VerifyBatchRequest(BaseModel):
    entry_ids: list[str] | None = None
    limit: int = 100


@router.post("/verify-batch")
async def verify_batch(
    body: VerifyBatchRequest,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Пакетная верификация документов: ИНН, обязательные поля, суммы."""
    q = (
        select(DataEntry)
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status.notin_(["archived"]))
    )
    if body.entry_ids:
        uuids = [uuid.UUID(eid) for eid in body.entry_ids]
        q = q.where(DataEntry.id.in_(uuids))
    q = q.order_by(DataEntry.created_at.desc()).limit(body.limit)

    result = await db.execute(q)
    entries = result.scalars().all()

    results = []
    passed = 0
    failed = 0

    for e in entries:
        errors = []
        meta = e.meta or {}

        # Проверка обязательных полей
        for field in REQUIRED_METADATA_FIELDS:
            if not meta.get(field):
                errors.append({"type": "missing_field", "field": field})

        # Проверка ИНН
        inn = meta.get("inn", "")
        if inn and not _validate_inn(str(inn)):
            errors.append({"type": "invalid_inn", "value": str(inn)})

        # Проверка суммы (должна быть > 0 если есть)
        amount = meta.get("amount")
        if amount is not None:
            try:
                if float(amount) < 0:
                    errors.append({"type": "negative_amount", "value": amount})
            except (ValueError, TypeError):
                errors.append({"type": "invalid_amount", "value": str(amount)})

        if errors:
            failed += 1
        else:
            passed += 1

        results.append({
            "entry_id": str(e.id),
            "title": e.title,
            "status": e.status,
            "passed": len(errors) == 0,
            "errors": errors,
        })

    return {
        "total": len(entries),
        "passed": passed,
        "failed": failed,
        "items": results,
    }


# ---------------------------------------------------------------------------
# 5. GET /audit-data/onec-sync-status
# ---------------------------------------------------------------------------

@router.get("/onec-sync-status")
async def get_onec_sync_status(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Статус синхронизации с 1С: коннекторы + статистика accounting_docs."""
    # Коннекторы 1С
    conn_result = await db.execute(
        select(Connector)
        .where(Connector.company_id == company.id)
        .where(Connector.type.in_(["oneC", "1c-odata", "1c-file"]))
    )
    connectors = conn_result.scalars().all()

    connector_info = []
    for c in connectors:
        connector_info.append({
            "id": str(c.id),
            "name": c.name,
            "type": c.type,
            "status": c.status,
            "sync_status": c.sync_status,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "records_count": c.records_count,
            "errors_count": c.errors_count,
        })

    # Accounting docs статистика
    doc_result = await db.execute(
        select(
            AccountingDoc.match_status,
            func.count(AccountingDoc.id).label("cnt"),
        )
        .where(AccountingDoc.company_id == company.id)
        .group_by(AccountingDoc.match_status)
    )
    match_stats = {row.match_status: row.cnt for row in doc_result.all()}

    total_docs = sum(match_stats.values())
    matched = match_stats.get("matched", 0) + match_stats.get("auto_matched", 0)

    return {
        "connectors": connector_info,
        "connectors_active": sum(1 for c in connectors if c.status == "active"),
        "connectors_total": len(connectors),
        "accounting_docs": {
            "total": total_docs,
            "matched": matched,
            "pending": match_stats.get("pending", 0),
            "unmatched": match_stats.get("unmatched", 0),
            "match_rate": round(matched / total_docs * 100, 1) if total_docs > 0 else 0,
        },
    }


# ---------------------------------------------------------------------------
# 6. GET /audit-data/period-gaps
# ---------------------------------------------------------------------------

@router.get("/period-gaps")
async def get_period_gaps(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
):
    """Пробелы в нумерации документов 1С + устаревшие неверифицированные."""
    # Пробелы в нумерации accounting_docs
    q = (
        select(AccountingDoc)
        .where(AccountingDoc.company_id == company.id)
        .order_by(AccountingDoc.doc_type, AccountingDoc.number)
    )
    if date_from:
        q = q.where(AccountingDoc.date >= date_from)
    if date_to:
        q = q.where(AccountingDoc.date <= date_to)

    result = await db.execute(q)
    docs = result.scalars().all()

    # Группируем по типу документа, ищем пробелы в числовой нумерации
    gaps = []
    by_type: dict[str, list[int]] = {}
    for d in docs:
        nums = re.findall(r"\d+", d.number)
        if nums:
            num = int(nums[-1])
            by_type.setdefault(d.doc_type, []).append(num)

    for doc_type, numbers in by_type.items():
        numbers.sort()
        for i in range(1, len(numbers)):
            diff = numbers[i] - numbers[i - 1]
            if diff > 1:
                gaps.append({
                    "doc_type": doc_type,
                    "gap_from": numbers[i - 1],
                    "gap_to": numbers[i],
                    "missing_count": diff - 1,
                })

    # Устаревшие неверифицированные (> 30 дней)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stale_result = await db.execute(
        select(func.count(DataEntry.id))
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status.in_(["new", "recognized"]))
        .where(DataEntry.created_at < stale_cutoff)
    )
    stale_count = stale_result.scalar() or 0

    return {
        "numbering_gaps": len(gaps),
        "gap_details": gaps[:50],
        "stale_unverified_count": stale_count,
        "stale_threshold_days": 30,
        "total_docs_checked": len(docs),
    }


# ---------------------------------------------------------------------------
# 7. GET /audit-data/compliance-check
# ---------------------------------------------------------------------------

@router.get("/compliance-check")
async def compliance_check(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Чек-лист готовности к закрытию периода."""
    checks = []

    # 1. Все документы верифицированы?
    unverified_result = await db.execute(
        select(func.count(DataEntry.id))
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status.in_(["new", "recognized", "error"]))
    )
    unverified = unverified_result.scalar() or 0
    checks.append({
        "id": "all_verified",
        "name": "Все документы верифицированы",
        "passed": unverified == 0,
        "details": f"{unverified} неверифицированных" if unverified > 0 else "OK",
    })

    # 2. Нет документов с ошибками?
    error_result = await db.execute(
        select(func.count(DataEntry.id))
        .where(DataEntry.company_id == company.id)
        .where(DataEntry.status == "error")
    )
    errors = error_result.scalar() or 0
    checks.append({
        "id": "no_errors",
        "name": "Нет документов с ошибками",
        "passed": errors == 0,
        "details": f"{errors} ошибок" if errors > 0 else "OK",
    })

    # 3. Все документы 1С сверены?
    unmatched_result = await db.execute(
        select(func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == company.id)
        .where(AccountingDoc.match_status.in_(["pending", "unmatched"]))
    )
    unmatched = unmatched_result.scalar() or 0
    checks.append({
        "id": "all_reconciled",
        "name": "Все документы 1С сверены",
        "passed": unmatched == 0,
        "details": f"{unmatched} не сверено" if unmatched > 0 else "OK",
    })

    # 4. Нет пробелов в нумерации?
    # Simplified: just check if accounting_docs exist
    doc_count_result = await db.execute(
        select(func.count(AccountingDoc.id))
        .where(AccountingDoc.company_id == company.id)
    )
    doc_count = doc_count_result.scalar() or 0
    checks.append({
        "id": "docs_present",
        "name": "Документы 1С загружены",
        "passed": doc_count > 0,
        "details": f"{doc_count} документов" if doc_count > 0 else "Нет документов 1С",
    })

    # 5. Коннекторы активны?
    conn_result = await db.execute(
        select(Connector)
        .where(Connector.company_id == company.id)
        .where(Connector.type.in_(["oneC", "1c-odata", "1c-file"]))
    )
    connectors = conn_result.scalars().all()
    all_active = all(c.status == "active" for c in connectors) if connectors else False
    inactive = [c.name for c in connectors if c.status != "active"]
    checks.append({
        "id": "connectors_active",
        "name": "Коннекторы 1С активны",
        "passed": all_active,
        "details": f"Неактивны: {', '.join(inactive)}" if inactive else ("OK" if connectors else "Нет коннекторов"),
    })

    # 6. Все контрагенты с валидным ИНН?
    cp_result = await db.execute(
        select(Counterparty).where(Counterparty.company_id == company.id)
    )
    counterparties = cp_result.scalars().all()
    bad_inn = [cp for cp in counterparties if not _validate_inn(cp.inn)]
    checks.append({
        "id": "valid_inns",
        "name": "Все ИНН контрагентов валидны",
        "passed": len(bad_inn) == 0,
        "details": f"{len(bad_inn)} невалидных ИНН" if bad_inn else "OK",
    })

    passed_total = sum(1 for c in checks if c["passed"])
    score = round(passed_total / len(checks) * 100) if checks else 0

    return {
        "score": score,
        "passed": passed_total,
        "total": len(checks),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# 8. POST /audit-data/webhook
# ---------------------------------------------------------------------------

class FindingItem(BaseModel):
    finding_type: str
    severity: str
    category: str = "documents"
    title: str
    description: str | None = None
    affected_entry_ids: list[str] = []
    recommendation: str | None = None


class WebhookRequest(BaseModel):
    findings: list[FindingItem]


@router.post("/webhook")
async def receive_findings(
    body: WebhookRequest,
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Приём findings от TSupport аудитора. Сохранение в audit_events."""
    from app.models import AuditEvent

    saved = 0
    for f in body.findings:
        event = AuditEvent(
            company_id=company.id,
            user_id="tsupport-auditor",
            user_name="TSupport AI Аудитор",
            action="audit_finding",
            details=(
                f"[{f.severity.upper()}] {f.title}"
                + (f"\n{f.description}" if f.description else "")
                + (f"\nРекомендация: {f.recommendation}" if f.recommendation else "")
            ),
        )
        db.add(event)
        saved += 1

    await db.commit()

    return {
        "received": len(body.findings),
        "saved": saved,
    }
