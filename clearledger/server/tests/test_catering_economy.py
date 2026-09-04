from app.services.goods_dashboard import (
    _catering_sale_facts, _edge_cost_by_dish, _merge_customer_returns, _week_of,
)


def test_cost_evidence_maps_exact_cost_to_dish():
    meta = {"Edge": {"CostEvidence": {
        "production": [{"dish_uuid": "latte", "quantity_millis": 2000}],
        "ingredients": [
            {"dish_uuid": "latte", "item_uuid": "milk",
             "required_amount_micros": 30000000, "status": "known"},
            {"dish_uuid": "latte", "item_uuid": "coffee",
             "required_amount_micros": 20000000, "status": "known"},
        ],
    }}}
    cost = _edge_cost_by_dish(meta)["latte"]
    assert cost["cost"] == 50
    assert cost["exact"] == 50
    assert cost["estimated"] == 0
    assert cost["qty"] == 2
    assert cost["status"] == "exact"


def test_hint_cost_never_becomes_exact():
    meta = {"Edge": {"CostEvidence": {
        "production": [{"dish_uuid": "latte", "quantity_millis": 1000}],
        "ingredients": [{"dish_uuid": "latte", "item_uuid": "milk",
                         "required_amount_micros": 25000000, "status": "hint"}],
    }}}
    cost = _edge_cost_by_dish(meta)["latte"]
    assert cost["status"] == "estimate"
    assert cost["exact"] == 0
    assert cost["estimated"] == 25


def test_sales_keep_vat_and_customer_returns_separate():
    meta = {
        "Смена": {"КодАЗС": "208", "Закрытие": "2026-08-31T20:00:00+03:00"},
        "Секции": {
            "продажа_общепит": {"строки": [{
                "Номенклатура": "latte", "Количество": 2,
                "Сумма": 244, "СуммаНДС": 44,
                "Ингредиенты": [{"Номенклатура": "milk", "Количество": 0.4}],
            }]},
            "возвраты": {"строки": [{
                "Номенклатура": "latte", "Количество": 1,
                "Сумма": 122, "СуммаНДС": 22,
            }]},
        },
    }
    fact = _catering_sale_facts([meta])["latte"]
    assert fact["gross"] == 244
    assert fact["vat"] == 44
    assert fact["returns"] == 122
    assert fact["return_vat"] == 22
    assert fact["vat_missing"] == 0


def test_week_starts_on_monday():
    assert _week_of("2026-08-31") == "2026-08-31"
    assert _week_of("2026-09-06") == "2026-08-31"


def test_standalone_customer_return_is_added_without_losing_vat():
    facts = _catering_sale_facts([{
        "Смена": {"Закрытие": "2026-08-31T20:00:00+03:00"},
        "Секции": {"продажа_общепит": {"строки": [{
            "Номенклатура": "latte", "Количество": 1,
            "Сумма": 122, "СуммаНДС": 22,
        }]}},
    }])
    _merge_customer_returns(facts, {
        "latte": {"returns": 122, "return_vat": 22, "vat_missing": 0},
    })
    assert facts["latte"]["returns"] == 122
    assert facts["latte"]["return_vat"] == 22


def test_return_only_dish_stays_in_period_economy():
    facts = _catering_sale_facts([{
        "Смена": {"Закрытие": "2026-08-31T20:00:00+03:00"},
        "Секции": {"возвраты": {"строки": [{
            "Номенклатура": "latte", "Количество": 1,
            "Сумма": 122, "СуммаНДС": 22,
        }]}},
    }])
    _merge_customer_returns(facts, {
        "cappuccino": {"returns": 244, "return_vat": 44, "vat_missing": 0},
    })
    assert facts["latte"]["returns"] == 122
    assert facts["latte"]["return_vat"] == 22
    assert facts["cappuccino"]["returns"] == 244
    assert facts["cappuccino"]["return_vat"] == 44
