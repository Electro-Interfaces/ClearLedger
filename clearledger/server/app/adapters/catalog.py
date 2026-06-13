"""
Справочник типов источников — декларативные записи каталога.

Каждый класс = ТИП источника («штекер») в справочнике: метаданные +
setup_schema + available_doc_types. Из записи справочника UI/код создаёт
экземпляр Source под компанию (привязка company_id + connection_config +
SourceCredentials) и настраивает по setup_schema.

status:
  "available" — поведение реализовано (test_connection/fetch_delta работают);
  "planned"   — только запись справочника: метаданные/форма есть, поведение
                = NotImplemented (реализуется при постройке адаптера).

Когда у типа появляется рабочее поведение — выносим его в отдельный модуль
adapters/<type>/ (как `sts`) и убираем запись отсюда.

Каталог под ГИГ — `D:\\Users\\magsp\\Ledger\\docs\\SOURCES_GIG.md`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters import register_adapter
from app.adapters.base import (
    RawBatch,
    SetupField,
    SourceAdapter,
    SourceDocType,
    TestResult,
)


class PlannedAdapter(SourceAdapter):
    """База для записей справочника без реализованного поведения."""

    status = "planned"

    async def test_connection(self, connection: dict[str, Any]) -> TestResult:
        return TestResult(
            ok=False,
            message=(
                f"Источник '{self.source_type}' есть в справочнике, "
                f"но поведение ещё не реализовано (status=planned)."
            ),
        )

    async def fetch_delta(
        self,
        connection: dict[str, Any],
        doc_type: str,
        since: datetime | None = None,
        until: datetime | None = None,
        filters: dict[str, Any] | None = None,
    ) -> RawBatch:
        raise NotImplementedError(
            f"Источник '{self.source_type}' в справочнике; fetch_delta не реализован."
        )


# Общий набор полей для 1С-источников (pull через COM/OData/HTTP).
_ONEC_FIELDS = [
    SetupField(
        key="mode",
        label="Режим подключения",
        field_type="select",
        default_value="com",
        options=[
            {"value": "com", "label": "COM (V83.COMConnector)"},
            {"value": "odata", "label": "OData (HTTP-публикация)"},
            {"value": "http_agent", "label": "HTTP-агент"},
        ],
        help_text="Способ pull из 1С (TradeLedger тянет из базы).",
    ),
    SetupField(
        key="connection_string",
        label="Строка соединения / URL",
        field_type="text",
        placeholder='Srvr="SQL1";Ref="azs_centre"  ·  https://host/base/odata/standard.odata',
        help_text="Для COM — Srvr/Ref; для OData/HTTP — URL базы.",
    ),
    SetupField(key="login", label="Логин", field_type="text"),
    SetupField(key="password", label="Пароль", field_type="password", secret=True),
]

# Операционная 1С: тот же pull-механизм, конфигурация — параметр.
_ONEC_OPERATIONAL_FIELDS = [
    SetupField(
        key="configuration",
        label="Конфигурация 1С",
        field_type="select",
        default_value="elsi_azk",
        options=[
            {"value": "elsi_azk", "label": "ЭЛСИ.АЗК (сеть АЗС)"},
            {"value": "ut", "label": "Управление торговлей (УТ)"},
            {"value": "ka", "label": "Комплексная автоматизация (КА)"},
            {"value": "roznica", "label": "Розница"},
            {"value": "moedelo", "label": "Моё дело"},
            {"value": "other", "label": "Прочая конфигурация"},
        ],
        help_text="Тип конфигурации определяет маппинг документов (политика — данные, механизм общий).",
    ),
    *_ONEC_FIELDS,
]


# ---------------------------------------------------------------------------
# Операционные системы 1С (ЛЮБАЯ конфигурация — источник; механизм pull общий)
# ---------------------------------------------------------------------------
@register_adapter("onec_operational")
class OnecOperationalAdapter(PlannedAdapter):
    label = "1С операционная база (УТ / КА / Розница / Моё дело / ЭЛСИ.АЗК)"
    category = "Учётные системы 1С"
    description = (
        "Любая операционная конфигурация 1С как опорный/внешний источник. "
        "Pull через COM/OData/HTTP — механизм общий, конфигурация задаётся полем. "
        "Для ГИГ конфигурация = ЭЛСИ.АЗК (сопутка/общепит + ТТК). Состав документов "
        "зависит от конфигурации."
    )
    icon = "Database"
    setup_schema = _ONEC_OPERATIONAL_FIELDS
    available_doc_types = [
        SourceDocType(id="sale", name="Реализация / ОРП", category="operational"),
        SourceDocType(id="purchase", name="Поступление (ПТУ)", category="operational"),
        SourceDocType(id="transfer", name="Перемещение", category="operational"),
        SourceDocType(id="writeoff", name="Списание", category="operational"),
        SourceDocType(id="inventory", name="Инвентаризация", category="operational"),
        SourceDocType(id="production_release", name="Выпуск продукции (общепит/произв.)", category="operational"),
        SourceDocType(id="recipe", name="ТТК / спецификация (рецептуры)", category="operational"),
    ]


# ---------------------------------------------------------------------------
# 1С:Бухгалтерия компании — ОСОБЫЙ источник (эталон), идёт отдельным механизмом
# ---------------------------------------------------------------------------
@register_adapter("onec_accounting")
class OnecAccountingAdapter(PlannedAdapter):
    status = "partial"  # механизм частично реализован отдельно (onec_router/OneCConnection)
    label = "1С:Бухгалтерия компании (эталон)"
    category = "Эталон компании (1С:Бухгалтерия)"
    description = (
        "ОСОБЫЙ источник: бухгалтерия компании = эталон (L4) + приёмник L3. "
        "Идёт ОТДЕЛЬНЫМ механизмом (onec_router/OneCConnection: sync НСИ / "
        "документов закрытого периода / учётполитики — уже частично реализован), "
        "не как обычный Source-адаптер. В справочнике — для полноты картины."
    )
    icon = "BookCheck"
    setup_schema = _ONEC_FIELDS
    available_doc_types = [
        SourceDocType(id="catalogs", name="НСИ (справочники)", category="reference"),
        SourceDocType(id="closed_period_docs", name="Документы закрытого периода (эталон)", category="reference"),
        SourceDocType(id="policy", name="Учётная политика", category="reference"),
    ]


# ---------------------------------------------------------------------------
# Топливный учёт АЗС (внешние источники для сверки срезов сменного отчёта)
# ---------------------------------------------------------------------------
@register_adapter("tradecorp")
class TradeCorpAdapter(PlannedAdapter):
    label = "TradeCorp (корп. процессинг)"
    category = "Топливный учёт АЗС"
    description = (
        "Процессинг корпоративных карт. Внешний источник для сверки "
        "реализации по картам (срез сменного отчёта)."
    )
    icon = "CreditCard"
    setup_schema = [
        SetupField(key="api_url", label="API URL", field_type="url"),
        SetupField(key="login", label="Логин", field_type="text"),
        SetupField(key="password", label="Пароль", field_type="password", secret=True),
        SetupField(key="emitent_id", label="ID эмитента", field_type="number",
                   default_value="15", required=False),
    ]
    available_doc_types = [
        SourceDocType(id="card_transactions", name="Транзакции корп-карт", category="control"),
    ]


@register_adapter("msto")
class MstoAdapter(PlannedAdapter):
    label = "MSTO (онлайн-заказы)"
    category = "Топливный учёт АЗС"
    description = (
        "Онлайн-заказы агрегаторов (Я.Заправки/Benzuber/FuelUp). Внешний "
        "источник для сверки онлайн-канала сменного отчёта."
    )
    icon = "Smartphone"
    setup_schema = [
        SetupField(key="api_url", label="API URL", field_type="url"),
        SetupField(key="username", label="Логин", field_type="text"),
        SetupField(key="password", label="Пароль", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="online_orders", name="Онлайн-заказы/продажи", category="control"),
    ]


# ---------------------------------------------------------------------------
# Платежи / фискализация / маркировка (контрольные источники)
# ---------------------------------------------------------------------------
@register_adapter("acquiring_sber")
class AcquiringSberAdapter(PlannedAdapter):
    label = "Эквайринг Сбербанк"
    category = "Платежи и эквайринг"
    description = (
        "Реестр оплат по банковским картам. Контрольный источник для сверки "
        "безналичного канала (retail_card)."
    )
    icon = "CreditCard"
    setup_schema = [
        SetupField(key="merchant_id", label="Merchant ID / терминал", field_type="text"),
        SetupField(key="api_url", label="API URL", field_type="url", required=False),
        SetupField(key="login", label="Логин", field_type="text"),
        SetupField(key="password", label="Пароль / ключ", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="card_payments", name="Реестр оплат по картам", category="control"),
    ]


@register_adapter("inkassation")
class InkassationAdapter(PlannedAdapter):
    label = "Инкассация (реестр внесений)"
    category = "Платежи и эквайринг"
    description = (
        "Реестр инкассации наличных (банк-выписка/инкассатор) — контроль "
        "фактически внесённых в банк наличных против наличной выручки смены."
    )
    icon = "Banknote"
    setup_schema = [
        SetupField(key="bank_api_url", label="API/файл выписки", field_type="text", required=False),
        SetupField(key="inn", label="ИНН", field_type="text"),
        SetupField(key="account", label="Расчётный счёт", field_type="text", required=False),
        SetupField(key="token", label="Токен/ключ", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="cash_deposits", name="Внесения наличных (инкассация)", category="control"),
    ]


@register_adapter("ofd")
class OfdAdapter(PlannedAdapter):
    label = "ОФД (оператор фискальных данных)"
    category = "Фискализация"
    description = (
        "Фискальные чеки для сверки Σ продаж. Вендор у ГИГ — TBD "
        "(Платформа/Такском/Контур/Первый ОФД)."
    )
    icon = "Receipt"
    setup_schema = [
        SetupField(key="provider", label="Оператор ОФД", field_type="select",
                   options=[
                       {"value": "platforma", "label": "Платформа ОФД"},
                       {"value": "taxcom", "label": "Такском"},
                       {"value": "kontur", "label": "Контур.ОФД"},
                       {"value": "first_ofd", "label": "Первый ОФД"},
                   ],
                   help_text="Вендор у ГИГ уточняется."),
        SetupField(key="inn", label="ИНН", field_type="text"),
        SetupField(key="api_url", label="API URL", field_type="url", required=False),
        SetupField(key="token", label="Токен / ключ", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="fiscal_receipts", name="Фискальные чеки", category="control"),
    ]


@register_adapter("chestny_znak")
class ChestnyZnakAdapter(PlannedAdapter):
    label = "Честный Знак (маркировка)"
    category = "Маркировка"
    description = (
        "Маркируемые товары: статусы/движение кодов (сверка) и вывод из "
        "оборота при продаже (приёмник). Двойная роль — источник и приёмник."
    )
    icon = "ScanBarcode"
    setup_schema = [
        SetupField(key="api_url", label="API URL", field_type="url",
                   default_value="https://markirovka.crpt.ru", required=False),
        SetupField(key="inn", label="ИНН участника", field_type="text"),
        SetupField(key="oms_id", label="OMS ID", field_type="text", required=False),
        SetupField(key="token", label="Токен (УКЭП / OMS)", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="marking_status", name="Статусы кодов маркировки", category="control"),
        SourceDocType(id="marking_movement", name="Движение маркируемых", category="control"),
    ]


# ---------------------------------------------------------------------------
# Касса/POS станции
# ---------------------------------------------------------------------------
@register_adapter("neftoms")
class NeftoMsAdapter(PlannedAdapter):
    label = "NeftoMS (POS станции)"
    category = "Касса/POS АЗС"
    description = (
        "MS SQL база станции (Нефтесервер): детальные чеки C_Food/ControlRibbon. "
        "Внешний источник (опционально, для гранулярной сверки)."
    )
    icon = "Server"
    setup_schema = [
        SetupField(key="host", label="SQL host", field_type="text"),
        SetupField(key="database", label="База", field_type="text", default_value="NeftoMS"),
        SetupField(key="user", label="Пользователь", field_type="text"),
        SetupField(key="password", label="Пароль", field_type="password", secret=True),
    ]
    available_doc_types = [
        SourceDocType(id="pos_receipts", name="POS-чеки", category="external"),
    ]
