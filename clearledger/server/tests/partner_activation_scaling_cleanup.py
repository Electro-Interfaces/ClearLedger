"""M15 inventory/validation ONLY, SOURCE ONLY / NOTRUN (including imports).

Despite the historical filename, this module performs NO row cleanup. ROOT may
inspect ONE selected scaling case while its actual world/factory is still live,
then close all clients/pools and destroy the EXACT wholly owned disposable PG
environment. Missing metadata or inspection failure never means cleanup passed.
No DML/DDL, pytest hook, target discovery, catalogue engine or disposal here.
"""
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.models import Counterparty, Organization, ServiceLocation, User, UserCompany
from app.models_partner import PartnerCredential, PartnerResourceItem
from app.models_partner_contracts import (
    PartnerContractCreatePrincipal as Principal,
    PartnerContractCreateProfile as Profile,
    PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type,
)


class ScalingInventoryRefused(RuntimeError):
    """Declared inventory could not be validated; never a cleanup verdict."""


# Fixed concrete tables and COMPLETE PK shapes. Order is only manifest order.
_SPECS = {
    "PartnerContractCreateType": (Type.__table__, (Type.profile_id, Type.type_code), (UUID, str)),
    "PartnerContractCreatePrincipal": (Principal.__table__, (Principal.id,), (UUID,)),
    "PartnerContractCreateRef": (Ref.__table__, (Ref.id,), (UUID,)),
    "PartnerCredential": (PartnerCredential.__table__, (PartnerCredential.id,), (UUID,)),
    "PartnerResourceItem": (PartnerResourceItem.__table__, (PartnerResourceItem.id,), (UUID,)),
    "UserCompany": (UserCompany.__table__, (UserCompany.user_id, UserCompany.company_id), (UUID, UUID)),
    "User": (User.__table__, (User.id,), (UUID,)),
    "Counterparty": (Counterparty.__table__, (Counterparty.id,), (UUID,)),
    "Organization": (Organization.__table__, (Organization.id,), (UUID,)),
    "ServiceLocation": (ServiceLocation.__table__, (ServiceLocation.id,), (str,)),
}
# Only PKs and known provenance pointers, never password/credential hashes.
_READ_COLUMNS = {
    "PartnerContractCreateType": (Type.profile_id, Type.type_code),
    "PartnerContractCreatePrincipal": (Principal.id, Principal.profile_id, Principal.actor_kind,
                                       Principal.user_id, Principal.machine_grant_id),
    "PartnerContractCreateRef": (Ref.id, Ref.profile_id, Ref.kind,
                                 Ref.organization_id, Ref.counterparty_id, Ref.location_id),
    "PartnerCredential": (PartnerCredential.id, PartnerCredential.client_id),
    "PartnerResourceItem": (PartnerResourceItem.id, PartnerResourceItem.installation_id,
                            PartnerResourceItem.kind, PartnerResourceItem.object_id,
                            PartnerResourceItem.equipment_id, PartnerResourceItem.counterparty_id,
                            PartnerResourceItem.contract_id, PartnerResourceItem.document_id),
    "UserCompany": (UserCompany.user_id, UserCompany.company_id, UserCompany.role_id,
                    UserCompany.organization_id, UserCompany.own_organization_id),
    "User": (User.id, User.company_id),
    "Counterparty": (Counterparty.id, Counterparty.company_id),
    "Organization": (Organization.id, Organization.company_id),
    "ServiceLocation": (ServiceLocation.id, ServiceLocation.company_id),
}
_IDENTITY = "SELECT current_database(), current_user, current_schema(), current_setting('transaction_read_only')"


def _require(condition, reason):
    if not condition:
        raise ScalingInventoryRefused(reason)


def _declared(w, expected_database, expected_user):
    """Validate the WHOLE declared tuple before opening any session."""
    _require(type(expected_database) is str and bool(expected_database)
             and type(expected_user) is str and bool(expected_user),
             "explicit exact database and user strings required")
    _require(type(w) is SimpleNamespace, "actual native world namespace required")
    fields = vars(w)
    factory = fields.get("factory")
    _require(type(factory) is async_sessionmaker and factory.class_ is AsyncSession,
             "actual native AsyncSession factory required")
    _require(type(factory.kw.get("bind")) is AsyncEngine
             and factory.kw.get("binds") is None and "sync_session_class" not in factory.kw,
             "engine-bound native factory required, never a foreign transaction")
    for name in ("company", "home", "admin", "member", "role", "iid", "grant",
                 "cp", "extra_cp", "org", "extra_org"):
        _require(type(fields.get(name)) is UUID, "missing/non-native world UUID: " + name)
    for name in ("loc", "extra_loc", "code", "inactive", "client_id"):
        _require(type(fields.get(name)) is str, "missing/non-native world string: " + name)
    _require(w.company != w.home and w.admin != w.member and w.cp != w.extra_cp
             and w.org != w.extra_org and w.loc != w.extra_loc and w.code != w.inactive,
             "ambiguous native world anchors")
    owned = fields.get("m15_owned")
    _require(type(owned) is tuple and bool(owned),
             "missing/empty/incomplete declared registry: inventory UNKNOWN")
    protected = {
        "User": {w.admin, w.member},
        "UserCompany": {(w.admin, w.company), (w.member, w.company)},
        "Counterparty": {w.cp, w.extra_cp},
        "Organization": {w.org, w.extra_org},
        "ServiceLocation": {w.loc, w.extra_loc},
    }
    declared, seen = [], set()
    for entry in owned:
        _require(type(entry) is tuple and len(entry) == 2, "invalid declared entry")
        name, native = entry
        _require(type(name) is str and name in _SPECS, "unknown/forbidden inventory model")
        _table, _columns, types = _SPECS[name]
        if len(types) == 1:
            _require(type(native) is types[0], "scalar PK must have its exact native type: " + name)
            key = (native,)
        else:
            _require(type(native) is tuple and len(native) == len(types),
                     "complete native composite PK tuple required: " + name)
            _require(all(type(value) is expected for value, expected in zip(native, types)),
                     "invalid native composite PK component: " + name)
            key = native
        # Native components are retained; no UUID conversion or string normalization.
        _require(native not in protected.get(name, ()), "base fixture parent is forbidden: " + name)
        item = (name, key)
        _require(item not in seen, "duplicate declared complete PK: " + name)
        seen.add(item)
        declared.append(item)
    return factory, tuple(declared)


def _predicate(columns, key):
    _require(len(columns) == len(key), "complete PK predicate required")
    return and_(*(column == value for column, value in zip(columns, key)))


def _manifest_sha256(declared):
    """Order-sensitive, length-framed typed bytes; native manifest stays native.

    UUID payload is its original 16 bytes; str payload is exact UTF-8, including
    spaces and Ёё. No str(UUID), UUID(str), case folding or opaque-ID rewriting.
    """
    digest = sha256(b"m15-declared-native-inventory-v1\0")
    for name, key in declared:
        payload = name.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big") + payload)
        digest.update(len(key).to_bytes(1, "big"))
        for value in key:
            tag, payload = (b"u", value.bytes) if type(value) is UUID else (b"s", value.encode("utf-8"))
            digest.update(tag + len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()


async def _inspect_rows(db, w, declared):
    """Read exact full PKs and known pointer provenance, never infer ownership."""
    profiles = (await db.execute(select(Profile.id).where(
        Profile.installation_id == w.iid, Profile.company_id == w.company,
        Profile.client_id == w.client_id))).all()
    _require(len(profiles) == 1 and type(profiles[0][0]) is UUID,
             "ambiguous/missing actual installation profile")
    profile_id = profiles[0][0]
    ids = {name: set() for name in _SPECS}
    counts = {name: 0 for name in _SPECS}
    for name, key in declared:
        ids[name].add(key[0] if len(key) == 1 else key)
    for name, key in declared:
        _table, columns, types = _SPECS[name]
        result = (await db.execute(select(*_READ_COLUMNS[name]).where(
            _predicate(columns, key)))).mappings().all()
        _require(len(result) == 1, "declared complete PK missing/ambiguous: " + name)
        row = result[0]
        actual_key = tuple(row[column.key] for column in columns)
        _require(all(type(value) is expected for value, expected in zip(actual_key, types))
                 and actual_key == key, "readback native complete PK mismatch: " + name)
        if name in ("PartnerContractCreateType", "PartnerContractCreatePrincipal", "PartnerContractCreateRef"):
            _require(row["profile_id"] == profile_id, "foreign profile descendant")
        if name == "PartnerContractCreateType":
            _require(key == (profile_id, w.code), "unsupported profile type selection")
        elif name == "PartnerContractCreatePrincipal":
            _require((row["actor_kind"] == "user" and row["user_id"] in {w.member, *ids["User"]}
                      and row["machine_grant_id"] is None)
                     or (row["actor_kind"] == "machine" and row["user_id"] is None
                         and row["machine_grant_id"] == w.grant), "unsupported principal pointers")
        elif name == "PartnerContractCreateRef":
            _require((row["kind"] == "organization" and row["organization_id"] in {w.org, *ids["Organization"]}
                      and row["counterparty_id"] is None and row["location_id"] is None)
                     or (row["kind"] == "counterparty" and row["counterparty_id"] in {w.cp, *ids["Counterparty"]}
                         and row["organization_id"] is None and row["location_id"] is None)
                     or (row["kind"] == "location" and row["location_id"] in {w.loc, *ids["ServiceLocation"]}
                         and row["organization_id"] is None and row["counterparty_id"] is None),
                     "unsupported reference pointers")
        elif name == "PartnerCredential":
            _require(row["client_id"] == w.client_id, "foreign credential")
        elif name == "PartnerResourceItem":
            _require(row["installation_id"] == w.iid and row["kind"] == "objects"
                     and row["object_id"] in ids["ServiceLocation"]
                     and all(row[field] is None for field in
                             ("equipment_id", "counterparty_id", "contract_id", "document_id")),
                     "unsupported resource item pointers")
        elif name == "UserCompany":
            _require(key[0] in ids["User"] and key[1] == w.company and row["role_id"] == w.role
                     and row["organization_id"] is None
                     and row["own_organization_id"] in {w.org, *ids["Organization"]},
                     "unsupported membership pointers")
        elif name == "User":
            _require(row["company_id"] == w.home and (key[0], w.company) in ids["UserCompany"],
                     "unsupported user home/membership")
        else:
            _require(row["company_id"] == w.company, "foreign reference parent")
        counts[name] += 1
    return counts


async def inspect_m15_owned(world, expected_database, expected_user):
    """Inventory ONLY; exact expected DB/user come from ROOT's owned descriptor.

    The actual fresh engine-bound session requests PostgreSQL read-only mode
    before its first statement and verifies the real server setting. Unsupported
    read-only mode fails, without fallback or isolation changes. Always rollback
    the read transaction and close the session, including error/cancellation.
    Result covers declared rows, not complete ownership/FK closure or disposal.
    """
    factory, declared = _declared(world, expected_database, expected_user)
    async with factory() as db:
        _require(type(db) is AsyncSession and type(db.sync_session) is Session
                 and db.bind is factory.kw["bind"] and not db.in_transaction()
                 and not db.new and not db.dirty and not db.deleted and not db.identity_map,
                 "fresh pristine native AsyncSession required")
        try:
            await db.connection(execution_options={"postgresql_readonly": True})
            identity = (await db.execute(text(_IDENTITY))).all()
            _require(len(identity) == 1 and len(identity[0]) == 4
                     and all(type(value) is str for value in identity[0])
                     and tuple(identity[0]) == (expected_database, expected_user, "core", "on"),
                     "actual database/user/core/read-only identity mismatch")
            counts = await _inspect_rows(db, world, declared)
            result = {
                "scope": "declared inventory only; not complete ownership or FK closure",
                "database": identity[0][0], "user": identity[0][1], "schema": identity[0][2],
                "transaction_read_only": True,
                "declared_count": len(declared), "present_count": sum(counts.values()),
                "counts_by_model": counts,
                "pk_components_by_model": {name: count * len(_SPECS[name][1]) for name, count in counts.items()},
                "native_manifest": declared, "manifest_sha256": _manifest_sha256(declared),
                "manifest_hash_order_sensitive": True,
                "pointer_provenance_checked": True, "registry_completeness": "UNKNOWN",
                "ownership_capture": "UNKNOWN", "physical_fk_closure": "UNKNOWN",
                "row_cleanup_performed": False, "whole_database_disposal": "ROOT responsibility; NOT VERIFIED",
            }
        finally:
            await db.rollback()
    return result
