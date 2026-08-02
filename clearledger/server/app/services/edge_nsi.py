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

import logging
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


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
             "ns_codes": 0, "stock_rows": 0, "stock_dropped": 0, "places": 0}

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
        # Штрихкод, снятый человеком (historical), заново не заводим: иначе
        # решение товароведа откатывалось следующим же снимком — станция
        # продолжает отдавать код, пока касса не перевыгружена, и в edge.barcode
        # копилось по строке на каждый цикл «снял — воскресили».
        снят = (await db.execute(text("""
            SELECT 1 FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
            WHERE b.code = :c AND b.status = 'historical'
              AND i.external_uuid = CAST(:u AS uuid)
        """), {"c": code, "u": uuid})).scalar_one_or_none()
        if снят:
            continue

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

    # ── Места хранения ───────────────────────────────────────────────────
    # Справочник приезжает вместе со снимком: свои склады станция знает из 1С,
    # центру их выдумывать неоткуда. Торговый зал определяем по коду, равному
    # номеру станции, — так заведено в 1С на всей сети.
    места: dict[str, str] = {}
    for r in book_rows:
        код = str(r.get("Место") or "")
        if код:
            места[код] = str(r.get("МестоНаименование") or "") or ("место " + код)
    for код, имя in места.items():
        await db.execute(text("""
            INSERT INTO edge.place (station_id, code, name, is_sales_floor)
            VALUES (:s, :c, :n, :f)
            ON CONFLICT (station_id, code) DO UPDATE
               SET name = excluded.name, updated_at = now()
        """), {"s": station_id, "c": код, "n": имя, "f": код == str(station_id)})
    stats["places"] = len(места)

    # ── Остатки ──────────────────────────────────────────────────────────
    # Берём физику учёта, а не витрину кассы: касса — производная, и класть её
    # в остаток значило бы считать одно и то же дважды.
    #
    # Ключ — ПАРА (место, штрихкод). Складывать места в одну цифру нельзя:
    # тогда товар со склада попадёт в витрину кассы, хотя на полке его нет.
    qty_by_key: dict[tuple[str, str], float] = {}
    for r in book_rows:
        code = str(r.get("ШтрихКод") or "")
        if not code:
            continue
        место = str(r.get("Место") or "") or str(station_id)
        qty_by_key[(место, code)] = qty_by_key.get((место, code), 0.0) + float(r.get("Остаток") or 0)

    # Снимок — ПОЛНАЯ картина остатков станции, а не список изменений. Строка,
    # которой в снимке нет, означает ноль, и держать её дальше нельзя: к 02.08
    # накопилось 1159 строк-сирот, из них 1021 с отрицательным остатком, и 33
    # позиции на 27 142 ₽ протекли в витрину кассы как товар, которого нет.
    for место in set(m for m, _ in qty_by_key) | set(места):
        живые = [c for m, c in qty_by_key if m == место and c]
        if живые:
            удалено = await db.execute(text("""
                DELETE FROM edge.stock s
                WHERE s.station_id = :st AND s.place = :pl
                  AND s.barcode_id NOT IN (
                      SELECT b.id FROM edge.barcode b
                      WHERE b.code = ANY(:codes) AND b.status = 'active')
            """), {"st": station_id, "pl": место, "codes": живые})
        else:
            # Место есть, а строк по нему в снимке нет — значит там пусто.
            удалено = await db.execute(text(
                "DELETE FROM edge.stock WHERE station_id = :st AND place = :pl"),
                {"st": station_id, "pl": место})
        stats["stock_dropped"] += удалено.rowcount or 0

    # Строка без карточки в справочнике не вставится: INSERT ... SELECT просто
    # ничего не найдёт. Раньше это проходило молча — три позиции станции не
    # доезжали до центра, и «остаток по данным центра» тихо отличался от
    # остатка станции. Молча терять строки учёта нельзя: пусть лучше видно.
    потеряно: list[str] = []
    for (место, code), qty in qty_by_key.items():
        res = await db.execute(text("""
            INSERT INTO edge.stock (station_id, place, barcode_id, qty)
            SELECT :s, :pl, b.id, :q FROM edge.barcode b
            WHERE b.code = :c AND b.status = 'active'
            ON CONFLICT (station_id, place, barcode_id)
            DO UPDATE SET qty = excluded.qty, updated_at = now()
        """), {"s": station_id, "pl": место, "c": code, "q": qty})
        строк = res.rowcount or 0
        stats["stock_rows"] += строк
        if строк == 0:
            потеряно.append(f"{code} ({место}, {qty:g})")
    if потеряно:
        stats["stock_no_barcode"] = len(потеряно)
        stats["stock_no_barcode_items"] = потеряно[:10]
        log.warning(
            "остатки станции %s: %d строк без карточки в справочнике — не приняты: %s",
            station_id, len(потеряно), ", ".join(потеряно[:10]))

    await db.commit()
    return stats


# ── Что станция решила сама ─────────────────────────────────────────────────
#
# Обратное направление НСИ: карточки и контрагенты, заведённые на станции, и
# цены, право на которые ей отдано. Это очередь на признание, а не справочник:
# каноном карточку делает человек в центре, сопоставляя её по штрихкоду с
# сетевой. Дедуп возможен только там, где виден справочник всей сети — иначе
# получается 208-я с её 95 группами дублей, наделанными «на местах».

def _ts(value) -> datetime | None:
    """Время из пакета — в объект.

    asyncpg типизирует параметр по колонке и строку в timestamptz не приводит:
    CAST в SQL тут не спасает, приведение нужно на стороне Python. Битую дату
    молча превращаем в None — приёмник не должен падать из-за формата даты, а
    «когда заведено» дополнит время получения.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def ingest_station_nsi(db: AsyncSession, company_id, station_id: int,
                             docs: list[dict]) -> dict:
    """Принять черновики справочников и изменения цен со станции."""
    stats = {"item_drafts": 0, "partner_drafts": 0, "price_changes": 0}

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        вид = doc.get("Тип")
        ключ = str(doc.get("ИсточникUUID") or "")
        if not ключ:
            # Без ключа нельзя ни отличить повтор, ни связать с решением центра:
            # такой документ примем один раз и не сможем найти второй.
            log.warning("станция %s: документ %s без ИсточникUUID — пропущен", station_id, вид)
            continue

        if вид == "item_draft":
            await db.execute(text("""
                INSERT INTO edge.item_draft
                    (company_id, station_id, source_uuid, name, unit, vat_rate, barcodes, created_at)
                VALUES (:cid, :st, :key, :name, :unit, :vat, :codes, coalesce(CAST(:at AS timestamptz), now()))
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET name = excluded.name, unit = excluded.unit,
                       vat_rate = excluded.vat_rate, barcodes = excluded.barcodes
                 WHERE edge.item_draft.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "name": doc.get("Наименование") or "", "unit": doc.get("Единица") or "шт",
                   "vat": doc.get("СтавкаНДС"), "codes": doc.get("Штрихкоды") or [],
                   "at": _ts(doc.get("Заведена"))})
            stats["item_drafts"] += 1

        elif вид == "partner_draft":
            await db.execute(text("""
                INSERT INTO edge.partner_draft
                    (company_id, station_id, source_uuid, name, inn, kpp, role, comment)
                VALUES (:cid, :st, :key, :name, :inn, :kpp, :role, :comment)
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET name = excluded.name, inn = excluded.inn, kpp = excluded.kpp,
                       role = excluded.role, comment = excluded.comment
                 WHERE edge.partner_draft.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "name": doc.get("Наименование") or "", "inn": doc.get("ИНН"),
                   "kpp": doc.get("КПП"), "role": doc.get("Роль") or "supplier",
                   "comment": doc.get("Комментарий")})
            stats["partner_drafts"] += 1

        elif вид == "price_change":
            # Изменение цены неизменяемо: это запись о случившемся, а не
            # состояние. Повтор пакета не должен переписывать автора и причину.
            await db.execute(text("""
                INSERT INTO edge.station_price_change
                    (company_id, station_id, source_uuid, item_uuid, barcode,
                     old_price, new_price, author, reason, changed_at)
                VALUES (:cid, :st, :key, :item, :bc, :old, :new, :author, :reason,
                        coalesce(CAST(:at AS timestamptz), now()))
                ON CONFLICT (company_id, station_id, source_uuid) DO NOTHING
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "item": doc.get("НоменклатураUUID") or "", "bc": doc.get("Штрихкод"),
                   "old": doc.get("ЦенаБыла"), "new": doc.get("ЦенаСтала") or 0,
                   "author": doc.get("Автор") or "", "reason": doc.get("Причина"),
                   "at": _ts(doc.get("Момент"))})
            stats["price_changes"] += 1

    await db.commit()
    if any(stats.values()):
        log.info("станция %s прислала справочники: %s", station_id, stats)
    return stats


async def station_drafts(db: AsyncSession, company_id, station_id: int | None = None) -> dict:
    """Открытые черновики станций — то, что ждёт решения человека в центре."""
    условие = "company_id = :cid AND resolved_at IS NULL"
    args: dict = {"cid": company_id}
    if station_id:
        условие += " AND station_id = :st"
        args["st"] = station_id

    items = (await db.execute(text(f"""
        SELECT id, station_id, source_uuid, name, unit, vat_rate, barcodes, created_at
        FROM edge.item_draft WHERE {условие} ORDER BY created_at
    """), args)).mappings().all()
    partners = (await db.execute(text(f"""
        SELECT id, station_id, source_uuid, name, inn, kpp, role, comment, created_at
        FROM edge.partner_draft WHERE {условие} ORDER BY created_at
    """), args)).mappings().all()
    prices = (await db.execute(text("""
        SELECT station_id, item_uuid, barcode, old_price, new_price, author, reason, changed_at
        FROM edge.station_price_change
        WHERE company_id = :cid AND (CAST(:st AS int) IS NULL OR station_id = CAST(:st AS int))
        ORDER BY changed_at DESC LIMIT 100
    """), {"cid": company_id, "st": station_id})).mappings().all()

    def плоско(rows):
        out = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    d[k] = float(v)
            out.append(d)
        return out

    return {"items": плоско(items), "partners": плоско(partners),
            "prices": плоско(prices)}


async def draft_candidates(db: AsyncSession, company_id, barcodes: list[str]) -> list[dict]:
    """Карточки сети, на которые похож черновик.

    Сопоставляем по штрихкоду — больше не по чему: наименования на станциях
    расходятся («LD Blue» и «LD Autograph» оказались одним товаром), а
    нормализация имён даёт ложные пары. Штрихкод либо совпал, либо нет.
    """
    if not barcodes:
        return []
    rows = (await db.execute(text("""
        SELECT DISTINCT i.id, i.external_uuid, i.name, i.unit, i.vat_rate, b.code, b.status
        FROM edge.barcode b JOIN edge.item i ON i.id = b.item_id
        WHERE b.code = ANY(:codes)
        ORDER BY i.name
    """), {"codes": barcodes})).mappings().all()
    return [{"item_id": r["id"], "uuid": str(r["external_uuid"]), "name": r["name"],
             "unit": r["unit"], "vat_rate": r["vat_rate"],
             "barcode": r["code"], "barcode_status": r["status"]} for r in rows]


async def resolve_item_draft(db: AsyncSession, company_id, draft_id: int,
                             action: str, item_id: int | None = None,
                             note: str | None = None) -> dict:
    """Решение центра по черновику карточки.

    Три исхода, и все три обязаны быть явными:

      · link   — это уже известный сети товар, просто станция про него не знала.
                 Привязываем штрихкоды к существующей карточке.
      · create — товара в сети нет, заводим новый и переносим штрихкоды.
      · reject — заведено ошибочно (опечатка в ШК, дубль внутри станции).

    Молчаливого «оставим как есть» тут быть не должно: черновик, который никто
    не разобрал, — это товар, который станция продаёт, а сеть не видит.
    """
    draft = (await db.execute(text("""
        SELECT id, station_id, name, unit, vat_rate, barcodes, resolved_at
        FROM edge.item_draft WHERE id = :id AND company_id = :cid
    """), {"id": draft_id, "cid": company_id})).mappings().first()
    if draft is None:
        raise ValueError("черновик не найден")
    if draft["resolved_at"] is not None:
        raise ValueError("черновик уже разобран")

    codes = list(draft["barcodes"] or [])

    if action == "reject":
        await db.execute(text("""
            UPDATE edge.item_draft SET resolved_at = now(), rejected = true, note = :n
            WHERE id = :id
        """), {"id": draft_id, "n": note})
        await db.commit()
        return {"action": "reject", "draft_id": draft_id}

    if action == "create":
        row = (await db.execute(text("""
            INSERT INTO edge.item (external_uuid, name, unit, vat_rate, source, price_owner)
            VALUES (gen_random_uuid(), :name, :unit, :vat, 'station', 'station')
            RETURNING id, external_uuid
        """), {"name": draft["name"], "unit": draft["unit"] or "шт",
               # Ставка обязательна в схеме, и форма станции её всегда
               # спрашивает. Подставляем розничную только на случай карточки,
               # заведённой до появления поля: молча уронить признание хуже.
               "vat": draft["vat_rate"] or "НДС22"})).mappings().first()
        item_id = row["id"]
        canon_uuid = str(row["external_uuid"])
    elif action == "link":
        if not item_id:
            raise ValueError("не указана карточка, к которой привязываем")
        row = (await db.execute(text(
            "SELECT external_uuid FROM edge.item WHERE id = :id"), {"id": item_id})).first()
        if row is None:
            raise ValueError("карточка не найдена")
        canon_uuid = str(row.external_uuid)
    else:
        raise ValueError(f"неизвестное решение: {action}")

    # Штрихкоды черновика переносим на канон. Чужой активный код не трогаем:
    # это коллизия справочника, и решать её отдельно — перевесить молча значит
    # сломать кассу тому товару, который сейчас по нему пробивается.
    привязано, коллизий = 0, 0
    for code in codes:
        занят = (await db.execute(text("""
            SELECT item_id FROM edge.barcode WHERE code = :c AND status = 'active'
        """), {"c": code})).first()
        if занят is not None:
            if занят.item_id != item_id:
                коллизий += 1
            continue
        await db.execute(text("""
            INSERT INTO edge.barcode (item_id, code, status) VALUES (:i, :c, 'active')
            ON CONFLICT DO NOTHING
        """), {"i": item_id, "c": code})
        привязано += 1

    await db.execute(text("""
        UPDATE edge.item_draft SET resolved_at = now(), resolved_item = :item, note = :n
        WHERE id = :id
    """), {"id": draft_id, "item": item_id, "n": note})
    await db.commit()
    return {"action": action, "draft_id": draft_id, "item_id": item_id,
            "uuid": canon_uuid, "barcodes_linked": привязано, "collisions": коллизий,
            "station_id": draft["station_id"], "codes": codes}


async def resolve_partner_draft(db: AsyncSession, company_id, draft_id: int,
                                action: str, note: str | None = None) -> dict:
    """Решение по контрагенту: принять в справочник сети или отклонить."""
    if action not in ("accept", "reject"):
        raise ValueError(f"неизвестное решение: {action}")
    res = await db.execute(text("""
        UPDATE edge.partner_draft
           SET resolved_at = now(), rejected = :rej, note = :n
         WHERE id = :id AND company_id = :cid AND resolved_at IS NULL
     RETURNING station_id, name
    """), {"id": draft_id, "cid": company_id, "rej": action == "reject", "n": note})
    row = res.mappings().first()
    if row is None:
        raise ValueError("черновик не найден или уже разобран")
    await db.commit()
    return {"action": action, "draft_id": draft_id, "name": row["name"],
            "station_id": row["station_id"]}
