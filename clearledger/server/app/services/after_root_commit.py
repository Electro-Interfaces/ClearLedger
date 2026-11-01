"""Best-effort audit scheduling after an owned SQLAlchemy root commits.

Calibrated to SQLAlchemy 2.0.36 internals; unknown ownership fails closed.
This is an in-memory queue, not a durable outbox or a delivery guarantee.
"""
from dataclasses import dataclass, field
import logging
from uuid import UUID

from sqlalchemy import __version__, event
from sqlalchemy.engine import Engine, RootTransaction
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

logger = logging.getLogger(__name__)
_STATE = "_audit_after_root_commit"
_INSTALLED = "_audit_after_root_commit_listeners"


@dataclass(frozen=True, slots=True)
class AuditNotification:
    company_id: UUID
    action: str
    who: str | None
    details: str | None


@dataclass
class _Queue:
    root: SessionTransaction
    items: dict[SessionTransaction, list[tuple[int, AuditNotification]]] = field(default_factory=dict)
    successful: set[SessionTransaction] = field(default_factory=set)
    sequence: int = 0
    physical_root: bool = False


def _configuration(session: Session) -> Engine:
    # get_bind overrides and mapper binds may silently enlist another engine.
    # Default immediate callers never enter this guard.
    if (__version__ != "2.0.36" or type(session) is not Session
            or "get_bind" in session.__dict__
            or session.get_bind.__func__ is not Session.get_bind
            or session._Session__binds or session.twophase
            or session.join_transaction_mode != "conditional_savepoint"
            or type(session.bind) is not Engine):
        raise ValueError("after_root_commit requires a single Engine-bound owned Session")
    engine = session.bind
    # Such hooks can supply an already-open transaction even for Engine binding.
    # Do not acquire a connection or guess ownership from an Engine-like object.
    if engine.dispatch.engine_connect or engine.dispatch.begin:
        raise ValueError("after_root_commit does not support connection transaction hooks")
    return engine


def _physical_root(session: Session, root: SessionTransaction) -> bool:
    engine = _configuration(session)
    found = False
    for connection, transaction, should_commit, autoclose in set(root._connections.values()):
        if (connection.engine is not engine or type(transaction) is not RootTransaction
                or should_commit is not True or autoclose is not True
                or connection.get_transaction() is not transaction
                or not transaction.is_active):
            raise ValueError("after_root_commit cannot own an external or joined transaction")
        found = True
    return found


def validate_audit_notification_session(db: AsyncSession) -> None:
    """Reject unsupported ownership before AuditEvent add; never start a root."""
    if type(db) is not AsyncSession:
        raise ValueError("after_root_commit requires an actual AsyncSession")
    session = db.sync_session
    _configuration(session)
    if not session.is_active:
        raise ValueError("after_root_commit requires an active Session")
    root = session.get_transaction()
    if root is not None:
        if root.parent is not None or root.nested:
            raise ValueError("after_root_commit requires an owned root")
        _physical_root(session, root)


def _scope(session: Session) -> SessionTransaction | None:
    return session.get_nested_transaction() or session.get_transaction()


def _discard(queue: _Queue, scope: SessionTransaction) -> None:
    for candidate in list(queue.items):
        ancestor = candidate
        while ancestor is not None and ancestor is not scope:
            ancestor = ancestor.parent
        if ancestor is scope:
            queue.items.pop(candidate, None)
            queue.successful.discard(candidate)
    queue.successful.discard(scope)


def _after_begin(session: Session, transaction: SessionTransaction, connection) -> None:
    queue = session.info.get(_STATE)
    if queue is not None:
        queue.physical_root = _physical_root(session, queue.root)


def _before_commit(session: Session) -> None:
    queue = session.info.get(_STATE)
    if queue is not None:
        _physical_root(session, queue.root)


def _after_commit(session: Session) -> None:
    queue = session.info.get(_STATE)
    if queue is not None:
        scope = _scope(session)
        if scope is not None:
            queue.successful.add(scope)


def _after_rollback(session: Session) -> None:
    queue = session.info.get(_STATE)
    scope = _scope(session)
    if queue is not None and scope is not None:
        _discard(queue, scope)


def _after_soft_rollback(session: Session, previous_transaction: SessionTransaction) -> None:
    queue = session.info.get(_STATE)
    if queue is not None:
        _discard(queue, previous_transaction)


def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    queue = session.info.get(_STATE)
    if queue is None:
        return
    if transaction is queue.root:
        # Detach before any callback, including a reentrant new transaction.
        session.info.pop(_STATE, None)
        batch = tuple(sorted(queue.items.get(transaction, ()))) if (
            transaction in queue.successful and queue.physical_root) else ()
        queue.items.clear()
        queue.successful.clear()
        for _, payload in batch:
            try:
                from app.services.notify import dispatch_async
                dispatch_async(payload.company_id, payload.action,
                               who=payload.who, details=payload.details)
            except Exception:  # Scheduling cannot turn a committed command into an error.
                logger.exception("Audit notification scheduling failed after root commit")
        return
    if not transaction.nested:
        return  # Flush-created SessionTransaction is not a commit boundary.
    if transaction in queue.successful:
        parent = transaction.parent
        while parent is not None and parent is not queue.root and not parent.nested:
            parent = parent.parent
        if parent is not None:
            queue.items.setdefault(parent, []).extend(queue.items.pop(transaction, ()))
        queue.successful.discard(transaction)
    else:
        _discard(queue, transaction)


def enqueue_audit_notification(
    db: AsyncSession, *, company_id: UUID, action: str,
    who: str | None, details: str | None,
) -> None:
    """Snapshot four immutable values in the current root/SAVEPOINT scope.

    AuditEvent add/autobegin belongs to log_audit. No commit, rollback, begin,
    connection acquisition, ORM reads or recipient lookup happens here.
    """
    validate_audit_notification_session(db)
    if (type(company_id) is not UUID or type(action) is not str
            or (who is not None and type(who) is not str)
            or (details is not None and type(details) is not str)):
        raise TypeError("audit notification payload must contain immutable UUID/text values")
    session = db.sync_session
    root = session.get_transaction()
    scope = _scope(session)
    if root is None or scope is None:
        raise ValueError("AuditEvent must establish the caller root before enqueue")
    if not getattr(session, _INSTALLED, False):
        for name, listener in (
            ("after_begin", _after_begin), ("before_commit", _before_commit),
            ("after_commit", _after_commit), ("after_rollback", _after_rollback),
            ("after_soft_rollback", _after_soft_rollback),
            ("after_transaction_end", _after_transaction_end),
        ):
            event.listen(session, name, listener)
        setattr(session, _INSTALLED, True)
    queue = session.info.get(_STATE)
    if queue is None:
        queue = _Queue(root=root, physical_root=_physical_root(session, root))
        session.info[_STATE] = queue
    if queue.root is not root:
        raise ValueError("audit queue root identity changed without transaction end")
    queue.items.setdefault(scope, []).append((queue.sequence, AuditNotification(
        company_id=company_id, action=action, who=who, details=details)))
    queue.sequence += 1
