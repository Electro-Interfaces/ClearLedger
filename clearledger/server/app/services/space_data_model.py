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
    AccountingDoc, Channel, ChargeSession, Contract, ContractLocation, CorporateClient,
    Counterparty, EzsEquipmentUnit, EzsSite, EzsSiteCost, EzsSiteDoc, EzsSiteEquipment,
    EzsSiteEvent, EzsTechConnection, HubexAsset, HubexTask, LocationTypeDef, RawBatchRecord,
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
         "Канал «Зарядные сессии ЭЗС» (выгрузка ПК)", "Продажи · Маркетинг · Финансы",
         "код станции → объект",
         ChargeSession.location_id.is_(None), "без объекта"),
        ("corporate_clients", "Корпоративные клиенты", CorporateClient,
         "Канал зарядных сессий (реестр ЮЛ)", "Корпоративный процессинг",
         "телефон → сессии · карточка контрагента → договор",
         CorporateClient.counterparty_id.is_(None),
         "без карточки контрагента"),
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
