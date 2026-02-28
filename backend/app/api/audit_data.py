"""Эндпоинты аудит-данных для облачного аудитора."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Float, func, select, text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.cloud_auth import verify_cloud_api_key
from app.models.models import (
    Entry, Counterparty, Contract, Organization, Nomenclature,
    OneCConnection, OneCSyncLog, Connector,
)

router = APIRouter(prefix="/audit-data", tags=["audit-data"], dependencies=[Depends(verify_cloud_api_key)])


# ---- Response schemas ----

class QualityResponse(BaseModel):
    total: int
    with_missing_fields: int
    missing_by_field: dict[str, int]
    invalid_inns: int
    no_counterparty: int


class DuplicateItem(BaseModel):
    entry_id: str
    duplicate_of: str | None
    fingerprint: str | None
    title: str | None


class RefIntegrityResponse(BaseModel):
    counterparties_without_contracts: int
    expired_contracts: int
    organizations_invalid: int
    nomenclature_gaps: int


class VerifyBatchRequest(BaseModel):
    entry_ids: list[str] | None = None
    filters: dict | None = None


class VerifyCheckItem(BaseModel):
    field: str
    check_type: str
    status: str
    confidence: int
    message: str


class VerifyBatchItem(BaseModel):
    entry_id: str
    checks: list[VerifyCheckItem]
    overall_status: str
    confidence: int


class ReconciliationResponse(BaseModel):
    total_entries: int
    verified: int
    unverified: int
    errors: int
    amount_total: float | None
    amount_verified: float | None
    discrepancies: int


class OnecSyncStatusResponse(BaseModel):
    last_sync: datetime | None
    status: str
    catalogs_synced: int
    documents_synced: int
    errors: int


class PeriodGapItem(BaseModel):
    gap_type: str
    description: str
    details: dict | None = None


class PeriodGapsResponse(BaseModel):
    gaps_in_numbering: int
    stale_unverified: int
    missing_expected: int
    items: list[PeriodGapItem]


class ComplianceCheckItem(BaseModel):
    check_name: str
    status: str  # pass | fail | warning
    details: str | None = None
    recommendation: str | None = None


class FindingIn(BaseModel):
    finding_type: str
    severity: str
    category: str
    title: str
    description: str | None = None
    affected_entry_ids: list[str] | None = None
    recommendation: str | None = None
    cloud_finding_id: str | None = None


class WebhookRequest(BaseModel):
    findings: list[FindingIn]


class WebhookResponse(BaseModel):
    received: int
    saved: int


# ---- Endpoints ----

@router.get("/quality", response_model=QualityResponse)
async def get_quality(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Агрегация качества документов."""
    # Total
    total_q = select(func.count(Entry.id))
    if company_id:
        total_q = total_q.where(Entry.company_id == company_id)
    total = (await db.execute(total_q)).scalar() or 0

    # With missing fields — entries where metadata_ has null/empty required fields
    required_fields = ["inn", "counterparty", "sum", "date", "number"]
    missing_by_field: dict[str, int] = {}

    for field in required_fields:
        q = select(func.count(Entry.id)).where(
            or_(
                Entry.metadata_[field].astext == "",
                Entry.metadata_[field].astext.is_(None),
                ~Entry.metadata_.has_key(field),
            )
        )
        if company_id:
            q = q.where(Entry.company_id == company_id)
        cnt = (await db.execute(q)).scalar() or 0
        missing_by_field[field] = cnt

    # Entries with at least one missing field
    conditions = []
    for field in required_fields:
        conditions.append(or_(
            Entry.metadata_[field].astext == "",
            Entry.metadata_[field].astext.is_(None),
            ~Entry.metadata_.has_key(field),
        ))
    with_missing = 0
    if conditions:
        q = select(func.count(Entry.id)).where(or_(*conditions))
        if company_id:
            q = q.where(Entry.company_id == company_id)
        with_missing = (await db.execute(q)).scalar() or 0

    # Invalid INNs — entries with inn that doesn't match 10 or 12 digit pattern
    try:
        invalid_inn_q = select(func.count(Entry.id)).where(
            Entry.metadata_["inn"].astext != "",
            Entry.metadata_.has_key("inn"),
            ~func.regexp_matches(Entry.metadata_["inn"].astext, r'^\d{10}$|^\d{12}$'),
        )
        if company_id:
            invalid_inn_q = invalid_inn_q.where(Entry.company_id == company_id)
        invalid_inns = (await db.execute(invalid_inn_q)).scalar() or 0
    except Exception:
        invalid_inns = 0

    # No counterparty
    no_cp_q = select(func.count(Entry.id)).where(
        or_(
            ~Entry.metadata_.has_key("counterparty"),
            Entry.metadata_["counterparty"].astext == "",
            Entry.metadata_["counterparty"].astext.is_(None),
        )
    )
    if company_id:
        no_cp_q = no_cp_q.where(Entry.company_id == company_id)
    no_counterparty = (await db.execute(no_cp_q)).scalar() or 0

    return QualityResponse(
        total=total,
        with_missing_fields=with_missing,
        missing_by_field=missing_by_field,
        invalid_inns=invalid_inns,
        no_counterparty=no_counterparty,
    )


@router.get("/duplicates", response_model=list[DuplicateItem])
async def get_duplicates(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Поиск дубликатов по fingerprint источника."""
    from app.models.models import Source

    # Find sources with same fingerprint
    subq = (
        select(Source.fingerprint)
        .group_by(Source.fingerprint)
        .having(func.count(Source.id) > 1)
    )
    if company_id:
        subq = subq.where(Source.company_id == company_id)

    q = (
        select(Entry.id, Entry.title, Source.fingerprint)
        .join(Source, Entry.source_id == Source.id)
        .where(Source.fingerprint.in_(subq))
        .order_by(Source.fingerprint, Entry.created_at)
    )
    if company_id:
        q = q.where(Entry.company_id == company_id)

    rows = (await db.execute(q)).all()

    result = []
    seen_fp: dict[str, str] = {}
    for row in rows:
        fp = row.fingerprint
        eid = str(row.id)
        dup_of = seen_fp.get(fp)
        result.append(DuplicateItem(
            entry_id=eid,
            duplicate_of=dup_of,
            fingerprint=fp,
            title=row.title,
        ))
        if fp not in seen_fp:
            seen_fp[fp] = eid

    return result


@router.get("/reference-integrity", response_model=RefIntegrityResponse)
async def get_reference_integrity(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Целостность НСИ."""
    # Counterparties without contracts
    cp_without = select(func.count(Counterparty.id)).where(
        ~Counterparty.id.in_(select(Contract.counterparty_id).where(Contract.counterparty_id.isnot(None)))
    )
    if company_id:
        cp_without = cp_without.where(Counterparty.company_id == company_id)
    cp_cnt = (await db.execute(cp_without)).scalar() or 0

    # Expired contracts (end_date < now, if tracked — using date as proxy)
    expired_q = select(func.count(Contract.id)).where(
        Contract.date < func.now() - text("INTERVAL '1 year'")
    )
    if company_id:
        expired_q = expired_q.where(Contract.company_id == company_id)
    expired = (await db.execute(expired_q)).scalar() or 0

    # Organizations without required fields (inn empty)
    org_invalid_q = select(func.count(Organization.id)).where(
        or_(Organization.inn == "", Organization.inn.is_(None))
    )
    if company_id:
        org_invalid_q = org_invalid_q.where(Organization.company_id == company_id)
    org_invalid = (await db.execute(org_invalid_q)).scalar() or 0

    # Nomenclature gaps (no code or no name)
    nom_q = select(func.count(Nomenclature.id)).where(
        or_(Nomenclature.code == "", Nomenclature.code.is_(None),
            Nomenclature.name == "", Nomenclature.name.is_(None))
    )
    if company_id:
        nom_q = nom_q.where(Nomenclature.company_id == company_id)
    nom_gaps = (await db.execute(nom_q)).scalar() or 0

    return RefIntegrityResponse(
        counterparties_without_contracts=cp_cnt,
        expired_contracts=expired,
        organizations_invalid=org_invalid,
        nomenclature_gaps=nom_gaps,
    )


@router.post("/verify-batch", response_model=list[VerifyBatchItem])
async def verify_batch(
    body: VerifyBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Пакетная верификация записей."""
    from app.api.verification import _validate_inn

    q = select(Entry)
    if body.entry_ids:
        q = q.where(Entry.id.in_([uuid.UUID(eid) for eid in body.entry_ids]))
    elif body.filters:
        if body.filters.get("status"):
            q = q.where(Entry.status == body.filters["status"])
        if body.filters.get("date_from"):
            q = q.where(Entry.created_at >= body.filters["date_from"])
        if body.filters.get("date_to"):
            q = q.where(Entry.created_at <= body.filters["date_to"])
        q = q.limit(100)
    else:
        q = q.limit(50)

    rows = (await db.execute(q)).scalars().all()
    results = []

    for entry in rows:
        checks: list[VerifyCheckItem] = []
        meta = entry.metadata_ or {}

        # INN check
        inn = (meta.get("inn") or "").strip()
        if inn:
            valid = _validate_inn(inn)
            checks.append(VerifyCheckItem(
                field="inn", check_type="inn_checksum",
                status="pass" if valid else "fail",
                confidence=100,
                message="ИНН корректен" if valid else "Некорректный ИНН",
            ))

        # Required fields
        for f in ["counterparty", "sum", "date", "number"]:
            val = meta.get(f)
            checks.append(VerifyCheckItem(
                field=f, check_type="required_field",
                status="pass" if val else "warning",
                confidence=100 if val else 0,
                message=f"Поле '{f}' заполнено" if val else f"Поле '{f}' отсутствует",
            ))

        fails = sum(1 for c in checks if c.status == "fail")
        warnings = sum(1 for c in checks if c.status == "warning")
        passes = sum(1 for c in checks if c.status == "pass")
        total_c = len(checks) or 1

        if fails >= 2:
            overall = "rejected"
        elif fails >= 1 or warnings >= 3:
            overall = "needs_review"
        else:
            overall = "approved"

        results.append(VerifyBatchItem(
            entry_id=str(entry.id),
            checks=checks,
            overall_status=overall,
            confidence=round((passes / total_c) * 100),
        ))

    return results


@router.get("/reconciliation-status", response_model=ReconciliationResponse)
async def get_reconciliation_status(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Статус сверки."""
    base = Entry.company_id == company_id if company_id else True

    q = select(
        func.count(Entry.id).label("total"),
        func.count().filter(Entry.status.in_(["verified", "transferred"])).label("verified"),
        func.count().filter(Entry.status.in_(["new", "recognized"])).label("unverified"),
        func.count().filter(Entry.status == "error").label("errors"),
    ).where(base)

    row = (await db.execute(q)).one()

    # Try to sum amounts from metadata
    try:
        amount_row = (await db.execute(
            select(
                func.sum(func.cast(Entry.metadata_["sum"].astext, Float)).label("amount_total"),
            ).where(base).where(Entry.metadata_.has_key("sum"))
        )).one()
        amount_total = float(amount_row.amount_total) if amount_row.amount_total else None
    except Exception:
        amount_total = None

    try:
        amount_v_row = (await db.execute(
            select(
                func.sum(func.cast(Entry.metadata_["sum"].astext, Float)).label("amount_verified"),
            ).where(base).where(
                Entry.metadata_.has_key("sum"),
                Entry.status.in_(["verified", "transferred"]),
            )
        )).one()
        amount_verified = float(amount_v_row.amount_verified) if amount_v_row.amount_verified else None
    except Exception:
        amount_verified = None

    return ReconciliationResponse(
        total_entries=row.total,
        verified=row.verified,
        unverified=row.unverified,
        errors=row.errors,
        amount_total=amount_total,
        amount_verified=amount_verified,
        discrepancies=row.errors,
    )


@router.get("/onec-sync-status", response_model=OnecSyncStatusResponse)
async def get_onec_sync_status(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Статус синхронизации с 1С."""
    conn_q = select(OneCConnection)
    if company_id:
        conn_q = conn_q.where(OneCConnection.company_id == company_id)
    conn_q = conn_q.order_by(OneCConnection.last_sync_at.desc().nullslast()).limit(1)
    conn = (await db.execute(conn_q)).scalar_one_or_none()

    if not conn:
        return OnecSyncStatusResponse(
            last_sync=None, status="not_configured",
            catalogs_synced=0, documents_synced=0, errors=0,
        )

    # Last sync logs
    logs_q = (
        select(OneCSyncLog)
        .where(OneCSyncLog.connection_id == conn.id)
        .order_by(OneCSyncLog.started_at.desc())
        .limit(10)
    )
    logs = (await db.execute(logs_q)).scalars().all()

    catalogs = sum(l.items_processed or 0 for l in logs if l.sync_type in ("catalogs", "full") and l.status == "success")
    documents = sum(l.items_processed or 0 for l in logs if l.sync_type in ("documents", "full") and l.status == "success")
    errors = sum(l.items_errors or 0 for l in logs)

    return OnecSyncStatusResponse(
        last_sync=conn.last_sync_at,
        status=conn.status or "unknown",
        catalogs_synced=catalogs,
        documents_synced=documents,
        errors=errors,
    )


@router.get("/period-gaps", response_model=PeriodGapsResponse)
async def get_period_gaps(
    date_from: str | None = None,
    date_to: str | None = None,
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Анализ пробелов за период."""
    conditions = []
    if company_id:
        conditions.append(Entry.company_id == company_id)
    if date_from:
        conditions.append(Entry.created_at >= date_from)
    if date_to:
        conditions.append(Entry.created_at <= date_to)

    where_clause = and_(*conditions) if conditions else True

    # Stale unverified (older than 7 days, still new/recognized)
    stale_q = select(func.count(Entry.id)).where(
        where_clause,
        Entry.status.in_(["new", "recognized"]),
        Entry.created_at < func.now() - text("INTERVAL '7 days'"),
    )
    stale = (await db.execute(stale_q)).scalar() or 0

    items = []
    if stale > 0:
        items.append(PeriodGapItem(
            gap_type="stale_unverified",
            description=f"{stale} документов старше 7 дней без верификации",
        ))

    return PeriodGapsResponse(
        gaps_in_numbering=0,  # Requires doc numbering analysis
        stale_unverified=stale,
        missing_expected=0,
        items=items,
    )


@router.get("/compliance-check", response_model=list[ComplianceCheckItem])
async def get_compliance_check(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Чек-лист готовности периода к закрытию."""
    checks: list[ComplianceCheckItem] = []
    base = Entry.company_id == company_id if company_id else True

    # 1. All entries verified
    unverified_q = select(func.count(Entry.id)).where(base, Entry.status.in_(["new", "recognized"]))
    unverified = (await db.execute(unverified_q)).scalar() or 0
    checks.append(ComplianceCheckItem(
        check_name="Все документы верифицированы",
        status="pass" if unverified == 0 else "fail",
        details=f"{unverified} неверифицированных документов" if unverified else None,
        recommendation="Верифицируйте все оставшиеся документы" if unverified else None,
    ))

    # 2. No errors
    errors_q = select(func.count(Entry.id)).where(base, Entry.status == "error")
    errors = (await db.execute(errors_q)).scalar() or 0
    checks.append(ComplianceCheckItem(
        check_name="Нет документов с ошибками",
        status="pass" if errors == 0 else "fail",
        details=f"{errors} документов с ошибками" if errors else None,
        recommendation="Исправьте или удалите документы с ошибками" if errors else None,
    ))

    # 3. NSI completeness — counterparties all have INN
    cp_no_inn_q = select(func.count(Counterparty.id)).where(
        or_(Counterparty.inn == "", Counterparty.inn.is_(None))
    )
    if company_id:
        cp_no_inn_q = cp_no_inn_q.where(Counterparty.company_id == company_id)
    cp_no_inn = (await db.execute(cp_no_inn_q)).scalar() or 0
    checks.append(ComplianceCheckItem(
        check_name="НСИ: все контрагенты с ИНН",
        status="pass" if cp_no_inn == 0 else "warning",
        details=f"{cp_no_inn} контрагентов без ИНН" if cp_no_inn else None,
        recommendation="Заполните ИНН для всех контрагентов" if cp_no_inn else None,
    ))

    # 4. 1C sync healthy
    conn_q = select(OneCConnection)
    if company_id:
        conn_q = conn_q.where(OneCConnection.company_id == company_id)
    conn = (await db.execute(conn_q.limit(1))).scalar_one_or_none()
    if conn:
        sync_ok = conn.status in ("active", "connected")
        checks.append(ComplianceCheckItem(
            check_name="Синхронизация с 1С активна",
            status="pass" if sync_ok else "warning",
            details=f"Статус: {conn.status}" if not sync_ok else None,
            recommendation="Проверьте подключение к 1С" if not sync_ok else None,
        ))

    # 5. Connectors healthy
    conn_err_q = select(func.count(Connector.id)).where(Connector.status == "error")
    if company_id:
        conn_err_q = conn_err_q.where(Connector.company_id == company_id)
    conn_errors = (await db.execute(conn_err_q)).scalar() or 0
    checks.append(ComplianceCheckItem(
        check_name="Коннекторы работают без ошибок",
        status="pass" if conn_errors == 0 else "warning",
        details=f"{conn_errors} коннекторов с ошибками" if conn_errors else None,
        recommendation="Проверьте настройки коннекторов с ошибками" if conn_errors else None,
    ))

    return checks


@router.post("/webhook", response_model=WebhookResponse)
async def receive_findings(
    body: WebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    """Приём findings от облачного аудитора (TSupport)."""
    from app.models.models import AuditFinding

    saved = 0
    for f in body.findings:
        finding = AuditFinding(
            id=uuid.uuid4(),
            finding_type=f.finding_type,
            severity=f.severity,
            category=f.category,
            title=f.title,
            description=f.description,
            affected_entry_ids=f.affected_entry_ids or [],
            recommendation=f.recommendation,
            cloud_finding_id=f.cloud_finding_id,
            status="open",
        )
        db.add(finding)
        saved += 1

    await db.commit()
    return WebhookResponse(received=len(body.findings), saved=saved)
