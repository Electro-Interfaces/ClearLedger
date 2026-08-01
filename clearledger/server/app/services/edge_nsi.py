"""Наполнение мастер-НСИ из снимков станции.

Разовый импорт из зеркала ЦБ дал основу, но поддерживать её вручную нельзя:
ассортимент меняется каждый день. При этом выгрузить справочник штрихкодов из
1С невозможно — его там НЕТ: в ЭЛСИ.АЗК штрихкод существует только как
измерение регистров ТоварыНаАЗК и ТоварыКПеремещениюНаАЗК, а цена — там же,
соседним измерением. Отдельных справочников не существует.

Зато есть поток: агент присылает снимок кассы и учёта каждый час, и в нём
штрихкод стоит рядом с UUID карточки и кодом нефтесервера. Этого достаточно,
чтобы мастер-НСИ жила сама.

Что делает синхронизация:
  · новые штрихкоды заводит, известные не трогает;
  · коллизию (ШК уже активен у другой карточки) НЕ перевешивает молча, а
    записывает как rejected — это дефект справочника, и решать его человеку;
  · цену пишет новой записью с историей, старую закрывает: цена, по которой
    продавали вчера, нужна для разбора вчерашних продаж;
  · коды нефтесервера переназначает, потому что они переиспользуются;
  · остаток обновляет по паре (станция, ШК) — без цены, в этом всё отличие
    от 1С.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _stock_doc(payload: dict) -> dict | None:
    for doc in payload.get("Документы") or []:
        if isinstance(doc, dict) and doc.get("Тип") == "stock_snapshot":
            return doc
    return None


async def sync_from_snapshot(db: AsyncSession, station_id: int, payload: dict) -> dict:
    """Обновить мастер-НСИ станции по свежему снимку. Возвращает счётчики."""
    doc = _stock_doc(payload)
    if doc is None:
        return {"skipped": "в пакете нет снимка"}

    station = (await db.execute(
        text("SELECT 1 FROM edge.station WHERE id = :s"), {"s": station_id}
    )).scalar_one_or_none()
    if station is None:
        # Станции нет в мастере — молча заводить её здесь нельзя: реквизиты
        # (склад, организация) знает только конфигурация, а не снимок.
        return {"skipped": f"станция {station_id} не заведена в мастер-НСИ"}

    cash_rows = doc.get("Касса") or []
    book_rows = doc.get("Учет") or []

    stats = {"barcodes_new": 0, "collisions": 0, "prices_changed": 0,
             "ns_codes": 0, "stock_rows": 0}

    # ── Штрихкоды ────────────────────────────────────────────────────────
    # Источник — обе половины снимка: касса знает, чем товар пробивается,
    # учёт добавляет то, что до кассы ещё не доехало.
    pairs: dict[tuple[str, str], None] = {}
    for r in cash_rows:
        uuid, code = str(r.get("Номенклатура") or ""), str(r.get("ШтрихКод") or "")
        if len(uuid) == 36 and code:
            pairs[(uuid, code)] = None
    for r in book_rows:
        uuid, code = str(r.get("Номенклатура") or ""), str(r.get("ШтрихКод") or "")
        if len(uuid) == 36 and code:
            pairs[(uuid, code)] = None

    for uuid, code in pairs:
        row = (await db.execute(text("""
            SELECT b.id, b.item_id, i.external_uuid
            FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
            WHERE b.code = :c AND b.status = 'active'
        """), {"c": code})).first()
        if row is not None:
            if str(row.external_uuid) != uuid:
                # Тот же ШК у другой карточки. Перевесить молча — значит
                # сломать кассу тому товару, который сейчас по нему пробивается.
                await db.execute(text("""
                    INSERT INTO edge.barcode (item_id, code, status, note)
                    SELECT i.id, :c, 'rejected', :note FROM edge.item i
                    WHERE i.external_uuid = CAST(:u AS uuid)
                      AND NOT EXISTS (SELECT 1 FROM edge.barcode b2
                                      WHERE b2.code = :c AND b2.item_id = i.id)
                """), {"c": code, "u": uuid,
                        "note": f"коллизия: ШК активен у карточки {row.external_uuid}"})
                stats["collisions"] += 1
            continue
        res = await db.execute(text("""
            INSERT INTO edge.barcode (item_id, code, status)
            SELECT i.id, :c, 'active' FROM edge.item i
            WHERE i.external_uuid = CAST(:u AS uuid)
            ON CONFLICT DO NOTHING
        """), {"c": code, "u": uuid})
        stats["barcodes_new"] += res.rowcount or 0

    # ── Цены ─────────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    seen_price: dict[str, float] = {}
    for r in cash_rows:
        uuid = str(r.get("Номенклатура") or "")
        price = float(r.get("Цена") or 0)
        if len(uuid) == 36 and price > 0:
            seen_price[uuid] = price

    for uuid, price in seen_price.items():
        current = (await db.execute(text("""
            SELECT p.id, p.price FROM edge.price p
            JOIN edge.item i ON i.id = p.item_id
            WHERE i.external_uuid = CAST(:u AS uuid)
              AND p.station_id = :s AND p.valid_to IS NULL
        """), {"u": uuid, "s": station_id})).first()
        if current is not None and abs(float(current.price) - price) < 0.005:
            continue
        if current is not None:
            await db.execute(text("UPDATE edge.price SET valid_to = :t WHERE id = :id"),
                             {"t": now, "id": current.id})
        await db.execute(text("""
            INSERT INTO edge.price (item_id, station_id, price, author)
            SELECT i.id, :s, :p, 'снимок станции' FROM edge.item i
            WHERE i.external_uuid = CAST(:u AS uuid)
        """), {"u": uuid, "s": station_id, "p": price})
        stats["prices_changed"] += 1

    # ── Коды нефтесервера ────────────────────────────────────────────────
    # Код уникален «в моменте», а не навсегда: снимок — истина последней
    # минуты, поэтому расходящиеся привязки закрываем и заводим заново.
    for r in cash_rows:
        code = str(r.get("ШтрихКод") or "")
        ns = r.get("КодНС")
        if not code or not isinstance(ns, int):
            continue
        bc = (await db.execute(text(
            "SELECT id FROM edge.barcode WHERE code = :c AND status = 'active'"
        ), {"c": code})).scalar_one_or_none()
        if bc is None:
            continue
        cur = (await db.execute(text("""
            SELECT id, barcode_id FROM edge.ns_code
            WHERE station_id = :s AND ns_code = :n AND status = 'active'
        """), {"s": station_id, "n": ns})).first()
        if cur is not None and cur.barcode_id == bc:
            continue
        if cur is not None:
            await db.execute(text("""
                UPDATE edge.ns_code SET status = 'released', released_at = :t WHERE id = :id
            """), {"t": now, "id": cur.id})
        # Тот же ШК мог висеть под другим кодом — освобождаем и его.
        await db.execute(text("""
            UPDATE edge.ns_code SET status = 'released', released_at = :t
            WHERE station_id = :s AND barcode_id = :b AND status = 'active'
        """), {"t": now, "s": station_id, "b": bc})
        await db.execute(text("""
            INSERT INTO edge.ns_code (station_id, ns_code, barcode_id, status)
            VALUES (:s, :n, :b, 'active') ON CONFLICT DO NOTHING
        """), {"s": station_id, "n": ns, "b": bc})
        stats["ns_codes"] += 1

    # ── Остатки ──────────────────────────────────────────────────────────
    # Берём физику учёта, а не витрину кассы: касса — производная, и класть
    # её в остаток значило бы считать одно и то же дважды.
    qty_by_code: dict[str, float] = {}
    for r in book_rows:
        code = str(r.get("ШтрихКод") or "")
        if code:
            qty_by_code[code] = qty_by_code.get(code, 0.0) + float(r.get("Остаток") or 0)

    for code, qty in qty_by_code.items():
        res = await db.execute(text("""
            INSERT INTO edge.stock (station_id, barcode_id, qty)
            SELECT :s, b.id, :q FROM edge.barcode b
            WHERE b.code = :c AND b.status = 'active'
            ON CONFLICT (station_id, barcode_id)
            DO UPDATE SET qty = excluded.qty, updated_at = now()
        """), {"s": station_id, "c": code, "q": qty})
        stats["stock_rows"] += res.rowcount or 0

    await db.commit()
    return stats
