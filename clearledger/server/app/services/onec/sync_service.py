from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc,
    Counterparty,
    NomenclatureItem,
    OneCConnection,
    OneCSyncLog,
    Organization,
    Warehouse,
)
from app.services.onec.com_client import OneCComClient
from app.services.onec.crypto import decrypt_password
from app.services.onec.exceptions import OneCError
from app.services.onec.odata_client import (
    ENTITY_COUNTERPARTIES,
    ENTITY_DOC_CORRECTION,
    ENTITY_DOC_OPZS,
    ENTITY_DOC_ORP,
    ENTITY_DOC_PTU,
    ENTITY_NOMENCLATURE,
    ENTITY_ORGANIZATIONS,
    ENTITY_WAREHOUSES,
    OneCODataClient,
)


# Тип объединения — формальная аннотация интерфейса. OneCComClient и
# OneCODataClient имеют одинаковый публичный API (metadata_catalogs,
# fetch_entity, iter_entity, count_entity, aclose, __aenter__/__aexit__),
# поэтому sync_service работает с любым из них.
OneCClient = OneCODataClient | OneCComClient

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

    async def _open_client(self, connection: OneCConnection) -> OneCClient:
        password = decrypt_password(connection.password_encrypted)
        mode = (connection.mode or "odata").lower()
        if mode == "com":
            # odata_url для COM хранит либо путь к файловой БД, либо ConnString.
            # Если задан простой путь — собираем ConnString автоматически.
            url = connection.odata_url.strip()
            if "=" not in url:
                conn_string = (
                    f'File="{url}";'
                    f'Usr="{connection.username}";'
                    f'Pwd="{password}";'
                )
            else:
                conn_string = url
            client = OneCComClient(conn_string)
            await client._ensure_started()  # noqa: SLF001 — выносим инициализацию из ленивого пути
            return client
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
        """Pull шапок документов БП ГИГ в AccountingDoc.

        Покрывает четыре ключевых типа для GIG Ledger:
        - ПТУ (поступление от поставщиков)
        - ОРП (отчёт о розничных продажах)
        - ОПЗС (отчёт производства за смену — общепит)
        - КорректировкаПоступления (возвраты/правки в БП 3.0)

        Идемпотентно: upsert по external_id = Ref_Key. Имена контрагента
        и организации подтягиваются из локальной БД по external_ref
        (по дизайну, сначала надо запустить sync_catalogs).
        Фильтр по checkpoint появится в следующем шаге — пока берём
        ограниченное окно от last_sync_at (если задано) или 100 свежих.
        """
        log = await self._start_log(connection, sync_type="documents")
        details: dict[str, Any] = {}
        try:
            async with await self._open_client(connection) as client:
                # Прежде чем грузить документы — построим карту GUID→имя из локальной БД.
                local_cp = await self._build_local_index(Counterparty, connection.company_id)
                local_org = await self._build_local_index(Organization, connection.company_id)
                # Для склада берём code (≤ 20 символов в БД), не name.
                local_wh = await self._build_local_index(Warehouse, connection.company_id, by="code")

                for entity, doc_type in [
                    (ENTITY_DOC_PTU,        "ПТУ"),
                    (ENTITY_DOC_ORP,        "ОРП"),
                    (ENTITY_DOC_OPZS,       "ОПЗС"),
                    (ENTITY_DOC_CORRECTION, "КорректировкаПоступления"),
                ]:
                    details[doc_type] = await self._sync_doc_type(
                        client=client,
                        connection=connection,
                        log=log,
                        entity=entity,
                        doc_type=doc_type,
                        local_cp=local_cp,
                        local_org=local_org,
                        local_wh=local_wh,
                    )
            await self._finish_log(log, "completed", details)
        except Exception as exc:
            await self._finish_log(log, "error", {"error": f"{type(exc).__name__}: {exc}", **details})
            raise
        return log

    async def _build_local_index(
        self, model: type, company_id: Any, *, by: str = "name"
    ) -> dict[str, str]:
        """{external_ref → attribute} для подстановки имени или кода."""
        rows = (await self.session.execute(
            select(model).where(
                model.company_id == company_id,
                model.external_ref.is_not(None),
            )
        )).scalars().all()
        return {r.external_ref: getattr(r, by) for r in rows if r.external_ref}

    async def _sync_doc_type(
        self,
        *,
        client: Any,
        connection: OneCConnection,
        log: OneCSyncLog,
        entity: str,
        doc_type: str,
        local_cp: dict[str, str],
        local_org: dict[str, str],
        local_wh: dict[str, str],
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}

        # Шапки документов БП 3.0 — поля заметно различаются между типами.
        # СуммаДокумента есть у ПТУ/ОРП/КП, нет у ОПЗС (производство).
        select_fields = ["Ref_Key", "DeletionMark", "Posted", "Number", "Date"]
        has_amount = entity in (ENTITY_DOC_PTU, ENTITY_DOC_ORP, ENTITY_DOC_CORRECTION)
        if has_amount:
            select_fields.append("СуммаДокумента")
        if entity in (ENTITY_DOC_PTU, ENTITY_DOC_CORRECTION):
            select_fields.append("Контрагент_Key")
        select_fields.append("Организация_Key")
        if entity in (ENTITY_DOC_PTU, ENTITY_DOC_ORP):
            select_fields.append("Склад_Key")

        filter_expr: str | None = None
        if connection.last_sync_at:
            ts = connection.last_sync_at.strftime("%Y-%m-%dT%H:%M:%S")
            filter_expr = f"Date ge datetime'{ts}'"

        async for item in client.iter_entity(entity, select=select_fields, filter_expr=filter_expr, orderby="Ref_Key", page_size=500):
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
                    select(AccountingDoc).where(
                        AccountingDoc.company_id == connection.company_id,
                        AccountingDoc.external_id == ref_key,
                    )
                )).scalar_one_or_none()

                cp_key = item.get("Контрагент_Key")
                org_key = item.get("Организация_Key")
                wh_key = item.get("Склад_Key")
                cp_name = local_cp.get(cp_key, "") if cp_key else ""
                org_name = local_org.get(org_key, "") if org_key else ""
                wh_code = (local_wh.get(wh_key, "") or "")[:20] if wh_key else None

                number = str(item.get("Number") or "").strip() or ref_key[:8]
                # AccountingDoc.date — VARCHAR(20). ISO-datetime занимает 25
                # символов, обрезаем до даты "YYYY-MM-DD" (10 символов).
                date_str = str(item.get("Date") or "").strip()[:10]
                amount = float(item.get("СуммаДокумента") or 0) if has_amount else 0.0
                status_1c = "Проведён" if item.get("Posted") else "Записан"

                if existing is None:
                    self.session.add(AccountingDoc(
                        id=uuid.uuid4(),
                        company_id=connection.company_id,
                        external_id=ref_key,
                        doc_type=doc_type,
                        number=number,
                        date=date_str,
                        counterparty_name=cp_name,
                        organization_name=org_name or None,
                        amount=amount,
                        status_1c=status_1c,
                        warehouse_code=wh_code,
                        lines=[],
                    ))
                    stats["created"] += 1
                else:
                    existing.number = number
                    existing.date = date_str
                    existing.counterparty_name = cp_name or existing.counterparty_name
                    existing.organization_name = org_name or existing.organization_name
                    existing.amount = amount
                    existing.status_1c = status_1c
                    if wh_code:
                        existing.warehouse_code = wh_code
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                logger.warning("Doc %s upsert failed (Ref_Key=%s): %s", doc_type, ref_key, exc)

        self._merge_log_stats(log, stats)
        return stats

    # ─── upsert по каждой сущности ──────────────────────────────────

    async def _sync_counterparties(
        self,
        client: OneCODataClient,
        connection: OneCConnection,
        log: OneCSyncLog,
    ) -> dict[str, int]:
        stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
        async for item in client.iter_entity(ENTITY_COUNTERPARTIES, select=COUNTERPARTY_SELECT, orderby="Ref_Key", page_size=500):
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
        async for item in client.iter_entity(ENTITY_ORGANIZATIONS, select=ORGANIZATION_SELECT, orderby="Ref_Key", page_size=500):
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
        async for item in client.iter_entity(ENTITY_WAREHOUSES, select=WAREHOUSE_SELECT, orderby="Ref_Key", page_size=500):
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
        async for item in client.iter_entity(ENTITY_NOMENCLATURE, select=NOMENCLATURE_SELECT, orderby="Ref_Key", page_size=500):
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
