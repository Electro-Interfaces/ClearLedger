from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select


class ReceiptValidationError(ValueError):
    pass


def parse_datetime(value: str | datetime | None, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ReceiptValidationError(f"{field}: нужна дата ISO") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _number(value, field: str, *, maximum: float = 1_000_000_000) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError(f"{field}: нужно число") from exc
    if not math.isfinite(result) or result < 0 or result > maximum:
        raise ReceiptValidationError(f"{field}: значение должно быть от 0 до {maximum:g}")
    return result


def _vat_from_gross(amount: float, rate) -> float | None:
    value = str(rate or "").casefold()
    if not value:
        return None
    if "без" in value or value in ("0", "ндс0"):
        return 0.0
    match = re.search(r"(\d+(?:[.,]\d+)?)", value)
    if match is None:
        return None
    percent = float(match.group(1).replace(",", "."))
    return round(amount * percent / (100 + percent), 2)


def normalize_lines(lines: list[dict] | None) -> list[dict]:
    if not isinstance(lines, list) or not lines:
        raise ReceiptValidationError("В документе нет позиций")
    result: list[dict] = []
    for index, source in enumerate(lines, 1):
        if not isinstance(source, dict):
            raise ReceiptValidationError(f"Строка {index}: неверный формат")
        line = dict(source)
        name = str(line.get("name") or "").strip()
        if not name:
            raise ReceiptValidationError(f"Строка {index}: укажите наименование")
        line["name"] = name[:500]
        for field in ("qty_expected", "qty_fact", "price", "vat_amount", "retail_price",
                      "markup", "pack_factor"):
            line[field] = _number(line.get(field), f"Строка {index}, {field}")
        line["qty_expected"] = round(line["qty_expected"], 3)
        line["qty_fact"] = round(line["qty_fact"], 3)
        line["price"] = round(line["price"], 4)
        line["amount"] = round(line["qty_fact"] * line["price"], 2)
        calculated_vat = _vat_from_gross(line["amount"], line.get("vat_rate"))
        line["vat_amount"] = (calculated_vat if calculated_vat is not None
                              else round(line["vat_amount"], 2))
        for field in ("upd_codes", "mark_codes", "pack_codes"):
            codes = line.get(field) or []
            if not isinstance(codes, list) or any(not str(code).strip() for code in codes):
                raise ReceiptValidationError(f"Строка {index}, {field}: неверный список кодов")
            line[field] = [str(code) for code in codes]
        result.append(line)
    return result


def normalize_services(services: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for index, source in enumerate(services or [], 1):
        if not isinstance(source, dict):
            raise ReceiptValidationError(f"Услуга {index}: неверный формат")
        service = dict(source)
        name = str(service.get("name") or "").strip()
        if not name:
            raise ReceiptValidationError(f"Услуга {index}: укажите наименование")
        service["name"] = name[:500]
        service["amount"] = round(_number(service.get("amount"), f"Услуга {index}, amount"), 2)
        source_vat = _number(service.get("vat_amount"), f"Услуга {index}, vat_amount")
        calculated_vat = _vat_from_gross(service["amount"], service.get("vat_rate"))
        service["vat_amount"] = (calculated_vat if calculated_vat is not None
                                 else round(source_vat, 2))
        result.append(service)
    return result


def _line_source_identity(line: dict, kind: str) -> str:
    explicit = next((str(line.get(field) or "").strip() for field in (
        "line_id", "Key", "Ключ", "ИдентификаторСтроки",
    ) if str(line.get(field) or "").strip()), "")
    if explicit:
        return f"source:{explicit}"
    if kind == "goods":
        parts = (
            line.get("nomenclature_ref"), line.get("barcode"),
            " ".join(str(line.get("name") or "").casefold().split()),
            line.get("unit"), line.get("series"), line.get("expiry"),
            line.get("purpose"),
        )
    else:
        parts = (
            line.get("key"),
            " ".join(str(line.get("name") or "").casefold().split()),
        )
    return "signature:" + json.dumps(
        parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def deterministic_line_id(receipt_id: uuid.UUID, kind: str, line: dict) -> uuid.UUID:
    if kind not in ("goods", "service"):
        raise ReceiptValidationError("Неизвестный вид строки приёмки")
    digest = hashlib.md5(
        f"{receipt_id}:{kind}:{_line_source_identity(line, kind)}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return uuid.UUID(digest)


def ensure_line_ids(
    receipt_id: uuid.UUID,
    lines: list[dict],
    services: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    seen: set[uuid.UUID] = set()

    def fill(rows: list[dict], kind: str) -> list[dict]:
        result = []
        identities: set[str] = set()
        for index, source in enumerate(rows):
            row = dict(source)
            raw = row.get("line_id")
            if raw:
                try:
                    line_id = uuid.UUID(str(raw))
                except ValueError as exc:
                    raise ReceiptValidationError(
                        f"Строка {kind} {index + 1}: line_id должен быть UUID"
                    ) from exc
            else:
                identity = _line_source_identity(row, kind)
                if identity in identities:
                    raise ReceiptValidationError(
                        "Неразличимые legacy-строки требуют ручного line_id"
                    )
                identities.add(identity)
                line_id = deterministic_line_id(receipt_id, kind, row)
            if line_id in seen:
                raise ReceiptValidationError("line_id строк приёмки должны быть уникальны")
            seen.add(line_id)
            row["line_id"] = str(line_id)
            result.append(row)
        return result

    return fill(lines, "goods"), fill(list(services or []), "service")


def assign_provisional_ambiguous_line_ids(
    receipt_id: uuid.UUID,
    lines: list[dict],
    services: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    def fill(rows: list[dict], kind: str) -> list[dict]:
        bases = [
            uuid.UUID(str(row["line_id"])) if row.get("line_id")
            else deterministic_line_id(receipt_id, kind, row)
            for row in rows
        ]
        counts = {value: bases.count(value) for value in set(bases)}
        occurrences: dict[uuid.UUID, int] = {}
        result = []
        for source, base in zip(rows, bases, strict=True):
            row = dict(source)
            if counts[base] > 1 and not row.get("line_id"):
                occurrence = occurrences.get(base, 0) + 1
                occurrences[base] = occurrence
                row["line_id"] = str(uuid.uuid5(
                    base, f"provisional-ambiguous:{occurrence}",
                ))
            else:
                row["line_id"] = str(base)
            result.append(row)
        return result

    return fill(lines, "goods"), fill(list(services or []), "service")


def assign_document_line_ids(
    lines: list[dict],
    services: list[dict] | None = None,
    *,
    existing_lines: list[dict] | None = None,
    existing_services: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    seen: set[uuid.UUID] = set()

    def assign(rows: list[dict], existing: list[dict], kind: str) -> list[dict]:
        previous: dict[str, list[uuid.UUID]] = {}
        for row in existing:
            if not row.get("line_id"):
                continue
            previous.setdefault(_line_source_identity(row, kind), []).append(
                uuid.UUID(str(row["line_id"])))
        result = []
        for source in rows:
            row = dict(source)
            raw = row.get("line_id")
            if raw:
                try:
                    line_id = uuid.UUID(str(raw))
                except ValueError as exc:
                    raise ReceiptValidationError("line_id должен быть UUID") from exc
            else:
                matches = previous.get(_line_source_identity(row, kind), [])
                available = [value for value in matches if value not in seen]
                if len(available) > 1:
                    raise ReceiptValidationError(
                        "Неразличимые строки требуют явного line_id"
                    )
                line_id = available[0] if available else uuid.uuid4()
            if line_id in seen:
                raise ReceiptValidationError("line_id строк приёмки должны быть уникальны")
            seen.add(line_id)
            row["line_id"] = str(line_id)
            result.append(row)
        return result

    return (
        assign(lines, list(existing_lines or []), "goods"),
        assign(list(services or []), list(existing_services or []), "service"),
    )


def totals(lines: list[dict], services: list[dict] | None = None) -> tuple[float, float]:
    total = round(
        sum(float(line.get("amount") or 0) for line in lines)
        + sum(float(service.get("amount") or 0) for service in services or []),
        2,
    )
    vat = round(
        sum(float(line.get("vat_amount") or 0) for line in lines)
        + sum(float(service.get("vat_amount") or 0) for service in services or []),
        2,
    )
    return total, vat


def require_basis(supplier, incoming_number, incoming_date) -> tuple[str, str, datetime]:
    supplier_value = str(supplier or "").strip()
    number_value = str(incoming_number or "").strip()
    parsed_date = parse_datetime(incoming_date, "Дата входящего документа")
    if not supplier_value:
        raise ReceiptValidationError("Укажите поставщика")
    if not number_value:
        raise ReceiptValidationError("Укажите номер входящего документа")
    if parsed_date is None:
        raise ReceiptValidationError("Укажите дату входящего документа")
    return supplier_value, number_value, parsed_date


def dedup_key(supplier, incoming_number, incoming_date) -> str | None:
    if not supplier or not incoming_number or not incoming_date:
        return None
    if isinstance(incoming_date, datetime):
        day = incoming_date.date()
    elif isinstance(incoming_date, date):
        day = incoming_date
    else:
        parsed = parse_datetime(str(incoming_date), "Дата входящего документа")
        day = parsed.date() if parsed else None
    if day is None:
        return None
    normalized = "\x1f".join((
        " ".join(str(supplier).casefold().split()),
        " ".join(str(incoming_number).casefold().split()),
        day.isoformat(),
    ))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def receipt_dedup_key(
    supplier_id, supplier_snapshot, incoming_number, incoming_date,
) -> str | None:
    identity = str(supplier_id) if supplier_id else supplier_snapshot
    return dedup_key(identity, incoming_number, incoming_date)


def allocation_identity(receipt_id: uuid.UUID, station_id: int, lines: list[dict]) -> tuple[str, str]:
    canonical = json.dumps(
        {"station_id": station_id, "lines": sorted(
            lines, key=lambda item: str(item.get("line_id") or item.get("line_index")),
        )},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(receipt_id, digest)), digest


def duplicate_plan(rows) -> list[dict]:
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        evidence = row.evidence or {}
        keys: set[tuple[str, str]] = set()
        document_id = str(evidence.get("document_id") or "").strip()
        if document_id:
            keys.add(("document_id", document_id))
        if row.source_uuid:
            keys.add(("source_uuid", str(row.source_uuid)))
        business_key = row.dedup_key or receipt_dedup_key(
            getattr(row, "supplier_id", None), getattr(row, "supplier", None),
            getattr(row, "incoming_number", None), getattr(row, "incoming_date", None))
        if business_key:
            keys.add(("business_key", str(business_key)))
        for key in keys:
            groups.setdefault(key, []).append(row)

    pairs: dict[tuple[str, str], dict] = {}
    for (reason, value), candidates in groups.items():
        unique = {str(row.id): row for row in candidates}
        if len(unique) < 2:
            continue
        ids = sorted(unique)
        pair_key = (ids[0], ids[-1])
        plan = pairs.setdefault(pair_key, {
            "receipt_ids": ids,
            "reasons": [],
            "statuses": {rid: unique[rid].status for rid in ids},
            "action": "manual_review",
        })
        plan["reasons"].append({"kind": reason, "value": value})
        accepted = [rid for rid in ids if unique[rid].status == "accepted"]
        if len(accepted) == 1:
            plan["suggested_keep_id"] = accepted[0]
    return sorted(pairs.values(), key=lambda item: item["receipt_ids"])


def movement_item_key(line: dict, index: int) -> str:
    return str(
        line.get("nomenclature_ref") or line.get("barcode")
        or " ".join(str(line.get("name") or "").casefold().split()) or f"line:{index}"
    )[:200]


async def record_acceptance(db, row, user_id=None) -> None:
    from app.models import StoreReceiptStockMovement

    movements = (await db.execute(select(StoreReceiptStockMovement).where(
        StoreReceiptStockMovement.company_id == row.company_id,
        StoreReceiptStockMovement.receipt_id == row.id,
    ))).scalars().all()
    existing_keys = {
        item if isinstance(item, str) else item.idempotency_key for item in movements
    }
    existing_lines = {
        str(item.line_id) for item in movements
        if not isinstance(item, str) and item.kind == "receipt_acceptance" and item.line_id
    }
    legacy_indexes = {
        item.line_index for item in movements
        if not isinstance(item, str) and item.kind == "receipt_acceptance"
    }
    station_id = row.station_id if row.delivery_scheme == "supplier_to_station" else None
    warehouse = str(
        row.receiving_warehouse
        or (row.evidence or {}).get("warehouse_id")
        or (f"station:{station_id}" if station_id is not None else "central")
    )[:200]
    accepted_lines = [(index, line) for index, line in enumerate(row.lines or [])
                      if float(line.get("qty_fact") or 0) > 0]
    goods_total = sum(float(line.get("qty_fact") or 0) * float(line.get("price") or 0)
                      for _, line in accepted_lines)
    into_cost_total = sum(float(service.get("amount") or 0)
                          for service in getattr(row, "services", None) or []
                          if service.get("into_cost"))
    allocated = 0.0
    for position, (index, line) in enumerate(accepted_lines):
        line_id = uuid.UUID(str(line.get("line_id") or deterministic_line_id(
            row.id, "goods", line)))
        quantity = float(line.get("qty_fact") or 0)
        price = float(line.get("price") or 0)
        base_amount = round(quantity * price, 2)
        if goods_total > 0 and into_cost_total > 0:
            if position == len(accepted_lines) - 1:
                service_share = round(into_cost_total - allocated, 2)
            else:
                service_share = round(into_cost_total * base_amount / goods_total, 2)
                allocated += service_share
        else:
            service_share = 0.0
        movement_amount = round(base_amount + service_share, 2)
        key = f"receipt:{row.id}:accept:{line_id}"
        legacy_key = f"receipt:{row.id}:accept:{index}"
        if (key in existing_keys or legacy_key in existing_keys
                or str(line_id) in existing_lines or index in legacy_indexes):
            continue
        db.add(StoreReceiptStockMovement(
            company_id=row.company_id, receipt_id=row.id, line_id=line_id,
            line_index=index, station_id=station_id,
            warehouse_id=getattr(row, "warehouse_id", None), warehouse=warehouse,
            item_key=movement_item_key(line, index),
            item_uuid=str(line.get("nomenclature_ref") or "") or None,
            barcode=str(line.get("barcode") or "") or None,
            quantity=quantity, unit_cost=round(movement_amount / quantity, 4),
            amount=movement_amount,
            kind="receipt_acceptance", idempotency_key=key, created_by=user_id,
        ))
