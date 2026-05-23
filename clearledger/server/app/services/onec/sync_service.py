from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Counterparty,
    NomenclatureItem,
    OneCConnection,
    OneCSyncLog,
    Organization,
    Warehouse,
)
from app.services.onec.crypto import decrypt_password
from app.services.onec.exceptions import OneCError
from app.services.onec.odata_client import (
    ENTITY_COUNTERPARTIES,
    ENTITY_NOMENCLATURE,
    ENTITY_ORGANIZATIONS,
    ENTITY_WAREHOUSES,
    OneCODataClient,
)

logger = logging.getLogger("clearledger.onec.sync")


# Поля справочников 1С, которые тянем в локальную нормализованную БД.
# Только то, что есть в существующих моделях ClearLedger — без расширения схемы.
COUNTERPARTY_SELECT = ["Ref_Key", "DeletionMark", "Description", "ИНН", "КПП"]
NOMENCLATURE_SELECT = ["Ref_Key", "DeletionMark", "Description", "Артикул", "Код"]
ORGANIZATION_SELECT = ["Ref_Key", "DeletionMark", "Description", "ИНН", "КПП"]
WAREHOUSE_SELECT    = ["Ref_Key", "DeletionMark", "Description", "Код"]


class OneCSyncService:
    """Pull-синхронизация НСИ из БП ГИГ в локальную нормализованную БД.

    Логика:
    - На каждый запрос создаётся OneCSyncLog со статусом 'running'.
    - По окончании — finished_at, status='completed' либо 'error', details.
    - Записи с DeletionMark=True пропускаются (мягкое удаление обновлений).
    - external_ref = Ref_Key (UUID 1С) — ключ дедупликации.
    - company_id берётся из OneCConnection.company_id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _open_client(self, connection: OneCConnection) -> OneCODataClient:
        password = decrypt_password(connection.password_encrypted)
        return OneCODataClient(
            base_url=connection.odata_url,
            username=connection.username,
            password=password,
        )

    async def _start_log(
        self,
        connection: OneCConnection,
        sync_type: str,
        direction: str = "in",
    ) -> OneCSyncLog:
        log = OneCSyncLog(
            id=uuid.uuid4(),
            connection_id=connection.id,
            direction=direction,
            sync_type=sync_type,
            status="running",
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def _finish_log(
        self,
        log: OneCSyncLog,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        log.status = status
        log.finished_at = datetime.now(tz=timezone.utc)
        if details:
            log.details = {**(log.details or {}), **details}

    # ─── публичные операции ─────────────────────────────────────────

    async def test_connection(self, connection: OneCConnection) -> dict[str, Any]:
        try:
            async with await self._open_client(connection) as client:
                catalogs = await client.metadata_catalogs()
            return {"available": True, "catalogs": catalogs, "error": None}
        except OneCError as exc:
            return {"available": False, "catalogs": [], "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — точка контакта с внешним миром, ловим всё
            logger.exception("Unexpected error during test_connection")
            return {"available": False, "catalogs": [], "error": f"{type(exc).__name__}: {exc}"}

    async def sync_catalogs(self, connection: OneCConnection) -> OneCSyncLog:
        log = await self._start_log(connection, sync_type="catalogs")
        details: dict[str, Any] = {}
        try:
            async with await self._open_client(connection) as client:
                details["organizations"] = await self._sync_organizations(client, connection, log)
                details["counterparties"] = await self._sync_counterparties(client, connection, log)
                details["warehouses"] = await self._sync_warehouses(client, connection, log)
                details["nomenclature"] = await self._sync_nomenclature(client, connection, log)
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def sync_documents(self, connection: OneCConnection) -> OneCSyncLog:
        """Заглушка для следующей итерации.

        Документы (ПТУ, ОРП, ОПЗС) требуют отдельной схемы хранения и
        фильтра по checkpoint — реализую после того, как pull НСИ
        стабилизируется на боевой публикации OData.
        """
        log = await self._start_log(connection, sync_type="documents")
        await self._finish_log(log, "completed", {"note": "documents-sync not implemented yet"})
        return log

    # ─── upsert по каждой сущности ──────────────────────────────────

    async def _sync_counterparties(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_COUNTERPARTIES, select=COUNTERPARTY_SELECT, page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Counterparty).where(
                        Counterparty.company_id == connection.company_id,
                        Counterparty.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    self.session.add(Counterparty(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        name=(item.get("Description") or "").strip() or "(без названия)",
                        inn=(item.get("ИНН") or "").strip(),
                        kpp=((item.get("КПП") or "").strip() or None),
                    ))
                    stats["created"] += 1
                else:
                    existing.name = (item.get("Description") or existing.name).strip() or existing.name
                    existing.inn = (item.get("ИНН") or existing.inn or "").strip()
                    existing.kpp = ((item.get("КПП") or "").strip() or None) or existing.kpp
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Counterparty upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_organizations(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_ORGANIZATIONS, select=ORGANIZATION_SELECT, page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Organization).where(
                        Organization.company_id == connection.company_id,
                        Organization.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                if existing is None:
                    self.session.add(Organization(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        name=(item.get("Description") or "").strip() or "(без названия)",
                        inn=(item.get("ИНН") or "").strip(),
                        kpp=((item.get("КПП") or "").strip() or None),
                    ))
                    stats["created"] += 1
                else:
                    existing.name = (item.get("Description") or existing.name).strip() or existing.name
                    existing.inn = (item.get("ИНН") or existing.inn or "").strip()
                    existing.kpp = ((item.get("КПП") or "").strip() or None) or existing.kpp
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Organization upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_warehouses(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_WAREHOUSES, select=WAREHOUSE_SELECT, page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(Warehouse).where(
                        Warehouse.company_id == connection.company_id,
                        Warehouse.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                code = (item.get("Код") or "").strip() or ref_key[:8]
                name = (item.get("Description") or "").strip() or code
                if existing is None:
                    self.session.add(Warehouse(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        code=code,
                        name=name,
                    ))
                    stats["created"] += 1
                else:
                    existing.code = code
                    existing.name = name
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Warehouse upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    async def _sync_nomenclature(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_NOMENCLATURE, select=NOMENCLATURE_SELECT, page_size=500):
            stats["processed"] += 1
            if item.get("DeletionMark"):
                stats["skipped"] += 1
                continue
            ref_key = item.get("Ref_Key")
            if not ref_key:
                stats["errors"] += 1
                continue
            try:
                existing = (await self.session.execute(
                    select(NomenclatureItem).where(
                        NomenclatureItem.company_id == connection.company_id,
                        NomenclatureItem.external_ref == ref_key,
                    )
                )).scalar_one_or_none()
                code = (item.get("Артикул") or item.get("Код") or "").strip() or ref_key[:8]
                name = (item.get("Description") or "").strip() or code
                if existing is None:
                    self.session.add(NomenclatureItem(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_ref=ref_key,
                        code=code,
                        name=name,
                        unit="шт",
                        unit_label="штука",
                    ))
                    stats["created"] += 1
                else:
                    existing.code = code
                    existing.name = name
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Nomenclature upsert failed (Ref_Key=%s): %s", ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    @staticmethod
    def _merge_log_stats(log: OneCSyncLog, stats: dict[str, int]) -> None:
        log.items_processed += stats["processed"]
        log.items_created += stats["created"]
        log.items_updated += stats["updated"]
        log.items_errors += stats["errors"]
