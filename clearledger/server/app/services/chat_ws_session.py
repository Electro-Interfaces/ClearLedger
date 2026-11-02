"""Native chat session proofs. No router imports, retained ORM sessions or raw JWTs."""
from __future__ import annotations

import asyncio
import contextvars
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app import auth
from app.database import async_session_factory
from app.deps import capture_company_header, scope_company_id
from app.models import ChatRoom, Company, User, UserCompany
from app.services import chat_access

# Operational targets accepted by ROOT, not token/session TTLs.
CHECK_CADENCE = 20.0
CHECK_TIMEOUT = 5.0
SEND_TIMEOUT = 5.0
DRAIN_TIMEOUT = 5.0
ParticipantCheck = Callable[[User, str, object], Awaitable[bool]]


def wall_time() -> float:
    return datetime.now(timezone.utc).timestamp()


def monotonic() -> float:
    return time.monotonic()


class SessionDenied(Exception):
    """Only fixed public reasons cross the socket boundary."""

    def __init__(self, reason: str = "session_revoked", code: int = 1008, *, cleanup_failed: bool = False):
        if (code, reason) not in {
            (1008, "session_revoked"), (1008, "session_expired"),
            (1008, "access_changed"), (1013, "temporarily_unavailable"),
        }:
            raise ValueError("Unknown native chat close decision")
        self.code, self.reason = code, reason
        self.cleanup_failed = cleanup_failed
        super().__init__(reason)


@dataclass(frozen=True)
class NativeWsSession:
    user_id: uuid.UUID
    token_version: int
    auth_time: float | None
    expires_at: float
    visit_company: str | None
    visit_partner: str | None
    selector: uuid.UUID | None
    company_id: uuid.UUID | None
    monotonic_expiry: float
    monotonic_horizon: float | None

    @classmethod
    def from_claims(cls, payload: dict, selector: str | None = None) -> NativeWsSession:
        try:
            # Native token_for has neither a payload typ nor token_use. These
            # belong to console/SSO/OAuth authorities, not a native chat login.
            if payload.get("typ") or payload.get("token_use"):
                raise ValueError()
            expiry = payload["exp"]
            if type(expiry) not in (int, float) or not math.isfinite(expiry):
                raise ValueError()
            raw_version = payload.get("tv")
            if raw_version is not None and not isinstance(raw_version, (int, float, str)):
                raise ValueError()
            version = int(raw_version or 0)
            at = payload.get("at")
            at = float(at) if at is not None else None
            if at is not None and not math.isfinite(at):
                raise ValueError()
            scoped = payload.get("scp")
            if scoped and scoped != auth.VISIT_SCOPE:
                raise ValueError()
            cid = str(uuid.UUID(str(payload.get("cid")))) if scoped else None
            pid = str(uuid.UUID(str(payload.get("pvs")))) if scoped else None
            # None means omitted; supplied blank is never an omitted selector.
            try:
                selected = uuid.UUID(selector) if selector is not None else None
            except (ValueError, TypeError, AttributeError):
                raise SessionDenied("access_changed") from None
            now, tick = wall_time(), monotonic()
            session = cls(uuid.UUID(payload["sub"]), version, at, float(expiry),
                          cid, pid, selected, None, tick + max(0.0, expiry - now),
                          tick + max(0.0, at + auth.MAX_SESSION_DAYS * 86400 - now)
                          if at is not None else None)
            session.require_live()
            return session
        except SessionDenied:
            raise
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise SessionDenied() from None

    def claims(self) -> dict:
        value = {"sub": str(self.user_id), "tv": self.token_version, "exp": self.expires_at}
        if self.auth_time is not None:
            value["at"] = self.auth_time
        if self.visit_company is not None:
            value.update(scp=auth.VISIT_SCOPE, cid=self.visit_company, pvs=self.visit_partner)
        return value

    def require_live(self) -> None:
        now, tick = wall_time(), monotonic()
        if now >= self.expires_at or tick >= self.monotonic_expiry:
            raise SessionDenied("session_expired")
        # The native at ceiling is strictly >, unlike exp's >= boundary.
        if self.auth_time is not None and (
            now - self.auth_time > auth.MAX_SESSION_DAYS * 86400
            or tick > self.monotonic_horizon
        ):
            raise SessionDenied("session_expired")

    def expiry_delay(self) -> float:
        ends = [self.monotonic_expiry]
        if self.monotonic_horizon is not None:
            ends.append(self.monotonic_horizon)
        return max(0.001, min(ends) - monotonic())

    def next_delay(self, checked_at: float) -> float:
        ends = [self.monotonic_expiry, checked_at + CHECK_CADENCE]
        if self.monotonic_horizon is not None:
            ends.append(self.monotonic_horizon)
        return max(0.001, min(ends) - monotonic())


@dataclass(frozen=True)
class NativeWsProof:
    user_id: uuid.UUID
    user_name: str
    company_id: uuid.UUID | None
    allowed: frozenset[str]
    checked_at: float


class DbCleanupFailed(RuntimeError):
    """No successful proof/drain may be reported after failed public close."""


@asynccontextmanager
async def managed_db(factory):
    """Close on this tracked task, not AsyncSession.__aexit__'s detached shield task."""
    db = factory()
    try:
        yield db
    finally:
        try:
            async with asyncio.timeout(DRAIN_TIMEOUT):
                await db.close()
        except (Exception, asyncio.CancelledError):
            raise DbCleanupFailed("Native database cleanup incomplete") from None


async def _tenant(user: User, db, session: NativeWsSession) -> uuid.UUID | None:
    try:
        if session.selector is not None:
            cid = await scope_company_id(user, db)
        elif auth.visit_company() is not None or user.company_id is not None:
            cid = await scope_company_id(user, db)
        else:
            # HTTP keeps its 400 for zero/multiple membership. Only this WS
            # adapter preserves the personal/direct stream without a tenant.
            members = list(await db.scalars(select(UserCompany.company_id).where(
                UserCompany.user_id == user.id)))
            if len(members) != 1:
                return None
            cid = await scope_company_id(user, db)
        if await db.get(Company, cid) is None:
            raise SessionDenied("access_changed")
        # scope_company_id's historical primary fallback is not live authority.
        await auth.assert_company_member(str(cid), user, db)
        return cid
    except HTTPException:
        raise SessionDenied("access_changed") from None


async def _channel(user: User, channel: str, tenant: uuid.UUID | None, db,
                   checker: ParticipantCheck | None = None) -> bool:
    if user.is_superadmin and not channel.startswith("chat:"):
        return True
    if channel == f"user:{user.id}":
        return True
    if channel.startswith("company:"):
        return tenant is not None and channel == f"company:{tenant}"
    if not channel.startswith("chat:"):
        return False
    try:
        room_id = uuid.UUID(channel[5:])
    except (ValueError, TypeError):
        return False
    try:
        if checker is not None:
            return await checker(user, channel, db)
        await chat_access.participant_eligibility(room_id, user, db)
        return True
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        return False


async def _check(session: NativeWsSession, channels: frozenset[str], *, initial: bool,
                 explicit_channel: str | None, checker: ParticipantCheck | None) -> NativeWsProof:
    try:
        session.require_live()
        async with managed_db(async_session_factory) as db:
            async with asyncio.timeout(CHECK_TIMEOUT):
                with db.no_autoflush:
                    payload = session.claims()
                    user = await auth.native_user_from_claims(payload, db)
                    visit = await auth.native_visit_from_claims(payload, user, db)
                    with auth.native_claims_context(payload, visit):
                        await capture_company_header(str(session.selector) if session.selector is not None else None)
                        tenant = await _tenant(user, db, session)
                        if not initial and tenant != session.company_id:
                            raise SessionDenied("access_changed")
                        # Bind all nested room/subject helpers to the resolved tenant.
                        await capture_company_header(str(tenant) if tenant is not None else None)
                        if initial:
                            channels = channels | {f"user:{user.id}"}
                            if tenant is not None:
                                channels = channels | {f"company:{tenant}"}
                        allowed = set()
                        for channel in sorted(channels):
                            session.require_live()
                            if await _channel(user, channel, tenant, db,
                                              checker if channel == explicit_channel else None):
                                allowed.add(channel)
                        # Revalidate native identity after potentially slow subject ACL.
                        db.expire_all()
                        user = await auth.native_user_from_claims(payload, db)
                        await auth.native_visit_from_claims(payload, user, db)
                        if await _tenant(user, db, session) != tenant:
                            raise SessionDenied("access_changed")
                        proof = NativeWsProof(user.id, user.name, tenant, frozenset(allowed), monotonic())
        session.require_live()  # session/transaction already closed before send
        return proof
    except DbCleanupFailed:
        raise SessionDenied("temporarily_unavailable", 1013, cleanup_failed=True) from None
    except SessionDenied:
        raise
    except HTTPException as exc:
        session.require_live()
        raise SessionDenied("session_revoked" if exc.status_code == 401 else "temporarily_unavailable",
                            1008 if exc.status_code == 401 else 1013) from None
    except (ValueError, TypeError, OverflowError):
        raise SessionDenied("temporarily_unavailable", 1013) from None
    except Exception:
        raise SessionDenied("temporarily_unavailable", 1013) from None


def start_check(session: NativeWsSession, channels: Iterable[str] = (), *, initial: bool = False,
                explicit_channel: str | None = None,
                checker: ParticipantCheck | None = None) -> asyncio.Task[NativeWsProof]:
    """A check's ContextVars cannot escape to its publisher or another socket."""
    return asyncio.create_task(_check(session, frozenset(channels), initial=initial,
                                      explicit_channel=explicit_channel, checker=checker),
                               context=contextvars.Context())


async def _delivery(session: NativeWsSession, room_id: uuid.UUID, payload: dict) -> bool:
    """A room payload needs recipient authority, including on a personal stream."""
    from app.services.ticket_communications import delivery_allowed_in_session
    try:
        session.require_live()
        async with managed_db(async_session_factory) as db:
            async with asyncio.timeout(CHECK_TIMEOUT):
                with db.no_autoflush:
                    claims = session.claims()
                    user = await auth.native_user_from_claims(claims, db)
                    visit = await auth.native_visit_from_claims(claims, user, db)
                    with auth.native_claims_context(claims, visit):
                        await capture_company_header(str(session.selector) if session.selector is not None else None)
                        tenant = await _tenant(user, db, session)
                        if tenant != session.company_id:
                            raise SessionDenied("access_changed")
                        await capture_company_header(str(tenant) if tenant is not None else None)
                        room = await db.get(ChatRoom, room_id)
                        if room is None or not room.is_active:
                            return False
                        if room.company_id is not None and room.type != "direct" and room.company_id != tenant:
                            return False
                        ordinary = room.scope_task_id is None and room.scope_ticket_id is None
                        if ordinary:
                            await chat_access.participant_eligibility(room_id, user, db)
                        # Subject owner ACL and ticket history stay authoritative,
                        # on this same owned session. No duplicate subject ACL probe.
                        if not await delivery_allowed_in_session(db, f"chat:{room_id}", payload, str(user.id)):
                            return False
                        db.expire_all()
                        user = await auth.native_user_from_claims(claims, db)
                        await auth.native_visit_from_claims(claims, user, db)
                        if await _tenant(user, db, session) != tenant:
                            raise SessionDenied("access_changed")
                        if ordinary:
                            await chat_access.participant_eligibility(room_id, user, db)
        session.require_live()
        return True
    except DbCleanupFailed:
        raise SessionDenied("temporarily_unavailable", 1013, cleanup_failed=True) from None
    except SessionDenied:
        raise
    except HTTPException as exc:
        session.require_live()
        if exc.status_code in (403, 404):
            return False
        raise SessionDenied("session_revoked" if exc.status_code == 401 else "temporarily_unavailable",
                            1008 if exc.status_code == 401 else 1013) from None
    except Exception:
        raise SessionDenied("temporarily_unavailable", 1013) from None


def start_delivery(session: NativeWsSession, channel: str, payload: dict) -> asyncio.Task[bool] | bool:
    from app.services.ticket_communications import delivery_room_reference
    recognized, room_id = delivery_room_reference(channel, payload)
    if room_id is None:
        # Preserve legacy helper opaque compatibility, but recognized WS room
        # messages never use a malformed/missing room reference as an allow.
        return not recognized and payload.get("roomId") is None
    return asyncio.create_task(_delivery(session, room_id, payload), context=contextvars.Context())


async def open_session(payload: dict, selector: str | None = None) -> tuple[NativeWsSession, NativeWsProof]:
    """Run inline on the manager's tracked, fresh-Context admission owner task."""
    session = NativeWsSession.from_claims(payload, selector)
    proof = await _check(session, frozenset(), initial=True, explicit_channel=None, checker=None)
    return replace(session, company_id=proof.company_id), proof
