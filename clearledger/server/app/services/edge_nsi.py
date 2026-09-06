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

import re as _re

import json
import logging
import hashlib
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Counterparty, EdgeDownlink
from app.services import sku
from app.services import item_group_guess
from app.services import matrix

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


def коды_в_обороте(cash_rows: list, own_rows: list) -> list[int]:
    """Номера, которые станция считает занятыми: кассовые плюс наши закрепления.

    Всё, чего нет в этом списке, центр гасит. Пока список строился по одной
    кассе, каждый снимок сносил наши закрепления: они живут в реестре агента и
    в dba.Tariffs до Дня X не попадают.
    """
    номера = set()
    for r in list(cash_rows or []) + list(own_rows or []):
        ns = r.get("КодНС")
        if isinstance(ns, int) and ns:
            номера.add(ns)
    return sorted(номера)


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

    # ⚠⚠ ЦЕНУ ИЗ КАССЫ НЕ ЧИТАЕМ. Направление одностороннее: цену назначает
    # станция (или центр, если политика это разрешает), и мы грузим её В кассу
    # файлом тарифов. Механизма смены цены на самой кассе нет — значит цифра
    # оттуда не факт о цене, а эхо нашей же прошлой выгрузки либо наследие
    # прежнего владельца оборудования.
    #
    # Пока снимок переписывал цену, на только что подключённой станции мы
    # затягивали к себе чужой прайс: касса АЗС 8 в сентябре 2026 держала цены
    # Норд-Лайна, и 225 таких приехали «снимком станции» — при том, что
    # администратор ГИГ не назначил ни одной. В первой же накладной они
    # подставились в графу «Продажа».
    #
    # Расхождение цены кассы с нашей — не повод переписать своё, а повод
    # показать его человеку: считаем и отдаём числом, решение за станцией.
    for uuid, price in seen_price.items():
        current = (await db.execute(text("""
            SELECT p.price FROM edge.price p
            JOIN edge.item i ON i.id = p.item_id
            WHERE i.external_uuid = CAST(:u AS uuid)
              AND p.station_id = :s AND p.valid_to IS NULL
        """), {"u": uuid, "s": station_id})).first()
        if current is None:
            stats["prices_absent"] = stats.get("prices_absent", 0) + 1
        elif abs(float(current.price) - price) >= 0.005:
            stats["prices_differ"] = stats.get("prices_differ", 0) + 1

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
            "   AND (station_id IS NULL OR station_id = :st)"
            " ORDER BY (station_id IS NULL) LIMIT 1"
        ), {"c": code, "st": station_id})).scalar_one_or_none()
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
    #
    # Кассой список не исчерпывается: до Дня X часть кодов закреплена нами и в
    # dba.Tariffs ещё не уехала. Станция везёт их разделом «КодыЛеджер» —
    # без него центр каждым снимком гасил ровно те закрепления, ради которых
    # реестр и заводился (43 гашения за один снимок 11.08.2026).
    own_rows = doc.get("КодыЛеджер") or []
    for r in own_rows:
        code = str(r.get("ШтрихКод") or "")
        ns = r.get("КодНС")
        if not code or not isinstance(ns, int):
            continue
        bc = (await db.execute(text(
            "SELECT id FROM edge.barcode WHERE code = :c AND status = 'active'"
            "   AND (station_id IS NULL OR station_id = :st)"
            " ORDER BY (station_id IS NULL) LIMIT 1"
        ), {"c": code, "st": station_id})).scalar_one_or_none()
        if bc is None:
            continue
        await db.execute(text("""
            UPDATE edge.ns_code SET status = 'released', released_at = :t
             WHERE station_id = :s AND status = 'active'
               AND (ns_code = :n) <> (barcode_id = :b)
        """), {"t": now, "s": station_id, "n": ns, "b": bc})
        await db.execute(text("""
            INSERT INTO edge.ns_code (station_id, ns_code, barcode_id, status)
            VALUES (:s, :n, :b, 'active') ON CONFLICT DO NOTHING
        """), {"s": station_id, "n": ns, "b": bc})

    увиденные = коды_в_обороте(cash_rows, own_rows)
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
            # Артикул станция чеканит сама из выданного блока, и карточка
            # приезжает наверх уже с номером. Принимаем только настоящий номер
            # станционного пула: битую строку лучше не иметь вовсе, чем выдать
            # карточке номер, который человек назвать не сможет.
            артикул_станции = str(doc.get("Артикул") or "").strip()
            if артикул_станции and sku.разобрать(артикул_станции) is None:
                log.warning("станция %s: черновик %s с негодным артикулом %r — номер отброшен",
                            station_id, ключ, артикул_станции)
                артикул_станции = ""
            await db.execute(text("""
                INSERT INTO edge.item_draft
                    (company_id, station_id, source_uuid, name, unit, vat_rate, barcodes,
                     created_at, author, sku)
                VALUES (:cid, :st, :key, :name, :unit, :vat, :codes,
                        coalesce(CAST(:at AS timestamptz), now()), :author,
                        nullif(:sku, ''))
                ON CONFLICT (company_id, station_id, source_uuid) DO UPDATE
                   SET name = excluded.name, unit = excluded.unit,
                       vat_rate = excluded.vat_rate, barcodes = excluded.barcodes,
                       author = coalesce(nullif(excluded.author, ''),
                                         edge.item_draft.author),
                       sku = coalesce(edge.item_draft.sku, excluded.sku)
                 WHERE edge.item_draft.resolved_at IS NULL
            """), {"cid": company_id, "st": station_id, "key": ключ,
                   "name": doc.get("Наименование") or "", "unit": doc.get("Единица") or "шт",
                   "vat": doc.get("СтавкаНДС"), "codes": doc.get("Штрихкоды") or [],
                   "at": _ts(doc.get("Заведена")), "author": doc.get("Автор") or "",
                   "sku": артикул_станции})
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

            # Право станции менять цену спрашиваем У МАТРИЦЫ — и на приёме
            # тоже, а не только при выгрузке вниз.
            #
            # Раньше входящая цена применялась безусловно: станция без права
            # всё равно переписывала цену своей АЗС, а колонка карточки
            # выставлялась в «station» ГЛОБАЛЬНО, то есть за всю сеть. Правило
            # товароведа «цену ведёт центр» не значило ничего в ту сторону,
            # откуда цена и приходит (найдено независимым аудитом 31.08.2026).
            #
            # Сам факт правки остаётся в журнале `station_price_change` при
            # любом решении: станция это сделала, и человек должен видеть, что
            # именно она пыталась поставить.
            item = (await db.execute(text("""
                SELECT id, coalesce(price_owner, 'master') AS price_owner
                FROM edge.item WHERE external_uuid::text = :u
            """), {"u": doc.get("НоменклатураUUID") or ""})).first()
            # Пустое «ЦенаСтала» — снятие цены, а не ноль. Станция снимает
            # цену законно (товар выведен из продажи; станцию только подключили
            # и цен ГИГ ещё нет), и это состояние должно доехать снятием: ноль
            # открытой ценой означал бы «продаём даром». 05.09.2026 так в центр
            # приехали 393 нуля с АЗС 8.
            сырая_цена = doc.get("ЦенаСтала")
            цену_сняли = сырая_цена is None or float(сырая_цена) <= 0
            new_price = 0.0 if цену_сняли else float(сырая_цена)
            if item is not None and not await matrix.цену_ведёт_станция(
                    db, company_id, station_id, item.id):
                stats["price_denied"] = stats.get("price_denied", 0) + 1
                log.warning(
                    "АЗС %s прислала цену по позиции, на которую матрица не даёт "
                    "права: item_id=%s, цена %s — в проекцию не применена",
                    station_id, item.id, new_price)
                continue
            if item is not None and new_price >= 0:
                changed_at = _ts(doc.get("Момент")) or datetime.now(timezone.utc)
                await db.execute(text("""
                    UPDATE edge.price SET valid_to = :at
                    WHERE item_id = :item AND station_id = :st AND valid_to IS NULL
                """), {"at": changed_at, "item": item.id, "st": station_id})
                if not цену_сняли:
                    await db.execute(text("""
                        INSERT INTO edge.price (item_id, station_id, price, valid_from, author)
                        VALUES (:item, :st, :price, :at, :author)
                    """), {"item": item.id, "st": station_id, "price": new_price,
                           "at": changed_at, "author": doc.get("Автор") or "станция"})
                else:
                    stats["price_cleared"] = stats.get("price_cleared", 0) + 1

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
                             note: str | None = None,
                             group_id: int | None = None) -> dict:
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
        SELECT id, station_id, name, unit, vat_rate, barcodes, resolved_at, source_uuid, sku
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
        # Артикул выдаётся В МОМЕНТ РОЖДЕНИЯ карточки, а не когда-нибудь потом.
        # Позиция матрицы без номера — та же невидимка: её не назвать по
        # телефону, не напечатать на ценнике и не найти в 1С.
        # Станция чеканит номер из своего блока и уже назвала им товар — на
        # ценнике, в накладной, в разговоре. Признание не имеет права его
        # сменить: человек продолжает называть карточку тем же номером.
        # Свой выдаём только карточке, приехавшей без номера (агент старой
        # версии или блок кончился).
        артикул = str(draft["sku"] or "").strip()
        if артикул and sku.разобрать(артикул) is None:
            артикул = ""
        if артикул:
            занят = (await db.execute(text(
                "SELECT 1 FROM edge.item WHERE sku = :s"), {"s": артикул})).first()
            if занят is not None:
                log.warning("артикул %s станции %s уже занят в сети — выдаём свой",
                            артикул, draft["station_id"])
                артикул = ""
        if not артикул:
            артикул = await sku.выдать_центральный(db)
        # Товарная группа проставляется В МОМЕНТ ЗАВЕДЕНИЯ, а не «потом».
        #
        # Карточка без группы — невидимка: она не попадает в отчёты по группам и
        # НЕ УЕЗЖАЕТ В КАССУ, потому что отдел кассы приходит свойством группы.
        # 31.08.2026 так на 208 висели десять позиций с товаром на полке.
        # Не указали явно — берём подсказку по названию; не сработала и она —
        # заводим без группы, но это видно счётчиком «без группы» в здоровье
        # каталога, а не тишиной.
        if group_id is None:
            подсказка = await item_group_guess.предложить(db, draft["name"])
            if подсказка is not None:
                group_id = подсказка["group_id"]
        row = (await db.execute(text("""
            INSERT INTO edge.item (external_uuid, sku, name, unit, vat_rate, source,
                                   price_owner, company_id, group_id)
            VALUES (gen_random_uuid(), :sku, :name, :unit, :vat, 'station', 'station',
                    :cid, :group)
            RETURNING id, external_uuid
        """), {"sku": артикул, "cid": company_id, "group": group_id,
               "name": draft["name"], "unit": draft["unit"] or "шт",
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
        # Занятость проверяем В ЯРУСЕ КОДА: сетевой EAN занят для всех, а
        # внутренний номер кухни — только для своей станции. Иначе «9233» с
        # АЗС 8 считался бы занятым чизкейком 208, где это другой товар.
        занят = (await db.execute(text("""
            SELECT item_id FROM edge.barcode
             WHERE code = :c AND status = 'active'
               AND (station_id IS NULL OR station_id = :st)
        """), {"c": code, "st": draft["station_id"]})).first()
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
        # Короткий номер — внутренний код станции, а не GTIN: закрепляем его
        # за станцией, иначе соседняя АЗС со своей нумерацией не сможет завести
        # свой товар под тем же номером.
        await db.execute(text("""
            INSERT INTO edge.barcode (item_id, code, status, station_id)
            VALUES (:i, :c, 'active', :st)
            ON CONFLICT DO NOTHING
        """), {"i": item_id, "c": code,
               "st": draft["station_id"] if len(code) < 8 else None})
        привязано += 1

    await db.execute(text("""
        UPDATE edge.item_draft SET resolved_at = now(), resolved_item = :item, note = :n
        WHERE id = :id
    """), {"id": draft_id, "item": item_id, "n": note})

    # Закрываем заявки-близнецы — те же штрихкоды, тот же товар.
    #
    # Станция заводит карточку заново, когда не видит уже заведённую: 04.09.2026
    # «Печенье Чоко-Пай» приехало ТРЕМЯ заявками за девять минут, от одного
    # человека, с тремя разными артикулами. Разбирать одно и то же трижды —
    # работа впустую, а оставить непризнанным хоть одну значит держать смену.
    близнецы: list[int] = []
    if codes:
        близнецы = [int(r[0]) for r in (await db.execute(text("""
            SELECT d.id FROM edge.item_draft d
            WHERE d.company_id = :cid AND d.id <> :id
              AND d.resolved_at IS NULL AND NOT d.rejected
              AND EXISTS (
                  SELECT 1 FROM unnest(d.barcodes) AS c
                  WHERE regexp_replace(c, '[^0-9]', '', 'g') = ANY(:codes)
              )
        """), {"cid": company_id, "id": draft_id,
               "codes": [_re.sub(r"[^0-9]", "", c) for c in codes]})).all()]
        if близнецы:
            await db.execute(text("""
                UPDATE edge.item_draft
                SET resolved_at = now(), resolved_item = :item,
                    note = coalesce(note, '') || ' · закрыт вместе с заявкой #' || :id
                WHERE id = ANY(:ids)
            """), {"item": item_id, "id": str(draft_id), "ids": близнецы})

    await db.commit()
    return {"action": action, "draft_id": draft_id, "item_id": item_id,
            "uuid": canon_uuid, "barcodes_linked": привязано, "collisions": коллизий,
            "station_id": draft["station_id"], "codes": codes,
            "twins_closed": близнецы}


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
          -- Удалённая карточка не спорит за код.
          --
          -- Из ста претензий восемь стояли за карточками, помеченными
          -- удалёнными: решать там нечего, а список они раздували и заставляли
          -- разбирать вручную то, чего уже нет.
          AND NOT ci.deleted AND NOT oi.deleted
        ORDER BY r.created_at DESC
        LIMIT :lim
    """), {"lim": limit})).mappings().all()

    def сжать(имя: str) -> str:
        return "".join(c for c in (имя or "").lower() if c.isalnum())

    out = []
    for r in rows:
        d = dict(r)
        # Совпали имена — это не спор за код, а две карточки одного товара.
        # Передача кода тут ничего не решит: он останется у одного из дублей, а
        # второй продолжит жить своей рецептурой. Лечится слиянием.
        d["same_item"] = сжать(r["claimant_name"]) == сжать(r["holder_name"])
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


# Сколько расхождений держим списком. Счётчики считаем по всем, но экрану нужны
# примеры, а не выгрузка: если разошлась тысяча позиций, беда видна и по сотне.
ПОКАЗЫВАТЬ_РАСХОЖДЕНИЙ = 200


async def ingest_station_catalog(db: AsyncSession, company_id, station_id: int,
                                 docs: list[dict]) -> dict:
    """Сверить каталог станции с сетевым и запомнить расхождения.

    Отвечает на вопрос «что станция знает, а центр — нет». 30.08.2026 десять
    напитков торговались на 208 четыре дня, а в центре их не было вовсе:
    карточка, легшая в базу станции не через приём пакета НСИ, называла себя
    сетевой, и заявка по ней не собиралась. Нашлись случайно — при раздаче
    артикулов. Теперь сравнение идёт каждым тактом станции.

    Черновики станции в расхождения не попадают: они ждут признания на своём
    экране, это работа, а не дыра.
    """
    сводка = next((d for d in docs
                   if isinstance(d, dict) and d.get("Тип") == "catalog_digest"), None)
    if сводка is None:
        return {"catalog_digest": 0}

    позиции = [p for p in (сводка.get("Позиции") or []) if isinstance(p, dict)]
    на_станции = {str(p.get("UUID") or ""): p for p in позиции if p.get("UUID")}

    все_карточки = {
        str(r["uuid"]): r for r in (await db.execute(text("""
            SELECT external_uuid::text AS uuid, coalesce(sku, '') AS sku, name,
                   id, deleted
            FROM edge.item
        """))).mappings().all()
    }
    в_центре = {u: r for u, r in все_карточки.items() if not r["deleted"]}

    нет_в_центре, черновиков = [], 0
    удаление_не_доехало = []
    for uuid_, позиция in на_станции.items():
        if uuid_ in в_центре:
            continue
        # Карточка, удалённая в центре, но живая на станции, — не «дыра в
        # сети», а отставшая станция: сеть о товаре знает и решила его убрать,
        # просто дельта не доехала. Диагноз «нет в центре» тут пугает зря, а
        # чинится это само — задание с карточкой везёт признак удаления.
        удалённая = все_карточки.get(uuid_)
        if удалённая is not None and удалённая["deleted"]:
            удаление_не_доехало.append(int(удалённая["id"]))
            continue
        # Карточка, заведённая станцией и ещё не признанная, живёт под своим
        # временным идентификатором — это очередь на разбор, а не потеря.
        if uuid_.startswith("draft-") or str(позиция.get("Источник") or "") == "station":
            черновиков += 1
            continue
        нет_в_центре.append({
            "uuid": uuid_, "sku": позиция.get("Артикул") or "",
            "name": позиция.get("Наименование") or "",
            "barcode": позиция.get("Штрихкод") or "",
        })

    # Обратная сторона: карточка сети, которой на станции нет. В версии, где
    # станция получает справочник целиком, это значит, что дельта не доехала.
    нет_на_станции = [
        {"uuid": uuid_, "sku": строка["sku"], "name": строка["name"]}
        for uuid_, строка in в_центре.items() if uuid_ not in на_станции
    ]

    # Досылаем отставшие удаления тем же тактом, каким заметили: станция на
    # связи прямо сейчас, а ждать, пока кто-то нажмёт кнопку в центре, значит
    # держать на полке товар, выведенный из ассортимента месяц назад.
    if удаление_не_доехало:
        from app.routers.store_router import _queue_nsi_delta  # цикл импорта
        for item_id in удаление_не_доехало[:200]:
            try:
                await _queue_nsi_delta(db, company_id, item_id, station_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("АЗС %s: удаление карточки %s не досланo: %s",
                            station_id, item_id, exc)
        log.info("АЗС %s: досланы удаления карточек — %d",
                 station_id, len(удаление_не_доехало))

    await db.execute(text("""
        INSERT INTO edge_catalog_check
               (company_id, station_id, checked_at, taken_at, station_items,
                center_items, missing_in_center, missing_on_station,
                drafts_pending)
        VALUES (:cid, :st, now(), :taken, :station_items,
                :center_items, CAST(:missing_center AS jsonb),
                CAST(:missing_station AS jsonb), :drafts)
        ON CONFLICT (company_id, station_id) DO UPDATE
           SET checked_at = now(), taken_at = excluded.taken_at,
               station_items = excluded.station_items,
               center_items = excluded.center_items,
               missing_in_center = excluded.missing_in_center,
               missing_on_station = excluded.missing_on_station,
               drafts_pending = excluded.drafts_pending
    """), {"cid": company_id, "st": station_id,
           # Момент съёмки приводим НА СТОРОНЕ PYTHON: asyncpg типизирует
           # параметр по колонке и строку в timestamptz не превращает, а CAST
           # в SQL тут не спасает — та же грабля, что у `_ts` выше.
           "taken": _ts(сводка.get("Снято")),
           "station_items": len(на_станции), "center_items": len(в_центре),
           "missing_center": json.dumps(нет_в_центре[:ПОКАЗЫВАТЬ_РАСХОЖДЕНИЙ],
                                        ensure_ascii=False),
           "missing_station": json.dumps(нет_на_станции[:ПОКАЗЫВАТЬ_РАСХОЖДЕНИЙ],
                                         ensure_ascii=False),
           "drafts": черновиков})
    await db.commit()

    if нет_в_центре:
        log.warning("АЗС %s: карточек нет в центре — %d (пример: %s)",
                    station_id, len(нет_в_центре), нет_в_центре[0]["name"])
    return {"catalog_digest": len(позиции),
            "deletions_resent": len(удаление_не_доехало),
            "missing_in_center": len(нет_в_центре),
            "missing_on_station": len(нет_на_станции),
            "drafts_pending": черновиков}


async def ingest_cash_check(db: AsyncSession, company_id, station_id: int,
                            docs: list[dict]) -> dict:
    """Запомнить сверку «касса ↔ учёт» станции для надзора сети.

    Центр остаток кассы NeftoMS сам не видит — станция шлёт снимок пакетом
    cash_state. Направление уже разложено на станции (выше учёта — разбор, ниже
    — окно разнесения, сырьё — норма), центр только сохраняет одну строку на
    станцию. Список «касса выше учёта» приходит обрезанным до лимита станции.
    """
    св = next((d for d in docs
               if isinstance(d, dict) and d.get("Тип") == "cash_state"), None)
    if св is None:
        return {"cash_state": 0}

    позиции = [p for p in (св.get("Позиции") or []) if isinstance(p, dict)]
    above_items = [{
        "ns_code": p.get("КодНС"),
        "name": p.get("Наименование") or "",
        "barcode": p.get("Штрихкод") or "",
        "in_cash": p.get("ВКассе"),
        "should_be": p.get("Должно"),
        "section": p.get("Отдел"),
    } for p in позиции]

    await db.execute(text("""
        INSERT INTO edge_cash_check
               (company_id, station_id, checked_at, taken_at, in_cash, should_be,
                matched, above, below, raw_material, not_in_cash, no_card, above_items)
        VALUES (:cid, :st, now(), :taken, :in_cash, :should_be, :matched,
                :above, :below, :raw, :not_in_cash, :no_card, CAST(:items AS jsonb))
        ON CONFLICT (company_id, station_id) DO UPDATE
           SET checked_at = now(), taken_at = excluded.taken_at,
               in_cash = excluded.in_cash, should_be = excluded.should_be,
               matched = excluded.matched, above = excluded.above,
               below = excluded.below, raw_material = excluded.raw_material,
               not_in_cash = excluded.not_in_cash, no_card = excluded.no_card,
               above_items = excluded.above_items
         -- ⚠ Старый снимок не перетирает свежий.
         --
         -- Сверка — СОСТОЯНИЕ, а не событие: у неё есть время съёмки, и назад
         -- время не идёт. Пакет, застрявший в очереди станции, доставляется
         -- повторно раз за разом; ревизия при этом не создаётся (тело то же),
         -- а обработка идёт — и утренний снимок ложился поверх вечернего.
         -- 01.09.2026 на 208 экран так показывал «снято в 11:51», когда
         -- последний снимок был снят в 20:48, и цифры стояли мёртво весь день.
           WHERE edge_cash_check.taken_at IS NULL
              OR excluded.taken_at IS NULL
              OR excluded.taken_at >= edge_cash_check.taken_at
    """), {"cid": company_id, "st": station_id,
           "taken": _ts(св.get("Снято")),
           "in_cash": int(св.get("ВКассе") or 0),
           "should_be": int(св.get("ДолжноБыть") or 0),
           "matched": int(св.get("Совпадает") or 0),
           "above": int(св.get("ВышеУчёта") or 0),
           "below": int(св.get("НижеУчёта") or 0),
           "raw": int(св.get("Сырьё") or 0),
           "not_in_cash": int(св.get("НетВКассе") or 0),
           "no_card": int(св.get("БезСправочника") or 0),
           "items": json.dumps(above_items, ensure_ascii=False)})
    await db.commit()

    if св.get("ВышеУчёта"):
        log.warning("АЗС %s: касса выше учёта — %d позиций",
                    station_id, св.get("ВышеУчёта"))
    return {"cash_state": 1, "above": int(св.get("ВышеУчёта") or 0)}
