"""Ручной пакет Ledger → БП ГИГ по контракту STORE_BP_EXPORT_CONTRACT.md.

Основной путь строится из канонических Edge-документов и мастер-НСИ. Старый
oneC-путь сохранён как переходный fallback. Документы всегда непроведённые,
идентификатор и хеш стабильны для неизменной версии фактов.
"""
from __future__ import annotations

import json as _json
import logging as _logging
import os as _os
import re as _re
import uuid as _uuid
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, CbNomenclature, StockOnHand, CbRef, CbInventoryDoc, CbMovementDoc
from app.services.bp_canon import packet_hash
from app.services.goods_dashboard import _day

_log = _logging.getLogger("edge.bp_export")

_WH_208 = {"208", "20800002"}   # склады станции 208 (Торговый зал + Склад)

# СтавкаНДС ЦБ («22%») → каноническое имя контракта («НДС22»). §4.
_NDS_MAP = {
    "22%": "НДС22", "20%": "НДС20", "18%": "НДС18", "10%": "НДС10",
    "7%": "НДС7", "5%": "НДС5", "0%": "НДС0",
    "18% / 118%": "НДС18_118", "20% / 120%": "НДС20_120", "22% / 122%": "НДС22_122",
    "10% / 110%": "НДС10_110", "5% / 105%": "НДС5_105", "7% / 107%": "НДС7_107",
    "без ндс": "БезНДС", "безндс": "БезНДС",
}

# Ставки, которые сопоставляет приёмник (TL_МаппингЦБ.СопоставитьСтавкуНДС). Всё, что
# вне списка, роняет документ в поступлениях и возвратах поставщику.
_BP_VAT_NAMES = frozenset(_NDS_MAP.values())
_DOC_ORDER = {
    "recipe": 0, "purchase": 1, "production_release": 2,
    "retail_sale_sidegoods": 3, "return_purchase": 4, "inventory": 5,
    "gain": 6, "writeoff": 7, "transfer": 8,
}


def _nds(v: str | None) -> str:
    """Канон-имя ставки. Пусто → "", неизвестное → исходная строка ЦБ.

    Неизвестную ставку нельзя ни обнулять, ни подменять: приёмник на несопоставленной
    ставке роняет документ (`ВызватьИсключение "Ставка НДС '…' не сопоставлена"`), и в
    TL_ОшибкиЗагрузки бухгалтер должен увидеть, ЧТО пришло из ЦБ, — с пустой строкой
    сообщение бесполезно. Возврат исходного значения заодно гасит фолбэк `_nds(строка)
    or _nds(ставка_номенклатуры)`: подставлять справочную ставку вместо непонятой —
    это ошибка приёмника Норд-Лайна (НДС10 пищевки молча становился НДС22), от которой
    контракт и защищается. Фолбэк остаётся работать там, где ставки в ЦБ просто нет.
    """
    v = (v or "").strip()
    return _NDS_MAP.get(v.lower(), _NDS_MAP.get(v, v))


def _iso(v) -> str:
    """ISO с таймзоной +03:00. На входе — ISO-строка из meta (уже +00:00) или пусто."""
    if not v:
        return ""
    s = str(v)
    # meta хранит +00:00; контракт БП — локальное +03:00. Пересчёт не делаем
    # (смены ЦБ уже в локальном времени станции) — только нормализуем суффикс.
    return s.replace("+00:00", "+03:00")


def _timestamp(value) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _stable_uuid(name: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"ledger.elsyplus.ru/{name}"))


def _vat_from_gross(amount: float, rate: str) -> float:
    match = _re.search(r"(22|20|18|10|7|5|0)", rate or "")
    percent = float(match.group(1)) if match else 0.0
    return round(amount * percent / (100 + percent), 2) if percent else 0.0


def _document_sort_key(doc: dict) -> tuple[int, str, str, str]:
    return (
        _DOC_ORDER.get(str(doc.get("Тип") or ""), 99),
        str(doc.get("Дата") or ""),
        str(doc.get("ИсточникUUID") or ""),
        str(doc.get("Номер") or ""),
    )


def package_filename(pkt: dict) -> str:
    """Имя файла пакета по контракту: АЗС{код}_{ГГГГ-ММ-ДД}_смена-{номер}_{uuid}.json."""
    sh = pkt.get("Смена") or {}
    код = str(sh.get("КодАЗС") or 0)
    код = код.zfill(3) if код.isdigit() else "0"
    дата = str(sh.get("Открытие") or "")[:10] or "0000-00-00"
    ном = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(sh.get("НомерСмены") or "").strip()) or "0"
    return f"АЗС{код}_{дата}_смена-{ном}_{pkt.get('ИдентификаторПакета')}.json"


class BpPackageEmitter:
    def __init__(self, session: AsyncSession, company_id):
        self.session = session
        self.company_id = company_id

    async def _nom_map(self) -> dict[str, CbNomenclature]:
        rows = (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()
        return {n.external_ref: n for n in rows}

    async def _refs(self, kind: str) -> dict[str, CbRef]:
        rows = (await self.session.execute(select(CbRef).where(
            CbRef.company_id == self.company_id, CbRef.kind == kind))).scalars().all()
        return {r.external_ref: r for r in rows}

    async def _edge_nom_map(self) -> dict[str, SimpleNamespace]:
        rows = (await self.session.execute(text("""
            SELECT i.external_uuid, i.code_1c, i.name, i.name_full, i.unit,
                   i.vat_rate, i.kind, i.sku_class, i.is_dish, i.deleted,
                   coalesce(array_agg(b.code ORDER BY b.code)
                            FILTER (WHERE b.status = 'active'), '{}') AS barcodes
            FROM edge.item i
            LEFT JOIN edge.barcode b ON b.item_id = i.id
            GROUP BY i.id
        """))).mappings().all()
        return {str(row["external_uuid"]): SimpleNamespace(
            external_ref=str(row["external_uuid"]), code=row["code_1c"],
            name=row["name"], full_name=row["name_full"], article=None,
            vat=row["vat_rate"], unit=row["unit"], kind=row["kind"],
            sku_class=row["sku_class"], is_dish=row["is_dish"],
            deleted=row["deleted"], barcodes=list(row["barcodes"] or []),
        ) for row in rows}

    async def _edge_partners(self) -> dict[str, dict]:
        rows = (await self.session.execute(text("""
            SELECT id, name, name_full, inn, kpp, role, archived
            FROM edge.partner
            WHERE company_id = :company_id
        """), {"company_id": self.company_id})).mappings().all()
        return {str(row["name"] or "").strip().casefold(): dict(row) for row in rows}

    async def _build_edge_shift_package(self, target: DataEntry, shift_key: str) -> dict:
        meta = target.meta or {}
        sm = meta.get("Смена") or {}
        nom = await self._edge_nom_map()
        orgs = await self._refs("organization")
        whs = await self._refs("warehouse")
        partners = await self._edge_partners()
        company_name = (await self.session.execute(text(
            "SELECT name FROM companies WHERE id = :company_id"
        ), {"company_id": self.company_id})).scalar_one_or_none() or ""
        station_rows = (await self.session.execute(text(
            "SELECT id, name, warehouse_uuid FROM edge.station"
        ))).mappings().all()
        station_wh = {int(row["id"]): str(row["warehouse_uuid"]) for row in station_rows}
        warehouse_names = {str(row["warehouse_uuid"]): str(row["name"] or "") for row in station_rows}

        org_uuid = str(sm.get("Организация") or "")
        wh_uuid = str(sm.get("Склад") or "")
        station = str(sm.get("КодАЗС") or "")
        shift_day = _day(sm)
        shift_open = _timestamp(sm.get("Открытие"))
        shift_close = _timestamp(sm.get("Закрытие"))
        if shift_open is not None and shift_close is not None and shift_open > shift_close:
            shift_open, shift_close = shift_close, shift_open
        target_internal = str(sm.get("НомерСменыВнутр") or "").strip()
        target_number = str(sm.get("НомерСмены") or sm.get("ОСЭНомер") or "").strip()

        try:
            station_code = int(station)
        except ValueError:
            station_code = 0
        shift = {
            "КодАЗС": station_code,
            "СкладUUID": wh_uuid,
            "ОрганизацияUUID": org_uuid,
            "НомерСмены": str(sm.get("НомерСмены") or sm.get("ОСЭНомер") or ""),
            "НомерСменыВнутр": sm.get("НомерСменыВнутр") or 0,
            "Открытие": _iso(sm.get("Открытие")),
            "Закрытие": _iso(sm.get("Закрытие")),
            "Оператор": str(sm.get("Оператор") or ""),
            "Касса": str(sm.get("Касса") or ""),
            "ОСЭНомер": str(sm.get("ОСЭНомер") or sm.get("НомерСмены") or ""),
        }

        nsi_nom: set[str] = set()
        nsi_org = {org_uuid} if org_uuid else set()
        nsi_wh = {wh_uuid} if wh_uuid else set()
        partner_nsi: dict[str, dict] = {}

        def item_line(line: dict, number: int, with_vat: bool = True) -> dict:
            result = deepcopy(line)
            item_uuid = str(result.get("Номенклатура") or "")
            if item_uuid:
                nsi_nom.add(item_uuid)
            card = nom.get(item_uuid)
            result["НомерСтроки"] = result.get("НомерСтроки") or number
            result["Единица"] = result.get("Единица") or (card.unit if card else "")
            if with_vat:
                result["СтавкаНДС"] = _nds(result.get("СтавкаНДС")) or _nds(card.vat if card else "")
                if "СуммаНДС" not in result:
                    result["СуммаНДС"] = _vat_from_gross(
                        float(result.get("Сумма") or 0), result["СтавкаНДС"])
            return result

        def partner_uuid(value: str) -> str:
            name = str(value or "").strip()
            if not name:
                return ""
            try:
                _uuid.UUID(name)
                return name
            except ValueError:
                pass
            row = partners.get(name.casefold())
            uid = _stable_uuid(f"edge-partner/{self.company_id}/{row['id'] if row else name.casefold()}")
            partner_nsi[uid] = {
                "name": row["name"] if row else name,
                "full_name": (row.get("name_full") if row else None) or (row["name"] if row else name),
                "inn": (row.get("inn") if row else None) or "",
                "kpp": (row.get("kpp") if row else None) or "",
                "archived": bool(row.get("archived")) if row else False,
            }
            return uid

        sec = meta.get("Секции") or {}
        retail_lines: list[dict] = []
        dishes: set[str] = set()
        inline_recipes: dict[str, list[dict]] = {}
        for key, sku_class in (("продажа_сопутка", "Сопутка"),
                               ("продажа_общепит", "Общепит")):
            for line in (sec.get(key) or {}).get("строки") or []:
                result = item_line(line, len(retail_lines) + 1)
                result["КлассSKU"] = sku_class
                if sku_class == "Общепит":
                    result["ЭтоБлюдо"] = True
                    # Блюдо сначала выпускается по ТТК, затем продаётся как
                    # сопутствующий товар. Льготные ставки ингредиентов на
                    # продажу готового блюда не переносятся.
                    result["СтавкаНДС"] = "НДС22"
                    result["СуммаНДС"] = _vat_from_gross(
                        float(result.get("Сумма") or 0), "НДС22")
                    dish_uuid = str(result.get("Номенклатура") or "")
                    if dish_uuid:
                        dishes.add(dish_uuid)
                        inline_recipes[dish_uuid] = result.pop("Ингредиенты", []) or []
                retail_lines.append(result)
        returned = [item_line(line, index) for index, line in enumerate(
            (sec.get("возвраты") or {}).get("строки") or [], 1)]
        payments = []
        for payment in (sec.get("оплаты") or {}).get("строки") or []:
            kind = str(payment.get("ВидОплаты") or payment.get("ФормаОплатыКанон")
                       or payment.get("ФормаОплаты") or "")
            payments.append({"ВидОплаты": kind, "Сумма": round(float(payment.get("Сумма") or 0), 2)})
        source_doc = meta.get("Документ") or {}
        retail = {
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": str(source_doc.get("ИсточникUUID") or sm.get("Смена") or ""),
            "Номер": str(source_doc.get("Номер") or shift["НомерСмены"]),
            "Дата": _iso(source_doc.get("Дата") or sm.get("Закрытие")),
            "Проведен": False,
            "ПометкаУдаления": bool(source_doc.get("ПометкаУдаления", False)),
            "Организация": str(source_doc.get("Организация") or org_uuid),
            "Склад": str(source_doc.get("Склад") or wh_uuid),
            "Подразделение": "",
            "СуммаДокумента": round(float(source_doc.get("СуммаДокумента") or 0), 2),
            "ВалютаДокумента": "RUB", "СуммаВключаетНДС": True,
            "Товары": retail_lines, "ВозвращенныеТовары": returned,
            "СуммаНДС": round(sum(float(line.get("СуммаНДС") or 0) for line in retail_lines)
                                      - sum(float(line.get("СуммаНДС") or 0) for line in returned), 2),
            "Оплаты": payments,
        }
        if retail["Организация"]:
            nsi_org.add(retail["Организация"])
        if retail["Склад"]:
            nsi_wh.add(retail["Склад"])

        entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id,
            DataEntry.source == "edge",
        ))).scalars().all()

        def in_shift(entry: DataEntry) -> bool:
            entry_shift = (entry.meta or {}).get("Смена") or {}
            if str(entry_shift.get("КодАЗС") or "") != station:
                return False
            entry_internal = str(entry_shift.get("НомерСменыВнутр") or "").strip()
            if target_internal and entry_internal:
                return target_internal == entry_internal
            entry_number = str(entry_shift.get("НомерСмены")
                               or entry_shift.get("ОСЭНомер") or "").strip()
            if entry.doc_type_id in {"production_release", "recipe"} \
                    and target_number and entry_number:
                return target_number == entry_number
            doc = (entry.meta or {}).get("Документ") or {}
            moment = _timestamp(doc.get("Дата") or entry_shift.get("Открытие"))
            if moment is None or shift_open is None:
                return bool(shift_day) and _day(entry_shift) == shift_day
            if shift_close is None or shift_close <= shift_open:
                return moment == shift_open
            # Полуинтервал не относит документ ровно на границе сразу к двум
            # соседним сменам. Выпуск связывается выше по номеру смены.
            return shift_open <= moment < shift_close

        related = [entry for entry in entries if in_shift(entry) and entry.id != target.id]

        # Документы, для которых приёмник TradeLedger.cfe пока не имеет раскладки
        # (возврат покупателя, списание ингредиентов). Раньше их наличие роняло
        # ValueError — и вся смена не выгружалась из-за одного возврата, хотя
        # сопутка и топливо собраны. Возврат покупателя — штатная операция
        # магазина, ронять из-за него всю смену нельзя.
        #
        # Правильная раскладка этих типов в БП требует стороны 1С (как их примет
        # .cfe), поэтому здесь их не собираем, а откладываем: смена уходит без
        # них, факт откладывания виден в логе, а сами документы остаются в
        # DataEntry — перевыгрузка подхватит их, когда приёмник научится. Молча
        # они не теряются, но и вслепую в пакет, который может уронить .cfe, не
        # попадают.
        DEFERRED_KINDS = {"return_sale", "ingredients_writeoff"}
        отложено = [entry for entry in related if entry.doc_type_id in DEFERRED_KINDS]
        related = [entry for entry in related if entry.doc_type_id not in DEFERRED_KINDS]
        if отложено:
            виды = sorted({e.doc_type_id for e in отложено})
            _log.warning(
                "смена %s: %d документ(ов) отложено (приёмник БП не поддерживает %s) — "
                "смена выгружена без них, документы ждут в DataEntry",
                shift_key, len(отложено), ", ".join(виды),
            )

        purchases: list[dict] = []
        productions: list[dict] = []
        returns: list[dict] = []
        inventories: list[dict] = []
        gains: list[dict] = []
        writeoffs: list[dict] = []
        transfers: list[dict] = []
        seen: set[tuple[str, str]] = set()
        code2guid = {str((ref.extra or {}).get("code") or ""): uid for uid, ref in whs.items()}
        for entry in related:
            kind = str(entry.doc_type_id or "")
            if kind in {"recipe", "retail_sale_sidegoods"}:
                continue
            doc = deepcopy((entry.meta or {}).get("Документ") or {})
            source_uuid = str(doc.get("ИсточникUUID") or entry.source_id or "")
            dedup = (kind, source_uuid)
            if dedup in seen or doc.get("ПометкаУдаления"):
                continue
            seen.add(dedup)
            doc["Тип"] = kind
            doc["ИсточникUUID"] = source_uuid
            doc["Дата"] = _iso(doc.get("Дата"))
            doc["Проведен"] = False
            doc["Организация"] = str(doc.get("Организация") or org_uuid)
            if doc["Организация"]:
                nsi_org.add(doc["Организация"])
            if kind != "transfer":
                doc["Склад"] = str(doc.get("Склад") or wh_uuid)
                nsi_wh.add(doc["Склад"])
            if kind == "production_release":
                releases = []
                for index, line in enumerate(doc.get("ВыпускБлюд") or [], 1):
                    item_uuid = str(line.get("Номенклатура") or "")
                    if item_uuid:
                        nsi_nom.add(item_uuid)
                    releases.append({
                        **line,
                        "НомерСтроки": line.get("НомерСтроки") or index,
                        "Идентификатор": str(line.get("Идентификатор") or f"dish-{index}"),
                        "Номенклатура": item_uuid,
                        "Единица": line.get("Единица") or (nom[item_uuid].unit if nom.get(item_uuid) else "шт"),
                        "Количество": float(line.get("Количество") or 0),
                        "Цена": float(line.get("Цена") or 0),
                        "Сумма": round(float(line.get("Сумма") or 0), 2),
                    })
                ingredients = []
                for index, line in enumerate(doc.get("Ингредиенты") or [], 1):
                    item_uuid = str(line.get("Номенклатура") or "")
                    if item_uuid:
                        nsi_nom.add(item_uuid)
                    ingredients.append({
                        **line,
                        "НомерСтроки": line.get("НомерСтроки") or index,
                        "ИдентификаторПродукция": str(line.get("ИдентификаторПродукция") or ""),
                        "Номенклатура": item_uuid,
                        "Единица": line.get("Единица") or (nom[item_uuid].unit if nom.get(item_uuid) else ""),
                        "Количество": float(line.get("Количество") or 0),
                    })
                doc["ВыпускБлюд"] = releases
                doc["Ингредиенты"] = ingredients
                doc["ВалютаДокумента"] = str(doc.get("ВалютаДокумента") or "RUB")
                doc["СуммаДокумента"] = round(float(doc.get("СуммаДокумента") or 0), 2)
                productions.append(doc)
                continue
            doc["Товары"] = [item_line(line, index, kind not in {"inventory", "writeoff", "transfer"})
                              for index, line in enumerate(doc.get("Товары") or [], 1)]
            if kind == "purchase":
                doc["Контрагент"] = partner_uuid(doc.get("Контрагент"))
                for index, service in enumerate(doc.get("Услуги") or [], 1):
                    service["НомерСтроки"] = service.get("НомерСтроки") or index
                    service["СтавкаНДС"] = _nds(service.get("СтавкаНДС"))
                    if "СуммаНДС" not in service:
                        service["СуммаНДС"] = _vat_from_gross(
                            float(service.get("Сумма") or 0), service["СтавкаНДС"])
                purchases.append(doc)
            elif kind == "return_purchase":
                doc["Контрагент"] = partner_uuid(doc.get("Контрагент"))
                returns.append(doc)
            elif kind == "inventory":
                for line in doc["Товары"]:
                    price = float(line.get("Цена") or 0)
                    line["Сумма"] = round(float(line.get("Количество") or 0) * price, 2)
                    line["СуммаУчет"] = round(float(line.get("КоличествоУчет") or 0) * price, 2)
                inventories.append(doc)
            elif kind == "gain":
                gains.append(doc)
            elif kind == "writeoff":
                writeoffs.append(doc)
            elif kind == "transfer":
                direction = str(doc.get("Направление") or "")
                from_uuid = code2guid.get(str(doc.get("МестоОтправитель") or ""), "")
                to_uuid = code2guid.get(str(doc.get("МестоПолучатель") or ""), "")
                if direction == "out":
                    from_uuid = from_uuid or wh_uuid
                    to_uuid = to_uuid or station_wh.get(int(doc.get("КодАЗСПолучателя") or 0), "")
                elif direction == "in":
                    to_uuid = to_uuid or wh_uuid
                doc["СкладОтправитель"] = from_uuid
                doc["СкладПолучатель"] = to_uuid
                if not from_uuid or not to_uuid:
                    raise ValueError(f"Перемещение {doc.get('Номер') or source_uuid}: не определены оба склада БП")
                nsi_wh.update({from_uuid, to_uuid})
                transfers.append(doc)

        # Рецепт берём из того же контекста смены, что и выпуск. Глобальная
        # «последняя карта блюда» делает повторный экспорт старой смены
        # недостоверным после изменения ТТК.
        recipe_entries = [entry for entry in related if entry.doc_type_id == "recipe"]
        recipe_by_dish = {}
        for entry in recipe_entries:
            doc = (entry.meta or {}).get("Документ") or {}
            dish_uuid = str(doc.get("БлюдоUUID") or "")
            if dish_uuid:
                recipe_by_dish[dish_uuid] = doc
        recipes = []
        for dish_uuid in sorted(dishes):
            source_recipe = recipe_by_dish.get(dish_uuid) or {}
            ingredients = source_recipe.get("Ингредиенты") or inline_recipes.get(dish_uuid) or []
            output_ingredients = []
            for ingredient in ingredients:
                ingredient_uuid = str(ingredient.get("НоменклатураUUID") or ingredient.get("Номенклатура") or "")
                if not ingredient_uuid:
                    continue
                nsi_nom.add(ingredient_uuid)
                output_ingredients.append({
                    "НоменклатураUUID": ingredient_uuid,
                    "Количество": float(ingredient.get("Количество") or 0),
                    "Единица": ingredient.get("Единица") or (nom[ingredient_uuid].unit if nom.get(ingredient_uuid) else ""),
                })
            recipes.append({
                "Тип": "recipe",
                "ИсточникUUID": str(source_recipe.get("ИсточникUUID") or _stable_uuid(f"edge-recipe/{dish_uuid}")),
                "БлюдоUUID": dish_uuid,
                "БлюдоНаименование": str(source_recipe.get("БлюдоНаименование") or (nom[dish_uuid].name if nom.get(dish_uuid) else "")),
                "ВидРецептуры": source_recipe.get("ВидРецептуры") or "dish",
                "ВерсияТТК": int(source_recipe.get("ВерсияТТК") or 0),
                "ВерсияНабораТТК": str(source_recipe.get("ВерсияНабораТТК") or ""),
                "Выход": float(source_recipe.get("Выход") or 1),
                "ЕдиницаВыхода": str(source_recipe.get("ЕдиницаВыхода") or "шт"),
                "Ингредиенты": output_ingredients,
            })

        released_dishes = {
            str(line.get("Номенклатура") or "")
            for production in productions
            for line in (production.get("ВыпускБлюд") or [])
            if line.get("Номенклатура")
        }
        missing_release = sorted(dishes - released_dishes)
        if missing_release:
            raise ValueError(
                "Пакет БП не собран: для проданных блюд нет выпуска этой смены: "
                + ", ".join(missing_release[:5])
            )

        documents = [*recipes, *purchases, retail, *productions, *returns, *inventories, *gains, *writeoffs, *transfers]
        documents.sort(key=_document_sort_key)
        for doc in documents:
            if doc.get("Тип") != "recipe":
                doc["Проведен"] = False

        def clean(value) -> str:
            return str(value or "").strip()

        nsi = []
        for uid in sorted(nsi_org):
            ref = orgs.get(uid)
            extra = (ref.extra or {}) if ref else {}
            nsi.append({"Тип": "Организация", "ИсточникUUID": uid,
                        "Наименование": clean(ref.name if ref else company_name),
                        "НаименованиеПолное": clean(extra.get("full_name")) or clean(ref.name if ref else company_name),
                        "ИНН": clean(extra.get("inn")), "КПП": clean(extra.get("kpp")),
                        "ОГРН": clean(extra.get("ogrn")), "ОКПО": clean(extra.get("okpo")),
                        "ЮрФизЛицо": clean(extra.get("jur_fiz")) or "ЮрЛицо", "ПометкаУдаления": False})
        for uid in sorted(nsi_wh):
            ref = whs.get(uid)
            extra = (ref.extra or {}) if ref else {}
            nsi.append({"Тип": "Склад", "ИсточникUUID": uid,
                        "Наименование": clean(ref.name if ref else warehouse_names.get(uid)) or f"АЗС {station}",
                        "Код": clean(extra.get("code")), "ВидСклада": clean(extra.get("kind_name")) or "АЗК",
                        "ПометкаУдаления": False})
        for uid, row in sorted(partner_nsi.items()):
            nsi.append({"Тип": "Контрагент", "ИсточникUUID": uid,
                        "Наименование": clean(row["name"]), "НаименованиеПолное": clean(row["full_name"]),
                        "ИНН": clean(row["inn"]), "КПП": clean(row["kpp"]), "ВидКонтрагента": "ЮрЛицо",
                        "ПометкаУдаления": row["archived"]})
        for uid in sorted(nsi_nom):
            card = nom.get(uid)
            sku_class = clean(card.sku_class if card else "") or ("Общепит" if card and card.is_dish else "Сопутка")
            nsi.append({"Тип": "Номенклатура", "ИсточникUUID": uid,
                        "КодЦБ": clean(card.code if card else ""), "Наименование": clean(card.name if card else ""),
                        "НаименованиеПолное": clean(card.full_name if card else "") or clean(card.name if card else ""),
                        "Артикул": clean(card.article if card else ""), "СтавкаНДС": _nds(card.vat if card else ""),
                        "Единица": clean(card.unit if card else ""), "ВидНоменклатуры": clean(card.kind if card else ""),
                        "КлассSKU": sku_class, "ЭтоБлюдо": bool(card.is_dish) if card else uid in dishes,
                        "ШтрихКоды": list(card.barcodes if card else []), "ПометкаУдаления": bool(card.deleted) if card else False})

        packet = {
            "ВерсияФормата": "2",
            "ВремяВыгрузки": shift["Закрытие"] or shift["Открытие"],
            "ИдентификаторПакета": _stable_uuid(f"bp-package/{self.company_id}/edge/{target.source_id or shift_key}"),
            "Источник": "Ledger Edge → Ledger",
            "Смена": shift, "Документы": documents, "НСИ": nsi, "ХешПакета": "",
        }
        packet["ХешПакета"] = packet_hash(packet)
        return packet

    async def build_shift_package(self, shift_key: str) -> dict:
        """Собрать пакет для одной смены (retail_sale + НСИ). shift_key = GUID смены."""
        # найти retail-запись смены
        rows = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source.in_(("edge", "oneC")),
            DataEntry.doc_type_id == "retail_sale_sidegoods"))).scalars().all()
        target = None
        for r in sorted(rows, key=lambda row: row.source != "edge"):
            sm = (r.meta or {}).get("Смена") or {}
            k = str(sm.get("Смена") or f"{_day(sm)}|{sm.get('КодАЗС') or '—'}")
            if k == shift_key:
                target = r
                break
        if target is None:
            raise ValueError(f"смена не найдена: {shift_key}")
        if target.source == "edge":
            return await self._build_edge_shift_package(target, shift_key)

        meta = target.meta or {}
        sm = meta.get("Смена") or {}
        nom = await self._nom_map()
        orgs = await self._refs("organization")
        whs = await self._refs("warehouse")
        kinds = await self._refs("nom_kind")

        # кэш UUID для НСИ
        nsi_nom: set[str] = set()
        nsi_org: set[str] = set()
        nsi_wh: set[str] = set()
        nsi_contr: set[str] = set()
        contr_names: dict[str, str] = {}
        dish_uuids: set[str] = set()  # блюда общепита смены → эмитим их recipe (ТТК)
        dish_inline_ings: dict[str, list] = {}  # OB-1: inline-ТТК из строк продаж (фолбэк)

        org_uuid = str(sm.get("Организация") or "")
        wh_uuid = str(sm.get("Склад") or "")
        if org_uuid:
            nsi_org.add(org_uuid)
        if wh_uuid:
            nsi_wh.add(wh_uuid)

        # ── Смена (шапка) ──
        код = 0
        try:
            код = int(str(sm.get("КодАЗС") or "0").strip() or 0)
        except ValueError:
            код = 0
        shift = {
            "КодАЗС": код,
            "СкладUUID": wh_uuid,
            "ОрганизацияUUID": org_uuid,
            "НомерСмены": str(sm.get("НомерСмены") or sm.get("ОСЭНомер") or "").strip(),
            "НомерСменыВнутр": sm.get("НомерСменыВнутр") or 0,
            "Открытие": _iso(sm.get("Открытие")),
            "Закрытие": _iso(sm.get("Закрытие")),
            "Оператор": "",
            "Касса": str(sm.get("Касса") or "").strip(),
            "ОСЭНомер": str(sm.get("ОСЭНомер") or sm.get("НомерСмены") or "").strip(),
        }

        # ── retail_sale_sidegoods ──
        sec = meta.get("Секции") or {}
        doc_meta = meta.get("Документ") or {}
        товары = []
        сумма_ндс_итого = 0.0
        сумма_док = 0.0
        n = 0
        for sec_key, класс in (("продажа_сопутка", "Сопутка"), ("продажа_общепит", "Общепит")):
            for ln in (sec.get(sec_key) or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                n += 1
                сумма = float(ln.get("Сумма") or 0)
                ндс = float(ln.get("СуммаНДС") or 0)
                сумма_ндс_итого += ндс
                сумма_док += сумма
                строка = {
                    "НомерСтроки": ln.get("НомерСтроки") or n,
                    "Номенклатура": g,
                    "Единица": (nom[g].unit if nom.get(g) else "") or "",
                    "Количество": float(ln.get("Количество") or 0),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(сумма, 2),
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")),
                    "СуммаНДС": round(ндс, 2),
                    "КлассSKU": класс,
                }
                if класс == "Общепит":
                    строка["ЭтоБлюдо"] = True
                    if g:
                        dish_uuids.add(g)
                        # OB-1: inline-ТТК из строки продажи (cb_normalize._expand_dish) —
                        # фолбэк, если recipe-DataEntry для блюда нет (иначе блюдо ушло
                        # бы в БП без ТТК и списалось с 41.02 в минус).
                        inl = [{"НоменклатураUUID": str(i.get("Номенклатура") or ""),
                                "Количество": float(i.get("Количество") or 0),
                                "БлюдоНаименование": (nom[g].name if nom.get(g) else "")}
                               for i in (ln.get("Ингредиенты") or [])
                               if i.get("Номенклатура")]
                        if inl:
                            dish_inline_ings[g] = inl
                товары.append(строка)

        оплаты = []
        for o in (sec.get("оплаты") or {}).get("строки") or []:
            вид = str(o.get("ФормаОплаты") or o.get("ФормаОплатыКанон") or "").strip()
            if "нал" in вид.lower():
                вид = "Наличные"
            оплаты.append({"ВидОплаты": вид, "Сумма": round(float(o.get("Сумма") or 0), 2)})

        # ── ВозвращенныеТовары (возвраты покупателей смены) — P1-фикс, раньше [] ──
        возвраты = []
        for i, ln in enumerate((sec.get("возвраты") or {}).get("строки") or [], 1):
            g = ln.get("Номенклатура")
            if g:
                nsi_nom.add(g)
            возвраты.append({
                "НомерСтроки": ln.get("НомерСтроки") or i,
                "Номенклатура": g,
                "Единица": (nom[g].unit if nom.get(g) else "") or "",
                "Количество": float(ln.get("Количество") or 0),
                "Цена": float(ln.get("Цена") or 0),
                "Сумма": round(float(ln.get("Сумма") or 0), 2),
                "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nom[g].vat if nom.get(g) else ""),
                "СуммаНДС": round(float(ln.get("СуммаНДС") or 0), 2),
            })

        retail = {
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": str(doc_meta.get("ИсточникUUID") or sm.get("Смена") or ""),
            "Номер": str(sm.get("НомерСмены") or "").strip(),
            "Дата": _iso(sm.get("Закрытие")),
            # П3-фикс: Проведен/ПометкаУдаления из ОРП ЦБ, не хардкод
            "Проведен": bool(doc_meta.get("Проведен", True)),
            "ПометкаУдаления": bool(doc_meta.get("ПометкаУдаления", False)),
            "Организация": org_uuid,
            "Склад": wh_uuid,
            "Подразделение": "",
            "СуммаДокумента": round(сумма_док, 2),
            "ВалютаДокумента": "RUB",
            "СуммаВключаетНДС": True,
            "Товары": товары,
            "ВозвращенныеТовары": возвраты,
            "СуммаНДС": round(сумма_ндс_итого, 2),
            "Оплаты": оплаты,
        }

        # ── purchase (приходы смены) ──
        # приход-DataEntry линкуется к смене через meta.Смена; per-line СтавкаНДС/
        # Единица деривируем из CbNomenclature (в meta прихода их нет).
        purch_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "purchase"))).scalars().all()
        purchases = []
        seen_purch: set[str] = set()   # дедуп ПТУ: двухсменные дни дают дубль DataEntry
        cparty_ref = await self._refs("counterparty")
        shift_day = _day(sm)
        shift_station = str(sm.get("КодАЗС") or "")
        # П1-фикс: линковка документов по ИНТЕРВАЛУ смены [НачалоДня(Открытие)..
        # КонецДня(Закрытие)] как эталон СобратьPurchase — ловит многодневные смены и
        # «сиротские» дни; двухсменный день = 2 пакета по GUID (идемпотентность снимает дубли).
        shift_open = (str(sm.get("Открытие") or "")[:10]) or shift_day
        shift_close = (str(sm.get("Закрытие") or "")[:10]) or shift_day
        if shift_open > shift_close:
            shift_open, shift_close = shift_close, shift_open

        def _in_shift(dsm: dict) -> bool:
            d = _day(dsm)
            return bool(d) and shift_open <= d <= shift_close and str(dsm.get("КодАЗС") or "") == shift_station

        for pe in purch_entries:
            psm = (pe.meta or {}).get("Смена") or {}
            if not _in_shift(psm):
                continue
            pdoc = (pe.meta or {}).get("Документ") or {}
            if pdoc.get("ПометкаУдаления"):   # П3: не эмитим удалённые в ЦБ документы
                continue
            puid = str(pdoc.get("ИсточникUUID") or "")
            if puid in seen_purch:   # дедуп: один ПТУ — один раз в пакете
                continue
            seen_purch.add(puid)
            контр = str(pdoc.get("Контрагент") or "")
            if контр:
                nsi_contr.add(контр)
                if контр in cparty_ref:
                    contr_names[контр] = cparty_ref[контр].name
            ptovары = []
            psum = pnds = 0.0
            for i, ln in enumerate(pdoc.get("Товары") or [], 1):
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                nn = nom.get(g)
                summ = float(ln.get("Сумма") or 0)
                nds = float(ln.get("СуммаНДС") or 0)
                psum += summ
                pnds += nds
                ptovары.append({
                    "НомерСтроки": ln.get("НомерСтроки") or i,
                    "Номенклатура": g,
                    "Количество": float(ln.get("Количество") or 0),
                    "Единица": (nn.unit or "" if nn else ""),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(summ, 2),
                    # П2-фикс: ставка НДС из СТРОКИ документа, карточка — только fallback
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nn.vat if nn else ""),
                    "СуммаНДС": round(nds, 2),
                })
            purchases.append({
                "Тип": "purchase",
                "ИсточникUUID": str(pdoc.get("ИсточникUUID") or ""),
                "Номер": str(pdoc.get("Номер") or "").strip(),
                "Дата": _iso(pdoc.get("Дата")),
                # П3-фикс: Проведен/ПометкаУдаления/Организация из документа ЦБ, не хардкод
                "Проведен": bool(pdoc.get("Проведен", True)),
                "ПометкаУдаления": bool(pdoc.get("ПометкаУдаления", False)),
                "Организация": str(pdoc.get("Организация") or org_uuid),
                "Контрагент": контр,
                "ДоговорКонтрагента": "",   # TODO-Ф1: не тянули договор
                "Склад": wh_uuid,
                "ВидОперации": "ОтПоставщика",   # фильтр пула = только ОтПоставщика
                "СуммаДокумента": round(psum, 2),
                "ВалютаДокумента": "RUB",
                # F8: реальный флаг из ЦБ (default True для старых пакетов до досбора)
                "СуммаВключаетНДС": bool(pdoc.get("СуммаВключаетНДС", True)),
                "НДСНеВыделять": False,
                "НДСВключенВСтоимость": False,
                "НомерВходящегоДокумента": "",   # TODO-Ф1
                "ДатаВходящегоДокумента": "",
                "СуммаНДС": round(pnds, 2),
                "Товары": ptovары,
            })

        # ── production_release (выпуск общепита) ──
        # meta.Документ уже пакет-item; дозаполняем Единица из CbNomenclature.
        prod_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "production_release"))).scalars().all()
        productions = []
        for pr in prod_entries:
            prsm = (pr.meta or {}).get("Смена") or {}
            if not _in_shift(prsm):
                continue
            it = dict((pr.meta or {}).get("Документ") or {})
            it.pop("_station", None)
            it.pop("_day", None)
            it["Дата"] = _iso(it.get("Дата"))
            for блюдо in it.get("ВыпускБлюд") or []:
                g = блюдо.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                блюдо["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
            for ing in it.get("Ингредиенты") or []:
                g = ing.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                ing["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
            productions.append(it)

        # ── gain (оприходование) ──
        gain_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "gain"))).scalars().all()
        gains = []
        for ge in gain_entries:
            gsm = (ge.meta or {}).get("Смена") or {}
            if not _in_shift(gsm):
                continue
            it = dict((ge.meta or {}).get("Документ") or {})
            for k in ("_station", "_day"):
                it.pop(k, None)
            it["Дата"] = _iso(it.get("Дата"))
            for ln in it.get("Товары") or []:
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                ln["Единица"] = (nom[g].unit or "" if nom.get(g) else "")
                ln["СтавкаНДС"] = _nds(ln.pop("СтавкаНДС_raw", "")) or _nds(nom[g].vat if nom.get(g) else "")
            gains.append(it)

        # ── return_purchase (возврат поставщику, F2) ──
        # Эталон СобратьReturnPurchase (bsl:815): на стороне БП → Документ.
        # КорректировкаПоступления с ВидОперации=СогласованноеИзменение. Порядок
        # контракта: после production, перед inventory.
        ret_entries = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
            DataEntry.doc_type_id == "return_purchase"))).scalars().all()
        returns = []
        for re_ in ret_entries:
            rsm = (re_.meta or {}).get("Смена") or {}
            if not _in_shift(rsm):
                continue
            rdoc = (re_.meta or {}).get("Документ") or {}
            if rdoc.get("ПометкаУдаления"):
                continue
            контр = str(rdoc.get("Контрагент") or "")
            if контр:
                nsi_contr.add(контр)
                if контр in cparty_ref:
                    contr_names[контр] = cparty_ref[контр].name
            rtov = []
            rsum = rnds = 0.0
            for i, ln in enumerate(rdoc.get("Товары") or [], 1):
                g = ln.get("Номенклатура")
                if g:
                    nsi_nom.add(g)
                nn = nom.get(g)
                summ = float(ln.get("Сумма") or 0)
                nds = float(ln.get("СуммаНДС") or 0)
                rsum += summ
                rnds += nds
                rtov.append({
                    "НомерСтроки": ln.get("НомерСтроки") or i,
                    "Номенклатура": g,
                    "Количество": float(ln.get("Количество") or 0),
                    "Единица": (nn.unit or "" if nn else ""),
                    "Цена": float(ln.get("Цена") or 0),
                    "Сумма": round(summ, 2),
                    "СтавкаНДС": _nds(ln.get("СтавкаНДС")) or _nds(nn.vat if nn else ""),
                    "СуммаНДС": round(nds, 2),
                })
            returns.append({
                "Тип": "return_purchase",
                "ИсточникUUID": str(rdoc.get("ИсточникUUID") or ""),
                "Номер": str(rdoc.get("Номер") or "").strip(),
                "Дата": _iso(rdoc.get("Дата")),
                "Проведен": bool(rdoc.get("Проведен", True)),
                "ПометкаУдаления": bool(rdoc.get("ПометкаУдаления", False)),
                "Организация": str(rdoc.get("Организация") or org_uuid),
                "Контрагент": контр,
                "ДоговорКонтрагента": "",
                "ПервичнаяПТУ_UUID": str(rdoc.get("ПервичнаяПТУ_UUID") or ""),
                "Склад": str(rdoc.get("Склад") or wh_uuid),
                "СуммаДокумента": round(rsum, 2) if rsum else float(rdoc.get("СуммаДокумента") or 0),
                "ВалютаДокумента": "RUB",
                "СуммаВключаетНДС": bool(rdoc.get("СуммаВключаетНДС", True)),
                "СуммаНДС": round(rnds, 2),
                "Товары": rtov,
            })

        # ── inventory / writeoff / transfer (движение того же дня) ──
        # строим из Cb*Doc (склады 208); поля пакета деривируем из строк аналитики.
        # интервал смены по дате-части (как эталон): день Открытия..день Закрытия
        _inv_range = func.substr(CbInventoryDoc.doc_date, 1, 10).between(shift_open, shift_close)
        _mov_range = func.substr(CbMovementDoc.doc_date, 1, 10).between(shift_open, shift_close)
        code2guid = {str((r.extra or {}).get("code") or ""): r.external_ref for r in whs.values()}
        inventories = []
        for r in (await self.session.execute(select(CbInventoryDoc).where(
                CbInventoryDoc.company_id == self.company_id,
                _inv_range,
                CbInventoryDoc.warehouse_code.in_(_WH_208)))).scalars().all():
            if r.deleted:   # эталон: «НЕ ПометкаУдаления» в отборе
                continue
            # полная ТЧ Товары (носитель факта): Цена/Сумма/СуммаУчет — из строк ЦБ
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                строки.append({
                    "НомерСтроки": ln.get("n") or i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(float(ln.get("fact") or 0), 3),
                    "КоличествоУчет": round(float(ln.get("uchet") or 0), 3),
                    "Цена": round(float(ln.get("price") or 0), 2),
                    "Сумма": round(float(ln.get("amount") or 0), 2),
                    "СуммаУчет": round(float(ln.get("amount_uchet") or 0), 2),
                })
            inventories.append({
                "Тип": "inventory", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                # BP-4: Склад из САМОГО документа (напр. помещение 20800002), не смены —
                # иначе движения кухни/склада приписывались торговому залу 208.
                "Организация": org_uuid, "Склад": code2guid.get(str(r.warehouse_code or ""), wh_uuid),
                "Комментарий": r.comment or "",
                "ДатаЗаполнения": _iso(r.fill_date) if r.fill_date else "", "Товары": строки,
                "СуммаДокумента": round(sum(s["Сумма"] for s in строки), 2),
            })

        writeoffs = []
        transfers = []
        # transfer: отбор эталона — «СкладОтправитель=смены ИЛИ СкладПолучатель=смены»
        # (входящие на 208 тоже эмитятся); writeoff (warehouse_to_code NULL) не задет.
        for r in (await self.session.execute(select(CbMovementDoc).where(
                CbMovementDoc.company_id == self.company_id,
                _mov_range,
                or_(CbMovementDoc.warehouse_code.in_(_WH_208),
                    CbMovementDoc.warehouse_to_code.in_(_WH_208))))).scalars().all():
            if r.deleted:   # эталон: «НЕ ПометкаУдаления» в отборе
                continue
            строки = []
            for i, ln in enumerate(r.lines or [], 1):
                g = ln.get("ref")
                if g:
                    nsi_nom.add(g)
                строки.append({
                    "НомерСтроки": ln.get("n") or i, "Номенклатура": g,
                    "Единица": (nom[g].unit or "" if nom.get(g) else ""),
                    "Количество": round(float(ln.get("qty") or 0), 3),
                    "Цена": round(float(ln.get("price") or 0), 2),
                    "_amount": round(float(ln.get("amount") or 0), 2),
                    "_cost": round(float(ln.get("cost") or 0), 2),
                })
            if r.kind == "writeoff":
                for s in строки:
                    s["Сумма"] = s.pop("_amount")
                    s.pop("_cost")
                writeoffs.append({
                    "Тип": "writeoff", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                    # BP-4: Склад документа (не смены) — списание с реального склада.
                    "Организация": org_uuid, "Склад": code2guid.get(str(r.warehouse_code or ""), wh_uuid),
                    "Подразделение": "",
                    "ИнвентаризацияUUID": r.inventory_ref or "",
                    "СуммаДокумента": round(float(r.total_amount or 0), 2),
                    "НДСвСтоимостиТоваров": "", "ВалютаДокумента": "RUB", "Товары": строки,
                })
            elif r.kind == "transfer":
                for s in строки:
                    s["Себестоимость"] = s.pop("_cost")   # реквизит ТЧ ЦБ (0 у внутренних)
                    s.pop("_amount")
                # Направление относительно складов смены (эталон: отправитель приоритетен)
                si = str(r.warehouse_code or "") in _WH_208
                di = str(r.warehouse_to_code or "") in _WH_208
                # фолбэк wh_uuid — только для складов смены; чужой склад без GUID → ""
                отпр = code2guid.get(str(r.warehouse_code or ""), wh_uuid if si else "")
                получ = code2guid.get(str(r.warehouse_to_code or ""), wh_uuid if di else "")
                if получ:
                    nsi_wh.add(получ)
                if отпр:
                    nsi_wh.add(отпр)
                направление = "Исходящее" if si else ("Входящее" if di else "Транзит")
                transfers.append({
                    "Тип": "transfer", "ИсточникUUID": r.external_ref, "Номер": r.number or "",
                    "Дата": _iso(r.doc_date), "Проведен": bool(r.posted), "ПометкаУдаления": False,
                    "Организация": org_uuid,
                    "СкладОтправитель": отпр, "СкладПолучатель": получ,
                    "Подразделение": "", "ВидОперации": "ТоварыПродукция",
                    "Направление": направление, "Товары": строки,
                    "СуммаДокумента": round(float(r.total_amount or 0), 2),
                })

        # ── recipe (ТТК блюд, модель B общепита) ──
        # Для блюд смены (общепит-строки retail) эмитим ТТК ПЕРВЫМИ: приёмник строит
        # Справочник.СпецификацияНоменклатуры, из неё генерит Комплектацию (собирает
        # себестоимость), затем блюдо продаётся товаром в ОРП. Без recipe — «продано
        # как товар, себестоимость не собрана».
        recipes = []
        if dish_uuids:
            recipe_entries = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id, DataEntry.source == "oneC",
                DataEntry.doc_type_id == "recipe"))).scalars().all()
            # У блюда бывает несколько ТТК-записей: ЦБ присылал их разными заходами, и
            # часть приехала без `ИсточникUUID`. Приёмник на пустом ключе документ
            # ОТБРАСЫВАЕТ (`ОбработатьРецепт`: «пустой ИсточникUUID» → ЗаписатьОшибкуНСИ),
            # спецификация не создаётся, Комплектация не собирается, и блюдо уходит в
            # ОРП товаром без себестоимости — 41.02 по нему в минус.
            #
            # Поэтому из дублей берём ту, у которой ключ есть; при прочих равных —
            # свежую. Раньше побеждала просто последняя в выборке, и на боевых данных
            # 484 ТТК из 511 уезжали с пустым ключом.
            recipe_by_dish: dict[str, dict] = {}
            for re_ in recipe_entries:
                rd = (re_.meta or {}).get("Документ") or {}
                bu = str(rd.get("БлюдоUUID") or "")
                if not bu:
                    continue
                prev = recipe_by_dish.get(bu)
                if prev is None or (not str(prev.get("ИсточникUUID") or "").strip()
                                    and str(rd.get("ИсточникUUID") or "").strip()):
                    recipe_by_dish[bu] = rd
            for du in sorted(dish_uuids):
                rd = recipe_by_dish.get(du)
                # OB-1: нет recipe-DataEntry → фолбэк на inline-ТТК строки продажи.
                src_ings = (rd.get("Ингредиенты") if rd else None) or dish_inline_ings.get(du) or []
                ингредиенты = []
                for ing in src_ings:
                    iu = str(ing.get("НоменклатураUUID") or "")
                    if not iu:
                        continue
                    nsi_nom.add(iu)  # ингредиент → в НСИ
                    ингредиенты.append({
                        "НоменклатураUUID": iu,
                        "Количество": float(ing.get("Количество") or 0),
                        "Единица": (nom[iu].unit if nom.get(iu) else "") or "",
                    })
                if not ингредиенты:
                    continue
                nsi_nom.add(du)  # блюдо → в НСИ
                recipes.append({
                    "Тип": "recipe",
                    # Ключ обязателен: приёмник отбрасывает ТТК без него. Если в ЦБ
                    # ключа не оказалось вовсе, ставим детерминированный `inline:<блюдо>` —
                    # он стабилен между выгрузками, поэтому идемпотентность приёмника
                    # сохраняется, а спецификация создаётся.
                    "ИсточникUUID": (str(rd.get("ИсточникUUID") or "").strip() if rd else "")
                                    or f"inline:{du}",
                    "БлюдоUUID": du,
                    "БлюдоНаименование": str((rd.get("БлюдоНаименование") if rd else None)
                                             or (nom[du].name if nom.get(du) else "")),
                    "Ингредиенты": ингредиенты,
                })

        # Сначала собираем блюдо по ТТК, затем продаём его как сопутку.
        документы = [*recipes, *purchases, retail, *productions, *returns, *inventories, *gains, *writeoffs, *transfers]
        документы.sort(key=_document_sort_key)
        for документ in документы:
            if документ.get("Тип") != "recipe":
                документ["Проведен"] = False

        # ── НСИ ──
        def _s(v) -> str:
            return str(v or "").strip()   # ЦБ хранит ИНН/Код fixed-width → обрезать

        нси = []
        for uid in sorted(nsi_org):
            r = orgs.get(uid)
            ex = (r.extra or {}) if r else {}
            нси.append({
                "Тип": "Организация", "ИсточникUUID": uid,
                "Наименование": _s(r.name if r else ""), "НаименованиеПолное": _s(ex.get("full_name")) or _s(r.name if r else ""),
                "ИНН": _s(ex.get("inn")), "КПП": _s(ex.get("kpp")), "ОГРН": _s(ex.get("ogrn")),
                "ОКПО": _s(ex.get("okpo")), "ЮрФизЛицо": _s(ex.get("jur_fiz")) or "ЮрЛицо",
                "ПометкаУдаления": bool(ex.get("deleted")),
            })
        for uid in sorted(nsi_wh):
            r = whs.get(uid)
            ex = (r.extra or {}) if r else {}
            нси.append({
                "Тип": "Склад", "ИсточникUUID": uid,
                "Наименование": _s(r.name if r else ""), "Код": _s(ex.get("code")),
                "ВидСклада": _s(ex.get("kind_name")) or "АЗК",
                "ПометкаУдаления": bool(ex.get("deleted")),
            })
        for uid in sorted(nsi_contr):
            # Контрагент автосоздаётся приёмником по Наименованию (ИНН/КПП опц.).
            # TODO-Ф1: ИНН/КПП/ВидКонтрагента из Catalog.Контрагенты.
            nm = _s(contr_names.get(uid, ""))
            нси.append({
                "Тип": "Контрагент", "ИсточникUUID": uid,
                "Наименование": nm, "НаименованиеПолное": nm,
                "ИНН": "", "КПП": "", "ВидКонтрагента": "ЮрЛицо",
                "ПометкаУдаления": False,
            })
        for g in sorted(nsi_nom):
            nn = nom.get(g)
            вид = _s(kinds[nn.kind_ref].name) if (nn and nn.kind_ref and nn.kind_ref in kinds) else ""
            класс = "Общепит" if вид == "Набор - комплект" else "Сопутка"
            нси.append({
                "Тип": "Номенклатура", "ИсточникUUID": g,
                "КодЦБ": _s(nn.code if nn else ""),
                "Наименование": _s(nn.name if nn else ""),
                "НаименованиеПолное": _s(nn.full_name if nn else "") or _s(nn.name if nn else ""),
                "Артикул": _s(nn.article if nn else ""),
                "СтавкаНДС": _nds(nn.vat if nn else ""),
                "Единица": _s(nn.unit if nn else ""),
                "ВидНоменклатуры": вид,
                "КлассSKU": класс,
                "ШтрихКоды": [],
                "ПометкаУдаления": False,
            })

        пакет = {
            "ВерсияФормата": "2",
            "ВремяВыгрузки": shift["Закрытие"] or shift["Открытие"],
            "ИдентификаторПакета": _stable_uuid(
                f"bp-package/{self.company_id}/oneC/{target.source_id or shift_key}"),
            "Источник": "TradeLedger (Ledger)",
            "Смена": shift,
            "Документы": документы,
            "НСИ": нси,
            "ХешПакета": "",
        }
        пакет["ХешПакета"] = packet_hash(пакет)
        return пакет

    async def emit_to_dir(self, shift_key: str, directory: str) -> dict:
        """Собрать пакет и записать JSON-файл в каталог (Ф3). Формат: UTF-8 без
        BOM, отступ таб (как ЗаписатьJSON приёмника). Возвращает сводку."""
        verification = await self.verify_shift_package(shift_key)
        if not verification["ok"]:
            failed = [check["Проверка"] for check in verification["checks"] if not check["ok"]]
            raise ValueError("Пакет не прошёл обязательную сверку: " + "; ".join(failed))
        пакет = await self.build_shift_package(shift_key)
        fname = package_filename(пакет)
        _os.makedirs(directory, exist_ok=True)
        path = _os.path.join(directory, fname)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            _json.dump(пакет, f, ensure_ascii=False, indent="\t")
        from collections import Counter
        return {
            "file": fname, "path": path, "hash": пакет["ХешПакета"],
            "documents": dict(Counter(d["Тип"] for d in пакет["Документы"])),
            "nsi": len(пакет["НСИ"]),
        }

    async def verify_shift_package(self, shift_key: str) -> dict:
        """Сверка сопутки: самосогласованность пакета + сверка с источником. Строит
        пакет и прогоняет проверки готовности к загрузке приёмником (без 1С-эталона):
        балансы документов, полнота НСИ, fail-fast НДС, хеш. Возвращает список проверок."""
        pkt = await self.build_shift_package(shift_key)
        docs = pkt["Документы"]
        нси = pkt["НСИ"]
        checks: list[dict] = []

        def add(name: str, ok: bool, detail: str = "") -> None:
            checks.append({"Проверка": name, "ok": bool(ok), "Детали": detail})

        nsi_by_type: dict[str, set] = {}
        for n in нси:
            nsi_by_type.setdefault(n.get("Тип"), set()).add(n.get("ИсточникUUID"))
        nom_set = nsi_by_type.get("Номенклатура", set())
        incomplete_nsi = [f"{n.get('Тип')}: {n.get('ИсточникUUID') or 'без UUID'}"
                          for n in нси if not n.get("ИсточникUUID") or not str(n.get("Наименование") or "").strip()]

        h = pkt.get("ХешПакета") or ""
        add("Хеш пакета — 64 hex", len(h) == 64 and all(c in "0123456789abcdef" for c in h), (h[:12] + "…") if h else "нет")
        add("Версия формата = 2", pkt.get("ВерсияФормата") == "2", str(pkt.get("ВерсияФормата")))
        add("НСИ-инвариант: документы>0 → НСИ непуста", not (docs and not нси), f"документов={len(docs)} НСИ={len(нси)}")
        add("НСИ: у каждой карточки заполнены UUID и наименование",
            not incomplete_nsi, f"ошибок: {incomplete_nsi[:5]}")
        posted = [f"{doc.get('Тип')} №{doc.get('Номер') or doc.get('ИсточникUUID')}"
                  for doc in docs if doc.get("Тип") != "recipe" and doc.get("Проведен") is not False]
        add("Все учётные документы передаются непроведёнными", not posted,
            f"нарушения: {posted[:5]}")

        ref_nom: set = set(); ref_org: set = set(); ref_wh: set = set(); ref_partner: set = set()
        lines_without_nom: list[str] = []
        for d in docs:
            for t in (d.get("Товары") or []):
                if t.get("Номенклатура"):
                    ref_nom.add(t["Номенклатура"])
                else:
                    lines_without_nom.append(f"{d.get('Тип')} №{d.get('Номер')}")
            for t in (d.get("ВозвращенныеТовары") or []):
                if t.get("Номенклатура"):
                    ref_nom.add(t["Номенклатура"])
                else:
                    lines_without_nom.append(f"{d.get('Тип')} №{d.get('Номер')} / возврат")
            for ing in (d.get("Ингредиенты") or []):
                ingredient_uuid = ing.get("НоменклатураUUID") or ing.get("Номенклатура")
                if ingredient_uuid:
                    ref_nom.add(ingredient_uuid)
            for release in (d.get("ВыпускБлюд") or []):
                if release.get("Номенклатура"):
                    ref_nom.add(release["Номенклатура"])
            if d.get("БлюдоUUID"):
                ref_nom.add(d["БлюдоUUID"])
            for k in ("Организация",):
                if d.get(k):
                    ref_org.add(d[k])
            if d.get("Контрагент"):
                ref_partner.add(d["Контрагент"])
            for k in ("Склад", "СкладОтправитель", "СкладПолучатель"):
                if d.get(k):
                    ref_wh.add(d[k])
        add("Номенклатура документов вся в НСИ", not (ref_nom - nom_set), f"нет в НСИ: {len(ref_nom - nom_set)}")
        add("Во всех строках определена номенклатура", not lines_without_nom,
            f"ошибок: {lines_without_nom[:5]}")
        add("Организации документов в НСИ", not (ref_org - nsi_by_type.get("Организация", set())), f"нет: {len(ref_org - nsi_by_type.get('Организация', set()))}")
        add("Склады документов в НСИ", not (ref_wh - nsi_by_type.get("Склад", set())), f"нет: {len(ref_wh - nsi_by_type.get('Склад', set()))}")
        add("Контрагенты документов в НСИ", not (ref_partner - nsi_by_type.get("Контрагент", set())),
            f"нет: {len(ref_partner - nsi_by_type.get('Контрагент', set()))}")

        retail = next((d for d in docs if d.get("Тип") == "retail_sale_sidegoods"), None)
        if retail:
            товары = retail.get("Товары") or []
            возвраты = retail.get("ВозвращенныеТовары") or []
            s_d = float(retail.get("СуммаДокумента") or 0)
            s_t = round(sum(float(t.get("Сумма") or 0) for t in товары)
                        - sum(float(t.get("Сумма") or 0) for t in возвраты), 2)
            add("Розница: Σ продаж − возвраты = СуммаДокумента", abs(s_t - s_d) < 0.02, f"{s_t} ↔ {s_d}")
            s_nds = round(sum(float(t.get("СуммаНДС") or 0) for t in товары)
                          - sum(float(t.get("СуммаНДС") or 0) for t in возвраты), 2)
            add("Розница: Σ СуммаНДС строк = СуммаНДС", abs(s_nds - float(retail.get("СуммаНДС") or 0)) < 0.02, f"{s_nds} ↔ {retail.get('СуммаНДС')}")
            s_p = round(sum(float(o.get("Сумма") or 0) for o in (retail.get("Оплаты") or [])), 2)
            add("Розница: Σ Оплаты = СуммаДокумента", abs(s_p - s_d) < 0.02, f"{s_p} ↔ {s_d}")
            retail_bad_vat = [t.get("СтавкаНДС") or "пусто" for t in [*товары, *возвраты]
                              if t.get("СтавкаНДС") not in _BP_VAT_NAMES]
            add("Розница: все построчные ставки НДС приёмник сопоставит",
                not retail_bad_vat, f"ошибок: {retail_bad_vat[:5]}")

        purch = [d for d in docs if d.get("Тип") == "purchase"]
        if purch:
            bad = [p.get("Номер") for p in purch
                   if abs(round(sum(float(t.get("Сумма") or 0) for t in (p.get("Товары") or []))
                                + sum(float(t.get("Сумма") or 0) for t in (p.get("Услуги") or [])), 2)
                          - float(p.get("СуммаДокумента") or 0)) >= 0.02]
            add(f"Поступления ({len(purch)}): Σ товаров и услуг = СуммаДокумента", not bad, f"расхождения: {bad}")

        recs = [d for d in docs if d.get("Тип") == "recipe"]
        if recs:
            no_ing = [r.get("БлюдоНаименование") for r in recs if not r.get("Ингредиенты")]
            add(f"Рецептуры ({len(recs)}): все с ингредиентами", not no_ing, f"без ингредиентов: {no_ing}")

        # OB-1: КАЖДОЕ блюдо смены (ЭтоБлюдо) должно иметь recipe в пакете — иначе
        # приёмник спишет его товаром с 41.02 в минус. Раньше verify это не ловил.
        dishes_sold = {t.get("Номенклатура") for d in docs
                       if d.get("Тип") == "retail_sale_sidegoods"
                       for t in (d.get("Товары") or []) if t.get("ЭтоБлюдо") and t.get("Номенклатура")}
        # ТТК засчитывается только с непустым ключом: приёмник отбрасывает документ
        # без `ИсточникUUID`, и «рецепт в пакете есть» тогда ничего не значит —
        # спецификация не создастся, Комплектация не соберётся, блюдо уйдёт товаром.
        # Раньше проверка смотрела только на наличие записи и считала такой пакет
        # здоровым.
        recipe_dishes = {r.get("БлюдоUUID") for r in recs
                         if str(r.get("ИсточникUUID") or "").strip()}
        keyless = [r.get("БлюдоНаименование") or r.get("БлюдоUUID")
                   for r in recs if not str(r.get("ИсточникUUID") or "").strip()]
        missing = dishes_sold - recipe_dishes
        add(f"Все блюда смены ({len(dishes_sold)}) имеют ТТК в пакете",
            not missing, f"без рецепта: {len(missing)}" + (f" {list(missing)[:3]}" if missing else ""))
        add("У каждой ТТК есть ключ ИсточникUUID",
            not keyless, f"без ключа: {len(keyless)} {keyless[:3]}")
        released_dishes = {line.get("Номенклатура") for d in docs
                           if d.get("Тип") == "production_release"
                           for line in (d.get("ВыпускБлюд") or []) if line.get("Номенклатура")}
        missing_release = dishes_sold - released_dishes
        add(f"Все блюда смены ({len(dishes_sold)}) выпущены до продажи",
            not missing_release,
            f"без выпуска: {len(missing_release)}"
            + (f" {list(missing_release)[:3]}" if missing_release else ""))

        bad_nsi_vat = [f"{n.get('Наименование')}: {n.get('СтавкаНДС') or 'пусто'}"
                       for n in нси if n.get("Тип") == "Номенклатура"
                       and n.get("СтавкаНДС") not in _BP_VAT_NAMES]
        add("НСИ: ставки НДС номенклатуры приёмник сопоставит",
            not bad_nsi_vat, f"ошибок: {bad_nsi_vat[:5]}")

        # Проверяем все документные ставки: общей подмены розницы на НДС22 больше нет.
        unmapped = [f"{d.get('Тип')} №{d.get('Номер')}: {t.get('СтавкаНДС') or 'пусто'}"
                    for d in docs if d.get("Тип") in ("purchase", "return_purchase", "gain")
                    for t in (d.get("Товары") or []) if t.get("СтавкаНДС") not in _BP_VAT_NAMES]
        unmapped += [f"purchase №{d.get('Номер')} / услуга: {service.get('СтавкаНДС') or 'пусто'}"
                     for d in docs if d.get("Тип") == "purchase"
                     for service in (d.get("Услуги") or [])
                     if service.get("СтавкаНДС") not in _BP_VAT_NAMES]
        add("Поступления, возвраты, оприходования: ставки НДС приёмник сопоставит",
            not unmapped, f"строк: {len(unmapped)} {unmapped[:5]}")

        # Архаичную ставку ловим у себя ДО выгрузки.
        _archaic = {"НДС18", "НДС18_118"}
        bad_vat = []
        for d in docs:
            for t in (d.get("Товары") or []):
                if t.get("СтавкаНДС") in _archaic:
                    bad_vat.append(f"{d.get('Тип')} №{d.get('Номер')}: {t.get('СтавкаНДС')}")
        bad_vat += [f"НСИ {n.get('Наименование')}: {n.get('СтавкаНДС')}"
                    for n in нси if n.get("СтавкаНДС") in _archaic]
        add("Нет архаичных ставок НДС18 (приёмник ест молча)", not bad_vat, f"строк: {bad_vat[:5]}")

        sm = pkt.get("Смена") or {}
        return {
            "shift_key": shift_key,
            "ok": all(c["ok"] for c in checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "total": len(checks),
            "Документов": len(docs),
            "НСИ": len(нси),
            "ХешПакета": h,
            "КодАЗС": sm.get("КодАЗС"),
            "checks": checks,
        }
