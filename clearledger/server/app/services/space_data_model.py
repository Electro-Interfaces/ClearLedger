"""Карта нормализованной базы пространства (docs/SPACE.md §8).

Витрина «Данные» до этого показывала нормализацию ПО КАНАЛАМ приёма — а каналов с
файлами всего три. Но нормализованный слой пространства шире каналов: контрагенты и
договоры заводятся из реестров И из корпоративной зарядки, объекты — из справочника И
руками в «Управлении», проектный контур (площадки, техприсоединение, документы,
затраты) вообще не приходит файлом. Пока витрина перечисляла каналы, эти сущности
были не видны — казалось, что нормализованная база это три набора данных.

Здесь карта самой БАЗЫ: какие сущности в ней живут, чем наполняются, кто потребляет и
где связи ещё не материализованы (роль записана строкой вместо ссылки на карточку).
Разрыв — не ошибка загрузки, а долг схемы: пока подрядчик проекта хранится текстом, его
нельзя сопоставить с тем же юрлицом в договорах.

ponytail: счётчики — отдельным COUNT на сущность (~30 запросов на открытие витрины).
Одним UNION ALL было бы быстрее, но это админский экран с ручным обновлением; сводить
в один запрос — когда станет заметно.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc, Channel, ChargePayment, ChargeSession, Contract, ContractLocation,
    CorporateClient, Counterparty, EzsCustomer, EzsEquipmentUnit, EzsReference,
    EzsRfidCard, EzsSite, EzsSiteCost, EzsSiteDoc, EzsSiteEquipment, EzsTariff,
    EzsSiteEvent, EzsTechConnection, ExportPacket, FuelExportDoc, FuelReceipt, FuelShift,
    HubexAsset, HubexTask, LocationTypeDef, OnlineOrder, RawBatchRecord,
    Region, ServiceLocation, SourceFile, StationContractSettlement, StationDispensePeriod,
    StationEnergyPeriod, UserCompany,
)
from app.services.space_links import any_unlinked, unlinked


# Сущность нормализованной базы: (ключ, метка, модель, чем наполняется, кто потребляет,
# ключ связи, [условие разрыва, подпись разрыва]).
_ENTITIES: list[tuple[str, str, list[tuple]]] = [
    ("core", "Опора пространства", [
        ("objects", "Объекты", ServiceLocation,
         "Справочник станций · «Управление» · проекты при вводе", "все продукты",
         "ось: код объекта",
         ServiceLocation.region_id.is_(None), "без региона"),
        ("counterparties", "Контрагенты", Counterparty,
         "Реестры аренды и э/э · корпоративная зарядка · Финансы", "договоры · корпоратив · закупка",
         "ИНН + нормализованное имя",
         or_(Counterparty.inn.is_(None), Counterparty.inn == ""), "без ИНН — сведение по имени"),
        ("contracts", "Договоры", Contract,
         "Реестры аренды и э/э · корпоративная зарядка · руками", "эксплуатация · корпоратив · финансы",
         "контрагент → договор → объекты",
         Contract.scope_type == "unassigned", "охват не задан"),
        ("contract_locations", "Охват договоров", ContractLocation,
         "Реестры (сопряжение по № БУ / ZOI-1)", "аренда · энергозакупка",
         "договор ↔ объект", None, None),
        ("equipment", "Оборудование", EzsEquipmentUnit,
         "Поставки ЭЗС · «Управление»", "эксплуатация · Координатор",
         "серийный № → объект",
         EzsEquipmentUnit.current_location_id.is_(None), "не установлено на объект"),
        ("members", "Люди пространства", UserCompany,
         "«Управление» · приглашения · единый вход", "все продукты · чат · поддержка",
         "учётная запись ↔ компания", None, None),
        ("regions", "Регионы", Region,
         "Справочник ядра", "объекты · проекты · аналитика", "канон региона", None, None),
        ("location_types", "Типы объектов", LocationTypeDef,
         "Справочник ядра", "карточка объекта", "тип объекта", None, None),
    ]),
    ("projects", "Проекты — от площадки до ввода", [
        ("sites", "Площадки-проекты", EzsSite,
         "Импорт реестра площадок · ведение вручную", "Проекты · инвестпрограмма",
         "кадастровый № / координаты → объект при вводе",
         any_unlinked((EzsSite.owner, EzsSite.owner_counterparty_id),
                      (EzsSite.supplier, EzsSite.supplier_counterparty_id),
                      (EzsSite.contractor, EzsSite.contractor_counterparty_id)),
         "собственник/поставщик/подрядчик без карточки контрагента"),
        ("site_events", "События площадок", EzsSiteEvent,
         "Смена стадии · касания · заметки", "Проекты (история и зависания)",
         "площадка → событие", None, None),
        ("site_docs", "Документы проектов", EzsSiteDoc,
         "Загрузка файлов проекта (ЕГРН, ТУ, акты)", "Проекты (гейты)",
         "площадка → файл", None, None),
        ("tech_connections", "Техприсоединения", EzsTechConnection,
         "Ведение по проекту", "Проекты · сроки ввода",
         "площадка → заявка ТП",
         unlinked(EzsTechConnection.grid_operator,
                  EzsTechConnection.grid_operator_counterparty_id),
         "сетевая организация без карточки контрагента"),
        ("site_equipment", "Оборудование проектов", EzsSiteEquipment,
         "Ведение по проекту · поставки", "Проекты · эксплуатация после ввода",
         "площадка → единица оборудования",
         unlinked(EzsSiteEquipment.supplier, EzsSiteEquipment.supplier_counterparty_id),
         "поставщик без карточки контрагента"),
        ("site_costs", "Затраты проектов", EzsSiteCost,
         "Ведение по проекту", "Проекты · бюджет",
         "площадка → статья затрат", None, None),
    ]),
    ("commerce", "Коммерция", [
        ("charge_sessions", "Зарядные сессии", ChargeSession,
         "Канал «Зарядные сессии ЭЗС» (выгрузка ПК · витрина АСУиМ)",
         "Продажи · Маркетинг · Финансы",
         "код станции → объект",
         ChargeSession.location_id.is_(None), "без объекта"),
        ("corporate_clients", "Корпоративные клиенты", CorporateClient,
         "Канал зарядных сессий (реестр ЮЛ) · organizations_ru витрины",
         "Корпоративный процессинг",
         "телефон · id организации витрины → сессии · карточка контрагента → договор",
         CorporateClient.counterparty_id.is_(None),
         "без карточки контрагента"),
        # ── Витрина АСУиМ ЭЗС (docs/CHANNEL_ASUIM_EZS.md), с 08.08.2026. Принесла в
        #    базу то, чего в выгрузках админпанели не было вовсе: деньги с фискальным
        #    чеком, справочник клиентов, карты и прайс. Без этих строк карта базы
        #    показывала 168 тыс. записей как несуществующие.
        ("charge_payments", "Платежи и чеки", ChargePayment,
         "Витрина АСУиМ (payments_ru)", "Продажи → «Платежи и чеки» · карточка объекта",
         "id платежа; id сессии → сессия (без FK: платежи обгоняют сессии)",
         ChargePayment.session_ext_id.is_(None), "без ссылки на сессию"),
        ("ezs_customers", "Клиенты ЭЗС", EzsCustomer,
         "Витрина АСУиМ (users_ru) — без персональных данных, только телефон",
         "Продажи → «Частные лица» (база и активация)",
         "телефон +7XXXXXXXXXX → сессии · id организации → ЮЛ",
         or_(EzsCustomer.phone.is_(None), EzsCustomer.phone == ""),
         "без телефона — с сессиями не связывается"),
        ("ezs_rfid_cards", "RFID-карты", EzsRfidCard,
         "Витрина АСУиМ (rfid_cards_ru)", "Продажи · разбор сессий по картам",
         "UID в верхнем регистре → сессия · владелец → клиент",
         EzsRfidCard.customer_ext_id.is_(None), "без владельца"),
        ("ezs_tariffs", "Прайс ЭЗС", EzsTariff,
         "Витрина АСУиМ (tariffs_ru)", "Продажи → «Тарифы» (факт против номинала)",
         "тариф + тип разъёма; привязка к станциям в выгрузке пуста",
         or_(EzsTariff.stations.is_(None), EzsTariff.stations == ""),
         "не привязан к станциям"),
        ("ezs_references", "Справочники витрины", EzsReference,
         "Витрина АСУиМ (brands_ru · chargepoint_groups_ru · cars_ru)",
         "паспорт станции · разбор парка",
         "бренд/группа/модель → станция (id бренда и группы в выгрузке пусты)",
         None, None),
    ]),
    ("fuel", "Топливная розница (L2)", [
        ("fuel_shifts", "Смены АЗС", FuelShift,
         "Канал продаж STS (shift_report)", "Учёт · Расхождения · Топливо",
         "станция + № смены; канал → смена",
         FuelShift.sales_missing.is_(True), "без детализации продаж"),
        ("fuel_receipts", "Приём топлива (ТТН)", FuelReceipt,
         "Канал приёма STS (receipts)", "Учёт · себестоимость",
         "станция + ТТН + код топлива", None, None),
        ("online_orders", "Онлайн-заказы", OnlineOrder,
         "Канал MSTO (агрегаторы)", "Сверка онлайн-канала смены",
         "sessionId MSTO; точка → объект",
         OnlineOrder.station_id.is_(None), "без объекта"),
    ]),
    ("export", "Выгрузка в учёт (L3/L4)", [
        ("export_docs", "Документы 1С", FuelExportDoc,
         "Сборка по сменам и ТТН (L2 → документы)", "выгрузка в БП",
         "смена/ТТН → документ", None, None),
        ("export_packets", "Пакеты выгрузки", ExportPacket,
         "Отбор документов в пакет смены", "1С БП (расширение TL)",
         "пакет → документы; идемпотентность по хешу", None, None),
    ]),
    ("energy", "Хозяйство и деньги", [
        ("settlements", "Платёжная дисциплина", StationContractSettlement,
         "Реестры аренды и энергоснабжения", "Эксплуатация · дебиторка",
         "объект + договор + период",
         StationContractSettlement.contract_id.is_(None), "без договора"),
        ("energy_periods", "Энергопотребление", StationEnergyPeriod,
         "Реестр энергоснабжения", "Энергозакупка · баланс",
         "объект + период", None, None),
        ("dispense_periods", "Отпуск по сводной", StationDispensePeriod,
         "Сводная выработка контрагента", "Сверка с сессиями",
         "объект + период", None, None),
        ("accounting_docs", "Первичка", AccountingDoc,
         "Загрузка документов · 1С", "Финансы",
         "контрагент + договор", None, None),
    ]),
    ("service", "Сервис", [
        ("hubex_tasks", "Заявки обслуживания", HubexTask,
         "HubEx FSM (боевая интеграция)", "Координатор · эксплуатация",
         "актив → объект",
         HubexTask.location_id.is_(None), "без объекта"),
        ("hubex_assets", "Активы обслуживания", HubexAsset,
         "HubEx FSM", "Координатор", "актив ↔ оборудование", None, None),
    ]),
    ("intake", "Приём (L1 — сырьё)", [
        ("channels", "Каналы", Channel,
         "«Данные» → подключения", "нормализация", "шаблон канала", None, None),
        ("source_files", "Загруженные файлы", SourceFile,
         "Загрузка в каналы", "нормализация", "канал → файл", None, None),
        ("raw_batches", "Сырые записи", RawBatchRecord,
         "Разбор файлов", "нормализация (L1 → L2)", "файл → строка", None, None),
    ]),
]


async def data_model(db: AsyncSession, company_id: uuid.UUID) -> dict[str, Any]:
    """Состав нормализованной базы компании: сущности, объёмы и незакрытые связи."""
    domains: list[dict[str, Any]] = []
    total_records = total_gaps = total_entities = 0

    for dkey, dlabel, items in _ENTITIES:
        entities: list[dict[str, Any]] = []
        for key, label, model, sources, consumers, link, gap_cond, gap_label in items:
            records = (await db.execute(select(func.count()).select_from(model)
                                        .where(model.company_id == company_id))).scalar() or 0
            gap = None
            if gap_cond is not None and records:
                gap = (await db.execute(select(func.count()).select_from(model)
                                        .where(model.company_id == company_id, gap_cond))).scalar() or 0
            entities.append({
                "key": key, "label": label, "table": model.__tablename__,
                "records": records, "sources": sources, "consumers": consumers, "link": link,
                "gap": gap or None, "gapLabel": gap_label if gap else None,
            })
            total_records += records
            total_gaps += gap or 0
            total_entities += 1
        domains.append({"key": dkey, "label": dlabel, "entities": entities})

    return {
        "domains": domains,
        "totals": {
            "entities": total_entities,
            "records": total_records,
            "gaps": total_gaps,
            "filled": sum(1 for d in domains for e in d["entities"] if e["records"] > 0),
        },
    }
