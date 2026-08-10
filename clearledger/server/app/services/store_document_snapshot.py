from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingSourceLink,
    DataEntry,
    EdgeAgent,
    EdgeDownlink,
    StoreDocumentProjection,
)
from app.services.store_document_contract import (
    ACCOUNTING_DOCUMENT_KINDS,
    PROJECTION_DOCUMENT_KINDS,
)

# Переоценка бухгалтерским документом не является, но в 1С она есть и
# человеку на станции нужна: снимок отдаёт всё, кроме кассовых чеков и
# смен — те живут своим архивом.
SNAPSHOT_DOCUMENT_KINDS = tuple(
    kind for kind in PROJECTION_DOCUMENT_KINDS
    if kind not in ("fiscal_receipt", "store_shift")
)


SNAPSHOT_KIND = "onec_document_snapshot"
# Станция видит документы, которых у неё нет локально: до перехода их вели в
# 1С, а приёмки центра заводит товаровед. «edge» сюда не входит — это её
# собственные документы, они и так лежат в её базе; касса ведёт свой архив.
ONEC_PROJECTION_SOURCES = ("onec_legacy", "bp", "store")
MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal("0.01")), ".2f")


def _datetime(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _строка(value: object) -> str | None:
    """Реквизит заголовка — только непустой строкой: пакет station-scoped, лишний
    null в нём меняет хеш снимка и заставляет станцию перекачивать то же самое."""
    return value if isinstance(value, str) and value.strip() else None


def _line(позиция: dict, имена: dict[str, str]) -> dict:
    """Строка документа для станции: только то, что человек читает в бланке."""
    ссылка = str(позиция.get("nomenclature_ref") or "")
    название = (позиция.get("name") or "").strip() or имена.get(ссылка, "")
    количество = позиция.get("qty_fact")
    if количество in (None, 0) and позиция.get("qty_expected"):
        количество = позиция.get("qty_expected")
    return {
        "name": название,
        "unit": (позиция.get("unit") or "").strip() or None,
        "barcode": позиция.get("barcode") or None,
        "qty": _decimal(количество or 0),
        "price": _decimal(позиция.get("price") or 0),
        "amount": _decimal(позиция.get("amount") or 0),
        "vat_rate": позиция.get("vat_rate") or None,
        "vat_amount": _decimal(позиция.get("vat_amount") or 0),
    }


def build_snapshot_headers(
    projections: list[StoreDocumentProjection],
    links: list[AccountingSourceLink],
    entries: list[DataEntry],
    состав: dict[uuid.UUID, list[dict]] | None = None,
) -> list[dict]:
    entry_by_document: dict[uuid.UUID, DataEntry] = {}
    for entry in sorted(entries, key=lambda row: int(row.revision or 0), reverse=True):
        if entry.document_id is not None:
            entry_by_document.setdefault(entry.document_id, entry)
    link_by_scope = {
        (link.projection_source, link.source_kind, link.source_document_id): link
        for link in links
    }
    headers: dict[str, dict] = {}
    for row in projections:
        if (row.document_kind not in SNAPSHOT_DOCUMENT_KINDS
                or row.projection_source not in ONEC_PROJECTION_SOURCES
                or row.source_document_id is None):
            continue
        # Документ центральной базы — самостоятельный факт: он заведён в 1С и
        # проведён в бухгалтерии. Подтверждённая связь с нашим документом даёт
        # станции дополнительную опору, но её отсутствие не повод прятать
        # документ от человека, который с ним работал.
        link = link_by_scope.get(
            (row.projection_source, row.document_kind, row.source_document_id))
        entry = entry_by_document.get(row.document_id)
        связь_полна = (link is not None
                       and link.canonical_document_id == row.document_id
                       and entry is not None and entry.revision and entry.content_hash)
        header = row.header if isinstance(row.header, dict) else {}
        warehouse = header.get("warehouse")
        item = {
            "source_id": f"{row.projection_source}:{row.source_record_id}",
            "kind": row.document_kind,
            "document_at": _datetime(row.document_at),
            "number": row.number,
            "counterparty": row.counterparty_name,
            "warehouse": warehouse if isinstance(warehouse, str) else None,
            "amount": _decimal(row.amount),
            "vat": _decimal(row.vat_amount),
            "operational_status": row.operational_status,
            # Реквизиты исходного документа 1С. Станция показывает их в карточке:
            # мы продолжаем историю этих документов, и бухгалтерия сверяет ленту
            # по тем же полям, с которыми работала годами.
            "author": row.author,
            "contract": _строка(header.get("contract")),
            "organization": _строка(header.get("organization")),
            "incoming_number": _строка(header.get("incoming_number")),
            "incoming_date": _строка(header.get("incoming_date")),
            # Состав документа. Шапка без табличной части бесполезна: человек
            # открывает документ, чтобы увидеть, что именно привезли и почём.
            "lines": (состав or {}).get(row.document_id) or [],
            "canonical_link": {
                "kind": row.document_kind,
                "document_id": str(link.canonical_document_id),
                "revision": int(entry.revision),
                "content_hash": str(entry.content_hash),
                "confirmed_at": link.confirmed_at.isoformat(),
            } if связь_полна else None,
        }
        existing = headers.get(item["source_id"])
        if existing is not None and existing != item:
            raise ValueError(f"Неоднозначный source_id {item['source_id']}")
        headers[item["source_id"]] = item
    return [headers[key] for key in sorted(headers)]


def snapshot_content_hash(headers: list[dict]) -> str:
    canonical = json.dumps(
        headers, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot_headers(headers: list[dict]) -> None:
    for header in headers:
        source_id = str(header.get("source_id") or "")
        try:
            if not source_id:
                raise ValueError("пустой source_id")
            if header.get("kind") not in SNAPSHOT_DOCUMENT_KINDS:
                raise ValueError("запрещённый kind")
            if not isinstance(header.get("number"), str) or not header["number"].strip():
                raise ValueError("не указан number")
            document_at = header.get("document_at")
            if not isinstance(document_at, str):
                raise ValueError("не указан document_at")
            datetime.fromisoformat(document_at)
            for field in ("amount", "vat"):
                value = header.get(field)
                if value is not None and (
                        not isinstance(value, str) or MONEY_RE.fullmatch(value) is None):
                    raise ValueError(f"{field} должен иметь два знака")
            link = header.get("canonical_link")
            if link is None:
                continue
            if not isinstance(link, dict):
                raise ValueError("canonical_link не объект")
            if link.get("kind") != header.get("kind"):
                raise ValueError("kind canonical_link не совпадает")
            uuid.UUID(str(link.get("document_id") or ""))
            if int(link.get("revision") or 0) <= 0:
                raise ValueError("некорректная revision canonical_link")
            if HASH_RE.fullmatch(str(link.get("content_hash") or "")) is None:
                raise ValueError("некорректный content_hash canonical_link")
            datetime.fromisoformat(str(link.get("confirmed_at") or ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Snapshot header {source_id or '<empty>'}: {exc}") from exc


async def _document_lines(
    db: AsyncSession, company_id: uuid.UUID,
    projections: list[StoreDocumentProjection],
) -> dict[uuid.UUID, list[dict]]:
    """Состав документов приёмки для снимка.

    Первичка неизменяема (триггер `accepted store receipt evidence is immutable`),
    и в исторических строках лежит только ссылка номенклатуры 1С. Наименование
    берём из справочника пространства по той же ссылке - он полный, товар туда
    приехал вместе с остатками.
    """
    ids = [row.document_id for row in projections
           if row.projection_source == "store" and row.source_kind == "receipt"]
    if not ids:
        return {}
    строки = (await db.execute(text(
        "SELECT id, lines FROM core.store_receipts "
        " WHERE company_id = :cid AND id = ANY(:ids) AND lines IS NOT NULL"),
        {"cid": company_id, "ids": ids})).all()
    ссылки = {str(позиция.get("nomenclature_ref") or "")
              for _, состав in строки if isinstance(состав, list)
              for позиция in состав if isinstance(позиция, dict)}
    ссылки.discard("")
    имена: dict[str, str] = {}
    if ссылки:
        # справочник edge.item — общий на пространство, своей колонки компании
        # у него нет: стек и так живёт одной компанией
        имена = {str(ref): name for ref, name in (await db.execute(text(
            "SELECT external_uuid, name FROM edge.item "
            " WHERE external_uuid = ANY(CAST(:refs AS uuid[]))"),
            {"refs": sorted(ссылки)})).all()}
    return {record_id: [_line(позиция, имена) for позиция in состав
                        if isinstance(позиция, dict)]
            for record_id, состав in строки if isinstance(состав, list)}


async def queue_onec_document_snapshot(
    db: AsyncSession, company_id: uuid.UUID, station_id: int,
) -> tuple[EdgeDownlink, bool]:
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
    ), {"scope_key": f"onec-document-snapshot:{company_id}:{station_id}"})
    agent = (await db.execute(select(EdgeAgent).where(
        EdgeAgent.company_id == company_id,
        EdgeAgent.station_id == station_id,
    ))).scalar_one_or_none()
    if agent is None:
        raise ValueError("Станция не зарегистрирована в контуре Edge")

    projections = list((await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == company_id,
        StoreDocumentProjection.station_id == station_id,
        StoreDocumentProjection.is_primary.is_(True),
        StoreDocumentProjection.projection_source.in_(ONEC_PROJECTION_SOURCES),
        StoreDocumentProjection.document_kind.in_(SNAPSHOT_DOCUMENT_KINDS),
    ))).scalars().all())
    document_ids = {row.document_id for row in projections}
    links = list((await db.execute(select(AccountingSourceLink).where(
        AccountingSourceLink.company_id == company_id,
        AccountingSourceLink.canonical_document_id.in_(document_ids),
        AccountingSourceLink.projection_source.in_(ONEC_PROJECTION_SOURCES),
        AccountingSourceLink.source_kind.in_(SNAPSHOT_DOCUMENT_KINDS),
    ))).scalars().all()) if document_ids else []
    entries = list((await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.document_id.in_(document_ids),
    ))).scalars().all()) if document_ids else []
    состав = await _document_lines(db, company_id, projections)
    headers = build_snapshot_headers(projections, links, entries, состав)
    validate_snapshot_headers(headers)
    content_hash = snapshot_content_hash(headers)

    previous = list((await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == company_id,
        EdgeDownlink.station_id == station_id,
        EdgeDownlink.kind == SNAPSHOT_KIND,
    ))).scalars().all())
    for task in previous:
        if (task.payload or {}).get("content_hash") == content_hash:
            return task, False
    revision = max(
        (int((task.payload or {}).get("revision") or 0) for task in previous),
        default=0,
    ) + 1
    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": 1,
        "station_id": station_id,
        "revision": revision,
        "content_hash": content_hash,
        "snapshot_at": now.isoformat(),
        "headers": headers,
    }
    task = EdgeDownlink(
        id=uuid.uuid4(), company_id=company_id, station_id=station_id,
        kind=SNAPSHOT_KIND, payload=payload,
        note=f"onec-document-snapshot:r{revision}",
        idempotency_key=f"onec-documents:{station_id}:{content_hash}",
    )
    db.add(task)
    return task, True
