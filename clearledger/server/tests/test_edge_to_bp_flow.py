import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.bp_canon import packet_hash
from app.services.bp_export import BpPackageEmitter, _nds, _stable_uuid
from app.services.cb_normalize import normalize_shift_package
from app.services.edge_projection import enrich_retail_meta
from app.services.goods_dashboard import _prefer_edge_sales


def _edge_package():
    return {
        "ИдентификаторПакета": "packet-208-42",
        "ХешПакета": "abc",
        "Смена": {
            "КодАЗС": 208,
            "НомерСмены": "2082080308202601",
            "НомерСменыВнутр": 42,
            "Открытие": "2026-08-03T08:00:00+03:00",
            "Закрытие": "2026-08-03T20:00:00+03:00",
            "СкладUUID": "warehouse-208",
            "ОрганизацияUUID": "gig",
        },
        "Документы": [{
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": "retail-42",
            "Номер": "2082080308202601",
            "Дата": "2026-08-03T20:00:00+03:00",
            "Проведен": True,
            "Организация": "gig",
            "Склад": "warehouse-208",
            "СуммаДокумента": 300,
            "Товары": [{
                "Номенклатура": "dish-coffee",
                "Количество": 2,
                "Цена": 150,
                "Сумма": 300,
                "СтавкаНДС": "НДС22",
                "СуммаНДС": 54.1,
            }],
            "Оплаты": [{"ВидОплаты": "Наличные", "Сумма": 300}],
        }],
    }


def test_edge_normalization_keeps_source_and_all_accounting_kinds():
    package = _edge_package()
    package["Документы"].append({
        "Тип": "inventory", "ИсточникUUID": "inventory-1", "Товары": [],
    })

    result = normalize_shift_package(package, source="edge", source_label="Ledger Edge")

    assert [entry["doc_type_id"] for entry in result["entries"]] == [
        "retail_sale_sidegoods", "inventory",
    ]
    assert all(entry["source"] == "edge" for entry in result["entries"])
    assert result["entries"][0]["meta"]["Смена"]["Смена"] == "retail-42"
    assert result["entries"][0]["meta"]["Смена"]["НомерСменыВнутр"] == 42
    assert result["skipped"] == []


def test_recipe_history_is_scoped_by_shift_and_version():
    first = _edge_package()
    first["Документы"] = [{
        "Тип": "recipe", "ИсточникUUID": "recipe-coffee",
        "БлюдоUUID": "dish-coffee", "ВерсияТТК": 4,
        "ВерсияНабораТТК": "ttk-v4", "Ингредиенты": [],
    }]
    second = deepcopy(first)
    second["ИдентификаторПакета"] = "packet-208-43"
    second["Смена"]["НомерСменыВнутр"] = 43
    second["Смена"]["НомерСмены"] = "2082080408202601"
    second["Документы"][0]["ВерсияТТК"] = 5
    second["Документы"][0]["ВерсияНабораТТК"] = "ttk-v5"

    first_entry = normalize_shift_package(first, source="edge")["entries"][0]
    second_entry = normalize_shift_package(second, source="edge")["entries"][0]

    assert first_entry["source_id"] != second_entry["source_id"]
    assert first_entry["meta"]["Смена"]["НомерСменыВнутр"] == 42
    assert second_entry["meta"]["Смена"]["НомерСменыВнутр"] == 43


def test_recipe_arriving_later_reclassifies_sale_and_expands_ingredients():
    package = _edge_package()
    package["Документы"][0]["Товары"][0]["СтавкаНДС"] = "НДС10"
    package["Документы"][0]["Товары"][0]["СуммаНДС"] = 27.27
    normalized = normalize_shift_package(package, source="edge")
    meta = normalized["entries"][0]["meta"]

    enriched = enrich_retail_meta(meta, {
        "dish-coffee": [{"НоменклатураUUID": "milk", "Количество": 0.15}],
    }, {"dish-coffee"})

    assert enriched["СодержитБлюда"] is True
    line = enriched["Секции"]["продажа_общепит"]["строки"][0]
    assert line["ЭтоБлюдо"] is True
    assert line["СтавкаНДС"] == "НДС22"
    assert line["СуммаНДС"] == 54.1
    assert line["Ингредиенты"] == [{
        "Номенклатура": "milk", "Количество": 0.3, "ИзБлюда": "dish-coffee",
    }]


def test_manual_package_identity_and_hash_are_deterministic():
    packet = _edge_package()
    packet["ИдентификаторПакета"] = _stable_uuid("bp-package/company/edge/shift")
    first = packet_hash(packet)
    second = packet_hash(packet)

    assert packet["ИдентификаторПакета"] == _stable_uuid("bp-package/company/edge/shift")
    assert first == second
    assert _nds("10%") == "НДС10"
    assert _nds("НДС22") == "НДС22"


def test_dashboard_prefers_edge_projection_of_same_shift():
    shift = {"КодАЗС": "208", "НомерСмены": "2082080308202601",
             "Закрытие": "2026-08-03T20:00:00+03:00"}
    rows = [
        SimpleNamespace(source="oneC", meta={"Смена": shift}),
        SimpleNamespace(source="edge", meta={"Смена": shift}),
    ]

    result = _prefer_edge_sales(rows)

    assert len(result) == 1
    assert result[0].source == "edge"


class _Result:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar


class _Session:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self.results.pop(0)


def _edge_item(item_uuid, name, vat, is_dish=False):
    return {
        "external_uuid": item_uuid, "code_1c": "", "name": name, "name_full": name,
        "unit": "шт", "vat_rate": vat, "kind": "Набор-комплект" if is_dish else "Товар",
        "sku_class": "Общепит" if is_dish else "Сопутка", "is_dish": is_dish,
        "deleted": False, "barcodes": [],
    }


def _emitter_session(entries):
    return _Session([
        _Result(rows=[_edge_item("dish-coffee", "Кофе", "НДС22", True),
                      _edge_item("milk", "Молоко", "НДС10")]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(rows=[]),
        _Result(scalar="ГИГ"),
        _Result(rows=[{"id": 208, "name": "АЗС 208", "warehouse_uuid": "warehouse-208"}]),
        _Result(rows=entries),
        _Result(rows=[]),
        _Result(rows=[]),
    ])


@pytest.mark.asyncio
async def test_edge_documents_build_manual_unposted_bp_package_with_ttk_and_line_vat():
    package = _edge_package()
    package["Документы"][0]["Товары"][0]["СтавкаНДС"] = "НДС10"
    package["Документы"][0]["Товары"][0]["СуммаНДС"] = 27.27
    normalized = normalize_shift_package(package, source="edge")
    retail_meta = enrich_retail_meta(normalized["entries"][0]["meta"], {
        "dish-coffee": [{"НоменклатураUUID": "milk", "Количество": 0.15}],
    }, {"dish-coffee"})
    target = SimpleNamespace(id="retail", source_id="shift:retail", meta=retail_meta)
    recipe = SimpleNamespace(
        id="recipe", doc_type_id="recipe", source_id="recipe:dish-coffee",
        meta={"Смена": retail_meta["Смена"], "Документ": {
            "Тип": "recipe", "ИсточникUUID": "recipe-1", "БлюдоUUID": "dish-coffee",
            "БлюдоНаименование": "Кофе", "ВидРецептуры": "dish", "ВерсияТТК": 4,
            "ВерсияНабораТТК": "ttk-abc", "Выход": 1, "ЕдиницаВыхода": "шт",
            "Ингредиенты": [{"НоменклатураUUID": "milk", "Количество": 0.15}],
        }},
    )
    production = SimpleNamespace(
        id="production", doc_type_id="production_release", source_id="production-42",
        meta={"Смена": retail_meta["Смена"], "Документ": {
            "Тип": "production_release", "ИсточникUUID": "production-42", "Номер": "СМ-42",
            "Дата": "2026-08-03T20:00:00+03:00", "Организация": "gig",
            "Склад": "warehouse-208", "ВалютаДокумента": "RUB", "СуммаДокумента": 80,
            "ВыпускБлюд": [{"НомерСтроки": 1, "Идентификатор": "dish-1",
                              "Номенклатура": "dish-coffee", "Количество": 2,
                              "Единица": "шт", "Цена": 40, "Сумма": 80}],
            "Ингредиенты": [{"НомерСтроки": 1, "ИдентификаторПродукция": "dish-1",
                               "Номенклатура": "milk", "Количество": 0.3, "Единица": "л"}],
        }},
    )
    purchase = SimpleNamespace(
        id="purchase", doc_type_id="purchase", source_id="purchase-1",
        meta={"Смена": retail_meta["Смена"], "Документ": {
            "Тип": "purchase", "ИсточникUUID": "purchase-1", "Номер": "П-1",
            "Дата": "2026-08-03T12:00:00+03:00", "Организация": "gig",
            "Склад": "warehouse-208", "СуммаДокумента": 110,
            "Товары": [{"Номенклатура": "milk", "Количество": 1, "Цена": 110,
                        "Сумма": 110, "СтавкаНДС": "НДС10", "СуммаНДС": 10}],
        }},
    )
    other_shift = dict(retail_meta["Смена"])
    other_shift["НомерСменыВнутр"] = 43
    other_shift["НомерСмены"] = "2082080308202602"
    newer_recipe = SimpleNamespace(
        id="recipe-new", doc_type_id="recipe", source_id="shift43:recipe:dish-coffee",
        meta={"Смена": other_shift, "Документ": {
            "Тип": "recipe", "ИсточникUUID": "recipe-2", "БлюдоUUID": "dish-coffee",
            "БлюдоНаименование": "Кофе", "ВидРецептуры": "dish", "ВерсияТТК": 5,
            "ВерсияНабораТТК": "ttk-new", "Выход": 1, "ЕдиницаВыхода": "шт",
            "Ингредиенты": [{"НоменклатураUUID": "milk", "Количество": 0.2}],
        }},
    )
    neighbor_purchase = SimpleNamespace(
        id="purchase-next", doc_type_id="purchase", source_id="purchase-next",
        meta={"Смена": {**other_shift, "НомерСменыВнутр": None}, "Документ": {
            "Тип": "purchase", "ИсточникUUID": "purchase-next", "Номер": "П-2",
            "Дата": "2026-08-03T21:00:00+03:00", "Организация": "gig",
            "Склад": "warehouse-208", "СуммаДокумента": 110, "Товары": [],
        }},
    )
    company_id = uuid.uuid4()

    first = await BpPackageEmitter(
        _emitter_session([recipe, purchase, production, newer_recipe, neighbor_purchase]), company_id,
    )._build_edge_shift_package(target, "retail-42")
    second = await BpPackageEmitter(
        _emitter_session([recipe, purchase, production, newer_recipe, neighbor_purchase]), company_id,
    )._build_edge_shift_package(target, "retail-42")

    assert first["Источник"] == "Ledger Edge → Ledger"
    assert first["ИдентификаторПакета"] == second["ИдентификаторПакета"]
    assert first["ХешПакета"] == second["ХешПакета"]
    assert {doc["Тип"] for doc in first["Документы"]} == {
        "recipe", "purchase", "production_release", "retail_sale_sidegoods",
    }
    assert [doc["Тип"] for doc in first["Документы"]] == [
        "recipe", "purchase", "production_release", "retail_sale_sidegoods",
    ]
    assert all(doc.get("Проведен") is False for doc in first["Документы"] if doc["Тип"] != "recipe")
    retail = next(doc for doc in first["Документы"] if doc["Тип"] == "retail_sale_sidegoods")
    assert retail["Товары"][0]["ЭтоБлюдо"] is True
    assert retail["Товары"][0]["СтавкаНДС"] == "НДС22"
    incoming = next(doc for doc in first["Документы"] if doc["Тип"] == "purchase")
    assert incoming["Товары"][0]["СтавкаНДС"] == "НДС10"
    release = next(doc for doc in first["Документы"] if doc["Тип"] == "production_release")
    assert release["Ингредиенты"][0]["Количество"] == 0.3
    assert release["Ингредиенты"][0]["ИдентификаторПродукция"] == "dish-1"
    ttk = next(doc for doc in first["Документы"] if doc["Тип"] == "recipe")
    assert ttk["ВерсияТТК"] == 4
    assert ttk["ВерсияНабораТТК"] == "ttk-abc"
    assert all(doc.get("ИсточникUUID") != "purchase-next" for doc in first["Документы"])


@pytest.mark.asyncio
async def test_edge_manual_package_refuses_catering_sale_without_release():
    package = _edge_package()
    normalized = normalize_shift_package(package, source="edge")
    retail_meta = enrich_retail_meta(normalized["entries"][0]["meta"], {
        "dish-coffee": [{"НоменклатураUUID": "milk", "Количество": 0.15}],
    }, {"dish-coffee"})
    target = SimpleNamespace(id="retail", source_id="shift:retail", meta=retail_meta)
    recipe = SimpleNamespace(
        id="recipe", doc_type_id="recipe", source_id="shift:recipe:dish-coffee",
        meta={"Смена": retail_meta["Смена"], "Документ": {
            "Тип": "recipe", "ИсточникUUID": "recipe-1", "БлюдоUUID": "dish-coffee",
            "ВерсияТТК": 4, "ВерсияНабораТТК": "ttk-abc",
            "Ингредиенты": [{"НоменклатураUUID": "milk", "Количество": 0.15}],
        }},
    )

    with pytest.raises(ValueError, match="нет выпуска этой смены"):
        await BpPackageEmitter(
            _emitter_session([recipe]), uuid.uuid4(),
        )._build_edge_shift_package(target, "retail-42")
