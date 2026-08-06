"""Изолированный по компании остаток собственного учёта станции."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreStockBalance


def _stock_doc(payload: dict) -> dict | None:
    for doc in payload.get("Документы") or []:
        if isinstance(doc, dict) and doc.get("Тип") == "stock_snapshot":
            return doc
    return None


def _moment(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def normalize_snapshot(payload: dict, station_id: int) -> tuple[str, datetime, list[dict]]:
    doc = _stock_doc(payload)
    if doc is None:
        return "", datetime.now(timezone.utc), []
    source = str(doc.get("ИсточникУчета") or "legacy_snapshot")
    taken_at = _moment(doc.get("Момент"))
    grouped: dict[tuple[str, str], dict] = {}
    for raw in doc.get("Учет") or []:
        if not isinstance(raw, dict):
            continue
        item_uuid = str(raw.get("Номенклатура") or "").strip()
        barcode = str(raw.get("ШтрихКод") or "").strip()
        if not item_uuid and not barcode:
            continue
        place = str(raw.get("Место") or station_id).strip()
        identity = item_uuid + "|" + barcode
        key = (place, hashlib.sha256(identity.encode("utf-8")).hexdigest())
        try:
            qty = Decimal(str(raw.get("Остаток") or 0))
            price = Decimal(str(raw.get("Цена"))) if raw.get("Цена") is not None else None
            cost = (Decimal(str(raw.get("Себестоимость")))
                    if raw.get("Себестоимость") is not None else None)
            cost_known = Decimal(str(raw.get("СебестоимостьПокрытие") or 0))
        except InvalidOperation:
            continue
        row = grouped.setdefault(key, {
            "place": place,
            "place_name": str(raw.get("МестоНаименование") or "").strip(),
            "balance_key": key[1],
            "item_uuid": item_uuid,
            "barcode": barcode,
            "name": str(raw.get("Наименование") or "").strip(),
            "quantity": Decimal("0"),
            "retail_price": price if price is not None and price >= 0 else None,
            "cost_unit": cost if cost is not None and cost >= 0 else None,
            "cost_known_pct": max(Decimal("0"), min(Decimal("100"), cost_known)),
        })
        row["quantity"] += qty
        if price is not None and price >= 0:
            row["retail_price"] = price
        if cost is not None and cost >= 0:
            row["cost_unit"] = cost
            row["cost_known_pct"] = max(Decimal("0"), min(Decimal("100"), cost_known))
    return source, taken_at, list(grouped.values())


async def sync_from_snapshot(db: AsyncSession, company_id, station_id: int,
                             payload: dict) -> dict:
    source, taken_at, rows = normalize_snapshot(payload, station_id)
    if not source:
        return {"skipped": "в пакете нет снимка"}
    if source != "edge_ledger":
        return {"skipped": f"источник учёта {source} не является журналом агента"}

    await db.execute(delete(StoreStockBalance).where(
        StoreStockBalance.company_id == company_id,
        StoreStockBalance.station_id == station_id,
    ))
    for row in rows:
        db.add(StoreStockBalance(
            company_id=company_id,
            station_id=station_id,
            source=source,
            snapshot_at=taken_at,
            **row,
        ))
    await db.flush()
    return {"stock_rows": len(rows), "source": source,
            "snapshot_at": taken_at.isoformat()}
