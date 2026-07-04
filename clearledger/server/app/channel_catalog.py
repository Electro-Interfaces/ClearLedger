"""
Справочник шаблонов КАНАЛОВ обработки первичных данных.

Канал = конвейер: связывает 1+ ИСТОЧНИКОВ (потоки) и прогоняет их через
стадии предобработки → преобразования → сверки → сохранения. Шаблон —
запись справочника, из которой создаётся экземпляр `Channel` под компанию
(с `ChannelStream` на каждый источник и `ChannelStage` на каждую стадию).

Параллель источникам (`adapters/catalog.py`): там — типы ИСТОЧНИКОВ, здесь —
типы КАНАЛОВ. Источники в потоках ссылаются на `source_type` ЕДИНОГО реестра
адаптеров (sts / onec_operational / onec_accounting / tradecorp / msto /
acquiring_sber / ofd / chestny_znak / neftoms).

status: "available" — все источники канала рабочие; "partial" — опорный
рабочий, часть сверки planned; "planned" — опорный источник ещё planned.

Каталог под ГИГ — `D:\\Users\\magsp\\Ledger\\docs\\SOURCES_GIG.md`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


# ---------------------------------------------------------------------------
# Декларативные части шаблона канала
# ---------------------------------------------------------------------------
@dataclass
class StreamDecl:
    """Поток канала: что из какого источника тянем и в какой роли."""

    source_type: str          # = source_type из реестра адаптеров
    doc_type: str             # = id из available_doc_types источника
    role: str                 # anchor | control | external | reference
    label: str


@dataclass
class StageDecl:
    """Стадия конвейера (предобработка → преобразование → сверка → …)."""

    stage_type: str           # fetch | normalize | transform | reconcile | validate | save
    name: str


@dataclass
class ChannelTemplateDecl:
    """Запись справочника каналов."""

    id: str
    label: str
    category: str
    description: str
    icon: str
    direction: str            # fuel | sidegoods | food | reference
    status: str               # available | partial | planned
    streams: list[StreamDecl]
    stages: list[StageDecl]
    reconcile_rules: list[str] = field(default_factory=list)  # id из reconcile_catalog
    schedule: dict = field(default_factory=lambda: {"mode": "manual"})


# ---------------------------------------------------------------------------
# Типовые наборы стадий
# ---------------------------------------------------------------------------
_STAGES_FULL = [
    StageDecl("fetch", "Сбор (выгрузка из источников)"),
    StageDecl("normalize", "Нормализация (предобработка → L2 CLEAN)"),
    StageDecl("transform", "Преобразование (доменные правила)"),
    StageDecl("reconcile", "Сверка (по разрезам)"),
    StageDecl("validate", "Контроль (пороги/полнота)"),
    StageDecl("save", "Сохранение (L2 → готово к L3)"),
]
_STAGES_INGEST = [
    StageDecl("fetch", "Сбор"),
    StageDecl("normalize", "Нормализация → L2 CLEAN"),
    StageDecl("save", "Сохранение"),
]
_SCHED_HOURLY = {"mode": "interval", "interval_minutes": 60,
                 "active_from": "07:00", "active_to": "23:00",
                 "pause_on_error": True, "max_retries": 3}
_SCHED_DAILY = {"mode": "cron", "cron": "0 7 * * *", "pause_on_error": True, "max_retries": 3}


# ---------------------------------------------------------------------------
# Справочник каналов ГИГ
# ---------------------------------------------------------------------------
CHANNEL_TEMPLATES: list[ChannelTemplateDecl] = [
    # ── Нефтепродукты ────────────────────────────────────────────────────
    ChannelTemplateDecl(
        id="fuel_shift",
        label="Топливо: сменный отчёт (со сверкой каналов)",
        category="Нефтепродукты",
        description=(
            "Опорный — сменный отчёт STS (все pay_type). Контрольные источники "
            "сверяют срезы: корп-карты ↔ TradeCorp, онлайн ↔ MSTO, банк-карты ↔ "
            "эквайринг, Σ ↔ ОФД. Многоисточниковый канал."
        ),
        icon="Fuel",
        direction="fuel",
        status="partial",   # опорный sts рабочий, контрольные planned
        streams=[
            StreamDecl("sts", "shift_report", "anchor", "Сменный отчёт"),
            StreamDecl("tradecorp", "card_transactions", "control", "Корп-карты"),
            StreamDecl("msto", "online_orders", "control", "Онлайн-заказы"),
            StreamDecl("acquiring_sber", "card_payments", "control", "Банк-карты"),
            StreamDecl("ofd", "fiscal_receipts", "control", "Фискальные Σ"),
        ],
        stages=_STAGES_FULL,
        reconcile_rules=["corp_fuel", "online_fuel", "acquiring_fuel", "receipts_ofd"],
        schedule=_SCHED_HOURLY,
    ),
    ChannelTemplateDecl(
        id="fuel_delivery",
        label="Топливо: приём (ТТН)",
        category="Нефтепродукты",
        description="ТТН по нефтепродуктам из STS (плотность/масса/объём) → ПТУ.",
        icon="Truck",
        direction="fuel",
        status="partial",
        streams=[StreamDecl("sts", "receipt", "anchor", "ТТН")],
        stages=_STAGES_INGEST,
        schedule=_SCHED_HOURLY,
    ),

    # ── Сопутка ──────────────────────────────────────────────────────────
    ChannelTemplateDecl(
        id="sidegoods",
        label="Сопутка (магазин)",
        category="Сопутка",
        description=(
            "Опорный — ЦБ ЭЛСИ.АЗК (ОРП/ПТУ/перемещение/списание/инвентаризация). "
            "Контроль: Честный Знак (маркируемые), ОФД (Σ), эквайринг (банк-карты)."
        ),
        icon="ShoppingCart",
        direction="sidegoods",
        status="planned",
        streams=[
            StreamDecl("onec_operational", "orp_sidegoods", "anchor", "ОРП сопутки"),
            StreamDecl("onec_operational", "purchase", "anchor", "Поступление (ПТУ)"),
            StreamDecl("onec_operational", "transfer", "anchor", "Перемещение"),
            StreamDecl("onec_operational", "writeoff", "anchor", "Списание"),
            StreamDecl("onec_operational", "inventory", "anchor", "Инвентаризация"),
            StreamDecl("chestny_znak", "marking_movement", "control", "Маркировка"),
            StreamDecl("ofd", "fiscal_receipts", "control", "Фискальные Σ"),
            StreamDecl("acquiring_sber", "card_payments", "control", "Банк-карты"),
        ],
        stages=_STAGES_FULL,
        reconcile_rules=["marking_sidegoods", "receipts_ofd"],
        schedule=_SCHED_DAILY,
    ),

    # ── Общепит ──────────────────────────────────────────────────────────
    ChannelTemplateDecl(
        id="food",
        label="Общепит",
        category="Общепит",
        description=(
            "Опорный — ЦБ ЭЛСИ.АЗК (ОРП-блюда, выпуск, списание ингредиентов); "
            "справочный поток — ТТК (рецептуры, разворот блюд на ингредиенты). "
            "Контроль: ОФД, эквайринг."
        ),
        icon="UtensilsCrossed",
        direction="food",
        status="planned",
        streams=[
            StreamDecl("onec_operational", "food_sale", "anchor", "ОРП блюд"),
            StreamDecl("onec_operational", "production_release", "anchor", "Выпуск продукции"),
            StreamDecl("onec_operational", "recipe", "reference", "ТТК (рецептуры)"),
            StreamDecl("ofd", "fiscal_receipts", "control", "Фискальные Σ"),
            StreamDecl("acquiring_sber", "card_payments", "control", "Банк-карты"),
        ],
        stages=[
            StageDecl("fetch", "Сбор (+ТТК)"),
            StageDecl("normalize", "Нормализация + разворот блюд по ТТК → ингредиенты"),
            StageDecl("transform", "Преобразование"),
            StageDecl("reconcile", "Сверка"),
            StageDecl("validate", "Контроль"),
            StageDecl("save", "Сохранение"),
        ],
        reconcile_rules=["receipts_ofd"],
        schedule=_SCHED_DAILY,
    ),

    # ── Энергоснабжение / Аренда (РусГидро) ───────────────────────────────
    ChannelTemplateDecl(
        id="reestr_contracts_payments",
        label="Энергоснабжение и аренда ЭЗС",
        category="Энергоснабжение",
        description=(
            "Ручная таблица (xlsx) «Договоры и оплаты ЭЗС»: по каждой станции — "
            "энергоснабжение и аренда с контрагентом, договором/разрешением и статусом "
            "оплаты. Загрузка файла → L1 RAW → нормализация → L2 (контрагенты/договоры/"
            "платёжная дисциплина) → разрезы «Поставщики э/э» и «Аренда»."
        ),
        icon="Table",
        direction="energy",
        status="available",
        streams=[
            StreamDecl("manual_table", "contracts_payments", "anchor", "Реестр договоров и оплат"),
        ],
        stages=_STAGES_INGEST,
        reconcile_rules=["energy_suppliers", "energy_rent"],
        schedule={"mode": "manual"},
    ),
    ChannelTemplateDecl(
        id="charge_sessions",
        label="Зарядные сессии ЭЗС",
        category="Электромобильность",
        description=(
            "Выгрузка зарядных сессий (xlsx, ChargeTransactions): по каждой сессии — "
            "станция, коннектор, энергия (кВтч), сумма, тариф, тип пользователя, результат. "
            "Загрузка файла → L1 RAW → нормализация (коннектор/ФЛ-ЮЛ) → L2 (charge_sessions) "
            "→ разрезы реализации ЭЗС. Разрез учёта привяжем позже."
        ),
        icon="Zap",
        direction="energy",
        status="available",
        streams=[
            StreamDecl("charge_sessions_excel", "charge_sessions", "anchor", "Сессии реализации"),
        ],
        stages=_STAGES_INGEST,
        schedule={"mode": "manual"},
    ),
    ChannelTemplateDecl(
        id="stations",
        label="Справочник станций ЭЗС",
        category="Электромобильность",
        description=(
            "Справочник объектов ЭЗС (xlsx): по каждой станции — паспорт (серийный, "
            "адрес, координаты, коннекторы, мощность, OCPP, бренд, владелец, HubEx). "
            "Загрузка файла → L1 RAW → нормализация → L2 (объекты / Точки обслуживания) "
            "→ разрез по региону / владельцу / статусу."
        ),
        icon="MapPin",
        direction="energy",
        status="available",
        streams=[
            StreamDecl("stations_excel", "stations", "anchor", "Паспорт станций"),
        ],
        stages=_STAGES_INGEST,
        schedule={"mode": "manual"},
    ),

    # ── Эталон ───────────────────────────────────────────────────────────
    ChannelTemplateDecl(
        id="reference_1c",
        label="Эталон: репликация 1С:Бухгалтерии (L4)",
        category="Эталон",
        description=(
            "ОСОБЫЙ канал: тянет из 1С:Бухгалтерии НСИ, документы закрытого "
            "периода и учётполитику → ReferenceSnapshot (L4). Идёт через onec_router."
        ),
        icon="BookCheck",
        direction="reference",
        status="partial",
        streams=[
            StreamDecl("onec_accounting", "catalogs", "reference", "НСИ"),
            StreamDecl("onec_accounting", "closed_period_docs", "reference", "Закрытый период (эталон)"),
            StreamDecl("onec_accounting", "policy", "reference", "Учётная политика"),
        ],
        stages=[
            StageDecl("fetch", "Репликация (sync)"),
            StageDecl("validate", "Снимок эталона (ReferenceSnapshot)"),
        ],
        schedule=_SCHED_DAILY,
    ),
]


def list_channel_templates() -> list[dict]:
    """Справочник шаблонов каналов для UI/API (сериализованный)."""
    return [asdict(t) for t in CHANNEL_TEMPLATES]


def get_channel_template(template_id: str) -> ChannelTemplateDecl | None:
    """Шаблон канала по id (для создания экземпляра Channel)."""
    return next((t for t in CHANNEL_TEMPLATES if t.id == template_id), None)
