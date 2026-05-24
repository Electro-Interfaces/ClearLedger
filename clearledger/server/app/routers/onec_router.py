"""
13 эндпоинтов /api/onec/* — интеграция с 1С:Бухгалтерия 3.0 (БП ГИГ).
Pull-only по идеологии ClearLedger v3 — клиент только ЧИТАЕТ из 1С,
запись в 1С выполняется её собственным расширением, которое тянет данные
из ClearLedger HTTP API.

Эндпоинт #12 (export) оставлен заглушкой со статусом 'not_implemented' —
EnterpriseData XML push реализуется отдельно после стабилизации pull.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import AccountingDoc, Company, OneCConnection, OneCSyncLog, User
from app.schemas import (
    OneCConnectionCreate,
    OneCConnectionResponse,
    OneCConnectionUpdate,
    OneCSyncLogResponse,
    OneCSyncResult,
    OneCSyncStats,
    OneCSyncStatusResponse,
    OneCTestResult,
)
from app.services.onec.crypto import encrypt_password
from app.services.onec.sync_service import OneCSyncService

router = APIRouter(prefix="/onec", tags=["1С интеграция"])


# ─── маппинг ORM → схема ────────────────────────────────────────────

def _connection_response(c: OneCConnection) -> OneCConnectionResponse:
    return OneCConnectionResponse(
        id=str(c.id),
        company_id=str(c.company_id),
        name=c.name,
        mode=c.mode,
        odata_url=c.odata_url,
        username=c.username,
        exchange_path=c.exchange_path,
        status=c.status,
        last_sync_at=c.last_sync_at,
        sync_interval_sec=c.sync_interval_sec,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _synclog_response(log: OneCSyncLog) -> OneCSyncLogResponse:
    return OneCSyncLogResponse(
        id=str(log.id),
        connection_id=str(log.connection_id),
        direction=log.direction,
        sync_type=log.sync_type,
        status=log.status,
        items_processed=log.items_processed,
        items_created=log.items_created,
        items_updated=log.items_updated,
        items_errors=log.items_errors,
        details=log.details or {},
        started_at=log.started_at,
        finished_at=log.finished_at,
    )


async def _resolve_company_id(value: str, db: AsyncSession) -> uuid.UUID:
    """Принимает UUID или slug компании, возвращает UUID. CompanyContext во
    фронте хранит slug ('gig', 'npk', 'rti'), а БД — UUID."""
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    result = await db.execute(select(Company).where(Company.slug == value))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown company: {value}")
    return company.id


async def _get_connection_or_404(connection_id: str, db: AsyncSession) -> OneCConnection:
    try:
        cid = uuid.UUID(connection_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid connection id") from exc
    result = await db.execute(select(OneCConnection).where(OneCConnection.id == cid))
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


def _sync_result_from_log(log: OneCSyncLog) -> OneCSyncResult:
    return OneCSyncResult(
        status=log.status,
        stats=OneCSyncStats(
            processed=log.items_processed,
            created=log.items_created,
            updated=log.items_updated,
            errors=log.items_errors,
        ),
        details=log.details or {},
        log_id=str(log.id),
    )


# ─── 1. GET /onec/connections ───────────────────────────────────────

@router.get("/connections", response_model=list[OneCConnectionResponse])
async def list_connections(
    company_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[OneCConnectionResponse]:
    stmt = select(OneCConnection)
    if company_id:
        cid = await _resolve_company_id(company_id, db)
        stmt = stmt.where(OneCConnection.company_id == cid)
    result = await db.execute(stmt.order_by(OneCConnection.created_at.desc()))
    return [_connection_response(c) for c in result.scalars().all()]


# ─── 2. GET /onec/connections/{id} ──────────────────────────────────

@router.get("/connections/{connection_id}", response_model=OneCConnectionResponse)
async def get_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    conn = await _get_connection_or_404(connection_id, db)
    return _connection_response(conn)


# ─── 3. POST /onec/connections ──────────────────────────────────────

@router.post("/connections", response_model=OneCConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: OneCConnectionCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    cid = await _resolve_company_id(payload.company_id, db)

    conn = OneCConnection(
        id=uuid.uuid4(),
        company_id=cid,
        name=payload.name,
        mode=payload.mode,
        odata_url=payload.odata_url.rstrip("/") if payload.mode == "odata" else payload.odata_url,
        username=payload.username,
        password_encrypted=encrypt_password(payload.password),
        exchange_path=payload.exchange_path,
        sync_interval_sec=payload.sync_interval_sec,
        status="inactive",
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)
    return _connection_response(conn)


# ─── 4. PATCH /onec/connections/{id} ────────────────────────────────

@router.patch("/connections/{connection_id}", response_model=OneCConnectionResponse)
async def update_connection(
    connection_id: str,
    payload: OneCConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCConnectionResponse:
    conn = await _get_connection_or_404(connection_id, db)
    if payload.name is not None:
        conn.name = payload.name
    if payload.mode is not None:
        conn.mode = payload.mode
    if payload.odata_url is not None:
        new_mode = payload.mode or conn.mode
        conn.odata_url = payload.odata_url.rstrip("/") if new_mode == "odata" else payload.odata_url
    if payload.username is not None:
        conn.username = payload.username
    if payload.password is not None:
        conn.password_encrypted = encrypt_password(payload.password)
    if payload.exchange_path is not None:
        conn.exchange_path = payload.exchange_path
    if payload.sync_interval_sec is not None:
        conn.sync_interval_sec = payload.sync_interval_sec
    if payload.status is not None:
        conn.status = payload.status
    await db.flush()
    await db.refresh(conn)
    return _connection_response(conn)


# ─── 5. DELETE /onec/connections/{id} ───────────────────────────────

@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    conn = await _get_connection_or_404(connection_id, db)
    await db.delete(conn)


# ─── 6. POST /onec/connections/{id}/test ────────────────────────────

@router.post("/connections/{connection_id}/test", response_model=OneCTestResult)
async def test_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCTestResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    result = await service.test_connection(conn)
    new_status = "active" if result["available"] else "error"
    conn.status = new_status
    await db.flush()
    return OneCTestResult(**result)


# ─── 7-9. POST /onec/connections/{id}/sync/* ────────────────────────

@router.post("/connections/{connection_id}/sync/catalogs", response_model=OneCSyncResult)
async def sync_catalogs(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_catalogs(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/documents", response_model=OneCSyncResult)
async def sync_documents(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_documents(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/batches", response_model=OneCSyncResult)
async def sync_batches(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    """Pull остатков партий товаров (FIFO) из РегистрНакопления.ПартииТоваровНаСкладах."""
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_batches(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/prices", response_model=OneCSyncResult)
async def sync_prices(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    """Pull РегС.ЦеныНоменклатуры — последняя цена на пару (Номенклатура, ВидЦен)."""
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_prices(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/policy", response_model=OneCSyncResult)
async def sync_policy(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    """Pull РегС.УчетнаяПолитика для всех организаций компании из БП.
    Хранит последнюю запись на организацию в OneCPolicy (settings JSONB +
    плоские колонки mpz_method/tax_system/vat_rate/pbu_18_02)."""
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    log = await service.sync_policy(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


@router.post("/connections/{connection_id}/sync/full", response_model=OneCSyncResult)
async def sync_full(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncResult:
    """Catalogs → Policy → Documents в одном вызове. Возвращает агрегат
    последнего этапа (documents) для совместимости со старой схемой."""
    conn = await _get_connection_or_404(connection_id, db)
    service = OneCSyncService(db)
    await service.sync_catalogs(conn)
    try:
        await service.sync_policy(conn)
    except Exception:
        # Политика не должна валить весь sync — у некоторых ЮЛ её нет.
        pass
    try:
        await service.sync_prices(conn)
    except Exception:
        # Цены тоже опциональны — если регистр пуст или нет прав.
        pass
    log = await service.sync_documents(conn)
    conn.last_sync_at = log.finished_at
    await db.flush()
    return _sync_result_from_log(log)


# ─── 10. GET /onec/connections/{id}/sync/status ─────────────────────

@router.get("/connections/{connection_id}/sync/status", response_model=OneCSyncStatusResponse)
async def get_sync_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OneCSyncStatusResponse:
    conn = await _get_connection_or_404(connection_id, db)
    # Текущий лог — самый свежий со статусом running.
    running = (await db.execute(
        select(OneCSyncLog)
        .where(OneCSyncLog.connection_id == conn.id, OneCSyncLog.status == "running")
        .order_by(desc(OneCSyncLog.started_at))
        .limit(1)
    )).scalar_one_or_none()
    return OneCSyncStatusResponse(
        is_syncing=running is not None,
        current_log=_synclog_response(running) if running else None,
        connection_status=conn.status,
        last_sync_at=conn.last_sync_at,
    )


# ─── 11. GET /onec/connections/{id}/history ─────────────────────────

@router.get("/connections/{connection_id}/history", response_model=list[OneCSyncLogResponse])
async def get_sync_history(
    connection_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[OneCSyncLogResponse]:
    conn = await _get_connection_or_404(connection_id, db)
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(OneCSyncLog)
        .where(OneCSyncLog.connection_id == conn.id)
        .order_by(desc(OneCSyncLog.started_at))
        .limit(limit)
    )
    return [_synclog_response(log) for log in result.scalars().all()]


# ─── 12-13. Экспорт (заглушки) ──────────────────────────────────────
# Идеология v3 предписывает pull со стороны 1С, а не push из ClearLedger.
# Эндпоинты оставлены для совместимости фронта, возвращают not_implemented.

@router.post("/connections/{connection_id}/export")
async def export_to_1c(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    await _get_connection_or_404(connection_id, db)
    return {
        "status": "not_implemented",
        "file_path": None,
        "entries_count": 0,
        "error": "Экспорт в 1С через EnterpriseData XML не реализован. "
                 "По идеологии ClearLedger v3 расширение 1С тянет данные из ClearLedger HTTP API.",
    }


@router.get("/connections/{connection_id}/export/status")
async def get_export_status(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    await _get_connection_or_404(connection_id, db)
    return {"status": "not_implemented", "files": [], "error": None}


# ─── 14. Ленивая загрузка ТЧ документа из 1С ────────────────────────
# Тянет одну/несколько табличных частей конкретного AccountingDoc из БП ГИГ
# и кладёт в AccountingDoc.lines (JSONB) как dict {tabular_name: [rows...]}.
# Используется при открытии детального просмотра в /1c/documents.
# Шаг 3 спеки docs/sverka-spec.md §3.2 (ленивая загрузка ТЧ).

# Карта ТЧ по типу документа БП → список имён реквизитов и полей которые тянем.
# Для ПТУ интересны Товары/Услуги (СтавкаНДС/СуммаНДС для сверки).
# Для ОРП — Товары (артикул/количество для сверки со сменой STS) + Оплата.
# Для ОПЗС — Продукция (выпуск) + Материалы (списание).
# Для КорректировкаПоступления — Товары/Услуги (как у ПТУ).
_DOC_TYPE_TO_1C: dict[str, str] = {
    "ПТУ":                       "ПоступлениеТоваровУслуг",
    "ОРП":                       "ОтчетОРозничныхПродажах",
    "ОПЗС":                      "ОтчетПроизводстваЗаСмену",
    "КорректировкаПоступления":  "КорректировкаПоступления",
}

_TABULAR_BY_DOC_TYPE: dict[str, list[tuple[str, list[str]]]] = {
    "ПТУ": [
        ("Товары",  ["Номенклатура", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС", "Всего", "СчетУчета"]),
        ("Услуги",  ["Номенклатура", "Содержание", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС", "Всего", "СчетЗатрат"]),
    ],
    "ОРП": [
        ("Товары",                       ["Номенклатура", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС", "Всего", "СчетУчетаНоменклатуры", "СчетУчетаДоходов"]),
        ("ОплатаПлатежнымиКартами",      ["ВидОплаты", "Сумма", "Эквайер", "СчетУчетаРасчетов"]),
        ("ДенежныеСредства",             ["СчетКассы", "СуммаНаличными"]),
    ],
    "ОПЗС": [
        ("Продукция",  ["Номенклатура", "Количество", "Цена", "Сумма", "СчетУчета"]),
        ("Материалы",  ["Номенклатура", "Количество", "Сумма", "СчетУчета"]),
    ],
    "КорректировкаПоступления": [
        ("Товары",  ["Номенклатура", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС", "Всего", "СчетУчета"]),
        ("Услуги",  ["Номенклатура", "Содержание", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС", "Всего", "СчетЗатрат"]),
    ],
}


@router.post("/connections/{connection_id}/document-lines/{doc_id}")
async def fetch_document_lines(
    connection_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """Тянет ТЧ конкретного AccountingDoc из 1С и кэширует в doc.lines.
    Идемпотентно — при повторном вызове перезатирает кэш."""
    conn = await _get_connection_or_404(connection_id, db)

    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid doc id") from exc

    doc = (await db.execute(
        select(AccountingDoc).where(AccountingDoc.id == doc_uuid)
    )).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    onec_type = _DOC_TYPE_TO_1C.get(doc.doc_type)
    tabs = _TABULAR_BY_DOC_TYPE.get(doc.doc_type)
    if not onec_type or not tabs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Тип документа '{doc.doc_type}' не поддерживается для ленивой загрузки ТЧ",
        )

    service = OneCSyncService(db)
    client = await service._open_client(conn)  # noqa: SLF001
    try:
        tabular: dict[str, list] = {}
        for name, fields in tabs:
            try:
                rows = await client.fetch_doc_lines(onec_type, doc.external_id, name, fields)
            except Exception as exc:  # noqa: BLE001 — некритичная ТЧ может отсутствовать
                rows = []
                tabular[f"_error_{name}"] = str(exc)[:200]
            tabular[name] = rows
        # Проводки — обязательная часть для цикла сверки (см. требование МАГ).
        try:
            postings = await client.fetch_postings(onec_type, doc.external_id)
        except Exception as exc:  # noqa: BLE001
            postings = []
            tabular["_error_postings"] = str(exc)[:200]
    finally:
        await client.aclose()

    # Сохраняем как {tabular: {...}, postings: [...], fetched_at: ...}
    new_lines = {
        "tabular": tabular,
        "postings": postings,
        "fetched_at": datetime.utcnow().isoformat(),
    }
    doc.lines = new_lines
    await db.flush()
    return {
        "doc_id": str(doc.id),
        "doc_type": doc.doc_type,
        "tabular_counts": {k: len(v) if isinstance(v, list) else 0 for k, v in tabular.items()},
        "postings_count": len(postings),
        "fetched_at": new_lines["fetched_at"],
    }


@router.post("/connections/{connection_id}/nomenclature-enrich")
async def enrich_nomenclature(
    connection_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """Batch-резолв Catalog.Номенклатура по GUID → имя/ед.изм/плотность/артикул.
    Нужен для конвертации тонн→литры на ТТН (см. docs/sverka-spec.md §5.3)."""
    conn = await _get_connection_or_404(connection_id, db)
    refs = body.get("refs") or []
    if not refs:
        return {}

    service = OneCSyncService(db)
    client = await service._open_client(conn)  # noqa: SLF001
    try:
        result = await client.enrich_nomenclature(refs)
    finally:
        await client.aclose()
    return result
