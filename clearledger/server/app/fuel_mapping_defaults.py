"""
Дефолты маппингов топливных каналов STS → 1С:БП для ГИГ.

Извлечены из расширения TradeLedger.cfe:
  - каналы оплаты + склады/флаг перемещения — TL_Настройки.ИнициализироватьПоУмолчаниюГИГ
    (D:\\Users\\magsp\\ELSYPLUS\\Ledger\\ext-bp\\src\\CommonModules\\TL_Настройки.bsl)
  - маппинг оплат (22 образца) — живой справочник TL_МаппингОплат прода (БП ГИГ, 192.168.40.31)
  - виды топлива + плотности — Топливо_<N>_* (там же)

Источник истины маппингов — приложение (решение 28.06.2026).
Контракт: docs/CHANNEL_STS_FUEL_SHIFT_TTN.md.
"""
from __future__ import annotations

# Каналы оплаты: code, name, warehouse_name, requires_transfer
GIG_PAYMENT_CHANNELS: list[dict] = [
    {"code": "retail",        "name": "Розница (наличные + эквайринг)", "warehouse_name": None,        "requires_transfer": False},
    {"code": "retail_cash",   "name": "Наличные",                       "warehouse_name": None,        "requires_transfer": False},
    {"code": "retail_card",   "name": "Банковские карты",               "warehouse_name": None,        "requires_transfer": False},
    {"code": "cards",         "name": "Топливные карты",                "warehouse_name": "Карты",     "requires_transfer": True},
    {"code": "online",        "name": "Онлайн (Яндекс, МобилПр.)",      "warehouse_name": "ЯНДЕКС",    "requires_transfer": True},
    {"code": "voucher",       "name": "Талоны",                         "warehouse_name": "Талоны",    "requires_transfer": True},
    {"code": "ledger",        "name": "Ведомости",                      "warehouse_name": "Ведомости", "requires_transfer": True},
    {"code": "writeoff_fuel", "name": "Списание топлива (Прочие)",      "warehouse_name": None,        "requires_transfer": False},
]

# Маппинг оплат: pattern (lower), channel_code, warehouse_override
# (база — живой справочник прода, 22 записи + досев 14.07.2026, см. хвост списка)
GIG_PAYMENT_MAPPINGS: list[dict] = [
    {"pattern": "наличн",       "channel_code": "retail_cash",   "warehouse_override": None},
    {"pattern": "сбербанк",     "channel_code": "retail_card",   "warehouse_override": None},
    {"pattern": "viacard",      "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "балтоп",       "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "baltop",       "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "корпоратив",   "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "корп.карты",   "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "топливн",      "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "агора",        "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "инфорком",     "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "газпромнефть", "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "мосресурс",    "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "яндекс",       "channel_code": "online",        "warehouse_override": "ЯНДЕКС"},
    {"pattern": "мобил",        "channel_code": "online",        "warehouse_override": "ЯНДЕКС"},
    {"pattern": "мобилпр.",     "channel_code": "online",        "warehouse_override": "ЯНДЕКС"},
    {"pattern": "benzuber",     "channel_code": "online",        "warehouse_override": "ЯНДЕКС"},
    {"pattern": "ведомост",     "channel_code": "ledger",        "warehouse_override": "Ведомости"},
    {"pattern": "талон",        "channel_code": "voucher",       "warehouse_override": "Талоны"},
    {"pattern": "прочи",        "channel_code": "writeoff_fuel", "warehouse_override": None},
    {"pattern": "прочие",       "channel_code": "writeoff_fuel", "warehouse_override": None},
    {"pattern": "купон",        "channel_code": "",              "warehouse_override": None},
    {"pattern": "прокач",       "channel_code": "",              "warehouse_override": None},
    # ↓ живой справочник прода (сверка 13-14.07.2026): дубли-аналитика и спец-виды.
    {"pattern": "дисконт",      "channel_code": "",              "warehouse_override": None},
    {"pattern": "монополи",     "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "кредит",       "channel_code": "ledger",        "warehouse_override": "Ведомости"},
    {"pattern": "кред.рубл",    "channel_code": "",              "warehouse_override": None},
    # ↓ транзакционный грейн STS (/v2/transactions) — имена видов оплаты отличаются
    # от сменного sales-блока: «Карта МПС» = банковские карты (64% реализаций ГИГ),
    # «КР» = локальные топливные карты. ПОРЯДОК: 'кр' строго после 'кредит'/'кред.рубл',
    # иначе подстрочный матч перехватит «Кредит».
    {"pattern": "мпс",          "channel_code": "retail_card",   "warehouse_override": None},
    {"pattern": "кр",           "channel_code": "cards",         "warehouse_override": "Карты"},
    {"pattern": "мерник",       "channel_code": "writeoff_fuel", "warehouse_override": None},
    {"pattern": "отпуск бо",    "channel_code": "writeoff_fuel", "warehouse_override": None},
]

# Виды топлива: service_code, fuel_name, nomenclature_tonnes, nomenclature_liters, density
GIG_FUEL_MAPPINGS: list[dict] = [
    {"service_code": 1, "fuel_name": "АИ-100",                 "nomenclature_tonnes": "АИ-100(т)",                 "nomenclature_liters": "АИ-100(л)",                 "density": 0.760},
    {"service_code": 2, "fuel_name": "АИ-92",                  "nomenclature_tonnes": "АИ-92(т)",                  "nomenclature_liters": "АИ-92 (л)",                 "density": 0.738},
    {"service_code": 3, "fuel_name": "АИ-95",                  "nomenclature_tonnes": "АИ-95(т)",                  "nomenclature_liters": "АИ-95 (л)",                 "density": 0.741},
    {"service_code": 4, "fuel_name": "АИ-98",                  "nomenclature_tonnes": "АИ-98(т)",                  "nomenclature_liters": "АИ-98(л)",                  "density": 0.755},
    {"service_code": 5, "fuel_name": "Дизельное топливо",      "nomenclature_tonnes": "Дизельное топливо (т)",      "nomenclature_liters": "Дизельное топливо (л)",      "density": 0.819},
    {"service_code": 6, "fuel_name": "Дизельное топливо ЗИМА", "nomenclature_tonnes": "Дизельное топливо ЗИМА (т)", "nomenclature_liters": "Дизельное топливо ЗИМА (л)", "density": 0.840},
    {"service_code": 7, "fuel_name": "Газ углеводородный",     "nomenclature_tonnes": "Газ углеводородный (т)",     "nomenclature_liters": "СУГ (л)",                    "density": 0.550},
]
