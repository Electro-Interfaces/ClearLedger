"""Единый ORM-скоуп сети для агрегатов ЭЗС (сужение по станциям/регионам).

Один источник истины для ORM-сервисов (корпоратив, розница, тарифы, карта,
динамика), чтобы region-join не расползался копиями по коду. Аналог raw-SQL
`_scope*` в overview_insights/charge_visits, но для `select().where()`.

Правила (CLAUDE.md, аудит 18–19.07):
- станция — по `charge_sessions.station_code` (ANY из выбранных кодов);
- регион — ТОЛЬКО нормализованно: `charge_sessions.location_id →
  service_locations.region_id → regions.name` (НЕ денорм-колонка
  `charge_sessions.region` — она из сырой CPO-выгрузки и двоит регионы);
- скоуп компании (`service_locations.company_id`) — обязателен в подзапросе.
"""
from __future__ import annotations

from sqlalchemy import String, cast, select

from app.models import ChargeSession, Region, ServiceLocation


def session_scope_conds(
    company_id,
    stations: list[str] | None = None,
    regions: list[str] | None = None,
) -> list:
    """ORM-условия сужения `ChargeSession` по станциям/регионам.

    Возвращает список условий для `.where(*conds)`. Пустой список = без сужения
    (весь контур компании). Используется как добавка к WHERE, где основной
    скоуп компании уже задан вызывающим.
    """
    S = ChargeSession
    conds: list = []
    if stations:
        conds.append(S.station_code.in_(list(stations)))
    if regions:
        sub = (
            select(cast(ServiceLocation.id, String))
            .join(Region, Region.id == ServiceLocation.region_id)
            .where(ServiceLocation.company_id == company_id,
                   Region.name.in_(list(regions)))
        )
        conds.append(S.location_id.in_(sub))
    return conds
