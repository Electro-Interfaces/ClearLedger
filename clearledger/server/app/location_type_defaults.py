"""
Встроенный (системный) набор типов точек обслуживания.

Единый источник: используется сидом в database.py (company_id=NULL,
is_builtin=true) и отдаётся фронту как фолбэк. Нижестоящий код опирается на
стабильный `code` (например 'fuel_station'), а не на лейбл.

Схема поля (fields[]) повторяет MetadataField фронта:
  {key, label, type: text|number|date|select|textarea, options?, unit?, required?}
"""

BUILTIN_LOCATION_TYPES: list[dict] = [
    {
        "code": "fuel_station",
        "name": "АЗС",
        "icon": "Fuel",
        "unit": "л",
        "nomenclature_kind": "fuel",
        "sort_order": 10,
        # Привязка к STS — через sourceBindings; метаполей минимум.
        "fields": [],
    },
    {
        "code": "ev_charging",
        "name": "Электрозарядная станция",
        "icon": "Zap",
        "unit": "кВт·ч",
        "nomenclature_kind": "energy",
        "sort_order": 20,
        "fields": [
            {
                "key": "connectorType", "label": "Тип коннектора", "type": "select",
                "options": ["Type 2", "CCS Combo 2", "CHAdeMO", "GB/T"],
            },
            {"key": "connectorCount", "label": "Число коннекторов", "type": "number"},
            {"key": "maxPowerKw", "label": "Макс. мощность", "type": "number", "unit": "кВт"},
            {"key": "currentType", "label": "Тип тока", "type": "select", "options": ["AC", "DC"]},
            {"key": "tariff", "label": "Тариф", "type": "number", "unit": "₽/кВт·ч"},
        ],
    },
    {
        "code": "retail",
        "name": "Магазин / сопутка",
        "icon": "Store",
        "unit": "шт",
        "nomenclature_kind": "goods",
        "sort_order": 30,
        "fields": [
            {"key": "area", "label": "Площадь", "type": "number", "unit": "м²"},
            {"key": "format", "label": "Формат", "type": "text"},
        ],
    },
    {
        "code": "food",
        "name": "Общепит",
        "icon": "Utensils",
        "unit": "шт",
        "nomenclature_kind": "food",
        "sort_order": 40,
        "fields": [
            {"key": "seats", "label": "Посадочных мест", "type": "number"},
            {"key": "cuisine", "label": "Тип кухни", "type": "text"},
        ],
    },
    {
        "code": "warehouse",
        "name": "Склад",
        "icon": "Warehouse",
        "unit": "",
        "nomenclature_kind": "none",
        "sort_order": 50,
        "fields": [
            {"key": "area", "label": "Площадь", "type": "number", "unit": "м²"},
        ],
    },
    {
        "code": "office",
        "name": "Офис",
        "icon": "Building2",
        "unit": "",
        "nomenclature_kind": "none",
        "sort_order": 60,
        "fields": [],
    },
    {
        "code": "other",
        "name": "Другое",
        "icon": "MapPin",
        "unit": "",
        "nomenclature_kind": "none",
        "sort_order": 70,
        "fields": [],
    },
]
