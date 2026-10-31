"""Typed parent guards for contract writes; callers own policy and the root.

No actor/ACL discovery, row locks, flush, transaction completion, or retries.
See docs/api/CONTRACT_WRITE_SCOPED_LOCKS_20261101.md for the frozen protocol.
Lifetime evidence covers SQLAlchemy transaction APIs, not raw transaction SQL
or direct driver control. Participating callers must exclude those operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import IntEnum
import hashlib
import json
from typing import TypeAlias
from uuid import UUID
import weakref

from sqlalchemy import Integer, bindparam, event, text
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction


class ScopedLockError(RuntimeError):
    """Fail closed: caller must roll back the entire root before retrying."""


class LockMode(IntEnum):
    SHARED = 1
    EXCLUSIVE = 2


class _TypedKey:
    __slots__ = ()

    def __post_init__(self) -> None:
        _validate_key(self)


@dataclass(frozen=True, slots=True)
class AppKey(_TypedKey):
    app_id: UUID


@dataclass(frozen=True, slots=True)
class ClientKey(_TypedKey):
    client_id: str


@dataclass(frozen=True, slots=True)
class UserKey(_TypedKey):
    user_id: UUID


@dataclass(frozen=True, slots=True)
class CompanyKey(_TypedKey):
    company_id: UUID


@dataclass(frozen=True, slots=True)
class InstallationKey(_TypedKey):
    installation_id: UUID


@dataclass(frozen=True, slots=True)
class CreateProfileKey(_TypedKey):
    profile_id: UUID


@dataclass(frozen=True, slots=True)
class RoleKey(_TypedKey):
    company_id: UUID
    role_id: UUID


@dataclass(frozen=True, slots=True)
class MemberKey(_TypedKey):
    company_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class RefCompositeKey(_TypedKey):
    company_id: UUID


@dataclass(frozen=True, slots=True)
class TypeCatalogKey(_TypedKey):
    type_code: str


ScopedKey: TypeAlias = (
    AppKey | ClientKey | UserKey | CompanyKey | InstallationKey
    | CreateProfileKey | RoleKey | MemberKey | RefCompositeKey | TypeCatalogKey
)

# ROOT allocation: separate PostgreSQL two-int keyspace, all signed int32.
_SCHEMA = {
    AppKey: (0x50430010, "app"),
    ClientKey: (0x50430020, "client"),
    UserKey: (0x50430030, "user"),
    CompanyKey: (0x50430040, "company"),
    InstallationKey: (0x50430050, "installation"),
    CreateProfileKey: (0x50430060, "create_profile"),
    RoleKey: (0x50430070, "role"),
    MemberKey: (0x50430080, "member"),
    RefCompositeKey: (0x50430090, "ref_composite"),
    TypeCatalogKey: (0x50430095, "type_catalog"),
}


def _validate_key(key: object) -> None:
    if type(key) not in _SCHEMA:
        raise TypeError("An exact scoped key type is required")
    for part in fields(key):
        value = getattr(key, part.name)
        expected = str if part.name in ("client_id", "type_code") else UUID
        if type(value) is not expected or (expected is str and not value):
            raise TypeError(f"{part.name} requires exact nonempty {expected.__name__}")


def encode_key(key: ScopedKey) -> bytes:
    """Only canonical encoder: compact sorted ASCII JSON, then UTF-8 (v1)."""
    _validate_key(key)
    parts = {part.name: (str(value) if type(value) is UUID else value)
             for part in fields(key) for value in (getattr(key, part.name),)}
    return json.dumps(
        {"v": 1, "key": _SCHEMA[type(key)][1], "parts": parts},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def advisory_key(key: ScopedKey) -> tuple[int, int]:
    payload = encode_key(key)
    return (_SCHEMA[type(key)][0],
            int.from_bytes(hashlib.sha256(payload).digest()[:4], "big", signed=True))


@dataclass(frozen=True, slots=True)
class LockRequest:
    key: ScopedKey
    mode: LockMode

    def __post_init__(self) -> None:
        _validate_key(self.key)
        if type(self.mode) is not LockMode:
            raise TypeError("An exact LockMode is required")


@dataclass(frozen=True, slots=True)
class ActualLock:
    namespace: int
    key: int
    mode: LockMode


@dataclass(frozen=True, slots=True)
class LockPlan:
    """Full immutable declaration; originals survive collision merging."""

    requests: tuple[LockRequest, ...]
    locks: tuple[ActualLock, ...] = field(init=False)

    def __post_init__(self) -> None:
        if type(self.requests) is not tuple or not self.requests:
            raise TypeError("A nonempty exact tuple of LockRequest is required")
        merged: dict[tuple[int, int], LockMode] = {}
        for request in self.requests:
            if type(request) is not LockRequest:
                raise TypeError("An exact LockRequest is required")
            request.__post_init__()
            actual = advisory_key(request.key)
            merged[actual] = max(merged.get(actual, LockMode.SHARED), request.mode)
        object.__setattr__(self, "locks", tuple(
            ActualLock(namespace, key, merged[(namespace, key)])
            for namespace, key in sorted(merged)
        ))


@dataclass(frozen=True, slots=True, eq=False)
class ScopedLockCapability:
    """Non-bearer receipt: only the exact registered instance is usable."""

    plan: LockPlan


@dataclass
class _Entrance:
    issuer: weakref.ReferenceType[Session]
    root: weakref.ReferenceType[SessionTransaction]
    phase: str = "preparing"
    connection: Connection | None = None
    transaction: RootTransaction | None = None
    capability: ScopedLockCapability | None = None


# Values do not retain the Session or its root. Caller-visible info is not an
# issuance registry; copying a capability/Session.info cannot manufacture one.
_ENTRANCES: weakref.WeakKeyDictionary[Session, _Entrance] = weakref.WeakKeyDictionary()

# A rollback_only Session can end its ORM root while the borrowed DB root
# keeps every acquired lock. Reserve the actual DB root independently of
# issuance, before lock SQL. Neither key nor value retains a Session/DB root;
# in particular, storing _Entrance here would retain the weak key indirectly.
_ATTEMPTS: weakref.WeakKeyDictionary[
    RootTransaction, weakref.ReferenceType[Connection]
] = weakref.WeakKeyDictionary()


def _transaction_created(session: Session, transaction: SessionTransaction) -> None:
    state = _ENTRANCES.get(session)
    if state is not None and state.issuer() is session and transaction.nested:
        state.phase = "poisoned"


def _transaction_ended(session: Session, transaction: SessionTransaction) -> None:
    state = _ENTRANCES.get(session)
    if (state is not None and state.issuer() is session
            and (transaction is state.root() or transaction.nested)):
        state.phase = "poisoned"


def _connection_begun(
    session: Session, transaction: SessionTransaction, connection: Connection,
) -> None:
    state = _ENTRANCES.get(session)
    if state is not None and state.issuer() is session and state.connection is not None:
        if transaction.nested or connection is not state.connection:
            state.phase = "poisoned"


def _watch_session(session: Session) -> None:
    for name, listener in (
        ("after_transaction_create", _transaction_created),
        ("after_transaction_end", _transaction_ended),
        ("after_begin", _connection_begun),
    ):
        if not event.contains(session, name, listener):
            event.listen(session, name, listener)


def _watch_connection(state: _Entrance) -> None:
    reference = weakref.ref(state)

    def invalidate(connection: Connection, *args: object) -> None:
        entrance = reference()
        if entrance is not None:
            entrance.phase = "poisoned"

    # Instance listeners only. Do not remove listeners inside a dispatch iterator.
    for name in ("commit", "rollback", "savepoint", "rollback_savepoint", "release_savepoint"):
        event.listen(state.connection, name, invalidate)


def _reject(message: str) -> None:
    raise ScopedLockError(message + "; roll back the entire root")


def _single_connection(root: SessionTransaction, connection: Connection) -> bool:
    # Deliberate narrow, source-pinned SQLAlchemy 2.0 integration: verify the
    # actual enlistment, including its DB transaction, not a proxy or caller flag.
    records = root._connections
    return bool(records) and all(
        record[0] is connection and record[1] is connection.get_transaction()
        for record in records.values()
    )


def _live(session: Session, state: _Entrance, phase: str) -> None:
    root, connection, transaction = state.root(), state.connection, state.transaction
    attempt = _ATTEMPTS.get(transaction) if transaction is not None else None
    if (state.issuer() is not session or state.phase != phase or not session.is_active or root is None
            or session.get_transaction() is not root or not root.is_active
            or root.parent is not None or root.nested or session.in_nested_transaction()
            or connection is None or connection.closed or connection.invalidated
            or connection.get_nested_transaction() is not None
            or transaction is None or type(transaction) is not RootTransaction
            or not transaction.is_active or connection.get_transaction() is not transaction
            or attempt is None or attempt() is not connection
            or connection._is_autocommit_isolation()
            or not _single_connection(root, connection)):
        state.phase = "poisoned"
        _reject("Scoped lock lifetime is invalid")


_SHARED_SQL = text(
    "SELECT pg_advisory_xact_lock_shared(CAST(:namespace AS INTEGER), CAST(:key AS INTEGER))"
).bindparams(bindparam("namespace", type_=Integer), bindparam("key", type_=Integer))
_EXCLUSIVE_SQL = text(
    "SELECT pg_advisory_xact_lock(CAST(:namespace AS INTEGER), CAST(:key AS INTEGER))"
).bindparams(bindparam("namespace", type_=Integer), bindparam("key", type_=Integer))


def acquire_scoped_locks(session: Session, plan: LockPlan) -> ScopedLockCapability:
    """Acquire exactly one complete plan in a clean single-connection root.

    Read-only MVCC discovery may already have autobegun the root. The caller
    must forbid earlier row/FK/advisory writes; this helper cannot discover them.
    No reentry, upgrade, extension, fallback or retry in the same root.
    """
    if not isinstance(session, Session) or type(plan) is not LockPlan:
        raise TypeError("Session and exact LockPlan required")
    if session.new or session.dirty or session.deleted:
        _reject("Scoped locks require clean entry")
    if not session.is_active or session.in_nested_transaction() or session.twophase:
        _reject("Active non-nested single-phase root required")
    root = session.get_transaction()
    previous = _ENTRANCES.get(session)
    if root is not None and previous is not None and previous.root() is root:
        _reject("This root already attempted a scoped plan")
    # Inspect existing Connection binds before Session.connection could join a
    # SAVEPOINT. Inactive nested objects also fail closed.
    bind = session.get_bind()
    existing = [bind] if isinstance(bind, Connection) else []
    if root is not None:
        existing.extend(record[0] for record in root._connections.values())
    if any(conn.closed or conn.invalidated or conn.get_nested_transaction() is not None
           or (conn.get_transaction() is not None and not conn.get_transaction().is_active)
           for conn in existing):
        _reject("Connection root is inactive or nested")
    _watch_session(session)
    if root is None:
        session.begin()
        root = session.get_transaction()
    if root is None or not root.is_active or root.parent is not None or root.nested:
        _reject("Active Session root required")
    state = _Entrance(weakref.ref(session), weakref.ref(root))
    _ENTRANCES[session] = state
    try:
        with session.no_autoflush:
            connection = session.connection()
            state.connection = connection
            state.transaction = connection.get_transaction()
            transaction = state.transaction
            if type(transaction) is not RootTransaction or not transaction.is_active:
                _reject("Active DB root required")
            if transaction in _ATTEMPTS:
                _reject("This DB root already attempted a scoped plan")
            _ATTEMPTS[transaction] = weakref.ref(connection)
            _watch_connection(state)
            if connection.dialect.name != "postgresql":
                _reject("PostgreSQL connection required")
            _live(session, state, "preparing")
            # Reconstruct to reject altered derived fields before any lock SQL.
            if LockPlan(plan.requests) != plan:
                _reject("Noncanonical plan")
            for lock in plan.locks:
                statement = _EXCLUSIVE_SQL if lock.mode is LockMode.EXCLUSIVE else _SHARED_SQL
                connection.execute(statement, {"namespace": lock.namespace, "key": lock.key})
                _live(session, state, "preparing")
            capability = ScopedLockCapability(plan)
            state.capability = capability
            state.phase = "prepared"
            return capability
    except BaseException:
        state.phase = "poisoned"
        raise


async def acquire_scoped_locks_async(
    session: AsyncSession, plan: LockPlan,
) -> ScopedLockCapability:
    """Same protocol on AsyncSession's actual sync_session via run_sync."""
    if not isinstance(session, AsyncSession):
        raise TypeError("AsyncSession required")
    return await session.run_sync(acquire_scoped_locks, plan)


def require_scoped_locks(
    session: Session, capability: ScopedLockCapability,
    required: tuple[LockRequest, ...],
) -> None:
    """Validate issuance, live root/connection and exact logical coverage.

    Authorized pending ORM writes are permitted here. Hash collisions grant
    neither a new logical key nor an EXCLUSIVE mode on a SHARED logical key.
    """
    if not isinstance(session, Session):
        raise TypeError("Session required (AsyncSession callers pass sync_session)")
    state = _ENTRANCES.get(session)
    if (type(capability) is not ScopedLockCapability or state is None
            or state.issuer() is not session or state.capability is not capability):
        _reject("Capability was not issued to this Session")
    _live(session, state, "prepared")
    if type(required) is not tuple:
        raise TypeError("Exact tuple of LockRequest required")
    for request in required:
        if type(request) is not LockRequest:
            raise TypeError("Exact LockRequest required")
        request.__post_init__()
        if not any(original.key == request.key and original.mode >= request.mode
                   for original in capability.plan.requests):
            _reject("Logical key/mode was not declared in the original plan")
