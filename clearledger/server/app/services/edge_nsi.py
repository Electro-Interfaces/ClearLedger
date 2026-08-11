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
import hashlib
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Counterparty, EdgeDownlink

# Ставка в снимке приходит процентом (так её хранит касса), в контракте БП —
# именем. Ноль это «Без НДС», законная ставка, а не отсутствие данных.
_VAT_BY_PERCENT = {22: "НДС22", 20: "НДС20", 18: "НДС18", 10: "НДС10",
                   7: "НДС7", 5: "НДС5", 0: "БезНДС"}

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
        # Станция заводится из первого же пакета.
        #
        # Раньше здесь был отказ «станция не заведена в мастер-НСИ», и завести
        # её можно было только SQL-ом руками: новая АЗС молча теряла снимок,
        # цены, коды кассы и места хранения, а причину было видно лишь в ответе
        # приёмника. Реквизиты, которых «знает только конфигурация», на деле
        # едут в шапке каждого пакета — станция сама их и сообщает.
        смена = (payload.get("Смена") or {}) if isinstance(payload, dict) else {}
        склад = str(смена.get("СкладUUID") or "").strip()
        орг = str(смена.get("ОрганизацияUUID") or "").strip()
        if not склад or not орг:
            return {"skipped": f"станция {station_id} не заведена, а в пакете нет "
                               "СкладUUID и ОрганизацияUUID"}
        await db.execute(text("""
            INSERT INTO edge.station (id, name, warehouse_uuid, org_uuid)
            VALUES (:s, :n, cast(:w as uuid), cast(:o as uuid))
            ON CONFLICT (id) DO NOTHING
        """), {"s": station_id, "n": str(смена.get("Касса") or f"АЗС №{station_id}")[:100],
               "w": склад, "o": орг})
        await db.commit()

    cash_rows = doc.get("Касса") or []
    book_rows = doc.get("Учет") or []

    stats = {"barcodes_new": 0, "collisions": 0, "prices_changed": 0,
             "ns_codes": 0, "places": 0}

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

    # ── Ставки НДС ───────────────────────────────────────────────────────
    # Ставка приезжает в кассу из 1С той же выгрузкой ассортимента, что и цена,
    # то есть касса знает её свежее нашего справочника. Мастер обновлялся один
    # раз и отставал: «Вода дистиллированная» держала НДС18/118 из позапрошлой
    # эпохи, а сок J7 — 22% вместо положенных ему 10%, и мы завышали налог в
    # выгрузке. Цену по снимку мы уже обновляем — ставка ровно такой же факт.
    for uuid, rate in {
        str(r.get("Номенклатура") or ""): _VAT_BY_PERCENT.get(int(r.get("СтавкаНДСПроцент")))
        for r in cash_rows + book_rows
        if len(str(r.get("Номенклатура") or "")) == 36
        and isinstance(r.get("СтавкаНДСПроцент"), (int, float))
    }.items():
        if not rate:
            continue
        res = await db.execute(text("""
            UPDATE edge.item SET vat_rate = :v, updated_at = now()
            WHERE external_uuid = CAST(:u AS uuid) AND vat_rate <> :v
        """), {"u": uuid, "v": rate})
        stats["vat_changed"] = stats.get("vat_changed", 0) + (res.rowcount or 0)

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

    # Код, пропавший из кассы, гаснет и в центре.
    #
    # Раздел «Касса» снимка — полный список dba.Tariffs, а не изменения: раз
    # позиции там нет, касса этот код больше не держит. Пока гасились только
    # конфликтующие привязки, реестр центра умел лишь расти: 856 активных
    # против 832 на станции, последнее гашение — за неделю до этого. Из такого
    # расхождения рождается ложный конфликт: код 644 в центре числился за
    # печеньем, которого касса под ним давно не выдаёт, и мешал отдать номер
    # новой карточке.
    увиденные = sorted({int(r["КодНС"]) for r in cash_rows
                        if isinstance(r.get("КодНС"), int) and r.get("КодНС")})
    if увиденные:
        res = await db.execute(text("""
            UPDATE edge.ns_code SET status = 'released', released_at = :t
             WHERE station_id = :s AND status = 'active'
               AND ns_code <> ALL(:codes)
        """), {"t": now, "s": station_id, "codes": увиденные})
        stats["ns_codes_released"] = res.rowcount or 0

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

    # ── Остатки сюда больше не пишутся ───────────────────────────────────
    #
    # Раньше остаток заполняли ДВА приёмника со своей арифметикой каждый: этот
    # писал edge.stock по штрихкоду и молча терял строки без кода, соседний —
    # store_stock_balances по паре «карточка + штрихкод» и считал верно. Два
    # экрана центра показывали разные цифры про одну станцию (13 883 против
    # 8 384), и понять, какая правда, было нельзя.
    #
    # Теперь источник один: edge_stock.sync_from_snapshot считает остаток и сам
    # пишет обе проекции. Здесь остаются справочники — штрихкоды, цены, ставки
    # НДС, коды нефтесервера, места хранения.

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
    stats = {"item_drafts": 0, "partner_drafts": 0, "price_changes": 0,
             "proposals": 0, "mrc_facts": 0}

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
                    (company_id, station_id, source_uuid, name, unit, vat_rate, barcodes,
                     created_at, author)
                VALUES (:cid, :st, :key, :name, :unit, :vat, :codes,
                        coalesce(CAST(:at AS timestamptz), now()), :author)
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET name = excluded.name, unit = excluded.unit,
                       vat_rate = excluded.vat_rate, barcodes = excluded.barcodes,
                       author = coalesce(nullif(excluded.author, ''),
                                         edge.item_draft.author)
                 WHERE edge.item_draft.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "name": doc.get("Наименование") or "", "unit": doc.get("Единица") or "шт",
                   "vat": doc.get("СтавкаНДС"), "codes": doc.get("Штрихкоды") or [],
                   "at": _ts(doc.get("Заведена")), "author": doc.get("Автор") or ""})
            stats["item_drafts"] += 1

        elif вид == "partner_draft":
            await db.execute(text("""
                INSERT INTO edge.partner_draft
                    (company_id, station_id, source_uuid, name, inn, kpp, role, comment, author)
                VALUES (:cid, :st, :key, :name, :inn, :kpp, :role, :comment, :author)
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET name = excluded.name, inn = excluded.inn, kpp = excluded.kpp,
                       role = excluded.role, comment = excluded.comment,
                       author = coalesce(nullif(excluded.author, ''),
                                         edge.partner_draft.author)
                 WHERE edge.partner_draft.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "name": doc.get("Наименование") or "", "inn": doc.get("ИНН"),
                   "kpp": doc.get("КПП"), "role": doc.get("Роль") or "supplier",
                   "comment": doc.get("Комментарий"), "author": doc.get("Автор") or ""})
            stats["partner_drafts"] += 1

        elif вид == "nsi_proposal":
            # Заявка станции на исправление сетевой карточки. Ничего не
            # применяет: канон правит центр, здесь только очередь на разбор.
            # Повтор пакета обновляет незакрытую заявку и не воскрешает
            # разобранную — иначе решение центра откатывалось бы само.
            await db.execute(text("""
                INSERT INTO edge.nsi_proposal
                    (company_id, station_id, source_uuid, item_uuid, field,
                     current, proposed, author, comment, created_at)
                VALUES (:cid, :st, :key, :item, :field, :cur, :prop, :author, :comment,
                        coalesce(CAST(:at AS timestamptz), now()))
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET proposed = excluded.proposed, comment = excluded.comment
                 WHERE edge.nsi_proposal.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "item": doc.get("НоменклатураUUID") or "",
                   "field": doc.get("Поле") or "", "cur": doc.get("ТекущееЗначение") or "",
                   "prop": doc.get("ПредложеноЗначение") or "",
                   "author": doc.get("Автор") or "", "comment": doc.get("Комментарий") or "",
                   "at": _ts(doc.get("Момент"))})
            stats["proposals"] += 1

        elif вид == "mrc_fact":
            # МРЦ, снятая станцией с кода маркировки.
            #
            # В очередь на разбор не кладём: максимальную розничную цену никто
            # не назначает — её печатают на пачке. Спрашивать человека «принять
            # ли то, что написано на упаковке» бессмысленно, а без неё контроль
            # «не продавать выше МРЦ» не работает вовсе: в справочнике сети её
            # нет ни у одной позиции, из 1С она не переносилась.
            #
            # Пишем только там, где своего значения у центра нет. Данные ЭДО
            # точнее выборки по последнему увиденному коду, и станция их не
            # переспорит.
            item = doc.get("НоменклатураUUID") or ""
            мрц = doc.get("МРЦ")
            if not item or not мрц or float(мрц) <= 0:
                continue
            применено = await db.execute(text("""
                UPDATE edge.item SET mrc = :mrc, updated_at = now()
                 WHERE external_uuid::text = :item AND mrc IS NULL
            """), {"item": item, "mrc": float(мрц)})
            # Считаем применённое, а не присланное: условие `mrc IS NULL`
            # отбрасывает большую часть фактов, и счётчик обещал работу,
            # которой не было.
            stats["mrc_facts"] += применено.rowcount or 0

        elif вид == "price_change":
            # Изменение цены неизменяемо: это запись о случившемся, а не
            # состояние. Повтор пакета не должен переписывать автора и причину.
            inserted = (await db.execute(text("""
                INSERT INTO edge.station_price_change
                    (company_id, station_id, source_uuid, item_uuid, barcode,
                     old_price, new_price, author, reason, changed_at)
                VALUES (:cid, :st, :key, :item, :bc, :old, :new, :author, :reason,
                        coalesce(CAST(:at AS timestamptz), now()))
                ON CONFLICT (company_id, station_id, source_uuid) DO NOTHING
                RETURNING id
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "item": doc.get("НоменклатураUUID") or "", "bc": doc.get("Штрихкод"),
                   "old": doc.get("ЦенаБыла"), "new": doc.get("ЦенаСтала") or 0,
                   "author": doc.get("Автор") or "", "reason": doc.get("Причина"),
                   "at": _ts(doc.get("Момент"))})).scalar_one_or_none()
            if inserted is None:
                continue
            stats["price_changes"] += 1

            # Политика v1 отдаёт станции весь ассортимент. Её новая цена — не
            # только журнал, а текущая цена мастер-проекции этой АЗС.
            item = (await db.execute(text("""
                SELECT id, coalesce(price_owner, 'master') AS price_owner
                FROM edge.item WHERE external_uuid::text = :u
            """), {"u": doc.get("НоменклатураUUID") or ""})).first()
            new_price = float(doc.get("ЦенаСтала") or 0)
            if item is not None and new_price >= 0:
                await db.execute(text(
                    "UPDATE edge.item SET price_owner = 'station' WHERE id = :item"
                ), {"item": item.id})
                changed_at = _ts(doc.get("Момент")) or datetime.now(timezone.utc)
                await db.execute(text("""
                    UPDATE edge.price SET valid_to = :at
                    WHERE item_id = :item AND station_id = :st AND valid_to IS NULL
                """), {"at": changed_at, "item": item.id, "st": station_id})
                await db.execute(text("""
                    INSERT INTO edge.price (item_id, station_id, price, valid_from, author)
                    VALUES (:item, :st, :price, :at, :author)
                """), {"item": item.id, "st": station_id, "price": new_price,
                       "at": changed_at, "author": doc.get("Автор") or "станция"})

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
        SELECT id, station_id, source_uuid, name, unit, vat_rate, barcodes, created_at,
               coalesce(author, '') AS author
        FROM edge.item_draft WHERE {условие} ORDER BY created_at
    """), args)).mappings().all()
    partners = (await db.execute(text(f"""
        SELECT id, station_id, source_uuid, name, inn, kpp, role, comment, created_at,
               coalesce(author, '') AS author
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

    proposals = (await db.execute(text(f"""
        SELECT p.id, p.station_id, p.item_uuid, p.field, p.current, p.proposed,
               p.author, p.comment, p.created_at, i.name AS item_name
        FROM edge.nsi_proposal p
        -- Приводим к тексту, а не к uuid: в заявке станции ссылка на карточку
        -- хранится строкой и бывает пустой, а CAST пустой строки к uuid роняет
        -- весь запрос — экран «Признание со станций» падал целиком.
        LEFT JOIN edge.item i ON i.external_uuid::text = p.item_uuid
        WHERE p.company_id = :cid AND p.resolved_at IS NULL
              {"AND p.station_id = :st" if station_id else ""}
        ORDER BY p.created_at
    """), args)).mappings().all()

    return {"items": плоско(items), "partners": плоско(partners),
            "prices": плоско(prices), "proposals": плоско(proposals)}


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
        SELECT id, station_id, name, unit, vat_rate, barcodes, resolved_at, source_uuid
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
        # source_uuid возвращаем, чтобы отказ доехал до станции адресно: там
        # черновик опознаётся именно по нему, а не по нашему номеру строки.
        return {"action": "reject", "draft_id": draft_id,
                "station_id": draft["station_id"],
                "source_uuid": str(draft["source_uuid"] or "")}

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
                # Штрихкод уже работает у другой карточки. Перевесить молча
                # нельзя: по нему сейчас пробивается товар, и касса той позиции
                # сломается. Записываем претензию строкой rejected — это дефект
                # справочника, и решать его человеку на отдельном экране.
                await db.execute(text("""
                    INSERT INTO edge.barcode (item_id, code, status, note)
                    VALUES (:i, :c, 'rejected', :note)
                    ON CONFLICT DO NOTHING
                """), {"i": item_id, "c": code,
                       "note": f"признание черновика АЗС {draft['station_id']}: "
                               f"код активен у карточки {занят.item_id}"})
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
    draft = (await db.execute(text("""
        SELECT id, station_id, source_uuid, name, inn, kpp, role, comment
          FROM edge.partner_draft
         WHERE id = :id AND company_id = :cid AND resolved_at IS NULL
         FOR UPDATE
    """), {"id": draft_id, "cid": company_id})).mappings().first()
    if draft is None:
        raise ValueError("черновик не найден или уже разобран")
    if action == "reject":
        await db.execute(text("""
            UPDATE edge.partner_draft
               SET resolved_at = now(), rejected = true, note = :n
             WHERE id = :id
        """), {"id": draft_id, "n": note})
        await db.commit()
        return {"action": action, "draft_id": draft_id, "name": draft["name"],
                "station_id": draft["station_id"]}

    if str(draft["role"] or "supplier") != "supplier":
        raise ValueError("в справочник приёмки можно принять только поставщика")
    if not str(draft["name"] or "").strip():
        raise ValueError("у поставщика нет наименования")
    inn = "".join(char for char in str(draft["inn"] or "") if char.isdigit())
    if len(inn) not in (10, 12):
        raise ValueError("для принятия поставщика нужен корректный ИНН")
    lock_key = int.from_bytes(
        hashlib.sha256(f"partner:{company_id}:{inn}".encode()).digest()[:8],
        "big", signed=True)
    await db.execute(select(__import__("sqlalchemy").func.pg_advisory_xact_lock(lock_key)))
    candidates = (await db.execute(select(Counterparty).where(
        Counterparty.company_id == company_id,
        __import__("sqlalchemy").func.regexp_replace(
            Counterparty.inn, r"\D", "", "g") == inn,
    ).with_for_update())).scalars().all()
    if len(candidates) > 1:
        raise ValueError("по ИНН найдено несколько канонических контрагентов; требуется ручной разбор")
    if candidates:
        canonical = candidates[0]
    else:
        canonical = Counterparty(
            id=uuid.uuid4(), company_id=company_id, inn=inn,
            kpp=str(draft["kpp"] or "").strip() or None,
            name=str(draft["name"] or "").strip(),
            type="ИП" if len(inn) == 12 else "ЮЛ", aliases=[], kind="external",
            raw={"source": "station_draft", "station_id": draft["station_id"],
                 "source_uuid": draft["source_uuid"]},
        )
        db.add(canonical)
        await db.flush()

    partners = (await db.execute(text("""
        SELECT id, external_uuid FROM edge.partner
         WHERE company_id = :cid
           AND regexp_replace(coalesce(inn, ''), '\\D', '', 'g') = :inn
         FOR UPDATE
    """), {"cid": company_id, "inn": inn})).mappings().all()
    if len(partners) > 1:
        raise ValueError("по ИНН найдено несколько partner; требуется ручной разбор")
    if partners and partners[0]["external_uuid"] not in (None, canonical.id):
        raise ValueError("partner уже связан с другим каноническим контрагентом")
    if partners:
        partner_id = partners[0]["id"]
        await db.execute(text("""
            UPDATE edge.partner
               SET external_uuid = :uuid, updated_at = now()
             WHERE id = :id
        """), {"uuid": canonical.id, "id": partner_id})
    else:
        partner_id = (await db.execute(text("""
            INSERT INTO edge.partner
                (company_id, external_uuid, name, name_full, inn, kpp, role, source, comment)
            VALUES (:cid, :uuid, :name, :name, :inn, :kpp, :role, 'station', :comment)
            RETURNING id
        """), {"cid": company_id, "uuid": canonical.id, "name": canonical.name,
                 "inn": inn, "kpp": canonical.kpp,
                 "role": draft["role"] or "supplier", "comment": draft["comment"]})).scalar_one()
    await db.execute(text("""
        INSERT INTO edge.partner_station (partner_id, station_id)
        VALUES (:partner, :station) ON CONFLICT DO NOTHING
    """), {"partner": partner_id, "station": draft["station_id"]})
    await db.execute(text("""
        UPDATE edge.partner_draft
           SET resolved_at = now(), rejected = false, note = :n
         WHERE id = :id
    """), {"id": draft_id, "n": note})
    downlink_key = f"partners:{draft['station_id']}:draft:{draft_id}"
    existing_task = (await db.execute(select(EdgeDownlink).where(
        EdgeDownlink.company_id == company_id,
        EdgeDownlink.idempotency_key == downlink_key,
    ))).scalar_one_or_none()
    if existing_task is None:
        db.add(EdgeDownlink(
            company_id=company_id, station_id=draft["station_id"], kind="partners",
            payload={"partners": [{
                "id": str(canonical.id), "name": canonical.name,
                "name_full": canonical.full_name or "", "inn": canonical.inn,
                "kpp": canonical.kpp or "", "role": draft["role"] or "supplier",
                "comment": draft["comment"] or "", "archived": False,
            }]},
            note=f"partner-draft:{draft_id}", idempotency_key=downlink_key,
        ))
    await db.commit()
    return {"action": action, "draft_id": draft_id, "name": canonical.name,
            "station_id": draft["station_id"], "supplier_id": str(canonical.id),
            "partner_id": partner_id, "pushed": True}


async def resolve_nsi_proposal(db: AsyncSession, company_id, proposal_id: int,
                               action: str, note: str | None = None) -> dict:
    """Решение центра по заявке станции об ошибке в сетевой карточке.

    Принять — значит применить правку к канону: со станции она не применялась,
    там карточка всё это время оставалась прежней. Отклонить — значит закрыть
    заявку с пояснением; станция увидит, что вопрос разобран, и не будет слать
    его снова.

    Правка применяется только к тому полю, о котором заявили. «Заодно поправлю
    название» здесь не делается: заявка — это ответственность конкретного
    человека за конкретное значение.
    """
    if action not in ("accept", "reject"):
        raise ValueError(f"неизвестное решение: {action}")

    p = (await db.execute(text("""
        SELECT id, station_id, item_uuid, field, proposed, resolved_at
        FROM edge.nsi_proposal WHERE id = :id AND company_id = :cid
    """), {"id": proposal_id, "cid": company_id})).mappings().first()
    if p is None:
        raise ValueError("заявка не найдена")
    if p["resolved_at"] is not None:
        raise ValueError("заявка уже разобрана")

    применено = None
    if action == "accept":
        item = (await db.execute(text("""
            SELECT id FROM edge.item WHERE external_uuid = CAST(:u AS uuid)
        """), {"u": p["item_uuid"]})).mappings().first()
        if item is None:
            raise ValueError("карточка сети не найдена — заявка относится к чужому товару")

        поле, значение = p["field"], (p["proposed"] or "").strip()
        if поле in ("name", "unit", "vat"):
            колонка = {"name": "name", "unit": "unit", "vat": "vat_rate"}[поле]
            await db.execute(text(f"""
                UPDATE edge.item SET {колонка} = :v WHERE id = :id
            """), {"v": значение, "id": item["id"]})
            применено = f"{колонка} = {значение}"
        elif поле == "barcode_add":
            # Тот же приём, что при признании черновика: чужой активный код не
            # перевешиваем молча — это ломает кассу тому, кто им сейчас торгует.
            занят = (await db.execute(text("""
                SELECT item_id FROM edge.barcode WHERE code = :c AND status = 'active'
            """), {"c": значение})).scalar_one_or_none()
            if занят is not None and занят != item["id"]:
                raise ValueError(f"штрихкод {значение} активен у другой карточки — "
                                 "разберите это как коллизию")
            await db.execute(text("""
                INSERT INTO edge.barcode (item_id, code, status) VALUES (:i, :c, 'active')
                ON CONFLICT DO NOTHING
            """), {"i": item["id"], "c": значение})
            применено = f"добавлен штрихкод {значение}"
        elif поле == "barcode_remove":
            await db.execute(text("""
                UPDATE edge.barcode SET status = 'historical',
                       note = coalesce(note || ' · ', '') || :note
                 WHERE item_id = :i AND code = :c AND status = 'active'
            """), {"i": item["id"], "c": значение,
                   "note": f"снят по заявке АЗС {p['station_id']}"})
            применено = f"снят штрихкод {значение}"
        else:
            raise ValueError(f"неизвестное поле заявки: {поле}")

    await db.execute(text("""
        UPDATE edge.nsi_proposal
           SET resolved_at = now(), rejected = :rej, note = :n
         WHERE id = :id
    """), {"id": proposal_id, "rej": action == "reject", "n": note})
    await db.commit()
    return {"action": action, "proposal_id": proposal_id,
            "station_id": p["station_id"], "applied": применено}


# ── Коллизии штрихкодов ─────────────────────────────────────────────────────
#
# Один штрихкод не может быть активен у двух карточек: это ловит уникальный
# индекс, и это не формальность. Касса ищет товар по ШК, и если код принадлежит
# двум позициям, продаётся та, которая выгрузилась последней, — а вторая
# «исчезает с полки», хотя лежит.
#
# Претензия на чужой код записывается строкой rejected: молча перевешивать
# нельзя (сломается касса тому, кто по нему сейчас пробивается), молча забыть
# тоже — товар так и останется непродаваемым. Поэтому очередь на решение.

async def barcode_collisions(db: AsyncSession, company_id, limit: int = 200) -> list[dict]:
    """Коды, на которые претендуют две карточки."""
    rows = (await db.execute(text("""
        SELECT r.id            AS claim_id,
               r.code,
               r.note          AS claim_note,
               r.created_at    AS claimed_at,
               ci.id           AS claimant_id,
               ci.name         AS claimant_name,
               ci.unit         AS claimant_unit,
               ci.source       AS claimant_source,
               a.id            AS holder_barcode_id,
               oi.id           AS holder_id,
               oi.name         AS holder_name,
               oi.unit         AS holder_unit,
               a.last_sold     AS holder_last_sold,
               (SELECT count(*) FROM edge.ns_code n
                 WHERE n.barcode_id = a.id AND n.status = 'active') AS holder_ns_codes,
               (SELECT coalesce(sum(st.qty), 0) FROM edge.stock st
                 WHERE st.barcode_id = a.id)                        AS holder_stock
        FROM edge.barcode r
        JOIN edge.item ci ON ci.id = r.item_id
        JOIN edge.barcode a ON a.code = r.code AND a.status = 'active'
        JOIN edge.item oi ON oi.id = a.item_id
        WHERE r.status = 'rejected'
        ORDER BY r.created_at DESC
        LIMIT :lim
    """), {"lim": limit})).mappings().all()

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


async def resolve_collision(db: AsyncSession, company_id, claim_id: int,
                            action: str, note: str | None = None) -> dict:
    """Решение по коллизии штрихкода.

      · move — код действительно принадлежит претенденту. Прежний владелец
               получает статус historical (не удаляем: по этому коду продавали,
               и вчерашние чеки должны читаться), претендент — active.
      · drop — претензия ошибочна, код остаётся у нынешнего владельца.

    Перевешивание меняет то, чем товар пробивается в кассе, поэтому станции
    после него нужна перевыгрузка — вызывающий ставит задания НСИ на обе
    карточки.
    """
    row = (await db.execute(text("""
        SELECT r.id, r.code, r.item_id AS claimant_id,
               a.id AS holder_barcode_id, a.item_id AS holder_id
        FROM edge.barcode r
        JOIN edge.barcode a ON a.code = r.code AND a.status = 'active'
        WHERE r.id = :id AND r.status = 'rejected'
    """), {"id": claim_id})).mappings().first()
    if row is None:
        raise ValueError("претензия не найдена или уже разобрана")

    if action == "drop":
        await db.execute(text("DELETE FROM edge.barcode WHERE id = :id"), {"id": claim_id})
        await db.commit()
        return {"action": "drop", "code": row["code"], "holder_id": row["holder_id"]}

    if action != "move":
        raise ValueError(f"неизвестное решение: {action}")

    # Порядок важен: сначала снимаем активность с прежнего владельца, иначе
    # уникальный индекс не даст второму коду стать активным.
    await db.execute(text("""
        UPDATE edge.barcode SET status = 'historical', note = coalesce(note || ' · ', '') || :n
        WHERE id = :id
    """), {"id": row["holder_barcode_id"],
           "n": note or "код передан другой карточке по решению центра"})
    await db.execute(text("""
        UPDATE edge.barcode SET status = 'active', note = :n WHERE id = :id
    """), {"id": claim_id, "n": note})
    await db.commit()
    return {"action": "move", "code": row["code"],
            "claimant_id": row["claimant_id"], "holder_id": row["holder_id"]}
