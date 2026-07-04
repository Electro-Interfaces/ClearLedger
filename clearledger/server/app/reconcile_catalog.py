"""
Справочник РАЗРЕЗОВ СВЕРКИ (ReconRule) — третий справочник TradeLedger.

Разрез = подключаемый компонент сверки из 6 кубиков (стратегия §6.2):
  streams (потоки+роли) · filter (предикат канала) · key (ключ разбиения) ·
  match (стратегия сопоставления) · compare (поля+допуски) · severity (пороги).
Исполняется ОДНИМ движком (целевой backend `ReconcileEngine`). Каналы
(`channel_catalog.py`) подключают разрезы по `id` (переиспользование).

status:
  "imperative" — рабочая реализация ЕСТЬ, но императивная (frontend TS,
                 своя топология) = **golden-эталон поведения**; цель — вынести
                 в единый движок (§6.4), сверяя byte-for-byte против golden;
  "planned"    — только декларация (движка/реализации нет).

Дисциплина переноса (§6.4): (1) вынести числа/предикаты в данные при
сохранении императивных движков → (2) снять golden на боевых ГИГ →
(3) унифицировать топологию. doc↔entry по ИНН — ОТДЕЛЬНАЯ ось, не сливать.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


# ---------------------------------------------------------------------------
# 6 кубиков разреза
# ---------------------------------------------------------------------------
@dataclass
class StreamRef:
    """Поток разреза: роль + откуда берётся (source_type × doc_type)."""

    role: str            # anchor | external | control | reference
    source_type: str
    doc_type: str
    label: str


@dataclass
class BonusField:
    """Поле-усилитель матчинга (вес + допуск/равенство)."""

    field: str
    weight: int
    tol: float | None = None   # допуск (если числовое)
    eq: bool = False           # точное равенство (если категориальное)


@dataclass
class MatchSpec:
    time_tolerance: str               # "90s" / "30min"
    pick: str = "nearest_time"
    bonus_fields: list[BonusField] = field(default_factory=list)


@dataclass
class CompareField:
    field: str
    tolerance_abs: float
    unit: str


@dataclass
class SeveritySpec:
    thresholds: dict                  # {none, rounding, minor, material}
    critical_fields: list[str] = field(default_factory=list)
    period_promote: dict = field(default_factory=dict)


@dataclass
class ReconRuleDecl:
    id: str
    label: str
    module: str                       # fuel | sidegoods | food
    description: str
    status: str                       # imperative | planned
    streams: list[StreamRef]
    key: list[str]
    match: MatchSpec
    compare: list[CompareField]
    severity: SeveritySpec
    filter: dict = field(default_factory=dict)   # предикат «мой канал»
    impl: str = ""                    # ссылка на реализацию (если есть)
    statuses_codomain: list[str] = field(default_factory=list)  # статусы результата


# Стандартные пороги severity для топливных литровых разрезов (§6.2)
_SEV_FUEL = SeveritySpec(
    thresholds={"none": 0.005, "rounding": 0.05, "minor": 1.0, "material": 100.0},
    critical_fields=["inn"],
    period_promote={"rounding": "minor", "minor": "material"},
)


# ---------------------------------------------------------------------------
# Справочник разрезов
# ---------------------------------------------------------------------------
RECONCILE_RULES: list[ReconRuleDecl] = [
    # ── GOLDEN: корп-карты (TradeCorp ↔ TF ↔ смена) — §6.2, импер. реализация ──
    ReconRuleDecl(
        id="corp_fuel",
        label="Корп-карты: TradeCorp ↔ смена",
        module="fuel",
        description=(
            "Трёхсторонняя сверка корп-процессинга: операции TF (STS /v2) ↔ "
            "транзакции TradeCorp, с привязкой к смене. Golden — императивная "
            "реализация во фронте; декларативная форма = §6.2."
        ),
        status="imperative",
        impl="src/services/reconciliation (executeReconciliation; Corp↔TF↔Смена)",
        streams=[
            StreamRef("anchor", "sts", "transactions", "TF-операции (STS)"),
            StreamRef("external", "tradecorp", "card_transactions", "Корп-карты"),
            StreamRef("control", "sts", "shift_report", "Смена"),
        ],
        filter={"tf.pay_channel": {"in": ["corp", "cards"]}},
        key=["station", "fuel"],
        match=MatchSpec(
            time_tolerance="90s",
            pick="nearest_time",
            bonus_fields=[
                BonusField("card_last4", 50, eq=True),
                BonusField("amount", 30, tol=1.0),
                BonusField("volume", 20, tol=0.01),
            ],
        ),
        compare=[CompareField("volume", 0.01, "л"), CompareField("amount", 1.0, "₽")],
        severity=_SEV_FUEL,
        statuses_codomain=["only_corp", "only_tf", "mismatch", "matched"],
    ),

    # ── GOLDEN: онлайн (MSTO ↔ TF ↔ смена) — 3 источника, импер. реализация ──
    ReconRuleDecl(
        id="online_fuel",
        label="Онлайн: MSTO ↔ TF ↔ смена",
        module="fuel",
        description=(
            "Трёхисточниковая сверка онлайн-заказов: MSTO ↔ операции TF ↔ смена. "
            "Маппинги агрегаторов/топлива. Golden — императивная реализация фронта."
        ),
        status="imperative",
        impl="src/services/mstoReconciliation (3 источника: MSTO↔TF↔Смена)",
        streams=[
            StreamRef("anchor", "sts", "transactions", "TF-операции (STS)"),
            StreamRef("external", "msto", "online_orders", "MSTO заказы"),
            StreamRef("control", "sts", "shift_report", "Смена"),
        ],
        filter={"tf.pay_channel": {"in": ["online"]}},
        key=["station", "fuel"],
        match=MatchSpec(
            time_tolerance="30min",
            pick="nearest_time",
            bonus_fields=[
                BonusField("amount", 50, tol=10.0),
                BonusField("volume", 50, tol=1.0),
            ],
        ),
        compare=[CompareField("volume", 1.0, "л"), CompareField("amount", 10.0, "₽")],
        severity=SeveritySpec(
            thresholds={"none": 1.0, "rounding": 10.0, "minor": 50.0, "material": 500.0},
            period_promote={"rounding": "minor", "minor": "material"},
        ),
        statuses_codomain=["only_msto", "msto_wait_done", "only_tf", "only_shift", "mismatch", "matched"],
    ),

    # ── PLANNED: банк-карты (эквайринг Сбер ↔ смена) ──
    ReconRuleDecl(
        id="acquiring_fuel",
        label="Банк-карты: эквайринг ↔ смена",
        module="fuel",
        description="Реестр оплат Сбер-эквайринга ↔ безналичный канал смены (retail_card).",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (retail_card)"),
            StreamRef("external", "acquiring_sber", "card_payments", "Реестр эквайринга"),
        ],
        filter={"shift.pay_type": {"in": ["retail_card"]}},
        key=["station", "date"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 10.0, "material": 100.0}),
    ),

    # ── PLANNED: фискализация (ОФД Σ ↔ смена) ──
    ReconRuleDecl(
        id="receipts_ofd",
        label="Фискализация: ОФД ↔ Σ продаж",
        module="fuel,sidegoods,food",
        description="Σ фискальных чеков ОФД ↔ итог продаж смены/ОРП.",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (Σ)"),
            StreamRef("external", "ofd", "fiscal_receipts", "Фискальные чеки"),
        ],
        key=["station", "shift"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 50.0, "material": 500.0}),
    ),

    # ── PLANNED: маркировка (Честный Знак ↔ ОРП сопутки) ──
    ReconRuleDecl(
        id="marking_sidegoods",
        label="Маркировка: Честный Знак ↔ ОРП сопутки",
        module="sidegoods",
        description="Движение кодов маркировки ↔ продажи маркируемых в ОРП сопутки.",
        status="planned",
        streams=[
            StreamRef("anchor", "onec_operational", "orp_sidegoods", "ОРП (маркируемые)"),
            StreamRef("external", "chestny_znak", "marking_movement", "Движение кодов ЧЗ"),
        ],
        key=["gtin", "datamatrix"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("quantity", 0.0, "шт")],
        severity=SeveritySpec(thresholds={"none": 0.0, "material": 1.0}, critical_fields=["datamatrix"]),
    ),

    # ── PLANNED: инкассация (наличные смены ↔ внесения в банк) ──
    ReconRuleDecl(
        id="inkassation",
        label="Инкассация: наличные смены ↔ банк",
        module="fuel,sidegoods,food",
        description="Наличная выручка смены ↔ фактически инкассировано в банк (контроль недостач).",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (наличные)"),
            StreamRef("external", "inkassation", "cash_deposits", "Реестр инкассации"),
        ],
        key=["station", "date"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 100.0, "material": 1000.0},
                              critical_fields=["station"]),
    ),

    # ── PLANNED: НДС (ставки/суммы смены ↔ ОФД) ──
    ReconRuleDecl(
        id="vat_check",
        label="НДС: смена ↔ ОФД",
        module="fuel,sidegoods,food",
        description="Контроль НДС (ставки/суммы) против фискальных данных ОФД.",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (НДС)"),
            StreamRef("external", "ofd", "fiscal_receipts", "ОФД (НДС)"),
        ],
        key=["station", "shift"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("vat", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 10.0, "material": 100.0}),
    ),

    # ── PLANNED: возвраты (ОРП ↔ чеки возврата ОФД) ──
    ReconRuleDecl(
        id="returns",
        label="Возвраты: ОРП ↔ ОФД",
        module="sidegoods,food",
        description="Возвращённые товары смены ↔ чеки возврата ОФД.",
        status="planned",
        streams=[
            StreamRef("anchor", "onec_operational", "orp_sidegoods", "Возвраты ОРП"),
            StreamRef("external", "ofd", "fiscal_receipts", "ОФД (возвраты)"),
        ],
        key=["station", "shift"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 50.0, "material": 500.0}),
    ),

    # ── PLANNED: талоны (смена ↔ расчёты эмитента/договор) ──
    ReconRuleDecl(
        id="voucher",
        label="Талоны: смена ↔ расчёты эмитента",
        module="fuel",
        description="Продажи по талонам ↔ расчёты с эмитентом талонов (договор/БП).",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (талоны)"),
            StreamRef("external", "onec_accounting", "closed_period_docs", "Расчёты по талонам (БП)"),
        ],
        key=["station", "date"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 50.0, "material": 500.0}),
    ),

    # ── PLANNED: ведомости (постоплата ↔ дебиторка 62.Р) ──
    ReconRuleDecl(
        id="ledger",
        label="Ведомости: смена ↔ дебиторка (62.Р)",
        module="fuel,sidegoods",
        description="Отпуск по ведомостям ↔ дебиторка контрагента-ведомости в БП.",
        status="planned",
        streams=[
            StreamRef("anchor", "sts", "shift_report", "Смена (ведомости)"),
            StreamRef("external", "onec_accounting", "closed_period_docs", "Дебиторка ведомостей (БП)"),
        ],
        key=["station", "contractor"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 1.0, "₽")],
        severity=SeveritySpec(thresholds={"none": 1.0, "minor": 100.0, "material": 1000.0}),
    ),

    # ── ENERGY (РусГидро): договорная полнота + платёжная дисциплина по ЭЗС ──
    # Потребляют L2 реестра «Договоры и оплаты ЭЗС» (StationContractSettlement),
    # роль energy/rent. Декларация разреза; движок — поверх settlements (фронт-агрегат).
    ReconRuleDecl(
        id="energy_suppliers",
        label="Поставщики э/э: договор + оплата по ЭЗС",
        module="energy",
        description=(
            "Контур энергоснабжения (закупка): по каждой ЭЗС — поставщик, договор "
            "энергоснабжения и статус оплаты («оплачено по»). Договорная полнота и "
            "платёжная дисциплина. Дополняет физическую сверку ПУ ЭЗС ↔ ПУ поставщика."
        ),
        status="planned",
        impl="StationContractSettlement(role=energy) + /payment-discipline/summary",
        streams=[
            StreamRef("anchor", "manual_table", "contracts_payments", "Реестр: энергоснабжение"),
        ],
        key=["station"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("paid_through", 0.0, "период")],
        severity=SeveritySpec(thresholds={"none": 0.0, "minor": 1.0, "material": 2.0}),
    ),
    ReconRuleDecl(
        id="energy_rent",
        label="Аренда: договор/разрешение + оплата по ЭЗС",
        module="energy",
        description=(
            "Контур аренды земли/площадки: по каждой ЭЗС — арендодатель, договор или "
            "разрешение и статус оплаты. Включает муниципальные основания (разрешение/"
            "постановление/приказ) и особый порядок (% от выручки, сервитут)."
        ),
        status="planned",
        impl="StationContractSettlement(role=rent) + /payment-discipline/summary",
        streams=[
            StreamRef("anchor", "manual_table", "contracts_payments", "Реестр: аренда"),
        ],
        key=["station"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("paid_through", 0.0, "период")],
        severity=SeveritySpec(thresholds={"none": 0.0, "minor": 1.0, "material": 2.0}),
    ),

    # ── ENERGY (РусГидро): расчёты по зарядным сессиям ЭЗС ──
    # Классификационный разрез: каждая сессия при нормализации помечается cut_key-
    # корзиной по каналу расчёта (эквайринг / корп.карты / без оплаты / служебные).
    # Ставит сессии ЭЗС в конвейер достоверности — основа сверки их выручки с
    # эквайрингом/ведомостями/1С (встречный источник для матча — план).
    ReconRuleDecl(
        id="ezs_settlement",
        label="Расчёты по сессиям ЭЗС (канал оплаты)",
        module="energy",
        description=(
            "Разрез зарядных сессий по каналу расчёта: моб. приложение ФЛ (эквайринг), "
            "юрлица/корп. (ведомости/договоры per-контрагент — client_name из "
            "обогащения), картовые без оплаты (утечка), служебные. Каждая сессия "
            "помечается cut_key при нормализации; корп-выручка сверяется по энергии×"
            "тарифу (amount мгновенного списания у ЮЛ = 0). Встречный источник — план."
        ),
        status="planned",
        impl="ChargeSession.cut_key (charge_sessions_normalize._cut_key); группировка по cut_key/client_name",
        streams=[
            StreamRef("anchor", "charge_sessions_excel", "sessions", "Сессии ЭЗС"),
        ],
        filter={"cut_key": {"in": ["ezs_app", "ezs_corp", "ezs_unpaid", "ezs_admin"]}},
        key=["cut_key", "client_name", "station"],
        match=MatchSpec(time_tolerance="0", pick="exact"),
        compare=[CompareField("amount", 0.01, "₽")],
        severity=SeveritySpec(thresholds={"none": 0.0, "minor": 100.0, "material": 1000.0}),
        statuses_codomain=["ezs_app", "ezs_corp", "ezs_unpaid", "ezs_admin"],
    ),
]


def list_reconcile_rules() -> list[dict]:
    """Справочник разрезов сверки для UI/API (сериализованный)."""
    return [asdict(r) for r in RECONCILE_RULES]
