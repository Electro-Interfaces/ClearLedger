"""Проекция сырых EdgePacket в канонические документы Ledger (DataEntry L2)."""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, EdgePacket
from app.services.cb_normalize import _build_sections, normalize_shift_package


def enrich_retail_meta(meta: dict, recipes: dict[str, list[dict]], dish_ids: set[str]) -> dict:
    """Повторно разбить продажу после прихода ТТК/признака блюда из мастер-НСИ."""
    result = copy.deepcopy(meta)
    sections = result.get("Секции") or {}
    lines: list[dict] = []
    for key in ("продажа_сопутка", "продажа_общепит"):
        lines.extend(copy.deepcopy((sections.get(key) or {}).get("строки") or []))

    for line in lines:
        line.pop("Ингредиенты", None)
        item_uuid = str(line.get("Номенклатура") or "")
        if item_uuid in dish_ids or item_uuid in recipes:
            line["ЭтоБлюдо"] = True
            line["КлассSKU"] = "Общепит"

    doc = dict(result.get("Документ") or {})
    doc["Товары"] = lines
    doc["ВозвращенныеТовары"] = copy.deepcopy(
        (sections.get("возвраты") or {}).get("строки") or []
    )
    doc["Оплаты"] = copy.deepcopy(
        (sections.get("оплаты") or {}).get("строки") or []
    )
    result["Секции"], result["СодержитБлюда"] = _build_sections(doc, recipes)
    return result


def _shift_identity(meta: dict) -> str:
    shift = (meta or {}).get("Смена") or {}
    station = str(shift.get("КодАЗС") or "")
    marker = str(shift.get("НомерСменыВнутр") or shift.get("НомерСмены")
                 or shift.get("ОСЭНомер") or shift.get("Смена") or "")
    return f"{station}:{marker}" if station and marker else ""


async def _dish_context(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> tuple[dict[str, list[dict]], dict[str, dict[str, list[dict]]], set[str]]:
    recipes: dict[str, list[dict]] = {}
    recipes_by_shift: dict[str, dict[str, list[dict]]] = {}
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.source == "edge",
        DataEntry.doc_type_id == "recipe",
    ).order_by(DataEntry.created_at, DataEntry.id))).scalars().all()
    for row in rows:
        doc = (row.meta or {}).get("Документ") or {}
        dish_uuid = str(doc.get("БлюдоUUID") or doc.get("Блюдо") or "")
        if dish_uuid:
            lines = doc.get("Ингредиенты") or []
            recipes[dish_uuid] = lines
            shift_key = _shift_identity(row.meta or {})
            if shift_key:
                recipes_by_shift.setdefault(shift_key, {})[dish_uuid] = lines

    dish_ids = set(recipes)
    item_rows = (await db.execute(text("""
        SELECT external_uuid
        FROM edge.item
        WHERE is_dish AND NOT deleted
    """))).scalars().all()
    dish_ids.update(str(item_uuid) for item_uuid in item_rows)
    return recipes, recipes_by_shift, dish_ids


async def refresh_retail_dishes(
    db: AsyncSession,
    company_id: uuid.UUID,
    station_id: int | None = None,
) -> int:
    recipes, recipes_by_shift, dish_ids = await _dish_context(db, company_id)
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.source == "edge",
        DataEntry.doc_type_id == "retail_sale_sidegoods",
    ))).scalars().all()
    updated = 0
    for row in rows:
        shift = (row.meta or {}).get("Смена") or {}
        if station_id is not None and str(shift.get("КодАЗС") or "") != str(station_id):
            continue
        shift_recipes = recipes_by_shift.get(_shift_identity(row.meta or {}), recipes)
        enriched = enrich_retail_meta(row.meta or {}, shift_recipes, dish_ids)
        if enriched != row.meta:
            row.meta = enriched
            updated += 1
    await db.flush()
    return updated


async def project_packet(
    db: AsyncSession,
    company_id: uuid.UUID,
    packet_uuid: str,
    station_id: int,
    payload: dict,
    refresh_dishes: bool = True,
) -> dict:
    """Идемпотентно материализовать один пакет в L2 и сохранить происхождение."""
    normalized = normalize_shift_package(
        payload,
        source="edge",
        source_label="Ledger Edge · агент станции",
    )
    expected_ids: set[str] = set()
    created = updated = removed = 0
    provenance = {
        "packet_uuid": packet_uuid,
        "packet_hash": str(payload.get("ХешПакета") or ""),
        "exported_at": payload.get("ВремяВыгрузки"),
        "station_id": station_id,
    }

    for draft in normalized["entries"]:
        sid = draft["source_id"]
        expected_ids.add(sid)
        draft["meta"]["Edge"] = provenance
        existing = (await db.execute(select(DataEntry).where(
            DataEntry.company_id == company_id,
            DataEntry.source == "edge",
            DataEntry.source_id == sid,
        ))).scalar_one_or_none()
        if existing is None:
            db.add(DataEntry(
                company_id=company_id,
                title=draft["title"],
                category_id=draft["category_id"],
                subcategory_id=draft["subcategory_id"],
                doc_type_id=draft["doc_type_id"],
                status=draft["status"],
                source=draft["source"],
                source_label=draft["source_label"],
                source_id=sid,
                layer=draft["layer"],
                meta=draft["meta"],
            ))
            created += 1
        else:
            existing.title = draft["title"]
            existing.category_id = draft["category_id"]
            existing.subcategory_id = draft["subcategory_id"]
            existing.doc_type_id = draft["doc_type_id"]
            existing.status = draft["status"]
            existing.layer = draft["layer"]
            existing.source_label = draft["source_label"]
            existing.meta = draft["meta"]
            updated += 1

    current = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.source == "edge",
    ))).scalars().all()
    for row in current:
        edge = (row.meta or {}).get("Edge") or {}
        if edge.get("packet_uuid") == packet_uuid and row.source_id not in expected_ids:
            await db.delete(row)
            removed += 1

    await db.flush()
    dishes_updated = 0
    if refresh_dishes:
        dishes_updated = await refresh_retail_dishes(db, company_id, station_id)
    return {
        "created": created,
        "updated": updated,
        "removed": removed,
        "dishes_updated": dishes_updated,
        "skipped_kinds": normalized.get("skipped", []),
    }


async def reproject_packets(
    db: AsyncSession,
    company_id: uuid.UUID,
    station_id: int | None = None,
) -> dict:
    query = select(EdgePacket).where(EdgePacket.company_id == company_id)
    if station_id is not None:
        query = query.where(EdgePacket.station_id == station_id)
    packets = (await db.execute(query.order_by(EdgePacket.received_at))).scalars().all()
    totals = {"packets": 0, "created": 0, "updated": 0, "removed": 0, "dishes_updated": 0}
    skipped: set[str] = set()
    for packet in packets:
        stats = await project_packet(
            db, company_id, packet.packet_uuid, packet.station_id, packet.payload,
            refresh_dishes=False,
        )
        totals["packets"] += 1
        for key in ("created", "updated", "removed"):
            totals[key] += stats[key]
        skipped.update(stats["skipped_kinds"])
    totals["dishes_updated"] = await refresh_retail_dishes(db, company_id, station_id)
    totals["skipped_kinds"] = sorted(skipped)
    return totals
