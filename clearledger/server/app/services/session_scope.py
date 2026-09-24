"""Единый ORM-скоуп сети для агрегатов ЭЗС (сужение по станциям/регионам).

Один источник истины для ORM-сервисов (корпоратив, розница, тарифы, карта,
динамика), чтобы region-join не расползался копиями по коду. Аналог raw-SQL
`_scope*` в overview_insights/charge_visits, но для `select().where()`.

Правила (CLAUDE.md, аудит 18–19.07):
- станция — по любому её номеру: основному, бухгалтерскому, прежнему
  (`station_match`), а не по тексту `charge_sessions.station_code`;
- регион — ТОЛЬКО нормализованно: `charge_sessions.location_id →
  service_locations.region_id → regions.name` (НЕ денорм-колонка
  `charge_sessions.region` — она из сырой CPO-выгрузки и двоит регионы);
- скоуп компании (`service_locations.company_id`) — обязателен в подзапросе.
"""
from __future__ import annotations

from sqlalchemy import String, bindparam, cast, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY

from app.models import ChargeSession, Region, ServiceLocation


def station_locations_sql(codes: str = ":stations", cid: str = ":company_id") -> str:
    """`(ARRAY(...))` объектов, которые носят какой-либо из номеров `codes`.

    У станции номеров несколько, и все они живые: основной (витрина перевела
    часть парка на номер по приказу, «381-0019»), бухгалтерский (`buNumber`,
    трёхзначный, «359») и прежние (`numberHistory`). В сессии лежит тот номер,
    под которым станция работала в тот день, поэтому сравнение по тексту кода
    находило только часть её истории: по «381-0019» у Тайшета 36 сессий из 630.

    Прежний и бухгалтерский номер ищутся, только если сейчас этот номер никому
    не принадлежит как основной: иначе выбор станции «580» подмешал бы в отчёт
    зарядки другой карточки, у которой 580 когда-то был.

    Подзапросы некоррелированные: коррелированный вариант стоил 1,5 с на запрос,
    этот — десятки миллисекунд (замер на rushydro 25.09.2026)."""
    arr = f"CAST({codes} AS varchar[])"
    co = f"CAST({cid} AS uuid)"
    free = (f"ARRAY(SELECT x FROM unnest({arr}) x WHERE NOT EXISTS (SELECT 1 FROM service_locations o"
            f" WHERE o.company_id = {co} AND o.station_number = x))")
    return (
        f"(ARRAY(SELECT sl.id FROM service_locations sl WHERE sl.company_id = {co} AND ("
        f"sl.station_number = ANY({arr})"
        f" OR sl.extra_metadata->>'buNumber' = ANY({free})"
        f" OR sl.extra_metadata->'numberHistory' @> ANY(ARRAY(SELECT jsonb_build_array("
        f"jsonb_build_object('было', y)) FROM unnest({free}) y)))"
        # Номер, которого нет ни в одной карточке, но он есть на сессиях, — это
        # старый номер той станции, к которой эти сессии привязаны.
        f" UNION SELECT s9.location_id FROM charge_sessions s9 WHERE s9.company_id = {co}"
        f" AND s9.location_id IS NOT NULL AND s9.station_code = ANY({free})))"
    )


def station_match(code_col, loc_col, company_id, codes) -> object:
    """ORM-условие «строка относится к станции с одним из номеров `codes`»."""
    arr = text(station_locations_sql(":st_codes", ":st_cid")).bindparams(
        bindparam("st_codes", list(codes), type_=ARRAY(String), unique=True),
        bindparam("st_cid", str(company_id), unique=True))
    return or_(code_col.in_(list(codes)), loc_col.op("= ANY")(arr))


def session_scope_conds(
    company_id,
    stations: list[str] | None = None,
    regions: list[str] | None = None,
) -> list:
    """ORM-условия сужения `ChargeSession` по станциям/регионам.

    Возвращает список условий для `.where(*conds)`. Пустой список = без сужения
    (весь контур компании). Используется как добавка к WHERE, где основной
    скоуп компании уже задан вызывающим.

    Сюда же подмешивается СКОУП ДАННЫХ участника (`app/scope.py`): у человека,
    которому выданы 5 станций, любой агрегат считается только по ним, какой бы
    фильтр он ни выбрал в интерфейсе. Это не пользовательский фильтр, а граница
    видимости, поэтому условия складываются (И), а не заменяют друг друга.
    """
    from app.scope import current_object_scope

    S = ChargeSession
    conds: list = []
    allowed = current_object_scope()
    if allowed:
        # `charge_sessions.location_id` — та же строка, что `service_locations.id`.
        # Станция-сирота (location_id NULL) со скоупом не видна: она не привязана ни
        # к одному объекту, а человек со скоупом видит только свои.
        conds.append(S.location_id.in_(allowed))
    if stations:
        conds.append(station_match(S.station_code, S.location_id, company_id, stations))
    if regions:
        sub = (
            select(cast(ServiceLocation.id, String))
            .join(Region, Region.id == ServiceLocation.region_id)
            .where(ServiceLocation.company_id == company_id,
                   Region.name.in_(list(regions)))
        )
        conds.append(S.location_id.in_(sub))
    return conds
