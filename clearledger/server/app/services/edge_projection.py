"""Проекция сырых EdgePacket в канонические документы Ledger (DataEntry L2)."""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, EdgePacket
from app.services.cb_normalize import _build_sections, normalize_shift_package


async def load_ingredients(db: AsyncSession) -> set[str]:
    """UUID позиций, входящих хоть в одну ТТК сети — сырьё кухни."""
    rows = await db.execute(text("SELECT DISTINCT item_uuid::text FROM edge.recipe_line"))
    return {r for r in rows.scalars() if r}


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


def _station_shift(meta: dict) -> tuple[str, str]:
    """Станция и номер смены — ключ, под которым один факт виден из обоих каналов.

    Раньше ключом был ВНУТРЕННИЙ номер кассы, но в выгрузке ЦБ его нет, и пара
    «станционный ОРП / ОРП из ЦБ» просто не встречалась в одной группе: 53 смены
    и 1,95 млн ₽ выручки остались посчитанными дважды. Общий у обоих каналов
    только номер смены.

    Он не уникален сам по себе — смена, начавшаяся 30 июля в 23:59, получает тот
    же номер, что и начавшаяся в 00:05 того же дня, — поэтому внутренний номер
    остаётся различителем ВНУТРИ группы: см. _supersede_rivals.
    """
    shift = (meta or {}).get("Смена") or {}
    return (str(shift.get("КодАЗС") or ""),
            str(shift.get("НомерСмены") or shift.get("Смена") or ""))


def _shift_inner(meta: dict) -> str:
    return str(((meta or {}).get("Смена") or {}).get("НомерСменыВнутр") or "")


def _станционный(row) -> bool:
    return bool(((row.meta or {}).get("Edge") or {}).get("from_station"))


def _doc_total(row) -> float:
    return round(float(((row.meta or {}).get("Документ") or {}).get("СуммаДокумента") or 0), 2)


def _split_by_inner(group: list) -> list[list]:
    """Разбить смены-однофамильцы на настоящие факты.

    Смена, открытая 30 июля в 23:59, и открытая в 00:05 того же дня делят номер,
    но не внутренний номер кассы. У документов ЦБ внутреннего номера нет вовсе,
    поэтому такую запись прикрепляем к той смене, с которой сходится сумма — а
    если сумма не решает однозначно, оставляем отдельно: лучше лишний документ в
    L2, чем вытесненная чужая смена.
    """
    свои: dict[str, list] = {}
    ничьи: list = []
    for row in group:
        (свои.setdefault(_shift_inner(row.meta or {}), []) if _shift_inner(row.meta or {})
         else ничьи).append(row)
    if not свои:
        return [ничьи]
    for row in ничьи:
        сумма = _doc_total(row)
        похожие = [k for k, rs in свои.items() if any(_doc_total(r) == сумма for r in rs)]
        цель = похожие[0] if len(похожие) == 1 else (next(iter(свои)) if len(свои) == 1 else None)
        if цель is None:
            свои.setdefault(f"?{row.id}", []).append(row)
        else:
            свои[цель].append(row)
    return list(свои.values())


# Пакеты одной и той же смены приезжают из двух источников: от агента станции и
# из выгрузки ЦБ (её заливали утилитой в тот же приёмник). Документы у них разные
# по `ИсточникUUID` — 1С отдаёт свой, агент считает детерминированный, — поэтому
# идемпотентность по ключу их не склеивает, и в L2 копилось по два документа на
# смену: 58 смен и 2,18 млн ₽ выручки, посчитанной дважды.
#
# Побеждает станция: она видит кассу напрямую, а ЦБ получает те же данные по РИБ
# с задержкой. Вытесненный документ не удаляется — помечается, чтобы история
# осталась, а выгрузка и витрины его не брали.
STATION_SOURCE = "Edge Agent"


def _from_station(payload: dict) -> bool:
    return str((payload or {}).get("Источник") or "").startswith(STATION_SOURCE)


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
    _, recipes_by_shift, dish_ids = await _dish_context(db, company_id)
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
        shift_recipes = recipes_by_shift.get(_shift_identity(row.meta or {}), {})
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
        ingredients=await load_ingredients(db),
    )
    expected_ids: set[str] = set()
    created = updated = removed = 0
    provenance = {
        "packet_uuid": packet_uuid,
        "packet_hash": str(payload.get("ХешПакета") or ""),
        "exported_at": payload.get("ВремяВыгрузки"),
        "station_id": station_id,
        "ProvisionalBusinessShiftID": str(
            payload.get("ProvisionalBusinessShiftID") or ""
        ),
        "ShiftCompleteness": copy.deepcopy(payload.get("ShiftCompleteness")),
        "CostEvidence": copy.deepcopy(payload.get("CostEvidence")),
        "BusinessDate": str(payload.get("BusinessDate") or ""),
        # Кто прислал факт: станция или выгрузка ЦБ. По этому признаку решается,
        # чей документ останется, когда одну смену описывают оба.
        "from_station": _from_station(payload),
        "source": str(payload.get("Источник") or ""),
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
    superseded = await _supersede_rivals(db, company_id, expected_ids, _from_station(payload))
    dishes_updated = 0
    if refresh_dishes:
        dishes_updated = await refresh_retail_dishes(db, company_id, station_id)
    return {
        "created": created,
        "updated": updated,
        "removed": removed,
        "superseded": superseded,
        "dishes_updated": dishes_updated,
        "skipped_kinds": normalized.get("skipped", []),
    }


async def _supersede_rivals(
    db: AsyncSession,
    company_id: uuid.UUID,
    touched_ids: set[str],
    from_station: bool,
) -> int:
    """Оставить по одному документу на смену: станционный вытесняет ЦБ-шный.

    Сравниваем по (станция, внутренний номер смены) — единственному ключу, под
    которым один и тот же факт приходит из обоих источников. Помечаем, а не
    удаляем: пакет ЦБ остаётся в истории и виден при разборе, просто выпадает
    из витрин и выгрузки.
    """
    if not touched_ids:
        return 0
    # Канал ЦБ пишет свои документы с source='oneC'. Пока выборка ограничивалась
    # каналом 'edge', станционный ОРП соперничал сам с собой, а пара «станция /
    # ЦБ» вообще не встречалась: 49 смен и 1,95 млн ₽ выручки остались вдвойне.
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.doc_type_id == "retail_sale_sidegoods",
    ))).scalars().all()

    groups: dict[tuple[str, str], list[DataEntry]] = {}
    for row in rows:
        key = _station_shift(row.meta or {})
        if all(key):
            groups.setdefault(key, []).append(row)

    count = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        for подгруппа in _split_by_inner(group):
            if len(подгруппа) < 2:
                continue
            # Победитель — документ станции; если станционного нет, оставляем тот,
            # что пришёл первым, чтобы выбор не прыгал между пересборками.
            подгруппа.sort(key=lambda r: (not _станционный(r), r.created_at, str(r.id)))
            for loser in подгруппа[1:]:
                if loser.status == "superseded":
                    continue
                loser.status = "superseded"
                count += 1
    if count:
        await db.flush()
    return count


async def reproject_packets(
    db: AsyncSession,
    company_id: uuid.UUID,
    station_id: int | None = None,
) -> dict:
    query = select(EdgePacket).where(EdgePacket.company_id == company_id)
    if station_id is not None:
        query = query.where(EdgePacket.station_id == station_id)
    # Порядок обязан быть полным: при равном `received_at` (перевыгрузка приходит
    # пачкой в одну секунду) сортировка только по времени оставляет очередь на
    # усмотрение планировщика, и победителем становится случайный пакет. Так в L2
    # оседала устаревшая версия — инвентаризация с нулём строк вместо 55.
    packets = (await db.execute(
        query.order_by(EdgePacket.received_at, EdgePacket.id))).scalars().all()
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
