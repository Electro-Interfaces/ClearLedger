"""ServiceLocation (service point) mutation invariants; caller owns admission/commit.

No HTTP, projection, audit, station/site/EVSE mutation or implicit commit here.
Legacy temporal renumber/retire producers are not invented by these commands.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text

from app.models import AuditEvent, Contract, ContractLocation, ObjectLink, ServiceLocation
from app.scope import current_object_scope, current_organization
from app.services.object_freeze import freeze_reasons


class LocationConflict(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


@dataclass(frozen=True)
class Mutation:
    location: ServiceLocation
    changes: dict[str, Any]


# Preserve import-owned snapshots and manually configured bindings on form edits.
_SERVICE_META_KEYS = {
    "ext_id", "stationId", "ocppId", "ocppUrl", "source", "nameSource",
    "nameHistory", "numberHistory", "zoi1", "buNumber", "connectorsSource",
}
_EDITABLE_LINK_KEYS = {"hubexAssetId", "hubexName", "hubexNote", "linkStatus",
                       "zoi1", "buNumber", "ocppUrl"}


def _is_service_meta(key: str, value: Any) -> bool:
    return key.startswith("asuim") or key in _SERVICE_META_KEYS or isinstance(value, (dict, list))


def merge_metadata(current: dict | None, incoming: dict | None) -> dict | None:
    cur, inc = current or {}, incoming or {}
    kept = {k: v for k, v in cur.items()
            if _is_service_meta(k, v) or (k in _EDITABLE_LINK_KEYS and k not in inc)}
    # An omitted number in a partial metadata edit is not a renumber operation.
    if incoming is not None and "number" not in inc and "number" in cur:
        kept["number"] = cur["number"]
    merged = {**kept, **{k: v for k, v in inc.items() if not _is_service_meta(k, v)}}
    return merged or None


def _number(value) -> str:
    return "" if value is None else str(value).strip()


async def _barrier(db, company_id, identifier):
    # Stable, transaction-scoped across processes and both HTTP entry points.
    # ID before company also serializes concurrent cross-tenant ID claims.
    for namespace, value in (("id", identifier), ("company", company_id)):
        key = int.from_bytes(hashlib.blake2b(
            f"location-command:v1:{namespace}:{value}".encode(), digest_size=8).digest(), "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def _locked(db, company_id, identifier):
    await _barrier(db, company_id, identifier)
    # FOR UPDATE conflicts with FK key-share checks in contract/session writers.
    # Reload even when admission already loaded this row into the identity map.
    return (await db.execute(select(ServiceLocation).where(ServiceLocation.id == identifier)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def _assert_visible(db, company_id, loc):
    if loc.company_id != company_id:
        raise LocationConflict(404, "Объект не найден в этой компании")
    allowed = current_object_scope()
    if allowed is not None and loc.id not in allowed:
        raise LocationConflict(404, "Объект не найден")
    org = current_organization()
    if org is not None:
        compatible = await db.scalar(select(ContractLocation.id).join(Contract, Contract.id == ContractLocation.contract_id)
            .where(ContractLocation.company_id == company_id, Contract.company_id == company_id,
                   ContractLocation.location_id == loc.id, Contract.organization_id == org).limit(1))
        if compatible is None:
            raise LocationConflict(404, "Объект не найден")


async def code_taken(db, company_id, code, *, except_id=None):
    rows = await db.execute(select(ServiceLocation.id).where(
        ServiceLocation.company_id == company_id, ServiceLocation.code == _number(code),
        ServiceLocation.id != except_id if except_id is not None else True).limit(1))
    return rows.first() is not None


async def _assert_numbers_free(db, company_id, values, *, except_id=None):
    values = {v for v in values if v}
    if not values:
        return
    rows = (await db.execute(select(ServiceLocation).where(ServiceLocation.company_id == company_id))).scalars().all()
    for other in rows:
        md = other.extra_metadata or {}
        # A retired alias remains reserved even for its original point. Current
        # values of that same point are exempt; this is not a new assignment.
        numbers = {_number(h.get("было")) for h in (md.get("numberHistory") or []) if isinstance(h, dict)}
        if other.id != except_id:
            numbers.update({_number(other.code), _number(other.station_number), _number(md.get("number"))})
        if values & numbers:
            raise LocationConflict(409, "Номер уже занят текущим или историческим объектом компании")
    # Existing dated number links include retired assignments. Do not overwrite
    # or fabricate intervals: assigning one of their values requires renumber API.
    historical = await db.scalar(select(ObjectLink.id).where(
        ObjectLink.company_id == company_id, ObjectLink.relation == "number",
        ObjectLink.child_id.in_(values),
        (ObjectLink.parent_id != except_id) | ObjectLink.valid_to.is_not(None)
        if except_id is not None else True).limit(1))
    if historical is not None:
        raise LocationConflict(409, "Номер уже зарегистрирован в истории компании")


def _prepare(loc, data):
    allowed = {"code", "name", "type", "status", "address", "description", "city", "street", "house",
               "latitude", "longitude", "metadata", "sourceBindings"}
    if set(data) - allowed:
        raise LocationConflict(422, "Недопустимое поле команды объекта")
    changes = dict(data)
    for key, limit in (("code", 100), ("name", 255), ("type", 30), ("status", 20)):
        if key in changes:
            value = changes[key]
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise LocationConflict(422, f"Недопустимое значение {key}")
            changes[key] = value.strip()
    if "sourceBindings" in changes:
        if not isinstance(changes["sourceBindings"], list):
            raise LocationConflict(422, "sourceBindings должен быть списком")
        changes["source_bindings"] = changes.pop("sourceBindings")
    if "metadata" in changes:
        incoming = changes.pop("metadata")
        if incoming is not None and not isinstance(incoming, dict):
            raise LocationConflict(422, "metadata должен быть объектом или null")
        if isinstance((incoming or {}).get("number"), (dict, list, bool)):
            raise LocationConflict(422, "Номер точки должен быть скалярным значением")
        changes["extra_metadata"] = merge_metadata(loc.extra_metadata, incoming) if loc else incoming
        if incoming is None or "number" in incoming:
            number = _number((incoming or {}).get("number"))
            if len(number) > 60:
                raise LocationConflict(422, "Номер точки слишком длинный")
            changes["station_number"] = number or None
    return changes


async def _apply(db, company_id, loc, changes):
    code_changed = "code" in changes and changes["code"] != loc.code
    number_changed = "station_number" in changes and _number(changes["station_number"]) != _number(loc.station_number)
    # Include the snapshot number as well as its materialized column, including
    # explicit null/empty. They may disagree on legacy rows.
    if "extra_metadata" in changes:
        number_changed |= _number((changes["extra_metadata"] or {}).get("number")) != _number((loc.extra_metadata or {}).get("number"))
    if code_changed or number_changed:
        reasons = await freeze_reasons(db, company_id, loc.id)
        if reasons:
            raise LocationConflict(409, "Номер объекта изменить нельзя: " + ", ".join(reasons))
        await _assert_numbers_free(db, company_id,
            [changes["code"] if code_changed else None,
             _number(changes.get("station_number")) if number_changed else None], except_id=loc.id)
    applied = {key: {"from": getattr(loc, key), "to": value} for key, value in changes.items()
               if getattr(loc, key) != value}
    for key, value in changes.items():
        setattr(loc, key, value)
    return Mutation(loc, applied)


async def create(db, company_id, identifier, data):
    """CREATE never updates an existing identity; transaction stays with caller."""
    existing = await _locked(db, company_id, identifier)
    if existing is not None:
        raise LocationConflict(409 if existing.company_id == company_id else 404, "Ключ объекта уже используется")
    linked = await db.scalar(select(ObjectLink.id).where(
        ((ObjectLink.parent_type == "point_of_service") & (ObjectLink.parent_id == identifier)) |
        ((ObjectLink.child_type == "point_of_service") & (ObjectLink.child_id == identifier))).limit(1))
    if linked is not None:
        raise LocationConflict(409, "Технический ключ уже использован в истории")
    history = await db.scalars(select(AuditEvent.details).where(
        AuditEvent.action.in_(["space.object.create", "space.object.update"]),
        AuditEvent.details.contains(identifier, autoescape=True)))
    for details in history:
        try:
            used_id = json.loads(details or "{}").get("objectId")
        except (ValueError, AttributeError):
            continue
        if used_id == identifier:
            raise LocationConflict(409, "Технический ключ уже использован в журнале")
    if current_object_scope() is not None or current_organization() is not None:
        raise LocationConflict(403, "Создание объекта вне назначенного контура запрещено")
    changes = _prepare(None, data)
    await _assert_numbers_free(db, company_id, [changes.get("code"), _number(changes.get("station_number"))])
    loc = ServiceLocation(id=identifier, company_id=company_id, source_bindings=[])
    for key, value in changes.items():
        setattr(loc, key, value)
    db.add(loc)
    return loc


async def upsert(db, company_id, identifier, data):
    """An existing ID denotes the same service point, never a tenant transfer."""
    loc = await _locked(db, company_id, identifier)
    if loc is None:
        return await create(db, company_id, identifier, data)
    await _assert_visible(db, company_id, loc)
    return (await _apply(db, company_id, loc, _prepare(loc, data))).location


async def update(db, company_id, identifier, data):
    loc = await _locked(db, company_id, identifier)
    if loc is None:
        return None
    await _assert_visible(db, company_id, loc)
    return await _apply(db, company_id, loc, _prepare(loc, data))
