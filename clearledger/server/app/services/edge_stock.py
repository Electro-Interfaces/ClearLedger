"""Изолированный по компании остаток собственного учёта станции."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StoreStockBalance

log = logging.getLogger(__name__)


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

    # Вторая проекция того же остатка — edge.stock.
    #
    # Она осталась от домультитенантных времён и живёт по (место, штрихкод):
    # по ней ходят карточка товара и выборки «Магазина». Раньше её заполнял
    # ВТОРОЙ приёмник со своей арифметикой, и два экрана центра показывали
    # разные цифры про одну станцию (13 883 против 8 384) — понять, какая
    # правда, было нельзя. Теперь источник один: считаем здесь, пишем обе
    # проекции.
    проекция = await записать_проекцию_по_штрихкодам(db, station_id, rows)

    return {"stock_rows": len(rows), "source": source,
            "snapshot_at": taken_at.isoformat(), **проекция}


def разложить_по_штрихкодам(rows: list[dict], station_id: int
                            ) -> tuple[dict[tuple[str, str], float], list[str]]:
    """Свести остаток по паре (место, штрихкод).

    Строки без штрихкода относим на штрихкод ТОЙ ЖЕ карточки в том же месте:
    без кода приходит списание сырья общепита, такие строки почти всегда
    минусовые, и потерять их значит показать товар, которого нет — на 208 это
    22 строки на −5 500 единиц при реальном остатке 8 611. Карточка без единого
    кода в этом месте уходит в потери — с именем, а не молча.

    Чистая функция без базы: арифметика остатка обязана проверяться отдельно от
    того, куда её потом записали.
    """
    qty_by_key: dict[tuple[str, str], float] = {}
    шк_карточки: dict[tuple[str, str], str] = {}
    без_кода: list[tuple[str, str, float, str]] = []

    for r in rows:
        место = str(r.get("place") or station_id)
        code = str(r.get("barcode") or "").strip()
        карточка = str(r.get("item_uuid") or "")
        qty = float(r.get("quantity") or 0)
        if code:
            qty_by_key[(место, code)] = qty_by_key.get((место, code), 0.0) + qty
            шк_карточки.setdefault((место, карточка), code)
            continue
        без_кода.append((место, карточка, qty, str(r.get("name") or "")))

    потеряно: list[str] = []
    for место, карточка, qty, имя in без_кода:
        code = шк_карточки.get((место, карточка))
        if code is None:
            потеряно.append(f"{имя or карточка} ({место}, {qty:g})")
            continue
        qty_by_key[(место, code)] = qty_by_key.get((место, code), 0.0) + qty

    return qty_by_key, потеряно


async def записать_проекцию_по_штрихкодам(db: AsyncSession, station_id: int,
                                          rows: list[dict]) -> dict:
    """Записать проекцию остатка по штрихкодам в edge.stock."""
    qty_by_key, потеряно = разложить_по_штрихкодам(rows, station_id)

    # Снимок — полная картина места, а не список изменений: строка, которой в
    # нём нет, означает ноль и держаться дальше не должна.
    места = {м for м, _ in qty_by_key} | {str(r.get("place") or station_id) for r in rows}
    удалено = 0
    for место in места:
        живые = [c for м, c in qty_by_key if м == место]
        if живые:
            res = await db.execute(text("""
                DELETE FROM edge.stock WHERE station_id = :st AND place = :pl
                  AND barcode_id NOT IN (
                      SELECT id FROM edge.barcode WHERE code = ANY(:codes))
            """), {"st": station_id, "pl": место, "codes": живые})
        else:
            res = await db.execute(text(
                "DELETE FROM edge.stock WHERE station_id = :st AND place = :pl"),
                {"st": station_id, "pl": место})
        удалено += res.rowcount or 0

    записано = 0
    for (место, code), qty in qty_by_key.items():
        res = await db.execute(text("""
            INSERT INTO edge.stock (station_id, place, barcode_id, qty)
            SELECT :s, :pl, b.id, :q FROM edge.barcode b
            WHERE b.code = :c AND b.status = 'active'
            ON CONFLICT (station_id, place, barcode_id)
            DO UPDATE SET qty = excluded.qty, updated_at = now()
        """), {"s": station_id, "pl": место, "c": code, "q": qty})
        записано += res.rowcount or 0

    out = {"stock_projection_rows": записано, "stock_projection_dropped": удалено}
    if потеряно:
        out["stock_no_code"] = len(потеряно)
        out["stock_no_code_items"] = потеряно[:10]
        log.warning("остатки станции %s: %d строк без штрихкода и без кода у карточки: %s",
                    station_id, len(потеряно), ", ".join(потеряно[:10]))
    return out
