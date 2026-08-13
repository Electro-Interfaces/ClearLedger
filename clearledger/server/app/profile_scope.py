"""Что из справочников поставки уместно компании с данным профилем.

Три каталога — типы источников (`/source-types`), шаблоны каналов
(`/channel-templates`) и разрезы сверки (`/reconcile-rules`) — описывают ВСЮ
поставку экосистемы: и сеть АЗС, и зарядные станции, и компанию без объектов.
Отдавались они целиком и всем, поэтому в пространстве «Аудит» (ПРОМИЗОЛ СПБ,
профиль `office`) мастер создания коннектора предлагал «Топливо: сменный отчёт»
и «Зарядные сессии ЭЗС», а в «Каталоге типов» стояли ОФД, инкассация и «Честный
знак» с рабочей кнопкой «Подключить».

Фильтр здесь, а не в двух витринах: каталог читают мастер, каталог типов и всё,
что появится следующим. Отбор на фронте закрыл бы только тот экран, где заметили.

Профиль компании — `Company.profile_id`: `fuel` (сеть АЗС), `retail` (розница),
`energy` (сеть ЭЗС), `office` (компания без объектов: аудит, бухгалтерия, услуги),
`trade`, `general`.
"""
from __future__ import annotations

# Источники, уместные любой компании: учётная система, документооборот, банк, файлы.
_COMMON_SOURCES = {
    "onec_operational", "onec_accounting", "edo", "bank_statement",
    "manual_table", "manual_form",
}
# Топливная розница: касса АЗС, агрегаторы, эквайринг, инкассация, ОФД, маркировка.
_RETAIL_SOURCES = {
    "sts", "sts_transactions", "neftoms", "tradecorp", "msto",
    "acquiring_sber", "inkassation", "ofd", "chestny_znak",
}
# Сеть зарядных станций: выгрузки сессий и станций.
_ENERGY_SOURCES = {"charge_sessions_excel", "stations_excel"}

_SOURCES_BY_PROFILE: dict[str, set[str]] = {
    "fuel": _COMMON_SOURCES | _RETAIL_SOURCES,
    "retail": _COMMON_SOURCES | _RETAIL_SOURCES,
    "energy": _COMMON_SOURCES | _ENERGY_SOURCES,
    "office": _COMMON_SOURCES,
    "trade": _COMMON_SOURCES,
    "general": _COMMON_SOURCES,
}

# Направление шаблона канала (`channel_catalog.ChannelTemplate.direction`) и модуль
# разреза сверки (`reconcile_catalog.ReconRule.module`) — одна и та же ось: чем
# компания вообще занимается. `reference` (репликация 1С) уместна всем.
_DIRECTIONS_BY_PROFILE: dict[str, set[str]] = {
    "fuel": {"fuel", "sidegoods", "food", "reference"},
    "retail": {"fuel", "sidegoods", "food", "reference"},
    "energy": {"energy", "reference"},
    "office": {"reference"},
    "trade": {"reference"},
    "general": {"reference"},
}


def _norm(profile_id: str | None) -> str:
    return profile_id or "general"


def source_types_for(profile_id: str | None) -> set[str]:
    """Типы источников, которые показываем компании этого профиля."""
    return _SOURCES_BY_PROFILE.get(_norm(profile_id), _COMMON_SOURCES)


def directions_for(profile_id: str | None) -> set[str]:
    """Направления шаблонов каналов и модулей сверки для этого профиля."""
    return _DIRECTIONS_BY_PROFILE.get(_norm(profile_id), {"reference"})


def allows_direction(profile_id: str | None, direction: str | None) -> bool:
    """Уместно ли направление профилю.

    Разрез сверки может относиться сразу к нескольким модулям («fuel,sidegoods,food»),
    поэтому строку разбираем, а не сравниваем целиком: иначе такой разрез не подошёл
    бы никому.
    """
    allowed = directions_for(profile_id)
    parts = {p.strip() for p in (direction or "").split(",") if p.strip()}
    return bool(parts & allowed) if parts else True
