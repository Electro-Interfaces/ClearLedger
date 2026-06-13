"""
Справочник ПРАВИЛ САМОСВЕРКИ (внутренняя ось) — арифметические инварианты
смены на наших данных L2, без внешних источников.

Дополняет reconcile_catalog (межисточниковая ось, нужен 2-й поток+креды):
самосверка работает на ОДНОЙ записи L2 и ловит ошибки нормализации/выгрузки
ДО экспорта в БП. Исполнитель — services/reconcile/selfcheck.

Каждое правило: applies_to (к каким записям) + invariants (список инвариантов
над именованными агрегатами из selfcheck.extract_aggregates).
"""
from __future__ import annotations


# Розничная ставка НДС сети (золотое правило 10: розн. ОРП 68.02 = 22/122)
_VAT_RATE = 22.0

SELFCHECK_RULES: list[dict] = [
    # ── Баланс смены: оплаты закрывают выручку (62.Р) ──
    {
        "id": "orp_balance",
        "label": "Баланс ОРП: оплаты == продажи − возвраты",
        "module": "sidegoods,food",
        "description": (
            "Сумма оплат смены равна выручке (сопутка+общепит) за вычетом "
            "возвратов — закрытие расчётов 62.Р. Расхождение = недонесённые "
            "оплаты или потеря строк при нормализации."
        ),
        "applies_to": {"doc_type_id": ["retail_sale_sidegoods"]},
        "invariants": [
            {
                "id": "balance",
                "label": "Σ оплаты == Σ продажи − Σ возвраты",
                "kind": "balance",
                "lhs": "опл",
                "plus": ["прод_сопутка", "прод_общепит"],
                "minus": ["возвраты"],
                "tol": 1.0,
                "severity": "material",
            },
        ],
    },

    # ── Итог документа == сумма продаж по секциям ──
    {
        "id": "orp_doc_total",
        "label": "Итог ОРП: СуммаДокумента == Σ продажи",
        "module": "sidegoods,food",
        "description": "СуммаДокумента шапки совпадает с суммой секций продаж (контроль разбора ТЧ).",
        "applies_to": {"doc_type_id": ["retail_sale_sidegoods"]},
        "invariants": [
            {
                "id": "doc_total",
                "label": "СуммаДокумента == Σ продажи",
                "kind": "balance",
                "lhs": "сумма_документа",
                "plus": ["прод_сопутка", "прод_общепит"],
                "minus": [],
                "tol": 1.0,
                "severity": "minor",
            },
        ],
    },

    # ── НДС построчно (fail-fast НДС: ловим устаревшие ставки 18/20) ──
    {
        "id": "orp_vat_retail",
        "label": "НДС ОРП: каждая строка на разрешённой ставке {0,10,22}",
        "module": "sidegoods,food",
        "description": (
            "Построчная проверка НДС: сопутка смешанная (часть 10%), общепит 22% "
            "— единая ставка на итог секции даёт ложные срабатывания. Каждая "
            "строка должна лечь на разрешённую ставку; строки на 18/20 (или с "
            "битой арифметикой НДС) подсвечиваются — дисциплина fail-fast НДС "
            "(золотое правило 10), ловим до экспорта в БП."
        ),
        "applies_to": {"doc_type_id": ["retail_sale_sidegoods"]},
        "invariants": [
            {
                "id": "vat_lines",
                "label": "Каждая строка НДС на ставке из {0%, 10%, 22%}",
                "kind": "vat_lines",
                "sections": ["продажа_сопутка", "продажа_общепит"],
                "allowed_rates": [0.0, 10.0, _VAT_RATE],
                "tol": 1.0,
                "severity": "minor",
            },
        ],
    },
]


def list_selfchecks() -> list[dict]:
    """Справочник правил самосверки для UI/API/исполнителя."""
    return [dict(r) for r in SELFCHECK_RULES]


def get_selfcheck(rule_id: str) -> dict | None:
    for r in SELFCHECK_RULES:
        if r["id"] == rule_id:
            return dict(r)
    return None
