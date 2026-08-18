"""Бизнес-роли «Магазина» и политика владения коммерческими данными.

Это отдельный слой от platform RBAC (`UserCompany.role`, `CompanyRole.modules`):
платформенная роль отвечает за доступ к экранам, бизнес-grant — за действие в
конкретной сети или на конкретной станции. Один человек может иметь несколько
grant одновременно.
"""
from __future__ import annotations

from datetime import datetime, timezone


ROLE_STATION_ADMINISTRATOR = "station_administrator"
ROLE_NETWORK_MERCHANDISER = "network_merchandiser"

SCOPE_STATION = "station"
SCOPE_NETWORK = "network"

STORE_POLICY_KEY = "storePolicy"
STORE_POLICY_VERSION = 1

# Кто вправе менять коммерческие данные — рецептуры, цены, ассортимент.
#
# «station» — только администратор АЗС; центр показывает аналитику. Так было
# в v1, и это остаётся умолчанием: станция ближе к товару, и молча включать
# запись центра нельзя.
#
# «shared» — правят обе стороны. Это не «центр вместо станции»: локальная
# работа на АЗС продолжается как была, у центра появляется своя. Спор
# разрешается временем — чья версия пришла последней, та и действует, ровно
# как две правки одного человека с разных экранов.
OWNER_STATION = "station"
OWNER_SHARED = "shared"
STORE_POLICY_OWNERS = (OWNER_STATION, OWNER_SHARED)

DEFAULT_STORE_POLICY = {
    "schema_version": STORE_POLICY_VERSION,
    "commercial_owner": "station",
    "central_mode": "projection",
    "fuel_mode": "analytics_only",
    "revision": "default-v1",
}


def normalize_business_grants(
    raw: list[dict] | None,
    *,
    network_id: str,
    station_ids: set[str] | None = None,
) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw or []:
        role = str((item or {}).get("role") or "").strip()
        scope_type = str((item or {}).get("scope_type") or "").strip()
        scope_id = str((item or {}).get("scope_id") or "").strip()
        if role == ROLE_STATION_ADMINISTRATOR:
            if scope_type != SCOPE_STATION or not scope_id:
                raise ValueError("Администратору АЗС нужна область конкретной станции")
            if station_ids is not None and scope_id not in station_ids:
                raise ValueError(f"Станция {scope_id} не принадлежит организации")
        elif role == ROLE_NETWORK_MERCHANDISER:
            if scope_type != SCOPE_NETWORK:
                raise ValueError("Товаровед сети назначается на всю сеть")
            scope_id = network_id
        else:
            raise ValueError(f"Неизвестная бизнес-роль: {role or 'пусто'}")
        key = (role, scope_type, scope_id)
        if key not in seen:
            seen.add(key)
            out.append({"role": role, "scope_type": scope_type, "scope_id": scope_id})
    return sorted(out, key=lambda g: (g["role"], g["scope_type"], g["scope_id"]))


def has_station_administrator(grants: list[dict] | None, station_id: int | str) -> bool:
    target = str(station_id)
    return any(
        str((grant or {}).get("role") or "") == ROLE_STATION_ADMINISTRATOR
        and str((grant or {}).get("scope_type") or "") == SCOPE_STATION
        and str((grant or {}).get("scope_id") or "") == target
        for grant in grants or []
    )


def has_network_merchandiser(grants: list[dict] | None, network_id: str) -> bool:
    return any(
        str((grant or {}).get("role") or "") == ROLE_NETWORK_MERCHANDISER
        and str((grant or {}).get("scope_type") or "") == SCOPE_NETWORK
        and str((grant or {}).get("scope_id") or "") == network_id
        for grant in grants or []
    )


def store_policy(customization: dict | None) -> dict:
    raw = dict((customization or {}).get(STORE_POLICY_KEY) or {})
    policy = {**DEFAULT_STORE_POLICY, **raw}
    # Fail-closed: неизвестный или старый режим читается как «станция».
    # Опечатка в настройке не должна открывать запись центра — но и не должна
    # отключать локальную работу АЗС.
    if policy.get("commercial_owner") not in STORE_POLICY_OWNERS:
        policy["commercial_owner"] = OWNER_STATION
    policy["schema_version"] = STORE_POLICY_VERSION
    policy["central_mode"] = "projection"
    policy["fuel_mode"] = "analytics_only"
    return policy


def new_store_policy(commercial_owner: str = OWNER_STATION) -> dict:
    if commercial_owner not in STORE_POLICY_OWNERS:
        commercial_owner = OWNER_STATION
    return {
        **DEFAULT_STORE_POLICY,
        "commercial_owner": commercial_owner,
        "revision": datetime.now(timezone.utc).isoformat(),
    }
