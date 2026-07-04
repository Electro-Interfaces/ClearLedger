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
# Электронный документооборот (ЭДО) — юридически значимая первичка
# ---------------------------------------------------------------------------
@register_adapter("edo")
class EdoAdapter(PlannedAdapter):
    label = "ЭДО"
    version = "0.1"
    category = "Электронный документооборот (ЭДО)"
    description = (
        "Входящие и исходящие юридически значимые электронные документы через "
        "оператора ЭДО (УПД, счета-фактуры, акты, накладные) — источник первички."
    )
    setup_guide = (
        "Что запросить и как подключить:\n"
        "\n"
        "1) Определить оператора ЭДО (Контур.Диадок, СБИС/Тензор, Такском, СберКорус "
        "Сфера, Калуга Астрал и др.), через которого компания ведёт документооборот.\n"
        "2) В ЛК оператора / у интегратора получить доступ к API: ключ разработчика "
        "(API-key / client credentials), идентификатор организации (ящик ЭДО / Box ID, "
        "напр. 2AE…@diadoc.ru), ИНН/КПП. Для приёма и подписи документов нужен "
        "сертификат УКЭП (квалифицированная подпись) организации.\n"
        "3) Состав данных: входящие документы (УПД, счёт-фактура, акт, ТОРГ-12, "
        "корректировочные), исходящие документы и статусы документооборота "
        "(подписан / запрошено уточнение / аннулирован) — первичка для поступлений "
        "и реализации.\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "FileCheck"
    setup_schema = [
        SetupField(key="provider", label="Оператор ЭДО", field_type="select", group="Оператор",
                   options=[
                       {"value": "diadoc", "label": "Контур.Диадок"},
                       {"value": "sbis", "label": "СБИС (Тензор)"},
                       {"value": "taxcom", "label": "Такском"},
                       {"value": "sfera", "label": "Сфера (СберКорус)"},
                       {"value": "astral", "label": "Калуга Астрал"},
                       {"value": "other", "label": "Другой оператор"},
                   ],
                   help_text="Оператор ЭДО, через которого ведётся документооборот."),
        SetupField(key="box_id", label="Идентификатор ящика ЭДО (Box ID)", field_type="text",
                   group="Идентификация", placeholder="2AE…@diadoc.ru",
                   help_text="Идентификатор участника/ящика ЭДО организации."),
        SetupField(key="inn", label="ИНН организации", field_type="text", group="Идентификация"),
        SetupField(key="kpp", label="КПП", field_type="text", required=False, group="Идентификация"),
        SetupField(key="api_url", label="API URL", field_type="url", required=False,
                   group="Доступ к API", help_text="Базовый URL API оператора (если требуется)."),
        SetupField(key="api_key", label="API-ключ / client secret", field_type="password",
                   secret=True, group="Доступ к API"),
        SetupField(key="cert_thumbprint", label="Сертификат УКЭП (отпечаток)", field_type="text",
                   required=False, group="Доступ к API",
                   help_text="Отпечаток квалифицированного сертификата для ЮЗ-подписи."),
    ]
    available_doc_types = [
        SourceDocType(id="incoming_docs", name="Входящие документы (УПД/СФ/акты)", category="external"),
        SourceDocType(id="outgoing_docs", name="Исходящие документы", category="external"),
        SourceDocType(id="doc_statuses", name="Статусы документооборота", category="control"),
    ]


# ---------------------------------------------------------------------------
# Топливный учёт АЗС (внешние источники для сверки срезов сменного отчёта)
# ---------------------------------------------------------------------------
@register_adapter("tradecorp")
class TradeCorpAdapter(PlannedAdapter):
    label = "Корп. карты"
    category = "Платежи и каналы продаж"
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
    label = "Онлайн-заказы"
    category = "Платежи и каналы продаж"
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
    label = "Эквайринг (Сбербанк)"
    version = "0.1"
    category = "Платежи и каналы продаж"
    description = (
        "Реестр операций по картам на терминалах + зачисления возмещений на счёт. "
        "Контрольный источник для сверки безналичных продаж по картам."
    )
    setup_guide = (
        "Два способа получить данные эквайринга у Сбербанка:\n"
        "\n"
        "1) Sber API (developers.sber.ru) — автоматическая выгрузка. Запросить у банка / "
        "в СберБизнес: подключение к Sber API, СберБизнес ID, учётные данные приложения "
        "(clientId/clientSecret), право (scope) на выписку по счёту — GET_STATEMENT_ACCOUNT, "
        "сертификат подписи (УКЭП) и номер расчётного счёта зачисления эквайринга. "
        "Выписка: GET /fintech/api/v2/statement/transactions (инкремент дня — /statement/increment); "
        "форматы 1C/MT940. Даёт зачисления возмещений по эквайрингу на счёт.\n"
        "\n"
        "2) Отчёт по эквайрингу из СберБизнес — реестр «Отчёт по зачислениям выручки, "
        "принятым по эквайрингу» (XLSX/CSV): дата операции и дата зачисления, сумма операции "
        "и сумма зачисления, комиссия банка, терминал (TID) и мерчант (MID), маскированная "
        "карта, платёжная система, RRN/код авторизации. Скачивается из ЛК СберБизнес или "
        "приходит на e-mail. Для сверки по точкам нужен реестр с TID/MID (привязка терминала "
        "к торговой точке).\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "CreditCard"
    setup_schema = [
        SetupField(
            key="mode", label="Способ получения", field_type="select",
            default_value="report_file",
            options=[
                {"value": "sber_api", "label": "Sber API (выписка по счёту)"},
                {"value": "report_file", "label": "Отчёт-реестр из СберБизнес (XLSX/CSV)"},
                {"value": "report_email", "label": "Реестр на e-mail (вложение)"},
            ],
            help_text="Способ доставки данных эквайринга от Сбербанка.",
        ),
        SetupField(key="merchant_id", label="Мерчант (MID) / № договора эквайринга", field_type="text",
                   placeholder="напр. 100000000123", group="Идентификация",
                   help_text="ID торговой точки/договора в Сбербанке."),
        SetupField(key="terminals", label="Терминалы (TID) → привязка к точкам", field_type="tags",
                   required=False, group="Идентификация",
                   help_text="Список TID терминалов; нужен для разнесения зачислений по торговым точкам."),
        SetupField(key="account", label="Расчётный счёт зачисления", field_type="text",
                   required=False, placeholder="40702810…", group="Доступ Sber API",
                   help_text="Счёт, на который Сбербанк зачисляет возмещение (для режима Sber API)."),
        SetupField(key="client_id", label="clientId приложения Sber API", field_type="text",
                   required=False, group="Доступ Sber API", help_text="Только для режима Sber API."),
        SetupField(key="client_secret", label="clientSecret Sber API", field_type="password",
                   required=False, secret=True, group="Доступ Sber API"),
        SetupField(key="api_url", label="Base URL Sber API", field_type="url", required=False,
                   default_value="https://api.sberbank.ru", group="Доступ Sber API",
                   help_text="По умолчанию промышленный контур Sber API."),
        SetupField(key="report_email", label="E-mail для реестра", field_type="text", required=False,
                   group="Реестр из СберБизнес / e-mail",
                   help_text="Адрес, на который Сбербанк присылает реестр (режим e-mail)."),
    ]
    available_doc_types = [
        SourceDocType(id="acquiring_register", name="Реестр операций эквайринга (карты/терминалы)", category="control"),
        SourceDocType(id="acquiring_settlement", name="Зачисления возмещений на счёт", category="control"),
    ]


@register_adapter("inkassation")
class InkassationAdapter(PlannedAdapter):
    label = "Инкассация"
    version = "0.1"
    category = "Платежи и каналы продаж"
    description = (
        "Реестр инкассации наличных — контроль фактически внесённых в банк сумм "
        "против наличной выручки смены."
    )
    setup_guide = (
        "Что запросить и как подключить:\n"
        "\n"
        "1) Источник реестра внесений: банк (инкассация банком / инкассаторской службой) "
        "или сервис самоинкассации (умные сейфы, устройства внесения).\n"
        "2) Получить доступ: API/файл выгрузки внесений (через банк-клиент или API банка), "
        "ИНН и расчётный счёт зачисления, токен/ключ.\n"
        "3) Состав данных: внесения наличных (дата, сумма, точка/устройство, реквизиты "
        "сумки/пакета) — для сверки с наличной выручкой смены.\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "Banknote"
    setup_schema = [
        SetupField(key="inn", label="ИНН организации", field_type="text", group="Идентификация"),
        SetupField(key="account", label="Расчётный счёт зачисления", field_type="text",
                   required=False, group="Идентификация"),
        SetupField(key="bank_api_url", label="API / файл выгрузки", field_type="text", required=False,
                   group="Доступ", help_text="URL API банка/сервиса или путь к файлу реестра."),
        SetupField(key="token", label="Токен / ключ", field_type="password", secret=True, group="Доступ"),
    ]
    available_doc_types = [
        SourceDocType(id="cash_deposits", name="Внесения наличных (инкассация)", category="control"),
    ]


# ---------------------------------------------------------------------------
# Банк — движения по расчётному счёту (выписка)
# ---------------------------------------------------------------------------
@register_adapter("bank_statement")
class BankStatementAdapter(PlannedAdapter):
    label = "Банк-выписка"
    version = "0.1"
    category = "Платежи и каналы продаж"
    description = (
        "Движения по расчётному счёту (выписка банка): поступления и списания — "
        "для сверки платежей и разнесения оплат/возмещений."
    )
    setup_guide = (
        "Что запросить и как подключить (2 способа):\n"
        "\n"
        "1) API банка — автоматическая выгрузка выписки. Запросить: подключение к API "
        "банка (Sber API / Т-Банк / Альфа / ВТБ и др.), учётные данные приложения "
        "(clientId/secret или токен), право на выписку по счёту, при необходимости сертификат, "
        "номер расчётного счёта.\n"
        "2) Файл из клиент-банка — выгрузка выписки в формате 1C (1CClientBankExchange) "
        "или MT940 / CSV. Загружается вручную либо из каталога обмена.\n"
        "3) Состав данных: проводки по счёту (дата, сумма, дебет/кредит, контрагент, ИНН, "
        "назначение платежа, БИК/счёт) — основа для сверки и разнесения оплат.\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "Landmark"
    setup_schema = [
        SetupField(key="mode", label="Способ получения", field_type="select", group="Способ",
                   default_value="file_1c",
                   options=[
                       {"value": "bank_api", "label": "API банка (выписка)"},
                       {"value": "file_1c", "label": "Файл 1C (1CClientBankExchange)"},
                       {"value": "mt940", "label": "Файл MT940 / CSV"},
                   ],
                   help_text="Способ доставки выписки от банка."),
        SetupField(key="bank", label="Банк", field_type="select", required=False, group="Банк",
                   options=[
                       {"value": "sber", "label": "Сбербанк"},
                       {"value": "tbank", "label": "Т-Банк"},
                       {"value": "alfa", "label": "Альфа-Банк"},
                       {"value": "vtb", "label": "ВТБ"},
                       {"value": "other", "label": "Другой банк"},
                   ]),
        SetupField(key="account", label="Расчётный счёт", field_type="text", group="Идентификация",
                   placeholder="40702810…"),
        SetupField(key="inn", label="ИНН организации", field_type="text", required=False, group="Идентификация"),
        SetupField(key="api_url", label="API URL банка", field_type="url", required=False, group="Доступ к API"),
        SetupField(key="client_id", label="clientId / логин", field_type="text", required=False, group="Доступ к API"),
        SetupField(key="api_key", label="Секрет / токен / ключ", field_type="password", secret=True,
                   required=False, group="Доступ к API"),
    ]
    available_doc_types = [
        SourceDocType(id="bank_transactions", name="Проводки по счёту (выписка)", category="control"),
    ]


@register_adapter("ofd")
class OfdAdapter(PlannedAdapter):
    label = "Чеки"
    version = "0.1"
    category = "Платежи и каналы продаж"
    description = (
        "Фискальные чеки от ОФД для сверки суммы продаж и разбивки по оплатам "
        "против выручки смены."
    )
    setup_guide = (
        "Что запросить и как подключить:\n"
        "\n"
        "1) Определить оператора ОФД (Платформа / Такском / Контур / Первый ОФД и др.), "
        "к которому подключены ККТ компании.\n"
        "2) В личном кабинете ОФД получить доступ к API: API-ключ/токен (раздел "
        "«Интеграция»/«API»), указать ИНН организации. Некоторые операторы требуют "
        "перечень ФН/РНМ касс или отдельный ключ на каждую ККТ.\n"
        "3) Состав данных: фискальные чеки (дата/время, ФН/ФД/ФП, признак расчёта "
        "приход/возврат, сумма, позиции и ставки НДС, форма оплаты нал/безнал) и отчёты "
        "о закрытии смены (Z-отчёты) — для сверки Σ продаж и разбивки оплат по смене.\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "Receipt"
    setup_schema = [
        SetupField(key="provider", label="Оператор ОФД", field_type="select", group="Оператор",
                   options=[
                       {"value": "platforma", "label": "Платформа ОФД"},
                       {"value": "taxcom", "label": "Такском"},
                       {"value": "kontur", "label": "Контур.ОФД"},
                       {"value": "first_ofd", "label": "Первый ОФД"},
                       {"value": "ofd_ru", "label": "ОФД.ру"},
                       {"value": "other", "label": "Другой ОФД"},
                   ],
                   help_text="ОФД, к которому подключены ККТ компании."),
        SetupField(key="kkt_list", label="ФН / РНМ ККТ", field_type="tags", required=False,
                   group="Оператор",
                   help_text="Список ФН или РНМ касс (если ОФД выдаёт данные поштучно)."),
        SetupField(key="inn", label="ИНН организации", field_type="text", group="Доступ к API ОФД"),
        SetupField(key="api_url", label="API URL", field_type="url", required=False,
                   group="Доступ к API ОФД", help_text="Базовый URL API оператора (если требуется)."),
        SetupField(key="token", label="API-ключ / токен", field_type="password", secret=True,
                   group="Доступ к API ОФД"),
    ]
    available_doc_types = [
        SourceDocType(id="fiscal_receipts", name="Фискальные чеки", category="control"),
        SourceDocType(id="kkt_shifts", name="Z-отчёты (закрытие смены ККТ)", category="control"),
    ]


@register_adapter("chestny_znak")
class ChestnyZnakAdapter(PlannedAdapter):
    label = "Честный Знак"
    version = "0.1"
    category = "Маркировка"
    description = (
        "Маркируемые товары (Честный Знак): статусы и движение кодов маркировки + "
        "вывод из оборота при продаже. Двойная роль — источник и приёмник."
    )
    setup_guide = (
        "Что запросить и как подключить:\n"
        "\n"
        "1) Регистрация участника в ГИС МТ «Честный Знак» (markirovka.crpt.ru); определить "
        "товарные группы (табак, пиво, вода, молочка и т.п.).\n"
        "2) Доступ к API: УКЭП организации для авторизации (получение токена); при работе "
        "через СУЗ — идентификатор OMS (OMS ID); ИНН участника.\n"
        "3) Состав данных: статусы кодов маркировки (в обороте / выбыл), движение кодов "
        "(ввод/вывод из оборота, отгрузка/приёмка), вывод из оборота в рознице — для сверки "
        "продаж маркируемых и приёмки.\n"
        "\n"
        "Поведение (выгрузка) пока не реализовано (status=planned) — настройте реквизиты, "
        "подключим при готовности доступа."
    )
    icon = "ScanBarcode"
    setup_schema = [
        SetupField(key="inn", label="ИНН участника", field_type="text", group="Участник"),
        SetupField(key="product_groups", label="Товарные группы", field_type="tags", required=False,
                   group="Участник", help_text="напр. tobacco, beer, water, milk…"),
        SetupField(key="api_url", label="API URL", field_type="url", required=False,
                   default_value="https://markirovka.crpt.ru", group="Доступ"),
        SetupField(key="oms_id", label="OMS ID (СУЗ)", field_type="text", required=False, group="Доступ"),
        SetupField(key="token", label="Токен (УКЭП / OMS)", field_type="password", secret=True, group="Доступ"),
    ]
    available_doc_types = [
        SourceDocType(id="marking_status", name="Статусы кодов маркировки", category="control"),
        SourceDocType(id="marking_movement", name="Движение маркируемых", category="control"),
    ]


# ---------------------------------------------------------------------------
# Касса/POS станции
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Ручная таблица (загруженный Excel/CSV как источник) — парсинг/нормализация
# server-side в канале (orchestrator), не через fetch_delta планировщика.
# ---------------------------------------------------------------------------
@register_adapter("manual_table")
class ManualTableAdapter(SourceAdapter):
    status = "available"
    label = "Таблица (ручная загрузка Excel)"
    category = "Ручные источники"
    description = (
        "Загруженная таблица (xlsx) как источник: реестры, выгрузки без API. "
        "Файл грузится в канал, парсинг и нормализация — server-side при запуске "
        "обработки канала. Для РусГидро: реестр «Договоры и оплаты ЭЗС»."
    )
    icon = "Table"
    setup_schema = [
        SetupField(key="sheet", label="Лист", field_type="text", required=False,
                   default_value="Общий свод", help_text="Имя листа Excel с данными."),
    ]
    available_doc_types = [
        SourceDocType(id="contracts_payments", name="Договоры и оплаты ЭЗС", category="reference"),
    ]

    async def test_connection(self, connection: dict[str, Any]) -> TestResult:
        return TestResult(ok=True, message="Ручной источник: загрузите таблицу в канал и запустите обработку.")

    async def fetch_delta(self, connection, doc_type, since=None, until=None, filters=None) -> RawBatch:
        # Парсинг идёт в оркестраторе (читает загруженный SourceFile); здесь — пусто.
        return RawBatch(source_id="", doc_type=doc_type, fetched_at=datetime.now(), items=[])


# ---------------------------------------------------------------------------
# Форма (ручной ввод) — третий механизм подключения наравне с API и Файлом.
# Данные вводятся в приложении по схеме сущности и пишутся в L2 (без файла/API).
# Ввод происходит через форму в карточке коннектора (не через fetch/расписание).
# ---------------------------------------------------------------------------
@register_adapter("manual_form")
class ManualFormAdapter(SourceAdapter):
    status = "available"
    label = "Форма (ручной ввод)"
    category = "Ручные источники"
    description = (
        "Ручной ввод данных по схеме прямо в приложении — без файла и без API. "
        "Пользователь заполняет форму в карточке коннектора → строки пишутся в "
        "нормализованную базу (L2). Схема полей задаётся под сущность (напр. ТТН)."
    )
    icon = "PenLine"
    setup_schema = []  # у самого подключения нет настройки связи; схема — у данных формы
    available_doc_types = [
        SourceDocType(id="manual_entry", name="Ручной ввод (форма)", category="anchor"),
    ]

    async def test_connection(self, connection: dict[str, Any]) -> TestResult:
        return TestResult(ok=True, message="Форма: заполните данные в карточке коннектора.")

    async def fetch_delta(self, connection, doc_type, since=None, until=None, filters=None) -> RawBatch:
        # Данные поступают из формы (submit), а не из fetch — здесь пусто.
        return RawBatch(source_id="", doc_type=doc_type, fetched_at=datetime.now(), items=[])


# ---------------------------------------------------------------------------
# ЭЗС: зарядные сессии (загруженный Excel) — парсинг/нормализация server-side
# ---------------------------------------------------------------------------
@register_adapter("charge_sessions_excel")
class ChargeSessionsExcelAdapter(SourceAdapter):
    status = "available"
    label = "ЭЗС: Зарядные сессии (Excel)"
    category = "Электромобильность (ЭЗС)"
    description = (
        "Выгрузка зарядных сессий ЭЗС (ChargeTransactions, xlsx) как источник: "
        "станция, коннектор, энергия (кВтч), сумма, тариф, тип пользователя. "
        "Файл грузится в канал, парсинг и нормализация (коннектор/ФЛ-ЮЛ) — "
        "server-side при запуске обработки канала. Для РусГидро."
    )
    icon = "Zap"
    setup_schema = [
        SetupField(key="sheet", label="Лист", field_type="text", required=False,
                   default_value="ChargeTransactions", help_text="Имя листа Excel с сессиями."),
    ]
    available_doc_types = [
        SourceDocType(id="charge_sessions", name="Зарядные сессии реализации", category="anchor"),
    ]

    async def test_connection(self, connection: dict[str, Any]) -> TestResult:
        return TestResult(ok=True, message="Источник сессий: загрузите таблицу в канал и запустите обработку.")

    async def fetch_delta(self, connection, doc_type, since=None, until=None, filters=None) -> RawBatch:
        return RawBatch(source_id="", doc_type=doc_type, fetched_at=datetime.now(), items=[])


@register_adapter("stations_excel")
class StationsExcelAdapter(SourceAdapter):
    status = "available"
    label = "ЭЗС: Справочник станций (Excel)"
    category = "Электромобильность (ЭЗС)"
    description = (
        "Справочник станций ЭЗС (паспорт: серийный, адрес, координаты, коннекторы, "
        "мощность, OCPP, бренд, владелец, HubEx-связка) как источник. Файл грузится "
        "в канал, парсинг и нормализация в объекты (Точки обслуживания) — server-side "
        "при запуске обработки канала. Для РусГидро."
    )
    icon = "MapPin"
    setup_schema = [
        SetupField(key="sheet", label="Лист", field_type="text", required=False,
                   default_value="Станции", help_text="Имя листа Excel со станциями."),
    ]
    available_doc_types = [
        SourceDocType(id="stations", name="Справочник станций ЭЗС", category="anchor"),
    ]

    async def test_connection(self, connection: dict[str, Any]) -> TestResult:
        return TestResult(ok=True, message="Источник станций: загрузите справочник в канал и запустите обработку.")

    async def fetch_delta(self, connection, doc_type, since=None, until=None, filters=None) -> RawBatch:
        return RawBatch(source_id="", doc_type=doc_type, fetched_at=datetime.now(), items=[])


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
