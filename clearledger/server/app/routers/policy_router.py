"""
/api/policy — учётная политика 1С (РегС.УчетнаяПолитика) +
/api/posting-templates — справочник схем проводок (план vs факт).

UI использует это для:
1) карточки учётной политики на /1c/policy (МПЗ, налогообложение, ПБУ18, НДС)
2) подсветки проводок в Sheet документа против ожидаемого шаблона
   (см. docs/sverka-spec.md §7 — сверка проводок).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import InventoryBatch, NomenclaturePrice, OneCPolicy, PostingTemplate, User

router = APIRouter(tags=["1С политика и схема проводок"])


# ─── схемы ───────────────────────────────────────────────────────────

class OneCPolicyResponse(BaseModel):
    id: str
    company_id: str
    organization_external_ref: str | None
    organization_name: str | None
    period: str | None
    mpz_method: str | None
    tax_system: str | None
    vat_rate: str | None
    pbu_18_02: bool
    separate_vat_accounting: bool
    settings: dict[str, Any]
    created_at: Any
    updated_at: Any


class PostingTemplateExpected(BaseModel):
    dt: str = Field(..., description="Счёт дебета (напр. '90.02.1')")
    kt: str = Field(..., description="Счёт кредита")
    formula: str | None = Field(None, description="Формула суммы (напр. 'СуммаДок * 22 / 122')")
    comment: str | None = None


class PostingTemplateResponse(BaseModel):
    id: str
    company_id: str | None
    doc_type: str
    operation_type: str | None
    name: str
    expected: list[PostingTemplateExpected]
    notes: str | None
    created_at: Any


class PostingTemplateCreate(BaseModel):
    company_id: str | None = None
    doc_type: str
    operation_type: str | None = None
    name: str
    expected: list[PostingTemplateExpected]
    notes: str | None = None


# ─── /policy ─────────────────────────────────────────────────────────

@router.get("/policy", response_model=list[OneCPolicyResponse])
async def list_policies(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[OneCPolicyResponse]:
    cid = await assert_company_member(company_id, current_user, db)
    rows = (await db.execute(
        select(OneCPolicy)
        .where(OneCPolicy.company_id == cid)
        .order_by(OneCPolicy.organization_name, OneCPolicy.period.desc())
    )).scalars().all()
    return [
        OneCPolicyResponse(
            id=str(p.id),
            company_id=str(p.company_id),
            organization_external_ref=p.organization_external_ref,
            organization_name=p.organization_name,
            period=p.period,
            mpz_method=p.mpz_method,
            tax_system=p.tax_system,
            vat_rate=p.vat_rate,
            pbu_18_02=p.pbu_18_02,
            separate_vat_accounting=p.separate_vat_accounting,
            settings=p.settings or {},
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in rows
    ]


# ─── /posting-templates ──────────────────────────────────────────────

@router.get("/posting-templates", response_model=list[PostingTemplateResponse])
async def list_posting_templates(
    company_id: str | None = None,
    doc_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PostingTemplateResponse]:
    stmt = select(PostingTemplate)
    if company_id:
        cid = await assert_company_member(company_id, current_user, db)
        # Возвращаем шаблоны компании + глобальные (company_id IS NULL)
        from sqlalchemy import or_
        stmt = stmt.where(or_(PostingTemplate.company_id == cid, PostingTemplate.company_id.is_(None)))
    if doc_type:
        stmt = stmt.where(PostingTemplate.doc_type == doc_type)
    rows = (await db.execute(stmt.order_by(PostingTemplate.doc_type, PostingTemplate.operation_type))).scalars().all()
    return [
        PostingTemplateResponse(
            id=str(t.id),
            company_id=str(t.company_id) if t.company_id else None,
            doc_type=t.doc_type,
            operation_type=t.operation_type,
            name=t.name,
            expected=[PostingTemplateExpected(**x) for x in (t.expected or [])],
            notes=t.notes,
            created_at=t.created_at,
        )
        for t in rows
    ]


@router.post("/posting-templates", response_model=PostingTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_posting_template(
    payload: PostingTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostingTemplateResponse:
    cid = await assert_company_member(payload.company_id, current_user, db) if payload.company_id else None
    t = PostingTemplate(
        id=uuid.uuid4(),
        company_id=cid,
        doc_type=payload.doc_type,
        operation_type=payload.operation_type,
        name=payload.name,
        expected=[x.model_dump() for x in payload.expected],
        notes=payload.notes,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return PostingTemplateResponse(
        id=str(t.id),
        company_id=str(t.company_id) if t.company_id else None,
        doc_type=t.doc_type,
        operation_type=t.operation_type,
        name=t.name,
        expected=[PostingTemplateExpected(**x) for x in (t.expected or [])],
        notes=t.notes,
        created_at=t.created_at,
    )


@router.delete("/posting-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_posting_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    try:
        tid = uuid.UUID(template_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid template id") from exc
    t = (await db.execute(select(PostingTemplate).where(PostingTemplate.id == tid))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template not found")
    await db.delete(t)


# ─── /prices ─────────────────────────────────────────────────────────

class PriceRow(BaseModel):
    id: str
    nomenclature_ref: str
    nomenclature_name: str | None
    price_type_ref: str
    price_type_name: str | None
    period: str
    price: float
    currency: str | None
    unit: str | None


# Подстроки для идентификации нефтепродуктов (case-insensitive).
# Эти товары — основной бизнес ГИГ, поэтому поднимаем их в начало списков.
FUEL_PATTERNS = [
    "АИ-", "АИ ", "А-92", "А-95", "А-98",
    "ДТ", "Дизель", "Дизельное",
    "Бензин", "Топливо",
    "СУГ", "ПБ", "Пропан", "Бутан", "СПБТ", "Газ моторн",
    "Нефть", "Мазут",
]


def _fuel_rank_sql(column):
    """SQL CASE — 0 для нефтепродуктов, 1 для остальных."""
    from sqlalchemy import case, func, or_
    conds = [func.upper(column).like(f"%{p.upper()}%") for p in FUEL_PATTERNS]
    return case((or_(*conds), 0), else_=1)


def _is_fuel(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(p.upper() in upper for p in FUEL_PATTERNS)


@router.get("/prices", response_model=list[PriceRow])
async def list_prices(
    company_id: str,
    nomenclature_ref: str | None = None,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PriceRow]:
    cid = await assert_company_member(company_id, current_user, db)
    stmt = select(NomenclaturePrice).where(NomenclaturePrice.company_id == cid)
    if nomenclature_ref:
        stmt = stmt.where(NomenclaturePrice.nomenclature_ref == nomenclature_ref)
    # Нефтепродукты — в начало, потом алфавит.
    fuel_rank = _fuel_rank_sql(NomenclaturePrice.nomenclature_name)
    stmt = stmt.order_by(
        fuel_rank,
        NomenclaturePrice.nomenclature_name,
        NomenclaturePrice.price_type_name,
    ).limit(max(1, min(limit, 5000)))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        PriceRow(
            id=str(p.id),
            nomenclature_ref=p.nomenclature_ref,
            nomenclature_name=p.nomenclature_name,
            price_type_ref=p.price_type_ref,
            price_type_name=p.price_type_name,
            period=p.period,
            price=float(p.price),
            currency=p.currency,
            unit=p.unit,
        ) for p in rows
    ]


# ─── /batches ────────────────────────────────────────────────────────

class BatchRow(BaseModel):
    id: str
    batch_doc_type: str | None
    batch_doc_ref: str
    batch_doc_number: str | None
    batch_doc_date: str | None
    nomenclature_ref: str
    nomenclature_name: str | None
    warehouse_ref: str | None
    warehouse_name: str | None
    organization_ref: str | None
    quantity_remaining: float
    amount_remaining: float
    unit_price: float | None
    source: str
    snapshot_at: Any


@router.get("/batches", response_model=list[BatchRow])
async def list_batches(
    company_id: str,
    warehouse_ref: str | None = None,
    nomenclature_ref: str | None = None,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BatchRow]:
    cid = await assert_company_member(company_id, current_user, db)
    stmt = select(InventoryBatch).where(InventoryBatch.company_id == cid)
    if warehouse_ref:
        stmt = stmt.where(InventoryBatch.warehouse_ref == warehouse_ref)
    if nomenclature_ref:
        stmt = stmt.where(InventoryBatch.nomenclature_ref == nomenclature_ref)
    fuel_rank_b = _fuel_rank_sql(InventoryBatch.nomenclature_name)
    stmt = stmt.order_by(
        fuel_rank_b,
        InventoryBatch.nomenclature_name,
        InventoryBatch.batch_doc_date,
    ).limit(max(1, min(limit, 5000)))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        BatchRow(
            id=str(b.id),
            batch_doc_type=b.batch_doc_type,
            batch_doc_ref=b.batch_doc_ref,
            batch_doc_number=b.batch_doc_number,
            batch_doc_date=b.batch_doc_date,
            nomenclature_ref=b.nomenclature_ref,
            nomenclature_name=b.nomenclature_name,
            warehouse_ref=b.warehouse_ref,
            warehouse_name=b.warehouse_name,
            organization_ref=b.organization_ref,
            quantity_remaining=float(b.quantity_remaining),
            amount_remaining=float(b.amount_remaining),
            unit_price=float(b.unit_price) if b.unit_price is not None else None,
            source=b.source,
            snapshot_at=b.snapshot_at,
        ) for b in rows
    ]


# ─── /nomenclature/{ref}/purchase-docs ───────────────────────────────
# Поиск ПТУ-документов где встречается данная номенклатура.
# Используется на страницах /1c/prices и /1c/batches при клике на строку.

class PurchaseDocRow(BaseModel):
    id: str
    external_id: str
    doc_type: str
    number: str
    date: str
    counterparty_name: str
    counterparty_inn: str | None
    organization_name: str | None
    amount: float
    line_quantity: float | None = None
    line_price: float | None = None
    line_sum: float | None = None


@router.get("/nomenclature/{nomenclature_ref}/purchase-docs", response_model=list[PurchaseDocRow])
async def list_nomenclature_purchase_docs(
    nomenclature_ref: str,
    company_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PurchaseDocRow]:
    """ПТУ-документы где упомянута данная номенклатура.

    Сначала ищет в локальной БД (AccountingDoc.lines.tabular.Товары).
    Если в БД пусто — делает прямой COM-запрос в 1С (через
    `find_docs_by_nomenclature`) и автоматически связывает результат с
    AccountingDoc по external_id (если документ уже синкан).
    """
    from app.models import AccountingDoc, OneCConnection
    from app.services.onec.sync_service import OneCSyncService
    from sqlalchemy import text, select
    cid = await assert_company_member(company_id, current_user, db)
    # 1. Локальный JSONB-поиск
    sql = text("""
        SELECT id, external_id, doc_type, number, date, counterparty_name,
               counterparty_inn, organization_name, amount, lines
        FROM accounting_docs
        WHERE company_id = :cid
          AND doc_type IN ('ПТУ', 'КорректировкаПоступления')
          AND lines->'tabular'->'Товары' @> CAST(:nom_filter AS jsonb)
        ORDER BY date DESC
        LIMIT :lim
    """)
    nom_filter = f'[{{"Номенклатура": "{nomenclature_ref}"}}]'
    result = await db.execute(sql, {"cid": str(cid), "nom_filter": nom_filter, "lim": max(1, min(limit, 200))})
    db_rows = result.fetchall()
    out: list[PurchaseDocRow] = []
    for r in db_rows:
        lines = r.lines or {}
        line_qty = line_price = line_sum = None
        try:
            tovary = (lines.get("tabular") or {}).get("Товары") or []
            for t in tovary:
                if isinstance(t, dict) and str(t.get("Номенклатура") or "") == nomenclature_ref:
                    line_qty = float(t.get("Количество") or 0) or None
                    line_price = float(t.get("Цена") or 0) or None
                    line_sum = float(t.get("Сумма") or t.get("Всего") or 0) or None
                    break
        except (TypeError, ValueError, AttributeError):
            pass
        out.append(PurchaseDocRow(
            id=str(r.id),
            external_id=r.external_id,
            doc_type=r.doc_type,
            number=r.number,
            date=str(r.date)[:10],
            counterparty_name=r.counterparty_name or "",
            counterparty_inn=r.counterparty_inn,
            organization_name=r.organization_name,
            amount=float(r.amount or 0),
            line_quantity=line_qty,
            line_price=line_price,
            line_sum=line_sum,
        ))
    if out:
        return out

    # 2. Fallback в 1С через прямой COM-запрос
    conn = (await db.execute(
        select(OneCConnection).where(OneCConnection.company_id == cid).limit(1)
    )).scalar_one_or_none()
    if not conn:
        return []
    svc = OneCSyncService(db)
    try:
        async with await svc._open_client(conn) as client:  # noqa: SLF001
            try:
                onec_rows = await client.find_docs_by_nomenclature(nomenclature_ref, limit=limit)
            except Exception:
                return []
    except Exception:
        return []
    if not onec_rows:
        return []
    # Сопоставляем external_id → AccountingDoc.id (если уже синкан)
    refs = [str(r.get("external_id") or "") for r in onec_rows if r.get("external_id")]
    local_map: dict[str, str] = {}
    if refs:
        local_docs = (await db.execute(
            select(AccountingDoc.id, AccountingDoc.external_id).where(
                AccountingDoc.company_id == cid,
                AccountingDoc.external_id.in_(refs),
            )
        )).all()
        local_map = {row.external_id: str(row.id) for row in local_docs}
    return [
        PurchaseDocRow(
            id=local_map.get(str(r.get("external_id") or ""), str(r.get("external_id") or "")),
            external_id=str(r.get("external_id") or ""),
            doc_type=str(r.get("doc_type") or "ПТУ"),
            number=str(r.get("number") or ""),
            date=str(r.get("date") or "")[:10],
            counterparty_name=str(r.get("counterparty_name") or ""),
            counterparty_inn=r.get("counterparty_inn"),
            organization_name=r.get("organization_name"),
            amount=float(r.get("amount") or 0),
            line_quantity=float(r.get("line_quantity") or 0) or None,
            line_price=float(r.get("line_price") or 0) or None,
            line_sum=float(r.get("line_sum") or 0) or None,
        )
        for r in onec_rows
    ]


# ─── /accounting-docs/{id}/postings/match ────────────────────────────
# Сопоставление фактических проводок документа с шаблоном.

class PostingMatchLine(BaseModel):
    dt: str
    kt: str
    fact_amount: float | None
    expected_formula: str | None
    expected_amount: float | None
    status: str = Field(..., description="ok|missing|extra|mismatch")
    delta: float | None = None
    comment: str | None = None


class PostingMatchResponse(BaseModel):
    template_id: str | None
    template_name: str | None
    doc_type: str
    operation_type: str | None
    base_amount: float
    lines: list[PostingMatchLine]
    summary: dict[str, int]


def _eval_formula(formula: str, base_amount: float) -> float | None:
    """Безопасный калькулятор формул проводок. Поддерживает:
    СуммаДок, +, -, *, /, скобки, числа. Без eval()."""
    if not formula:
        return None
    expr = formula.replace("СуммаДок", str(base_amount)).replace("СуммаДокумента", str(base_amount))
    # Допустимые символы: цифры, точка, операторы, пробелы, скобки.
    allowed = set("0123456789.+-*/ ()")
    if not all(c in allowed for c in expr):
        return None
    try:
        # compile + eval строго с пустыми globals/locals.
        code = compile(expr, "<formula>", "eval")
        for name in code.co_names:
            return None  # любой идентификатор — отказ
        result = eval(code, {"__builtins__": {}}, {})  # noqa: S307
        return round(float(result), 2)
    except Exception:
        return None


@router.get("/accounting-docs/{doc_id}/postings/match", response_model=PostingMatchResponse)
async def match_doc_postings(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PostingMatchResponse:
    """Сопоставляет факт vs шаблон. Возвращает разметку для подсветки в UI."""
    from app.models import AccountingDoc
    try:
        did = uuid.UUID(doc_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid doc id") from exc
    doc = (await db.execute(select(AccountingDoc).where(AccountingDoc.id == did))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Подбираем шаблон по (doc_type, operation_type). Сначала с конкретной компанией.
    from sqlalchemy import or_
    stmt = select(PostingTemplate).where(
        PostingTemplate.doc_type == doc.doc_type,
        or_(PostingTemplate.operation_type == doc.operation_type, PostingTemplate.operation_type.is_(None)),
        or_(PostingTemplate.company_id == doc.company_id, PostingTemplate.company_id.is_(None)),
    ).order_by(
        # company-specific и более точный operation_type вперёд
        PostingTemplate.company_id.is_(None),
        PostingTemplate.operation_type.is_(None),
    )
    template = (await db.execute(stmt.limit(1))).scalar_one_or_none()

    base_amount = float(doc.amount or 0.0)

    # Факт-проводки из lines.postings
    fact_postings: list[dict[str, Any]] = []
    if isinstance(doc.lines, dict):
        for p in doc.lines.get("postings") or []:
            if isinstance(p, dict):
                fact_postings.append(p)

    fact_by_pair: dict[tuple[str, str], float] = {}
    for p in fact_postings:
        dt = str(p.get("СчетДт") or p.get("dt") or "")
        kt = str(p.get("СчетКт") or p.get("kt") or "")
        amt = float(p.get("Сумма") or p.get("amount") or 0.0)
        if dt and kt:
            key = (dt, kt)
            fact_by_pair[key] = fact_by_pair.get(key, 0.0) + amt

    lines: list[PostingMatchLine] = []
    matched_keys: set[tuple[str, str]] = set()

    if template:
        for exp in template.expected or []:
            dt = exp.get("dt") or ""
            kt = exp.get("kt") or ""
            formula = exp.get("formula")
            comment = exp.get("comment")
            key = (dt, kt)
            expected_amt = _eval_formula(formula, base_amount) if formula else None
            fact_amt = fact_by_pair.get(key)
            if fact_amt is None:
                status_v = "missing"
                delta = None
            elif expected_amt is None:
                status_v = "ok"
                delta = None
            else:
                delta = round(fact_amt - expected_amt, 2)
                status_v = "ok" if abs(delta) < 0.05 else "mismatch"
            lines.append(PostingMatchLine(
                dt=dt, kt=kt, fact_amount=fact_amt,
                expected_formula=formula, expected_amount=expected_amt,
                status=status_v, delta=delta, comment=comment,
            ))
            matched_keys.add(key)

    # Лишние факт-проводки (нет в шаблоне)
    for key, amt in fact_by_pair.items():
        if key in matched_keys:
            continue
        lines.append(PostingMatchLine(
            dt=key[0], kt=key[1], fact_amount=amt,
            expected_formula=None, expected_amount=None,
            status="extra", delta=None, comment=None,
        ))

    summary = {
        "ok": sum(1 for x in lines if x.status == "ok"),
        "missing": sum(1 for x in lines if x.status == "missing"),
        "extra": sum(1 for x in lines if x.status == "extra"),
        "mismatch": sum(1 for x in lines if x.status == "mismatch"),
    }
    return PostingMatchResponse(
        template_id=str(template.id) if template else None,
        template_name=template.name if template else None,
        doc_type=doc.doc_type,
        operation_type=doc.operation_type,
        base_amount=base_amount,
        lines=lines,
        summary=summary,
    )
