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
        # Реальный набор реестра РусГидро (HubEx/Onder). connectorTypes — коды 0–6
        # как в источнике; недостоверные dev-поля (статус/связь/прошивка) не храним.
        "fields": [
            {"key": "number", "label": "Номер станции", "type": "text"},
            {"key": "serialNumber", "label": "Серийный № (HubEx)", "type": "text"},
            {"key": "inventoryNumber", "label": "Инвентарный номер", "type": "text"},
            {"key": "ownerTitle", "label": "Владелец", "type": "text"},
            {"key": "ownerId", "label": "ID владельца", "type": "number"},
            {"key": "federalDistrict", "label": "Федеральный округ", "type": "text"},
            {"key": "federalSubject", "label": "Регион", "type": "text"},
            {"key": "cityName", "label": "Город", "type": "text"},
            {"key": "placement", "label": "Расположение (трасса/город)", "type": "text"},
            {"key": "siteType", "label": "Локация (тип площадки)", "type": "text"},
            {"key": "installPlace", "label": "Место установки", "type": "text"},
            {"key": "accessNote", "label": "Ограничения / замечания", "type": "text"},
            {"key": "latitude", "label": "Широта", "type": "number"},
            {"key": "longitude", "label": "Долгота", "type": "number"},
            {"key": "speed", "label": "Скорость (быстрая/медленная)", "type": "text"},
            {"key": "manufacturer", "label": "Бренд", "type": "text"},
            {"key": "model", "label": "Модель", "type": "text"},
            {"key": "connectorCount", "label": "Кол-во коннекторов", "type": "number"},
            {"key": "connectorTypes", "label": "Типы коннекторов (коды)", "type": "text"},
            {"key": "maxPowerKw", "label": "Макс. мощность", "type": "number", "unit": "кВт"},
            {"key": "protocolOcpp", "label": "Протокол OCPP", "type": "select",
             "options": ["Нет", "OCPP 1.6", "OCPP 2.0.1"]},
            {"key": "stage", "label": "Стадия", "type": "text"},
            # Связка с HubEx (asset_id) — ключ будущего HubEx-адаптера.
            {"key": "hubexAssetId", "label": "HubEx asset_id", "type": "number"},
            {"key": "hubexName", "label": "HubEx название", "type": "text"},
            {"key": "linkStatus", "label": "Статус связки HubEx", "type": "select",
             "options": ["ok", "review", "conflict", "test", "no_match"]},
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
