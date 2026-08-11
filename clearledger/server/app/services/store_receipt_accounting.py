from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingSourceLink,
    Contract,
    ContractLocation,
    Counterparty,
    DataEntry,
    Organization,
    ServiceLocation,
    StoreReceipt,
    Warehouse,
)
from app.services.accounting_outbox import append_canonical_fact
from app.services.store_receipts import ReceiptValidationError, ensure_line_ids


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)
_ORIGIN_MAP = {
    "station": "edge",
    "center": "store",
    "edo": "edo",
}


class ReceiptAccountingError(ValueError):
    pass


@dataclass(frozen=True)
class ReceiptReadiness:
    ready: bool
    errors: tuple[str, ...]
    document: dict | None = None
    snapshots: dict | None = None
    content_hash: str | None = None


def _snapshot_supplier(row: Counterparty) -> dict:
    return {
        "id": str(row.id), "external_ref": row.external_ref,
        "inn": row.inn, "kpp": row.kpp, "ogrn": row.ogrn,
        "name": row.name, "short_name": row.short_name,
        "full_name": row.full_name, "legal_address": row.legal_address,
        "actual_address": row.actual_address,
        "postal_address": (row.raw or {}).get("postal_address") if row.raw else None,
        "phone": row.phone, "email": row.email,
        "bank_account": row.bank_account, "bank_bik": row.bank_bik,
        "bank_name": row.bank_name,
        "lifecycle_status": row.lifecycle_status,
    }


def _snapshot_contract(row: Contract) -> dict:
    return {
        "id": str(row.id), "external_ref": row.external_ref,
        "number": row.number, "date": row.date,
        "counterparty_id": row.counterparty_id,
        "organization_id": row.organization_id,
        "type": row.type, "kind": row.kind, "currency": row.currency,
        "valid_until": row.valid_until, "is_closed": bool(row.is_closed),
        "scope_type": row.scope_type,
    }


def _snapshot_organization(row: Organization) -> dict:
    return {
        "id": str(row.id), "external_ref": row.external_ref,
        "inn": row.inn, "kpp": row.kpp, "ogrn": row.ogrn,
        "name": row.name, "full_name": row.full_name,
        "legal_address": row.legal_address,
        "actual_address": row.actual_address,
        "postal_address": row.postal_address,
        "bank_account": row.bank_account, "bank_bik": row.bank_bik,
    }


def _snapshot_warehouse(row: Warehouse) -> dict:
    return {
        "id": str(row.id), "external_ref": row.external_ref,
        "code": row.code, "name": row.name,
        "address": row.address, "type": row.type,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "station_id": row.station_id,
    }


def _canonical_hash(document: dict) -> str:
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _contract_owner_keys(row) -> set[str]:
    result = {str(row.id)}
    if row.external_ref:
        result.add(str(row.external_ref))
    return result


def _parse_valid_until(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _money(value, label: str, errors: list[str]) -> Decimal:
    try:
        result = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label}: неверная денежная сумма")
        return Decimal("0.00")
    if not result.is_finite() or result < 0:
        errors.append(f"{label}: сумма должна быть конечной и неотрицательной")
        return Decimal("0.00")
    return result.quantize(Decimal("0.01"))


def _number(value, label: str, errors: list[str]) -> Decimal:
    try:
        result = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label}: неверное число")
        return Decimal("0")
    if not result.is_finite() or result < 0:
        errors.append(f"{label}: значение должно быть конечным и неотрицательным")
        return Decimal("0")
    return result


def _vat_percent(value) -> Decimal | None:
    rate = str(value or "").casefold().replace(" ", "")
    if "безндс" in rate:
        return Decimal("0")
    match = re.fullmatch(r"(?:ндс)?(0|10|20|22)(?:[.,]0+)?%?", rate)
    return Decimal(match.group(1)) if match else None


def _strict_document_values(
    receipt: StoreReceipt,
    lines: list[dict],
    services: list[dict],
    errors: list[str],
) -> dict:
    vat_included = (receipt.evidence or {}).get("vat_included")
    for index, row in enumerate(lines, 1):
        _number(row.get("qty_expected"), f"Товар {index}, количество по документу", errors)
        qty_fact = _number(
            row.get("qty_fact"), f"Товар {index}, принятое количество", errors)
        price = _number(row.get("price"), f"Товар {index}, цена", errors)
        amount = _money(row.get("amount"), f"Товар {index}, сумма", errors)
        vat_amount = _money(row.get("vat_amount"), f"Товар {index}, НДС", errors)
        expected_amount = (qty_fact * price).quantize(Decimal("0.01"))
        if amount != expected_amount:
            errors.append(f"Товар {index}: сумма не равна количеству × цене")
        percent = _vat_percent(row.get("vat_rate"))
        if percent is None:
            errors.append(f"Товар {index}: неизвестная ставка НДС")
        elif isinstance(vat_included, bool):
            divisor = Decimal("100") + percent if vat_included else Decimal("100")
            expected_vat = (
                Decimal("0.00") if percent == 0
                else (amount * percent / divisor).quantize(Decimal("0.01"))
            )
            if vat_amount != expected_vat:
                errors.append(f"Товар {index}: сумма НДС не соответствует ставке")
    for index, row in enumerate(services, 1):
        amount = _money(row.get("amount"), f"Услуга {index}, сумма", errors)
        vat_amount = _money(row.get("vat_amount"), f"Услуга {index}, НДС", errors)
        percent = _vat_percent(row.get("vat_rate"))
        if percent is None:
            errors.append(f"Услуга {index}: неизвестная ставка НДС")
        elif isinstance(vat_included, bool):
            divisor = Decimal("100") + percent if vat_included else Decimal("100")
            expected_vat = (
                Decimal("0.00") if percent == 0
                else (amount * percent / divisor).quantize(Decimal("0.01"))
            )
            if vat_amount != expected_vat:
                errors.append(f"Услуга {index}: сумма НДС не соответствует ставке")

    goods_total = sum((_money(row.get("amount"), "Товар", errors) for row in lines),
                      Decimal("0.00"))
    services_total = sum((_money(row.get("amount"), "Услуга", errors) for row in services),
                         Decimal("0.00"))
    vat_total = sum(
        (_money(row.get("vat_amount"), "НДС строки", errors) for row in [*lines, *services]),
        Decimal("0.00"),
    )
    document_total = goods_total + services_total
    stored_total = _money(receipt.total_amount, "Итог документа", errors)
    stored_vat = _money(receipt.vat_amount, "Итог НДС", errors)
    if stored_total != document_total:
        errors.append("Итог документа не совпадает с товарными и сервисными строками")
    if stored_vat != vat_total:
        errors.append("Итог НДС не совпадает с НДС строк")

    evidence = receipt.evidence or {}
    declared = {
        "declared_goods_total": goods_total,
        "declared_services_total": services_total,
        "declared_vat_total": vat_total,
        "declared_total": document_total,
    }
    for field, expected in declared.items():
        if evidence.get(field) is not None:
            actual = _money(evidence[field], field, errors)
            if actual != expected:
                errors.append(f"Контрольный итог {field} не совпадает")

    currency = str(evidence.get("currency") or "").strip().upper()
    if not currency:
        errors.append("Не указана валюта документа")
    vat_included = evidence.get("vat_included")
    if not isinstance(vat_included, bool):
        errors.append("Не указан режим включения НДС")
    invoice_kind = str(evidence.get("invoice_kind") or "").strip()
    invoice_number = str(evidence.get("invoice_number") or "").strip()
    invoice_date = str(evidence.get("invoice_date") or "").strip()
    if not invoice_kind:
        errors.append("Не указан вид УПД/счёта-фактуры")
    if invoice_kind and (not invoice_number or not invoice_date):
        errors.append("Не заполнены номер и дата УПД/счёта-фактуры")

    # Приёмник БП (TradeLedger) сейчас не заполняет ТЧ «Услуги» поступления и не
    # создаёт «Поступление доп. расходов». Отдать такой документ готовым значит
    # получить в БП поступление на сумму товаров при СуммаДокумента с услугами —
    # расхождение всплывёт только в сверке, уже после проведения. До появления
    # механизма в приёмнике группа блокируется целиком (phase4 §7 п.8).
    if services:
        errors.append(
            "Приёмник БП пока не переносит услуги поступления и не создаёт "
            "«Поступление доп. расходов» — документ с услугами не выгружается"
        )

    return {
        "currency": currency,
        "vat_included": vat_included,
        "vat_deductible": evidence.get("vat_deductible"),
        "invoice_kind": invoice_kind,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "control_totals": {
            "goods": float(goods_total),
            "services": float(services_total),
            "vat": float(vat_total),
            "document": float(document_total),
        },
    }


async def _contract_covers_receipt(
    session: AsyncSession, receipt: StoreReceipt, contract: Contract, *, lock: bool = False,
) -> bool:
    if contract.scope_type == "company":
        return True
    if contract.scope_type != "locations" or receipt.station_id is None:
        return False
    statement = select(ContractLocation.id).join(
            ServiceLocation, ServiceLocation.id == ContractLocation.location_id,
        ).where(
            ContractLocation.company_id == receipt.company_id,
            ContractLocation.contract_id == contract.id,
            ServiceLocation.company_id == receipt.company_id,
            ServiceLocation.code == str(receipt.station_id),
        ).limit(1)
    if lock:
        statement = statement.with_for_update()
    location = (await session.execute(statement)).scalar_one_or_none()
    return location is not None


async def assess_receipt(
    session: AsyncSession, receipt: StoreReceipt, *, lock: bool = False,
) -> ReceiptReadiness:
    errors: list[str] = []
    if receipt.origin not in _ORIGIN_MAP:
        errors.append("Неизвестный источник приёмки")
    if receipt.status != "accepted":
        errors.append("Приёмка ещё не принята")
    for field, label in (
        (receipt.supplier_id, "поставщик"),
        (receipt.contract_id, "договор"),
        (receipt.organization_id, "организация"),
        (receipt.warehouse_id, "склад"),
    ):
        if field is None:
            errors.append(f"Не выбран канонический {label}")
    if not receipt.incoming_number or receipt.incoming_date is None:
        errors.append("Не заполнены номер и дата входящего документа")
    if (receipt.evidence or {}).get("line_identity_needs_review"):
        errors.append("Не подтверждены постоянные line_id строк приёмки")
    if (receipt.evidence or {}).get("manual_candidate_ids"):
        errors.append("Не разрешено совпадение с другим документом приёмки")

    supplier = contract = organization = warehouse = None
    if receipt.supplier_id:
        statement = select(Counterparty).where(
            Counterparty.id == receipt.supplier_id,
            Counterparty.company_id == receipt.company_id,
            Counterparty.kind == "external",
        )
        supplier = (await session.execute(
            statement.with_for_update() if lock else statement
        )).scalar_one_or_none()
        if supplier is None:
            errors.append("Поставщик не принадлежит компании")
        elif supplier.lifecycle_status != "verified":
            errors.append("Поставщик не имеет статус verified")
    if receipt.contract_id:
        statement = select(Contract).where(
            Contract.id == receipt.contract_id,
            Contract.company_id == receipt.company_id,
        )
        contract = (await session.execute(
            statement.with_for_update() if lock else statement
        )).scalar_one_or_none()
        if contract is None:
            errors.append("Договор не принадлежит компании")
    if receipt.organization_id:
        statement = select(Organization).where(
            Organization.id == receipt.organization_id,
            Organization.company_id == receipt.company_id,
        )
        organization = (await session.execute(
            statement.with_for_update() if lock else statement
        )).scalar_one_or_none()
        if organization is None:
            errors.append("Организация не принадлежит компании")
    if receipt.warehouse_id:
        statement = select(Warehouse).where(
            Warehouse.id == receipt.warehouse_id,
            Warehouse.company_id == receipt.company_id,
        )
        warehouse = (await session.execute(
            statement.with_for_update() if lock else statement
        )).scalar_one_or_none()
        if warehouse is None:
            errors.append("Склад не принадлежит компании")

    for row, label in (
        (supplier, "поставщика"), (contract, "договора"),
        (organization, "организации"), (warehouse, "склада"),
    ):
        if row is not None and not str(row.external_ref or "").strip():
            errors.append(f"Не подтверждена ссылка БП для {label}")

    if supplier is not None and contract is not None:
        if str(contract.counterparty_id) not in _contract_owner_keys(supplier):
            errors.append("Договор принадлежит другому поставщику")
        kind = str(contract.kind or contract.type or "").casefold().replace(" ", "")
        if "споставщик" not in kind:
            errors.append("Договор не имеет вид «С поставщиком»")
        if contract.is_closed:
            errors.append("Договор закрыт")
        valid_until = _parse_valid_until(contract.valid_until)
        if contract.valid_until and valid_until is None:
            errors.append("Срок договора имеет неверный формат")
        if valid_until and valid_until < receipt.doc_date.date():
            errors.append("Срок договора истёк на дату приёмки")
        if not await _contract_covers_receipt(session, receipt, contract, lock=lock):
            errors.append("Договор не покрывает станцию приёмки")
    if organization is not None and contract is not None:
        if str(contract.organization_id) not in _contract_owner_keys(organization):
            errors.append("Организация приёмки не совпадает с договором")
    if warehouse is not None and organization is not None:
        if warehouse.organization_id != organization.id:
            errors.append("Склад не принадлежит организации приёмки")
        if receipt.delivery_scheme == "supplier_to_station":
            if receipt.station_id is None or warehouse.station_id != receipt.station_id:
                errors.append("Склад не привязан к станции приёмки")
        elif warehouse.station_id is not None:
            errors.append("Центральный склад не должен быть привязан к станции")

    try:
        lines, services = ensure_line_ids(
            receipt.id, copy.deepcopy(receipt.lines or []),
            copy.deepcopy(receipt.services or []),
        )
    except ReceiptValidationError as exc:
        errors.append(str(exc))
        lines, services = [], []
    if not lines:
        errors.append("В приёмке нет товарных строк")
    strict_values = _strict_document_values(receipt, lines, services, errors)

    if errors:
        return ReceiptReadiness(False, tuple(dict.fromkeys(errors)))

    snapshots = {
        "supplier": _snapshot_supplier(supplier),
        "contract": _snapshot_contract(contract),
        "organization": _snapshot_organization(organization),
        "warehouse": _snapshot_warehouse(warehouse),
    }
    document = {
        "Тип": "purchase",
        "document_id": str(receipt.id),
        "ИсточникUUID": str(receipt.id),
        "Дата": receipt.doc_date.isoformat(),
        "Номер": receipt.number,
        "organization_id": str(receipt.organization_id),
        "supplier_id": str(receipt.supplier_id),
        "contract_id": str(receipt.contract_id),
        "warehouse_id": str(receipt.warehouse_id),
        "station_id": receipt.station_id,
        "НомерВходящегоДокумента": receipt.incoming_number,
        "ДатаВходящегоДокумента": receipt.incoming_date.isoformat(),
        "Товары": lines,
        "Услуги": services,
        "СуммаДокумента": float(receipt.total_amount or 0),
        "СуммаНДС": float(receipt.vat_amount or 0),
        "ВалютаДокумента": strict_values["currency"],
        "СуммаВключаетНДС": strict_values["vat_included"],
        "НДСКВычету": strict_values["vat_deductible"],
        "ВидДокументаНДС": strict_values["invoice_kind"],
        "НомерСчетаФактуры": strict_values["invoice_number"],
        "ДатаСчетаФактуры": strict_values["invoice_date"],
        "КонтрольныеИтоги": strict_values["control_totals"],
        "Снимки": snapshots,
        "evidence": copy.deepcopy(receipt.evidence or {}),
    }
    return ReceiptReadiness(
        True, (), document, snapshots, _canonical_hash(document),
    )


def mark_needs_review(receipt: StoreReceipt, errors: list[str] | tuple[str, ...]) -> None:
    receipt.accounting_status = "needs_review"
    receipt.accounting_error = "; ".join(dict.fromkeys(str(item) for item in errors))[:4000]


async def link_receipt_canonical_refs(
    session: AsyncSession,
    company_id: uuid.UUID,
    receipt_id: uuid.UUID,
    *,
    supplier_id: uuid.UUID,
    contract_id: uuid.UUID,
    organization_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    confirmed_by: uuid.UUID,
    expected_version: int | None = None,
    note: str | None = None,
) -> StoreReceipt:
    await session.execute(_RECEIPT_LOCK, {
        "scope_key": f"store-receipt-accounting:{company_id}:{receipt_id}",
    })
    receipt = (await session.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id,
        StoreReceipt.company_id == company_id,
    ).with_for_update())).scalar_one_or_none()
    if receipt is None:
        raise ReceiptAccountingError("Приёмка не найдена")
    if receipt.status != "accepted":
        raise ReceiptAccountingError("Позднее связывание разрешено только принятой приёмке")
    if expected_version is not None and int(receipt.version or 0) != expected_version:
        raise ReceiptAccountingError("Документ изменён другим пользователем; обновите данные")

    async def exact(model, value):
        return (await session.execute(select(model).where(
            model.id == value, model.company_id == company_id,
        ).with_for_update())).scalar_one_or_none()

    supplier = await exact(Counterparty, supplier_id)
    contract = await exact(Contract, contract_id)
    organization = await exact(Organization, organization_id)
    warehouse = await exact(Warehouse, warehouse_id)
    if supplier is None or supplier.kind != "external":
        raise ReceiptAccountingError("Поставщик не найден в компании")
    if contract is None or organization is None or warehouse is None:
        raise ReceiptAccountingError("Договор, организация или склад не найдены в компании")
    if str(contract.counterparty_id) not in _contract_owner_keys(supplier):
        raise ReceiptAccountingError("Договор принадлежит другому поставщику")
    if str(contract.organization_id) not in _contract_owner_keys(organization):
        raise ReceiptAccountingError("Договор принадлежит другой организации")
    if warehouse.organization_id != organization.id:
        raise ReceiptAccountingError("Склад принадлежит другой организации")
    if receipt.delivery_scheme == "supplier_to_station":
        if receipt.station_id is None or warehouse.station_id != receipt.station_id:
            raise ReceiptAccountingError("Склад не привязан к станции приёмки")
    elif warehouse.station_id is not None:
        raise ReceiptAccountingError("Для центральной приёмки нужен центральный склад")

    receipt.supplier_id = supplier.id
    receipt.contract_id = contract.id
    receipt.organization_id = organization.id
    receipt.warehouse_id = warehouse.id
    receipt.version = int(receipt.version or 0) + 1
    await session.flush()
    return await canonicalize_receipt(
        session, company_id, receipt_id, confirmed_by, note,
    )


async def canonicalize_receipt(
    session: AsyncSession,
    company_id: uuid.UUID,
    receipt_id: uuid.UUID,
    confirmed_by: uuid.UUID,
    note: str | None = None,
) -> StoreReceipt:
    await session.execute(_RECEIPT_LOCK, {
        "scope_key": f"store-receipt-accounting:{company_id}:{receipt_id}",
    })
    receipt = (await session.execute(select(StoreReceipt).where(
        StoreReceipt.id == receipt_id,
        StoreReceipt.company_id == company_id,
    ).with_for_update())).scalar_one_or_none()
    if receipt is None:
        raise ReceiptAccountingError("Приёмка не найдена")

    readiness = await assess_receipt(session, receipt, lock=True)
    if not readiness.ready:
        mark_needs_review(receipt, readiness.errors)
        await session.flush()
        raise ReceiptAccountingError(receipt.accounting_error or "Приёмка не готова")

    links = (await session.execute(select(AccountingSourceLink).where(
        AccountingSourceLink.company_id == company_id,
        AccountingSourceLink.projection_source == _ORIGIN_MAP[receipt.origin],
        AccountingSourceLink.source_kind == "purchase",
        AccountingSourceLink.source_document_id == receipt.id,
    ).with_for_update())).scalars().all()
    if len(links) > 1 or (links and links[0].canonical_document_id != receipt.id):
        mark_needs_review(receipt, ["Неоднозначная связь исходного документа"])
        await session.flush()
        raise ReceiptAccountingError(receipt.accounting_error)

    existing = (await session.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.document_id == receipt.id,
    ).order_by(DataEntry.revision.desc()).with_for_update())).scalars().all()
    same = next((row for row in existing if row.content_hash == readiness.content_hash), None)
    revision = same.revision if same is not None else ((existing[0].revision or 0) + 1 if existing else 1)
    if same is None:
        document = {**readiness.document, "revision": revision,
                    "content_hash": readiness.content_hash}
        entry = DataEntry(
            id=uuid.uuid4(), company_id=company_id,
            title=f"Поступление {receipt.number}",
            category_id="store", subcategory_id="purchase", doc_type_id="purchase",
            status="verified", source=_ORIGIN_MAP[receipt.origin],
            source_label="Приёмка магазина", source_id=str(receipt.id),
            layer="clean", meta={
                "document": document,
                "snapshots": copy.deepcopy(readiness.snapshots),
                "evidence": copy.deepcopy(receipt.evidence or {}),
            },
        )
        result = await append_canonical_fact(
            session, entry, document_id=receipt.id, revision=revision,
            content_hash=readiness.content_hash,
            fact_origin=_ORIGIN_MAP[receipt.origin],
        )
        same = result.row

    if not links:
        session.add(AccountingSourceLink(
            id=uuid.uuid4(), company_id=company_id,
            projection_source=_ORIGIN_MAP[receipt.origin],
            source_kind="purchase", source_document_id=receipt.id,
            canonical_document_id=receipt.id, confirmed_by=confirmed_by,
            confirmed_at=datetime.now(timezone.utc), note=note,
        ))

    receipt.supplier_snapshot = copy.deepcopy(readiness.snapshots["supplier"])
    receipt.contract_snapshot = copy.deepcopy(readiness.snapshots["contract"])
    receipt.organization_snapshot = copy.deepcopy(readiness.snapshots["organization"])
    receipt.warehouse_snapshot = copy.deepcopy(readiness.snapshots["warehouse"])
    receipt.accounting_status = "ready"
    receipt.accounting_error = None
    receipt.accounting_revision = int(revision)
    receipt.content_hash = readiness.content_hash
    await session.flush()
    return receipt


async def assert_purchase_documents_ready(
    session: AsyncSession, company_id: uuid.UUID, packet: dict,
) -> None:
    for index, document in enumerate(packet.get("Документы") or []):
        if str(document.get("Тип") or "") != "purchase":
            continue
        try:
            document_id = uuid.UUID(str(document.get("document_id") or ""))
            revision = int(document.get("revision"))
        except (TypeError, ValueError) as exc:
            raise ReceiptAccountingError(
                f"purchase[{index}] не содержит exact document_id/revision"
            ) from exc
        content_hash = str(document.get("content_hash") or "").lower()
        if revision <= 0 or not _HASH_RE.fullmatch(content_hash):
            raise ReceiptAccountingError(
                f"purchase[{index}] не содержит exact revision/content_hash"
            )
        await session.execute(_RECEIPT_LOCK, {
            "scope_key": f"store-receipt-accounting:{company_id}:{document_id}",
        })
        receipt = (await session.execute(select(StoreReceipt).where(
            StoreReceipt.id == document_id,
            StoreReceipt.company_id == company_id,
        ).with_for_update())).scalar_one_or_none()
        if receipt is None:
            raise ReceiptAccountingError(f"purchase[{index}] не найден в StoreReceipt")
        if (receipt.accounting_status != "ready"
                or receipt.accounting_revision != revision
                or receipt.content_hash != content_hash):
            raise ReceiptAccountingError(
                f"purchase[{index}] не имеет exact ready accounting revision"
            )
        live = await assess_receipt(session, receipt, lock=True)
        if not live.ready or live.content_hash != content_hash:
            raise ReceiptAccountingError(
                f"purchase[{index}] live НСИ/snapshot больше не соответствует ready revision"
            )
        entry = (await session.execute(select(DataEntry).where(
            DataEntry.company_id == company_id,
            DataEntry.document_id == document_id,
            DataEntry.revision == revision,
            DataEntry.content_hash == content_hash,
        ).with_for_update())).scalar_one_or_none()
        link = (await session.execute(select(AccountingSourceLink).where(
            AccountingSourceLink.company_id == company_id,
            AccountingSourceLink.source_kind == "purchase",
            AccountingSourceLink.source_document_id == document_id,
            AccountingSourceLink.canonical_document_id == document_id,
        ).with_for_update())).scalar_one_or_none()
        if entry is None or entry.status != "verified" or link is None:
            raise ReceiptAccountingError(
                f"purchase[{index}] не подтверждён canonical fact/source link"
            )
