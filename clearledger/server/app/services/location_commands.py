"""ServiceLocation (service point) mutation invariants; caller owns admission/commit.

No HTTP, projection, audit, station/site/EVSE mutation or implicit commit here.
Legacy temporal renumber/retire producers are not invented by these commands.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select, text

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
    "nameHistory", "numberHistory", "identifierHistory", "fieldProvenance", "zoi1", "buNumber", "connectorsSource",
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


def validate_identifier(identifier: str) -> str:
    """Validate the existing String(40) identity without rewriting opaque IDs."""
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 40 or "\x00" in identifier:
        raise ValueError("Ключ объекта должен содержать от 1 до 40 символов без нулевого байта")
    return identifier


@dataclass(frozen=True, eq=False)
class LockedLocationSet:
    """Preheld identities, not admission; only the issuing root transaction may use it."""

    identifiers: frozenset[str]
    _db: Any = field(repr=False)
    _root: Any = field(repr=False)
    _company: str = field(repr=False)


@dataclass
class _LocationEntrance:
    root: Any
    mode: str
    capability: LockedLocationSet | None = None


_ENTRANCE_KEY = "location-command:v1:entrance"
_SET_CONFLICT = "Набор блокировок объекта недействителен: требуется новая транзакция"


def _entrance(db, root):
    state = db.info.get(_ENTRANCE_KEY)
    return state if isinstance(state, _LocationEntrance) and state.root is root else None


async def _root_transaction(db):
    # Retain the sync root object's identity, not an AsyncSessionTransaction proxy
    # or the current SAVEPOINT. begin() does not flush or commit caller state.
    root = db.sync_session.get_transaction()
    if root is None:
        await db.begin()
        root = db.sync_session.get_transaction()
    return root


def _require_location_set(db, company_id, identifier, capability):
    root = db.sync_session.get_transaction()
    state = _entrance(db, root)
    if (not isinstance(capability, LockedLocationSet) or capability._db is not db
            or root is None or not root.is_active or capability._root is not root
            or state is None or state.mode != "prepared" or state.capability is not capability
            or capability._company != str(company_id) or identifier not in capability.identifiers):
        raise LocationConflict(409, _SET_CONFLICT)


async def _advisory_lock(db, namespace, value):
    # Preserve the exact v1 namespace, bytes, digest and signed bigint encoding.
    key = int.from_bytes(hashlib.blake2b(
        f"location-command:v1:{namespace}:{value}".encode(), digest_size=8).digest(), "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def acquire_location_set(db, company_id, identifiers):
    """Acquire the FULL opaque-ID set before the existing company barrier.

    Caller must enter before incompatible row/FK writes, and revalidate targets
    after waiting. This API cannot discover arbitrary prior SQL locks. It does
    not load rows, admit a principal, flush, mutate domain state or commit.
    A fresh acquisition in a SAVEPOINT is unsafe: rollback would release its
    locks while leaving the root alive. A preheld root set may be used there.
    """
    try:
        if isinstance(identifiers, (str, bytes)):
            raise TypeError
        ordered = sorted({validate_identifier(value) for value in identifiers})
    except ValueError as exc:
        raise LocationConflict(422, str(exc)) from exc
    except TypeError as exc:
        raise LocationConflict(422, "Недопустимый набор ключей объектов") from exc

    root = await _root_transaction(db)
    state = _entrance(db, root)
    if state is not None:
        cap = state.capability
        if (root.is_active and state.mode == "prepared" and cap is not None
                and cap._db is db and cap._company == str(company_id)
                and frozenset(ordered) <= cap.identifiers):
            return cap
        # Includes a single-path entrance, an incomplete acquisition, an
        # extension, or another company. Never acquire another ID after C.
        raise LocationConflict(409, _SET_CONFLICT)
    if not root.is_active or db.in_nested_transaction():
        raise LocationConflict(409, _SET_CONFLICT)

    state = _LocationEntrance(root, "preparing")
    db.info[_ENTRANCE_KEY] = state
    try:
        for identifier in ordered:
            await _advisory_lock(db, "id", identifier)
        await _advisory_lock(db, "company", company_id)
    except BaseException:
        # Some IDs may already be held. No retry/extension until outer rollback.
        state.mode = "failed"
        raise
    cap = LockedLocationSet(frozenset(ordered), db, root, str(company_id))
    state.mode, state.capability = "prepared", cap
    return cap


async def _barrier(db, company_id, identifier):
    root = await _root_transaction(db)
    state = _entrance(db, root)
    if state is not None and state.mode != "single":
        # Protect old _locked/update/upsert/create callers in a prepared root T,
        # not just the new explicit-token reader. Known IDs require no new lock.
        _require_location_set(db, company_id, identifier, state.capability)
        return
    if state is None:
        db.info[_ENTRANCE_KEY] = _LocationEntrance(root, "single")
    # Existing single-path outcomes/order remain unchanged outside prepared T.
    for namespace, value in (("id", identifier), ("company", company_id)):
        await _advisory_lock(db, namespace, value)


async def _reload_location(db, company_id, identifier):
    # Tenant predicate precedes row lock; never load/lock another tenant's row.
    return (await db.execute(select(ServiceLocation).where(
                            ServiceLocation.id == identifier, ServiceLocation.company_id == company_id)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def _locked(db, company_id, identifier):
    try:
        validate_identifier(identifier)
    except ValueError as exc:
        raise LocationConflict(422, str(exc)) from exc
    await _barrier(db, company_id, identifier)
    # FOR UPDATE conflicts with FK key-share checks in contract/session writers.
    # Reload even when admission already loaded this row into the identity map.
    return await _reload_location(db, company_id, identifier)


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


async def locked_visible(db, company_id, identifier):
    """Admit an existing service point without mutation or implicit commit.

    Reuse the tenant-first reload and the current object/organization context;
    the caller still owns company membership and the transaction lifetime.
    """
    loc = await _locked(db, company_id, identifier)
    if loc is None:
        raise LocationConflict(404, "Объект не найден")
    await _assert_visible(db, company_id, loc)
    return loc


async def locked_visible_in_set(db, company_id, identifier, locked_set):
    """Reload an existing admitted point under a preheld root set; no commit.

    Admission is the CURRENT O/G context at lookup, never cached by the token.
    Company membership remains the caller's responsibility, as in locked_visible.
    Apply the target's patch AFTER reload: populate_existing must not silently
    discard its unflushed changes. Unrelated pending entities are not flushed.
    """
    try:
        validate_identifier(identifier)
    except ValueError as exc:
        raise LocationConflict(422, str(exc)) from exc
    _require_location_set(db, company_id, identifier, locked_set)
    for entity in db.dirty:
        if (isinstance(entity, ServiceLocation) and inspect(entity).identity == (identifier,)
                and db.is_modified(entity, include_collections=True)):
            raise LocationConflict(409, "Объект содержит несохранённые изменения")
    with db.no_autoflush:
        loc = await _reload_location(db, company_id, identifier)
        if loc is None:
            raise LocationConflict(404, "Объект не найден")
        await _assert_visible(db, company_id, loc)
    return loc


async def code_taken(db, company_id, code, *, except_id=None):
    # Internal occupancy is company-wide even when the actor sees one point.
    # Core columns avoid actor ORM criteria without loading hidden entities.
    columns = ServiceLocation.__table__.c
    rows = await db.execute(select(columns.id).where(
        columns.company_id == company_id, columns.code == _number(code),
        columns.id != except_id if except_id is not None else True).limit(1))
    return rows.first() is not None


def _history_entries(metadata, key):
    """Read history without repairing legacy dictionaries or inventing domains."""
    history = metadata.get(key)
    detail = ("История номеров повреждена: требуется сверка перед изменением номера"
              if key == "numberHistory" else
              "История идентификаторов повреждена: требуется сверка перед изменением")
    if history is None:
        return []
    if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
        raise LocationConflict(409, detail)
    if key == "identifierHistory":
        for entry in history:
            domain = entry.get("domain")
            if domain != "code" and domain != "station_number":
                continue  # Unknown legacy dictionaries remain opaque and intact.
            old, new = entry.get("old"), entry.get("new")
            if (not isinstance(old, str) or not old.strip() or "new" not in entry or
                    not (isinstance(new, str) and new.strip() or
                         domain == "station_number" and new is None)):
                raise LocationConflict(409, detail)
    return history


async def _assert_numbers_free(db, company_id, values, *, except_id=None):
    values = {v for v in values if v}
    if not values:
        return
    columns = ServiceLocation.__table__.c
    rows = (await db.execute(select(columns.id, columns.code, columns.station_number,
        columns.extra_metadata).where(columns.company_id == company_id))).all()
    for other in rows:
        md = other.extra_metadata or {}
        # A retired alias remains reserved even for its original point. Current
        # values of that same point are exempt; this is not a new assignment.
        try:
            number_history = _history_entries(md, "numberHistory")
            identifier_history = _history_entries(md, "identifierHistory")
        except LocationConflict as exc:
            # A hidden malformed history cannot prove that a number is free.
            raise LocationConflict(409, "Номер уже занят текущим или историческим объектом компании") from exc
        numbers = {_number(h.get("было")) for h in number_history}
        numbers.update(_number(h.get("old")) for h in identifier_history
                       if h.get("domain") == "code" or h.get("domain") == "station_number")
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
        if loc is None and incoming is not None and "identifierHistory" in incoming:
            raise LocationConflict(422, "История идентификаторов заполняется сервером")
        if loc is None and incoming is not None and "fieldProvenance" in incoming:
            raise LocationConflict(422, "Происхождение полей заполняется сервером")
        if isinstance((incoming or {}).get("number"), (dict, list, bool)):
            raise LocationConflict(422, "Номер точки должен быть скалярным значением")
        changes["extra_metadata"] = merge_metadata(loc.extra_metadata, incoming) if loc else incoming
        if incoming is None or "number" in incoming:
            number = _number((incoming or {}).get("number"))
            if len(number) > 60:
                raise LocationConflict(422, "Номер точки слишком длинный")
            changes["station_number"] = number or None
    return changes


def _with_identifier_history(loc, changes, *, actor_id=None, source=None):
    """Record typed transitions and station-only aliases without inferring validity.

    Called only after the command acquired its barrier and reloaded the row.
    Construct a fresh metadata tree: neither the ORM snapshot nor an incoming
    list may be mutated before all guards have succeeded.
    """
    current_md = loc.extra_metadata or {}
    next_md = changes.get("extra_metadata", loc.extra_metadata) or {}
    history = _history_entries(current_md, "numberHistory")
    identifier_history = _history_entries(current_md, "identifierHistory")
    outgoing = []
    seen_transitions = set()
    for domain, field, old, new in (
        ("code", "code", loc.code, changes.get("code", loc.code)),
        ("station_number", "station_number", loc.station_number, changes.get("station_number", loc.station_number)),
        ("station_number", "metadata.number", current_md.get("number"), next_md.get("number")),
    ):
        old, new = _number(old), _number(new)
        transition = (domain, old, new or None)
        if old and old != new and transition not in seen_transitions:
            outgoing.append((domain, field, old, new or None))
            seen_transitions.add(transition)
    if not outgoing:
        return changes
    # SQL containment matches JSON strings exactly. Numeric/whitespace legacy
    # entries must stay untouched, but cannot replace a searchable new alias.
    seen = {entry["было"] for entry in history if isinstance(entry.get("было"), str)}
    additions = []
    identifier_additions = []
    recorded_at = datetime.now(timezone.utc).isoformat()
    for domain, field, old, new in outgoing:
        provenance = {"field": field, "source": source or "unknown",
                      "actor": str(actor_id) if actor_id is not None else None,
                      "recordedAt": recorded_at}
        identifier_additions.append({"domain": domain, "old": old, "new": new, **provenance})
        if domain == "station_number" and old not in seen:
            additions.append({"было": old, **provenance})
            seen.add(old)
    metadata = deepcopy(next_md)
    metadata["identifierHistory"] = deepcopy(identifier_history) + identifier_additions
    if additions:
        metadata["numberHistory"] = deepcopy(history) + additions
    return {**changes, "extra_metadata": metadata}


def _with_manual_name_provenance(loc, changes, *, name_intent=None, actor_id=None, source=None):
    """Record an explicit admitted wrapper intent, never infer it from source/text.

    Only existing points and actual name changes participate. Unknown stored
    provenance stays opaque: a new manual edit cannot silently repair it.
    """
    if name_intent not in (None, "manual"):
        raise LocationConflict(422, "Недопустимое намерение изменения названия")
    if name_intent is None or "name" not in changes or changes["name"] == loc.name:
        return changes
    if actor_id is None or not isinstance(source, str) or not source:
        raise LocationConflict(422, "Для ручного названия требуется автор и источник")
    current_md = loc.extra_metadata or {}
    provenance = current_md.get("fieldProvenance", {})
    detail = "Происхождение названия повреждено или неизвестно: требуется сверка"
    if not isinstance(provenance, dict):
        raise LocationConflict(409, detail)
    if "name" in provenance:
        old = provenance["name"]
        if (not isinstance(old, dict) or old.get("authority") not in ("manual", "cpo_registry", "sessions")
                or "actor" not in old or not (old["actor"] is None or isinstance(old["actor"], str) and old["actor"].strip())
                or old["authority"] == "manual" and old["actor"] is None
                or not isinstance(old.get("source"), str) or not old["source"].strip()
                or not isinstance(old.get("recordedAt"), str)):
            raise LocationConflict(409, detail)
        try:
            recorded = datetime.fromisoformat(old["recordedAt"])
        except ValueError as exc:
            raise LocationConflict(409, detail) from exc
        if recorded.utcoffset() is None:
            raise LocationConflict(409, detail)
    metadata = deepcopy(changes.get("extra_metadata", loc.extra_metadata) or {})
    provenance = deepcopy(provenance)
    provenance["name"] = {**provenance.get("name", {}), "authority": "manual",
                          "actor": str(actor_id), "source": source,
                          "recordedAt": datetime.now(timezone.utc).isoformat()}
    metadata["fieldProvenance"] = provenance
    return {**changes, "extra_metadata": metadata}


async def _apply(db, company_id, loc, changes, *, actor_id=None, source=None, name_intent=None):
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
        changes = _with_identifier_history(loc, changes, actor_id=actor_id, source=source)
        await _assert_numbers_free(db, company_id,
            [changes["code"] if code_changed else None,
             _number(changes.get("station_number")) if number_changed else None], except_id=loc.id)
    changes = _with_manual_name_provenance(loc, changes, name_intent=name_intent,
                                          actor_id=actor_id, source=source)
    applied = {key: {"from": getattr(loc, key), "to": value} for key, value in changes.items()
               if getattr(loc, key) != value}
    for key, value in changes.items():
        setattr(loc, key, value)
    return Mutation(loc, applied)


async def create(db, company_id, identifier, data):
    """CREATE never updates an existing identity; transaction stays with caller."""
    existing = await _locked(db, company_id, identifier)
    if existing is not None:
        raise LocationConflict(409, "Ключ объекта уже используется")
    # ID advisory lock remains global, but tenant rejection must not lock/load
    # another company's row. Ordinary MVCC existence reads do not await its row
    # lock; every supported ID claimant holds the same advisory barrier.
    if await db.scalar(select(ServiceLocation.id).where(ServiceLocation.id == identifier)) is not None:
        raise LocationConflict(404, "Объект не найден в этой компании")
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


async def upsert(db, company_id, identifier, data, *, actor_id=None, source=None, name_intent=None):
    """An existing ID denotes the same service point, never a tenant transfer."""
    loc = await _locked(db, company_id, identifier)
    if loc is None:
        # A scoped ORM miss may still be an existing point in this company.
        # Keep hidden-existing 404 distinct from restricted new-create 403,
        # using only a scalar existence read after the same advisory barrier.
        columns = ServiceLocation.__table__.c
        if await db.scalar(select(columns.id).where(
                columns.company_id == company_id, columns.id == identifier)) is not None:
            raise LocationConflict(404, "Объект не найден")
        return await create(db, company_id, identifier, data)
    await _assert_visible(db, company_id, loc)
    return (await _apply(db, company_id, loc, _prepare(loc, data), actor_id=actor_id, source=source,
                         name_intent=name_intent)).location


async def update(db, company_id, identifier, data, *, actor_id=None, source=None, name_intent=None):
    loc = await _locked(db, company_id, identifier)
    if loc is None:
        return None
    await _assert_visible(db, company_id, loc)
    return await _apply(db, company_id, loc, _prepare(loc, data), actor_id=actor_id, source=source,
                        name_intent=name_intent)
