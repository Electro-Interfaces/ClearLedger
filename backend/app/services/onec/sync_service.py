"""Sync-оркестратор: OData → ClearLedger (справочники + документы)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.models import (
    OneCConnection, OneCSyncLog,
    Counterparty, Organization, Nomenclature, Contract,
    Warehouse, BankAccount,
)
from app.services.onec.crypto import decrypt_password
from app.services.onec.odata_client import ODataClient, ODataConnectionError
from app.services.onec import mapping

logger = logging.getLogger("onec.sync")


# ── Справочники (Фаза 1) ──────────────────────────────────

CATALOG_MAP = [
    ("Catalog_Контрагенты", Counterparty, mapping.map_counterparty, "inn"),
    ("Catalog_Организации", Organization, mapping.map_organization, "inn"),
    ("Catalog_Номенклатура", Nomenclature, mapping.map_nomenclature, "code"),
    ("Catalog_Склады", Warehouse, mapping.map_warehouse, "code"),
]


async def sync_catalogs(connection_id: UUID) -> dict[str, Any]:
    """Синхронизирует все справочники из 1С."""
    async with async_session() as db:
        conn = await _get_connection(db, connection_id)
        log = OneCSyncLog(
            connection_id=conn.id,
            direction="inbound",
            sync_type="catalogs",
            status="running",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

    total_stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}
    details: dict[str, Any] = {}

    try:
        password = decrypt_password(conn.password_encrypted)
        async with ODataClient(conn.odata_url, conn.username, password) as client:
            for entity_name, model_cls, mapper, upsert_key in CATALOG_MAP:
                stats = await _sync_one_catalog(
                    client, conn, entity_name, model_cls, mapper, upsert_key,
                )
                details[entity_name] = stats
                for k in ("processed", "created", "updated", "errors"):
                    total_stats[k] += stats[k]

            # Договоры — отдельно (требуют resolve FK)
            contract_stats = await _sync_contracts(client, conn)
            details["Catalog_ДоговорыКонтрагентов"] = contract_stats
            for k in ("processed", "created", "updated", "errors"):
                total_stats[k] += contract_stats[k]

            # Банковские счета — отдельно (требуют resolve FK)
            ba_stats = await _sync_bank_accounts(client, conn)
            details["Catalog_БанковскиеСчета"] = ba_stats
            for k in ("processed", "created", "updated", "errors"):
                total_stats[k] += ba_stats[k]

        status = "success"
    except ODataConnectionError as e:
        logger.error("Sync catalogs failed: %s", e)
        details["error"] = str(e)
        status = "error"
    except Exception as e:
        logger.exception("Unexpected sync error")
        details["error"] = str(e)
        status = "error"

    # Обновляем лог
    async with async_session() as db:
        await db.execute(
            update(OneCSyncLog).where(OneCSyncLog.id == log.id).values(
                status=status,
                items_processed=total_stats["processed"],
                items_created=total_stats["created"],
                items_updated=total_stats["updated"],
                items_errors=total_stats["errors"],
                details=details,
                finished_at=datetime.now(timezone.utc),
            )
        )
        # Обновляем last_sync_at на подключении
        if status == "success":
            await db.execute(
                update(OneCConnection).where(OneCConnection.id == connection_id).values(
                    last_sync_at=datetime.now(timezone.utc),
                    status="active",
                )
            )
        await db.commit()

    return {"status": status, "stats": total_stats, "details": details, "log_id": str(log.id)}


async def _sync_one_catalog(
    client: ODataClient,
    conn: OneCConnection,
    entity_name: str,
    model_cls: type,
    mapper: Any,
    upsert_key: str,
) -> dict[str, int]:
    """Синхронизирует один справочник."""
    stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}

    try:
        items = await client.get_catalog(entity_name)
    except ODataConnectionError:
        raise
    except Exception as e:
        logger.error("Ошибка загрузки %s: %s", entity_name, e)
        stats["errors"] = 1
        return stats

    async with async_session() as db:
        for item in items:
            stats["processed"] += 1
            try:
                mapped = mapper(item)
                if not mapped.get(upsert_key):
                    continue

                # Upsert по ключу
                existing = await _find_by_key(
                    db, model_cls, conn.company_id, upsert_key, mapped[upsert_key]
                )

                if existing:
                    for k, v in mapped.items():
                        if v is not None and hasattr(existing, k):
                            setattr(existing, k, v)
                    existing.updated_at = datetime.now(timezone.utc)
                    stats["updated"] += 1
                else:
                    obj = model_cls(company_id=conn.company_id, **{
                        k: v for k, v in mapped.items()
                        if hasattr(model_cls, k)
                    })
                    db.add(obj)
                    stats["created"] += 1
            except Exception as e:
                logger.warning("Ошибка маппинга %s: %s", entity_name, e)
                stats["errors"] += 1

        await db.commit()

    return stats


async def _sync_contracts(client: ODataClient, conn: OneCConnection) -> dict[str, int]:
    """Синхронизирует договоры (с resolve контрагент/организация по external_ref)."""
    stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}

    try:
        items = await client.get_catalog("Catalog_ДоговорыКонтрагентов")
    except Exception as e:
        logger.error("Ошибка загрузки договоров: %s", e)
        stats["errors"] = 1
        return stats

    async with async_session() as db:
        # Кеш external_ref → id для контрагентов
        cp_cache = await _build_ref_cache(db, Counterparty, conn.company_id)
        org_cache = await _build_ref_cache(db, Organization, conn.company_id)

        for item in items:
            stats["processed"] += 1
            try:
                mapped = mapping.map_contract(item)
                if not mapped.get("number"):
                    continue

                counterparty_id = cp_cache.get(mapped.pop("counterparty_ref", None))

                # Upsert по number + counterparty_id
                q = select(Contract).where(
                    Contract.company_id == conn.company_id,
                    Contract.number == mapped["number"],
                )
                if counterparty_id:
                    q = q.where(Contract.counterparty_id == counterparty_id)
                result = await db.execute(q)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.date = mapped.get("date")
                    existing.type = mapped.get("type", "Прочее")
                    existing.updated_at = datetime.now(timezone.utc)
                    stats["updated"] += 1
                else:
                    contract = Contract(
                        company_id=conn.company_id,
                        number=mapped["number"],
                        date=mapped.get("date"),
                        counterparty_id=counterparty_id,
                        organization_id=org_cache.get(mapped.get("organization_ref")),
                        type=mapped.get("type", "Прочее"),
                    )
                    db.add(contract)
                    stats["created"] += 1
            except Exception as e:
                logger.warning("Ошибка маппинга договора: %s", e)
                stats["errors"] += 1

        await db.commit()

    return stats


async def _sync_bank_accounts(client: ODataClient, conn: OneCConnection) -> dict[str, int]:
    """Синхронизирует банковские счета (с resolve организации по external_ref)."""
    stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}

    try:
        items = await client.get_catalog("Catalog_БанковскиеСчета")
    except Exception as e:
        logger.error("Ошибка загрузки банковских счетов: %s", e)
        stats["errors"] = 1
        return stats

    async with async_session() as db:
        org_cache = await _build_ref_cache(db, Organization, conn.company_id)

        for item in items:
            stats["processed"] += 1
            try:
                mapped = mapping.map_bank_account(item)
                if not mapped.get("number"):
                    continue

                org_id = org_cache.get(mapped.pop("organization_ref", None))

                # Upsert по номеру счёта
                result = await db.execute(
                    select(BankAccount).where(
                        BankAccount.company_id == conn.company_id,
                        BankAccount.number == mapped["number"],
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    for k, v in mapped.items():
                        if v is not None and hasattr(existing, k):
                            setattr(existing, k, v)
                    existing.organization_id = org_id
                    existing.updated_at = datetime.now(timezone.utc)
                    stats["updated"] += 1
                else:
                    ba = BankAccount(
                        company_id=conn.company_id,
                        organization_id=org_id,
                        **{k: v for k, v in mapped.items() if hasattr(BankAccount, k)},
                    )
                    db.add(ba)
                    stats["created"] += 1
            except Exception as e:
                logger.warning("Ошибка маппинга банковского счёта: %s", e)
                stats["errors"] += 1

        await db.commit()

    return stats


# ── Документы (Фаза 2) ────────────────────────────────────

DOCUMENT_MAP = [
    ("Document_ПоступлениеТоваровУслуг", "Товары"),
    ("Document_РеализацияТоваровУслуг", "Товары"),
    ("Document_ПлатежноеПоручениеИсходящее", None),
    ("Document_СчетФактураПолученный", None),
    ("Document_СчетФактураВыданный", None),
]


async def sync_documents(connection_id: UUID) -> dict[str, Any]:
    """Синхронизирует документы из 1С."""
    async with async_session() as db:
        conn = await _get_connection(db, connection_id)
        log = OneCSyncLog(
            connection_id=conn.id,
            direction="inbound",
            sync_type="documents",
            status="running",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

    total_stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}
    details: dict[str, Any] = {}

    try:
        password = decrypt_password(conn.password_encrypted)
        async with ODataClient(conn.odata_url, conn.username, password) as client:
            # Кеши для resolve FK
            async with async_session() as db:
                cp_cache = await _build_ref_cache(db, Counterparty, conn.company_id)
                org_cache = await _build_ref_cache(db, Organization, conn.company_id)
                # ИНН-кеш для counterparty_inn
                cp_inn_cache = await _build_inn_cache(db, Counterparty, conn.company_id)

            for entity_name, expand in DOCUMENT_MAP:
                stats = await _sync_one_doc_type(
                    client, conn, entity_name, expand, cp_cache, org_cache, cp_inn_cache,
                )
                details[entity_name] = stats
                for k in ("processed", "created", "updated", "errors"):
                    total_stats[k] += stats[k]

        status = "success"
    except ODataConnectionError as e:
        logger.error("Sync documents failed: %s", e)
        details["error"] = str(e)
        status = "error"
    except Exception as e:
        logger.exception("Unexpected sync error")
        details["error"] = str(e)
        status = "error"

    async with async_session() as db:
        await db.execute(
            update(OneCSyncLog).where(OneCSyncLog.id == log.id).values(
                status=status,
                items_processed=total_stats["processed"],
                items_created=total_stats["created"],
                items_updated=total_stats["updated"],
                items_errors=total_stats["errors"],
                details=details,
                finished_at=datetime.now(timezone.utc),
            )
        )
        if status == "success":
            await db.execute(
                update(OneCConnection).where(OneCConnection.id == connection_id).values(
                    last_sync_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()

    return {"status": status, "stats": total_stats, "details": details, "log_id": str(log.id)}


async def _sync_one_doc_type(
    client: ODataClient,
    conn: OneCConnection,
    entity_name: str,
    expand: str | None,
    cp_cache: dict[str | None, UUID | None],
    org_cache: dict[str | None, UUID | None],
    cp_inn_cache: dict[str | None, str | None],
) -> dict[str, int]:
    """Синхронизирует один тип документа."""
    from app.models.models import Entry  # для accounting_docs (через Entry)

    stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}

    try:
        items = await client.get_catalog(entity_name, expand=expand)
    except ODataConnectionError:
        raise
    except Exception as e:
        logger.error("Ошибка загрузки %s: %s", entity_name, e)
        stats["errors"] = 1
        return stats

    async with async_session() as db:
        for item in items:
            stats["processed"] += 1
            try:
                mapped = mapping.map_document(entity_name, item)
                ref_key = mapped["external_id"]
                if not ref_key:
                    continue

                # Resolve контрагент
                cp_ref = mapped.pop("counterparty_ref", None)
                org_ref = mapped.pop("organization_ref", None)
                wh_ref = mapped.pop("warehouse_ref", None)

                # Получаем имя и ИНН контрагента из кеша
                cp_id = cp_cache.get(cp_ref)
                if cp_id:
                    cp_row = (await db.execute(
                        select(Counterparty.name, Counterparty.inn).where(Counterparty.id == cp_id)
                    )).first()
                    if cp_row:
                        mapped["counterparty_name"] = cp_row.name
                        mapped["counterparty_inn"] = cp_row.inn

                org_id = org_cache.get(org_ref)
                if org_id:
                    org_row = (await db.execute(
                        select(Organization.name).where(Organization.id == org_id)
                    )).first()
                    if org_row:
                        mapped["organization_name"] = org_row.name

                # Табличная часть
                lines_data = item.get(expand, []) if expand else []
                lines = mapping.map_doc_lines(lines_data) if lines_data else []

                # Upsert в entries как source=oneC
                result = await db.execute(
                    select(Entry).where(
                        Entry.company_id == conn.company_id,
                        Entry.source_type == "oneC",
                        Entry.metadata_["_1c.guid"].astext == ref_key,
                    )
                )
                existing = result.scalar_one_or_none()

                metadata = {
                    "_1c.guid": ref_key,
                    "_1c.docType": mapped["doc_type"],
                    "_1c.number": mapped["number"],
                    "_1c.date": mapped.get("date", ""),
                    "_1c.amount": str(mapped["amount"]),
                    "_1c.counterparty": mapped["counterparty_name"],
                    "_1c.counterpartyInn": mapped.get("counterparty_inn", ""),
                    "_1c.organization": mapped.get("organization_name", ""),
                    "_1c.status": mapped["status_1c"],
                    "_1c.lines": str(len(lines)),
                }

                doc_type_to_category = {
                    "receipt": "incoming",
                    "sales": "outgoing",
                    "payment-out": "bank",
                    "invoice-received": "incoming",
                    "invoice-issued": "outgoing",
                }
                category_id = doc_type_to_category.get(mapped["doc_type"], "other")

                if existing:
                    existing.title = f"{mapped['number']} от {mapped.get('date', '')}"
                    existing.metadata_ = metadata
                    existing.updated_at = datetime.now(timezone.utc)
                    stats["updated"] += 1
                else:
                    entry = Entry(
                        company_id=conn.company_id,
                        title=f"{mapped['number']} от {mapped.get('date', '')}",
                        category_id=category_id,
                        subcategory_id=mapped["doc_type"],
                        doc_type_id=mapped["doc_type"],
                        status="new",
                        source_type="oneC",
                        source_label=f"1С: {entity_name.replace('Document_', '')}",
                        metadata_=metadata,
                    )
                    db.add(entry)
                    stats["created"] += 1

            except Exception as e:
                logger.warning("Ошибка маппинга документа %s: %s", entity_name, e)
                stats["errors"] += 1

        await db.commit()

    return stats


async def sync_full(connection_id: UUID) -> dict[str, Any]:
    """Полная синхронизация: справочники → документы."""
    async with async_session() as db:
        conn = await _get_connection(db, connection_id)
        log = OneCSyncLog(
            connection_id=conn.id,
            direction="inbound",
            sync_type="full",
            status="running",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

    try:
        cat_result = await sync_catalogs(connection_id)
        doc_result = await sync_documents(connection_id)

        total_stats = {
            "processed": cat_result["stats"]["processed"] + doc_result["stats"]["processed"],
            "created": cat_result["stats"]["created"] + doc_result["stats"]["created"],
            "updated": cat_result["stats"]["updated"] + doc_result["stats"]["updated"],
            "errors": cat_result["stats"]["errors"] + doc_result["stats"]["errors"],
        }
        status = "success" if cat_result["status"] == "success" and doc_result["status"] == "success" else "error"
        details = {"catalogs": cat_result["details"], "documents": doc_result["details"]}
    except Exception as e:
        total_stats = {"processed": 0, "created": 0, "updated": 0, "errors": 1}
        status = "error"
        details = {"error": str(e)}

    async with async_session() as db:
        await db.execute(
            update(OneCSyncLog).where(OneCSyncLog.id == log.id).values(
                status=status,
                items_processed=total_stats["processed"],
                items_created=total_stats["created"],
                items_updated=total_stats["updated"],
                items_errors=total_stats["errors"],
                details=details,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    return {"status": status, "stats": total_stats, "details": details, "log_id": str(log.id)}


# ── Утилиты ───────────────────────────────────────────────

async def _get_connection(db: AsyncSession, connection_id: UUID) -> OneCConnection:
    """Получает подключение 1С."""
    result = await db.execute(
        select(OneCConnection).where(OneCConnection.id == connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise ValueError(f"Подключение 1С {connection_id} не найдено")
    return conn


async def _find_by_key(
    db: AsyncSession, model_cls: type, company_id: str, key_field: str, key_value: str
) -> Any:
    """Поиск записи по company_id + ключевому полю."""
    col = getattr(model_cls, key_field)
    result = await db.execute(
        select(model_cls).where(
            getattr(model_cls, "company_id") == company_id,
            col == key_value,
        )
    )
    return result.scalar_one_or_none()


async def _build_ref_cache(
    db: AsyncSession, model_cls: type, company_id: str
) -> dict[str | None, UUID | None]:
    """Строит кеш external_ref → id."""
    result = await db.execute(
        select(getattr(model_cls, "external_ref"), getattr(model_cls, "id")).where(
            getattr(model_cls, "company_id") == company_id,
            getattr(model_cls, "external_ref").isnot(None),
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def _build_inn_cache(
    db: AsyncSession, model_cls: type, company_id: str
) -> dict[str | None, str | None]:
    """Строит кеш external_ref → inn."""
    result = await db.execute(
        select(getattr(model_cls, "external_ref"), getattr(model_cls, "inn")).where(
            getattr(model_cls, "company_id") == company_id,
            getattr(model_cls, "external_ref").isnot(None),
        )
    )
    return {row[0]: row[1] for row in result.all()}
