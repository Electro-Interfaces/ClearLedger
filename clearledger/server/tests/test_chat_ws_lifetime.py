"""ROOT-only native WS/PG characterization; FakeSocket cases are not TCP wire proof."""
import os

if os.environ.get("RUN_CHAT_WS_LIFETIME_TESTS") != "1":
    raise RuntimeError("ROOT-approved chat WS lifetime runner required")

import asyncio
import contextvars
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import QueryParams

from app import auth, database
from app.deps import capture_company_header, scope_company_id
from app.models import (Company, CompanyRole, User, UserCompany, ChatRoom,
                        ChatParticipant, ChatMessage, PartnerSpace, Task, TaskParticipant, TaskWatcher)
from app.routers import chat_router
from app.services import chat_ws, chat_ws_session as policy, ticket_communications

pytestmark = pytest.mark.asyncio(loop_scope="session")


class FakeSocket:
    """Explicitly a transport fixture; every session still uses real JWT/PG."""
    def __init__(self):
        self.messages = []
        self.received = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_args = None
        self.accepted = False
        self.query_params = QueryParams()

    async def accept(self):
        self.accepted = True

    async def send_json(self, value):
        self.messages.append(value)
        self.received.set()

    async def close(self, code=1000, reason=""):
        self.close_args = (code, reason)
        self.closed.set()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def native_database():
    from urllib.parse import urlsplit
    raw = os.environ["TEST_DATABASE_URL"]
    target = urlsplit(raw)
    if (raw != os.environ.get("DATABASE_URL") or target.hostname != "127.0.0.1"
            or target.port != 33547 or target.path != "/api_chat_ws_lifetime_test_20261031"):
        raise RuntimeError("Dedicated ROOT synthetic native WS database required")
    engine = create_async_engine(raw, pool_size=2, max_overflow=0,
                                 connect_args={"server_settings": {"statement_timeout": "20000",
                                     "lock_timeout": "2000", "idle_in_transaction_session_timeout": "30000"}})
    # Only the transitive ORM FK closure used by native WS; no startup/seed/jobs.
    roots = [Company, CompanyRole, User, UserCompany, ChatRoom, ChatParticipant,
             PartnerSpace, Task, TaskParticipant, TaskWatcher, ChatMessage]
    tables = set()
    def visit(table):
        if table in tables:
            return
        tables.add(table)
        for fk in table.foreign_keys:
            visit(fk.column.table)
    for model in roots:
        visit(model.__table__)
    async with engine.begin() as conn:
        # Existing native User computed columns require the existing canonical
        # function, even in this minimal ORM closure. No startup/migrations/seed.
        from app.services.phone_e164 import PHONE_FUNCTION_DDL
        await conn.execute(text(PHONE_FUNCTION_DDL))
        await conn.run_sync(lambda sync: database.Base.metadata.create_all(sync, tables=list(tables)))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def native_world(native_database, monkeypatch):
    engine, factory = native_database
    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(policy, "async_session_factory", factory)
    monkeypatch.setattr(chat_ws, "async_session_factory", factory)
    async with factory() as db:
        a, b = [Company(id=uuid.uuid4(), name="Synthetic WS", slug=f"ws-{uuid.uuid4().hex}",
                        profile_id="energy") for _ in range(2)]
        db.add_all([a, b])
        await db.flush()
        users = [User(id=uuid.uuid4(), name=f"Synthetic WS {i}", email=f"ws-{uuid.uuid4().hex}@example.test",
                      password_hash="!synthetic", company_id=a.id, token_version=0, is_superadmin=False)
                 for i in range(2)]
        db.add_all(users)
        await db.flush()
        for u in users:
            db.add(UserCompany(user_id=u.id, company_id=a.id, role="user", modules=["docs"]))
        room = ChatRoom(id=uuid.uuid4(), company_id=a.id, type="group", name="Synthetic room",
                        created_by=users[0].id, is_active=True)
        db.add(room)
        await db.flush()
        db.add_all([ChatParticipant(room_id=room.id, user_id=u.id, role="member") for u in users])
        await db.commit()
    managers = [chat_ws.ChatConnectionManager()]
    monkeypatch.setattr(chat_router, "manager", managers[0])
    async def connect(manager, socket, actor=None, selector=None, **token_kw):
        actor = actor or users[0]
        token = auth.token_for(actor, **token_kw)
        if manager not in managers:
            managers.append(manager)
        identity, proof = await manager.admit(auth.decode_token(token),
            str(a.id) if selector is None else selector)
        socket.became_online = await manager.connect(socket, str(actor.id), str(proof.company_id) if proof.company_id else None,
                              session=identity, proof=proof)
        return identity, proof
    world = SimpleNamespace(engine=engine, factory=factory, a=a, b=b, user=users[0], other=users[1],
                            room=room, channel=f"chat:{room.id}", connect=connect, managers=managers)
    yield world
    for manager in managers:
        await manager.stop()
    assert all(not t for m in managers for t in (*m._owned_tasks, *m._delivery_tasks) if not t.done())


async def admit(world, payload, selector=None):
    manager = chat_ws.ChatConnectionManager()
    world.managers.append(manager)
    return await manager.admit(payload, selector)


async def issue(world, *, actor=None, selector=None, **kwargs):
    actor = actor or world.user
    return await admit(world, auth.decode_token(auth.token_for(actor, **kwargs)), selector)


def cleanup_update_barrier(world, monkeypatch):
    """Pause only AFTER the manager's actual PG UPDATE, before commit/return."""
    entered, release = asyncio.Event(), asyncio.Event()
    class RealCleanupSession:
        def __init__(self): self.db = world.factory()
        def __getattr__(self, name): return getattr(self.db, name)
        async def execute(self, statement, *args, **kwargs):
            result = await self.db.execute(statement, *args, **kwargs)
            if str(statement).startswith("UPDATE users SET last_seen_at"):
                entered.set()
                await release.wait()
            return result
        async def close(self): await self.db.close()
    monkeypatch.setattr(chat_ws, "async_session_factory", RealCleanupSession)
    return entered, release


async def join_late_cleanup(manager, socket, entered, release):
    late = []
    try:
        await asyncio.wait_for(entered.wait(), policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 1)
        owner = manager._closing[socket]
        assert socket not in manager._sessions and not owner.done()
        late = [asyncio.create_task(manager.close(socket), name=f"ws-test-late-close-{i}") for i in range(2)]
        # Drain ready callbacks/no-op paths without adding a wall-time allowance;
        # the real UPDATE transaction remains held by release inside DRAIN5.
        for _ in range(6): await asyncio.sleep(0)
        assert manager._closing[socket] is owner and not owner.done()
        assert all(not waiter.done() for waiter in late)
    finally:
        release.set()
        if late: await asyncio.gather(*late)  # real owner errors remain failures
    assert owner.done() and socket not in manager._closing
    assert not [task for task in manager._owned_tasks
                if task.get_name() == "chat-ws-cleanup" and not task.done()]


async def test_signed_native_handshake_and_guarded_frames(native_world, monkeypatch):
    world = native_world
    manager = chat_ws.ChatConnectionManager()
    world.managers.append(manager)
    monkeypatch.setattr(chat_router, "manager", manager)
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api")
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    async def send(event):
        await outgoing.put(event)
        if event["type"] == "websocket.close":
            await incoming.put({"type": "websocket.disconnect", "code": event["code"]})
    token = auth.token_for(world.user)
    scope = {"type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.5"},
             "scheme": "ws", "path": "/api/chat/ws", "raw_path": b"/api/chat/ws",
             "query_string": f"token={token}&company_id={world.a.id}".encode(), "headers": [],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2), "subprotocols": []}
    task = asyncio.create_task(app(scope, incoming.get, send), context=contextvars.Context())
    try:
        assert (await asyncio.wait_for(outgoing.get(), 5))["type"] == "websocket.accept"
        connected = await asyncio.wait_for(outgoing.get(), 5)
        import json
        assert json.loads(connected["text"]) == {"type": "connected", "userId": str(world.user.id)}
        await incoming.put({"type": "websocket.receive", "text": '{"type":"ping"}'})
        # A normal own-company presence frame may precede the pong.
        for _ in range(3):
            event = await asyncio.wait_for(outgoing.get(), 5)
            if json.loads(event["text"])["type"] == "pong":
                break
        else:
            pytest.fail("No guarded pong")
    finally:
        await incoming.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(task, 5)
    assert manager._sessions == {} and manager._meta == {}


@pytest.mark.parametrize("change", ["missing-exp", "string-exp", "nan-exp", "inf-exp", "bool-exp",
    "foreign-typ", "foreign-use", "bad-tv", "nan-at", "inf-at", "unknown-scp", "bad-sub", "blank-selector"])
async def test_native_shape_denials_are_fixed(native_world, change):
    payload = auth.decode_token(auth.token_for(native_world.user))
    selector = None
    values = {"string-exp": "later", "nan-exp": float("nan"), "inf-exp": float("inf"), "bool-exp": True}
    if change == "missing-exp": payload.pop("exp")
    elif change in values: payload["exp"] = values[change]
    elif change == "foreign-typ": payload["typ"] = "station_console"
    elif change == "foreign-use": payload["token_use"] = "partner_access"
    elif change == "bad-tv": payload["tv"] = "not-an-integer"
    elif change == "nan-at": payload["at"] = float("nan")
    elif change == "inf-at": payload["at"] = float("inf")
    elif change == "unknown-scp": payload["scp"] = "foreign"
    elif change == "bad-sub": payload["sub"] = "not-uuid"
    else: selector = ""
    with pytest.raises(policy.SessionDenied) as exc:
        await admit(native_world, payload, selector)
    assert (exc.value.code, exc.value.reason) == (1008, "access_changed" if change == "blank-selector" else "session_revoked")


@pytest.mark.parametrize("kind", ["legacy", "mail-only", "no-password", "locked-login"])
async def test_native_current_rules_have_no_new_disable_policy(native_world, kind):
    world = native_world
    async with world.factory() as db:
        u = await db.get(User, world.user.id)
        if kind == "mail-only": u.mail_only = True
        if kind == "no-password": u.password_hash = ""
        if kind == "locked-login": u.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()
    payload = auth.decode_token(auth.token_for(world.user))
    if kind == "legacy":
        payload.pop("tv"); payload.pop("at")
    session, proof = await admit(native_world, payload)
    assert proof.user_id == world.user.id and session.company_id == world.a.id


@pytest.mark.parametrize("kind", ["explicit-own", "explicit-foreign", "explicit-missing", "explicit-blank",
    "primary", "primary-revoked", "sole", "zero", "multiple", "superadmin"])
async def test_tenant_truth_table(native_world, kind):
    w = native_world
    selector = None
    async with w.factory() as db:
        u = await db.get(User, w.user.id)
        if kind in {"sole", "zero", "multiple"}: u.company_id = None
        if kind in {"primary-revoked", "zero"}:
            await db.delete(await db.get(UserCompany, (u.id, w.a.id)))
        if kind == "multiple": db.add(UserCompany(user_id=u.id, company_id=w.b.id, role="user"))
        if kind == "superadmin": u.is_superadmin = True
        await db.commit()
    if kind == "explicit-own": selector = str(w.a.id)
    if kind == "explicit-foreign": selector = str(w.b.id)
    if kind == "explicit-missing": selector = str(uuid.uuid4())
    if kind == "explicit-blank": selector = ""
    if kind in {"explicit-foreign", "explicit-missing", "explicit-blank", "primary-revoked"}:
        with pytest.raises(policy.SessionDenied): await issue(w, selector=selector)
    else:
        session, proof = await issue(w, selector=selector)
        assert proof.company_id == (None if kind in {"zero", "multiple"} else w.a.id)
        assert session.company_id == proof.company_id


@pytest.mark.parametrize("mutation", ["tv", "user-delete", "membership", "primary"])
async def test_current_identity_revalidation(native_world, mutation):
    w = native_world
    session, _ = await issue(w)
    async with w.factory() as db:
        u = await db.get(User, w.user.id)
        if mutation == "tv": u.token_version += 1
        elif mutation == "user-delete":
            # This fixture's participant/user references must be removed first.
            await db.delete(await db.scalar(select(ChatParticipant).where(
                ChatParticipant.user_id == u.id, ChatParticipant.room_id == w.room.id)))
            room = await db.get(ChatRoom, w.room.id)
            room.created_by = w.other.id
            await db.delete(await db.get(UserCompany, (u.id, w.a.id)))
            await db.flush(); await db.delete(u)
        elif mutation == "membership": await db.delete(await db.get(UserCompany, (u.id, w.a.id)))
        elif mutation == "primary": u.company_id = w.b.id
        await db.commit()
    with pytest.raises(policy.SessionDenied) as exc:
        await policy.start_check(session)
    assert exc.value.reason == ("session_revoked" if mutation in {"tv", "user-delete"} else "access_changed")


@pytest.mark.parametrize("mutation", ["participant", "inactive", "chat-scope"])
async def test_ordinary_room_revocation_uses_current_owner(native_world, mutation):
    w = native_world
    session, _ = await issue(w)
    assert w.channel in (await policy.start_check(session, [w.channel])).allowed
    async with w.factory() as db:
        if mutation == "participant":
            await db.delete(await db.scalar(select(ChatParticipant).where(
                ChatParticipant.user_id == w.user.id, ChatParticipant.room_id == w.room.id)))
        elif mutation == "inactive": (await db.get(ChatRoom, w.room.id)).is_active = False
        else:
            role = CompanyRole(id=uuid.uuid4(), company_id=w.a.id, name="Synthetic scoped", chat_scope="support")
            db.add(role); await db.flush()
            (await db.get(UserCompany, (w.user.id, w.a.id))).role_id = role.id
        await db.commit()
    assert w.channel not in (await policy.start_check(session, [w.channel])).allowed


async def test_pure_probe_has_no_foreign_audit_explicit_entry_keeps_hooks(native_world, monkeypatch):
    w = native_world
    called = []
    async def audit(*args): called.append("audit")
    monkeypatch.setattr(chat_router, "_audit_foreign_access", audit)
    async with w.factory() as db:
        (await db.get(User, w.user.id)).is_superadmin = True
        await db.delete(await db.scalar(select(ChatParticipant).where(
            ChatParticipant.user_id == w.user.id, ChatParticipant.room_id == w.room.id)))
        await db.commit()
    session, _ = await issue(w)
    assert w.channel in (await policy.start_check(session, [w.channel])).allowed
    assert called == []
    assert w.channel in (await policy.start_check(session, [w.channel], explicit_channel=w.channel,
                                                  checker=chat_router._ws_can_subscribe)).allowed
    assert called == ["audit"]


@pytest.mark.parametrize("jump", ["forward", "backward-monotonic"])
async def test_local_deadline_clock_guards(native_world, monkeypatch, jump):
    session, _ = await issue(native_world)
    if jump == "forward": monkeypatch.setattr(policy, "wall_time", lambda: session.expires_at + 1)
    else:
        monkeypatch.setattr(policy, "wall_time", lambda: session.expires_at - 3600)
        monkeypatch.setattr(policy, "monotonic", lambda: session.monotonic_expiry + 1)
    with pytest.raises(policy.SessionDenied) as exc: session.require_live()
    assert (exc.value.code, exc.value.reason) == (1008, "session_expired")


async def test_contexts_are_isolated_and_restored(native_world):
    from app.scope import (current_object_scope, current_organization,
                           set_request_scope, set_request_organization)
    w = native_world
    async with w.factory() as db:
        db.add(UserCompany(user_id=w.user.id, company_id=w.b.id, role="user"))
        await db.commit()
    await capture_company_header(str(w.b.id))
    old_objects, old_org = current_object_scope(), current_organization()
    sentinel_org = uuid.uuid4()
    set_request_scope(["parent-object"])
    set_request_organization(sentinel_org)
    try:
        with auth.native_claims_context({"sub": "parent-only"}, w.b.id):
            session, proof = await issue(w, selector=str(w.a.id))
            results = await asyncio.gather(*(policy.start_check(session, [w.channel]) for _ in range(3)))
            assert all(p.company_id == w.a.id for p in results)
            assert auth.visit_company() == w.b.id
            assert auth.current_token_claims() == {"sub": "parent-only"}
            assert current_object_scope() == ["parent-object"]
            assert current_organization() == sentinel_org
            async with w.factory() as db:
                assert await scope_company_id(w.user, db) == w.b.id
    finally:
        await capture_company_header(None)
        set_request_scope(old_objects)
        set_request_organization(old_org)
    assert auth.current_token_claims() is None and auth.visit_company() is None


async def test_coalesced_current_proofs(native_world, monkeypatch):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    entered, release = asyncio.Event(), asyncio.Event()
    original = auth.native_user_from_claims
    calls = []
    async def paused(*args):
        calls.append(1); entered.set(); await release.wait()
        return await original(*args)
    monkeypatch.setattr(auth, "native_user_from_claims", paused)
    # Force a real due check, not an injected allow result.
    from dataclasses import replace
    state = manager._sessions[socket]
    state.proof = replace(state.proof, checked_at=policy.monotonic() - policy.CHECK_CADENCE)
    waiters = [asyncio.create_task(manager.current(socket)) for _ in range(3)]
    await asyncio.wait_for(entered.wait(), 5); release.set()
    await asyncio.gather(*waiters)
    assert len(calls) == 2  # initial current User plus final revalidation in ONE check


async def test_idle_signed_expiry_closes_and_reaps(native_world):
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await native_world.connect(manager, socket,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=2))
    await asyncio.wait_for(socket.closed.wait(), 5)
    assert socket.close_args == (1008, "session_expired")
    assert manager._meta == {} and manager._sessions == {}


async def test_missing_manager_authority_is_fail_closed(native_world):
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    with pytest.raises(policy.SessionDenied): manager.subscribe(socket, native_world.channel)
    assert not await manager.send(socket, {"type": "pong"})


async def test_unsubscribe_during_guarded_send(native_world, monkeypatch):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    await manager.subscribe_current(socket, w.channel, chat_router._ws_can_subscribe)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ticket_communications.delivery_allowed_in_session
    async def paused(*args):
        entered.set(); await release.wait(); return await original(*args)
    monkeypatch.setattr(ticket_communications, "delivery_allowed_in_session", paused)
    task = asyncio.create_task(manager._broadcast_local(w.channel, {"type": "chat:message"}))
    await asyncio.wait_for(entered.wait(), 5); manager.unsubscribe(socket, w.channel); release.set(); await task
    assert socket.messages == []


async def test_cancel_check_and_terminal_stop(native_world, monkeypatch):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    entered = asyncio.Event()
    original = auth.native_user_from_claims
    async def paused(*args):
        entered.set(); await asyncio.Event().wait(); return await original(*args)
    monkeypatch.setattr(auth, "native_user_from_claims", paused)
    task = asyncio.create_task(manager.subscribe_current(socket, w.channel, chat_router._ws_can_subscribe))
    await asyncio.wait_for(entered.wait(), 5); await manager.stop()
    await asyncio.gather(task, return_exceptions=True)
    assert manager._sessions == {} and manager._meta == {}
    assert socket.close_args == (1001, "server_shutdown")
    assert not await manager.send(socket, {"type": "pong"})


async def test_transient_database_failure_is_not_revoke(native_world, monkeypatch):
    session, _ = await issue(native_world)
    async def fail(*args): raise RuntimeError("synthetic private database detail")
    monkeypatch.setattr(auth, "native_user_from_claims", fail)
    with pytest.raises(policy.SessionDenied) as exc: await policy.start_check(session)
    assert (exc.value.code, exc.value.reason) == (1013, "temporarily_unavailable")
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("kind", ["bad-signature", "expired", "foreign-console", "bad-tv", "bad-at",
    "nan-exp", "inf-exp", "bad-exp", "missing-exp", "nan-iat", "inf-iat", "bad-iat",
    "nan-nbf", "inf-nbf", "bad-nbf", "nan-at", "inf-at", "nan-tv", "inf-tv",
    "container-tv", "container-at"])
async def test_signed_token_boundary(native_world, kind):
    w = native_world
    extra = {"typ": "station_console"} if kind == "foreign-console" else (
        {"tv": "malformed"} if kind == "bad-tv" else {"at": "malformed"} if kind == "bad-at" else {})
    if kind in {"nan-exp", "inf-exp", "bad-exp"}:
        extra["exp"] = {"nan-exp": float("nan"), "inf-exp": float("inf"), "bad-exp": "malformed"}[kind]
    if "-" in kind:
        shape, field = kind.split("-", 1)
        if field in {"iat", "nbf", "at", "tv"} and shape in {"nan", "inf", "container", "bad"}:
            extra[field] = {"nan": float("nan"), "inf": float("inf"), "container": {}, "bad": "malformed"}[shape]
    token = auth.token_for(w.user, extra=extra,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=-1 if kind == "expired" else 60))
    if kind == "missing-exp":
        payload = auth.decode_token(token)
        payload.pop("exp")
        token = auth.jwt.encode(payload, auth.settings.secret_key, algorithm=auth.settings.algorithm)
    if kind == "bad-signature":
        head, body, signature = token.split(".")
        token = head + "." + body + "." + ("B" if signature[0] != "B" else "A") + signature[1:]
    with pytest.raises(policy.SessionDenied) as exc:
        await chat_router._ws_user(token)
    assert exc.value.code == 1008
    assert exc.value.reason == ("session_expired" if kind == "expired" else "session_revoked")


async def test_selected_company_deleted_after_handshake(native_world):
    w = native_world
    async with w.factory() as db:
        u = await db.get(User, w.user.id)
        u.is_superadmin = True
        c = Company(id=uuid.uuid4(), name="Synthetic removable", slug=f"ws-{uuid.uuid4().hex}", profile_id="energy")
        db.add(c); await db.commit()
    session, _ = await issue(w, selector=str(c.id))
    async with w.factory() as db:
        # Exercise an actual DB deletion without ORM reverse-relationship loads
        # of unrelated tables outside this intentionally minimal fixture schema.
        await db.execute(delete(Company).where(Company.id == c.id))
        await db.commit()
        assert await db.get(Company, c.id) is None
    with pytest.raises(policy.SessionDenied) as exc:
        await policy.start_check(session)
    assert (exc.value.code, exc.value.reason) == (1008, "access_changed")


@pytest.mark.parametrize("mode", ["visit", "revoke-partner", "other-company", "superadmin-visit"])
async def test_visit_priority_and_live_connection(native_world, mode):
    w = native_world
    async with w.factory() as db:
        db.add(UserCompany(user_id=w.user.id, company_id=w.b.id, role="user"))
        partner = PartnerSpace(id=uuid.uuid4(), company_id=w.b.id, role="vendor",
                               code=f"vendor-{uuid.uuid4().hex[:8]}", is_active=True)
        db.add(partner)
        if mode == "superadmin-visit": (await db.get(User, w.user.id)).is_superadmin = True
        await db.commit()
    token = auth.token_for(w.user, extra={"scp": "visit", "cid": str(w.b.id), "pvs": str(partner.id)})
    if mode in {"other-company", "superadmin-visit"}:
        with pytest.raises(policy.SessionDenied):
            await chat_router._ws_user(token, str(w.a.id) if mode == "other-company" else None)
    else:
        session, proof = await chat_router._ws_user(token)
        assert proof.company_id == w.b.id and session.company_id == w.b.id
        if mode == "revoke-partner":
            async with w.factory() as db:
                (await db.get(PartnerSpace, partner.id)).is_active = False
                await db.commit()
            with pytest.raises(policy.SessionDenied) as exc: await policy.start_check(session)
            assert exc.value.reason == "session_revoked"


async def test_companyless_direct_and_superadmin_exceptions(native_world):
    w = native_world
    async with w.factory() as db:
        u = await db.get(User, w.user.id); u.company_id = None
        await db.delete(await db.get(UserCompany, (u.id, w.a.id)))
        (await db.get(ChatRoom, w.room.id)).type = "direct"
        await db.commit()
    session, _ = await issue(w)
    assert session.company_id is None
    assert w.channel in (await policy.start_check(session, [w.channel])).allowed
    async with w.factory() as db:
        (await db.get(User, w.user.id)).is_superadmin = True; await db.commit()
    session, _ = await issue(w)
    foreign_user_channel = f"user:{w.other.id}"
    assert foreign_user_channel in (await policy.start_check(session, [foreign_user_channel])).allowed


@pytest.mark.parametrize("change", ["watcher", "modules"])
async def test_real_task_acl_and_module_revocation(native_world, change):
    w = native_world
    async with w.factory() as db:
        task = Task(id=uuid.uuid4(), company_id=w.a.id, author_id=w.user.id,
                    title="Synthetic private task", visibility="private")
        db.add(task); await db.flush()
        watcher = TaskWatcher(task_id=task.id, user_id=w.other.id)
        db.add(watcher)
        (await db.get(ChatRoom, w.room.id)).scope_task_id = task.id
        await db.commit()
    session, _ = await issue(w, actor=w.other)
    assert w.channel in (await policy.start_check(session, [w.channel])).allowed
    async with w.factory() as db:
        if change == "watcher":
            await db.delete(await db.scalar(select(TaskWatcher).where(
                TaskWatcher.task_id == task.id, TaskWatcher.user_id == w.other.id)))
        else: (await db.get(UserCompany, (w.other.id, w.a.id))).modules = ["pulse"]
        await db.commit()
    assert w.channel not in (await policy.start_check(session, [w.channel])).allowed


async def test_ticket_rpc_boundary_and_history_guard_are_retained(native_world, monkeypatch):
    w = native_world
    allowed = [True]
    calls = []
    async def external_support(db, cid, user, tid, **kwargs):
        calls.append((cid, user.id, tid))
        return {"canStaffChat": allowed[0]}
    # Only the external authoritative RPC boundary is synthetic, not native auth.
    monkeypatch.setattr(ticket_communications, "access", external_support)
    now = datetime.now(timezone.utc)
    async with w.factory() as db:
        room = await db.get(ChatRoom, w.room.id)
        room.scope_ticket_id = uuid.uuid4(); room.scope_product = "support"
        room.scope_purpose = "support_staff"; room.audience = "internal"
        participant = await db.scalar(select(ChatParticipant).where(
            ChatParticipant.room_id == room.id, ChatParticipant.user_id == w.user.id))
        participant.history_from = now
        old = ChatMessage(id=uuid.uuid4(), room_id=room.id, user_id=w.other.id,
                          user_name="Synthetic", content="old private body", type="text",
                          created_at=now - timedelta(days=1))
        db.add(old); await db.commit()
    session, _ = await issue(w)
    assert w.channel in (await policy.start_check(session, [w.channel])).allowed
    assert not await ticket_communications.delivery_allowed(w.channel,
        {"type": "chat:message", "id": str(old.id)}, str(w.user.id))
    allowed[0] = False
    assert w.channel not in (await policy.start_check(session, [w.channel])).allowed
    assert calls and all(cid == w.a.id and uid == w.user.id for cid, uid, _ in calls)


async def test_expiry_after_delivery_await_stops_bytes(native_world, monkeypatch):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    session, _ = await w.connect(manager, socket)
    await manager.subscribe_current(socket, w.channel, chat_router._ws_can_subscribe)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ticket_communications.delivery_allowed_in_session
    async def paused(*args):
        entered.set(); await release.wait(); return await original(*args)
    monkeypatch.setattr(ticket_communications, "delivery_allowed_in_session", paused)
    task = asyncio.create_task(manager._broadcast_local(w.channel, {"type": "chat:message"}))
    await asyncio.wait_for(entered.wait(), 5)
    monkeypatch.setattr(policy, "wall_time", lambda: session.expires_at + 1)
    release.set(); await task
    assert socket.messages == []
    assert socket.close_args == (1008, "session_expired")


async def test_native_seven_day_strict_boundary(native_world, monkeypatch):
    now = datetime.now(timezone.utc)
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None): return now
    monkeypatch.setattr(auth, "datetime", Frozen)
    payload = {"tv": 0, "at": now.timestamp() - 7 * 86400}
    assert auth.session_valid(payload, native_world.user)
    payload["at"] -= 0.001
    assert not auth.session_valid(payload, native_world.user)
    payload.pop("at")
    assert auth.session_valid(payload, native_world.user)


@pytest.mark.parametrize("kind", ["connected", "pong", "subscribe:denied"])
async def test_every_direct_send_has_local_expiry_guard(native_world, monkeypatch, kind):
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    identity, _ = await native_world.connect(manager, socket)
    monkeypatch.setattr(policy, "wall_time", lambda: identity.expires_at + 1)
    assert not await manager.send(socket, {"type": kind})
    assert socket.messages == []
    assert socket.close_args == (1008, "session_expired")


async def test_idle_tv_revoke_at_real_operational_cadence(native_world):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    async with w.factory() as db:
        (await db.get(User, w.user.id)).token_version += 1
        await db.commit()
    await asyncio.wait_for(socket.closed.wait(), policy.CHECK_CADENCE + policy.CHECK_TIMEOUT + policy.SEND_TIMEOUT + 1)
    assert socket.close_args == (1008, "session_revoked")


async def test_terminal_close_serializes_with_inflight_send(native_world):
    w = native_world
    manager = chat_ws.ChatConnectionManager()
    entered, release = asyncio.Event(), asyncio.Event()
    class Paused(FakeSocket):
        async def send_json(self, value):
            entered.set(); await release.wait(); await super().send_json(value)
    socket = Paused()
    await w.connect(manager, socket)
    send = asyncio.create_task(manager.send(socket, {"type": "pong"}))
    close = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        close = manager._begin_close(socket, 1008, "session_revoked")
        assert not await manager.send(socket, {"type": "late"})
    finally:
        release.set()
        assert not await asyncio.wait_for(send, 5)
        if close is not None: await asyncio.wait_for(asyncio.shield(close), 5)
    # The first frame was already admitted to ASGI before terminal close.
    assert socket.messages == [{"type": "pong"}]
    assert socket.close_args == (1008, "session_revoked")


async def test_cancel_during_accept_cleans_registration(native_world):
    w = native_world
    manager = chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    entered = asyncio.Event()
    class Paused(FakeSocket):
        async def accept(self): entered.set(); await asyncio.Event().wait()
    socket = Paused()
    task = asyncio.create_task(w.connect(manager, socket))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, 5)
    assert manager._sessions == {} and manager._meta == {} and manager._online == {}


async def test_short_db_session_released_before_send(native_world):
    w = native_world
    manager = chat_ws.ChatConnectionManager()
    class Observed(FakeSocket):
        async def send_json(self, value):
            assert w.engine.pool.checkedout() == 0
            await super().send_json(value)
    socket = Observed()
    _, proof = await w.connect(manager, socket)
    assert not hasattr(proof, "_sa_instance_state")
    assert await manager.send(socket, {"type": "pong"})


async def test_check_timeout_is_transient_and_reaped(native_world, monkeypatch):
    identity, _ = await issue(native_world)
    async def blocked(*args): await asyncio.Event().wait()
    monkeypatch.setattr(auth, "native_user_from_claims", blocked)
    check = policy.start_check(identity)
    with pytest.raises(policy.SessionDenied) as exc: await asyncio.wait_for(check, policy.CHECK_TIMEOUT + 1)
    assert (exc.value.code, exc.value.reason) == (1013, "temporarily_unavailable")
    assert check.done()


async def test_http_native_wrapper_still_touches_presence(native_world):
    from fastapi.security import HTTPAuthorizationCredentials
    w = native_world
    token = auth.token_for(w.user)
    # Public scoped helper restores the test caller after exercising old HTTP side effects.
    with auth.native_claims_context(auth.current_token_claims(), auth.visit_company()):
        async with w.factory() as db:
            result = await auth.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
            assert result.id == w.user.id
            assert auth.current_token_claims()["sub"] == str(w.user.id)
        async with w.factory() as db:
            assert (await db.get(User, w.user.id)).last_seen_at is not None


async def test_two_actor_contexts_do_not_leak_into_publisher(native_world, monkeypatch):
    from app.models import Organization
    from app.scope import current_object_scope, current_organization
    from app.services import chat_access
    w = native_world
    async with w.factory() as db:
        orgs = [Organization(id=uuid.uuid4(), company_id=c.id, inn=f"SYNTH{i}", name="Synthetic org")
                for i, c in enumerate((w.a, w.b))]
        db.add_all(orgs); await db.flush()
        ma = await db.get(UserCompany, (w.user.id, w.a.id))
        ma.object_scope = ["scope-A"]; ma.own_organization_id = orgs[0].id
        db.add(UserCompany(user_id=w.other.id, company_id=w.b.id, role="user", modules=["docs"],
                           object_scope=["scope-B"], own_organization_id=orgs[1].id))
        (await db.get(User, w.other.id)).company_id = w.b.id
        room = ChatRoom(id=uuid.uuid4(), company_id=w.b.id, type="group", name="Synthetic B", is_active=True)
        db.add(room); await db.flush()
        db.add(ChatParticipant(room_id=room.id, user_id=w.other.id, role="member"))
        await db.commit()
    a, _ = await issue(w, selector=str(w.a.id))
    b, _ = await issue(w, actor=w.other, selector=str(w.b.id))
    seen, together = {}, asyncio.Event()
    original = chat_access.chat_scope_of
    async def observe(user, cid, db):
        seen[user.id] = (auth.current_token_claims()["sub"], auth.visit_company(),
                         await scope_company_id(user, db), tuple(current_object_scope() or ()),
                         current_organization())
        if len(seen) == 2: together.set()
        await asyncio.wait_for(together.wait(), 5)
        return await original(user, cid, db)
    monkeypatch.setattr(chat_access, "chat_scope_of", observe)
    parent = (auth.current_token_claims(), auth.visit_company(), current_object_scope(), current_organization())
    results = await asyncio.gather(policy.start_check(a, [w.channel]),
                                   policy.start_check(b, [f"chat:{room.id}"]))
    assert w.channel in results[0].allowed and f"chat:{room.id}" in results[1].allowed
    assert seen[w.user.id] == (str(w.user.id), None, w.a.id, ("scope-A",), orgs[0].id)
    assert seen[w.other.id] == (str(w.other.id), None, w.b.id, ("scope-B",), orgs[1].id)
    assert (auth.current_token_claims(), auth.visit_company(), current_object_scope(), current_organization()) == parent


async def test_slow_proof_cannot_delay_signed_expiry(native_world, monkeypatch):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket, expires_at=datetime.now(timezone.utc) + timedelta(seconds=2))
    entered = asyncio.Event()
    async def blocked(*args): entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(auth, "native_user_from_claims", blocked)
    pending = asyncio.create_task(manager.subscribe_current(socket, w.channel, chat_router._ws_can_subscribe))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(socket.closed.wait(), 5)
        assert socket.close_args == (1008, "session_expired")
    finally:
        await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 5)


async def test_close_timeout_retains_failure_not_authorization(native_world, monkeypatch):
    from dataclasses import replace
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    real = []
    class BlockedClose:
        def __init__(self): self.db = w.factory(); real.append(self.db)
        def __getattr__(self, name): return getattr(self.db, name)
        async def close(self): await asyncio.Event().wait()
    monkeypatch.setattr(policy, "async_session_factory", BlockedClose)
    state = manager._sessions[socket]
    state.proof = replace(state.proof, checked_at=policy.monotonic() - policy.CHECK_CADENCE)
    cleanup_entered, cleanup_release = cleanup_update_barrier(w, monkeypatch)
    operation = asyncio.create_task(manager.send(socket, {"type": "pong"}))
    try:
        async with asyncio.timeout(policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 2):
            await asyncio.wait_for(cleanup_entered.wait(), policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 1)
            assert not operation.done()
            await join_late_cleanup(manager, socket, cleanup_entered, cleanup_release)
            assert not await asyncio.wait_for(operation, policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 2)
        assert socket.messages == []
        assert socket.close_args == (1013, "temporarily_unavailable")
        assert manager._drain_failed
        assert w.engine.pool.checkedout() == 1  # before fault fixture repairs its session
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
    finally:
        cleanup_release.set()
        if not operation.done(): operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        # Fault-injection owns its real session. Public close, never driver internals.
        for db in real: await db.close()
        w.managers.remove(manager)
    assert w.engine.pool.checkedout() == 0


async def test_cancel_during_db_close_cannot_return_proof(native_world, monkeypatch):
    w = native_world
    identity, _ = await issue(w)
    entered = asyncio.Event()
    real = []
    class PausedClose:
        def __init__(self): self.db = w.factory(); real.append(self.db)
        def __getattr__(self, name): return getattr(self.db, name)
        async def close(self): entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(policy, "async_session_factory", PausedClose)
    task = policy.start_check(identity)
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(policy.SessionDenied) as exc: await asyncio.wait_for(task, 5)
        assert exc.value.cleanup_failed and exc.value.code == 1013
        assert w.engine.pool.checkedout() == 1  # close was interrupted, not physically proved
    finally:
        for db in real: await db.close()
    assert task.done() and w.engine.pool.checkedout() == 0


async def test_failed_transport_close_cancels_tracked_children(native_world):
    w = native_world
    manager = chat_ws.ChatConnectionManager()
    class BrokenClose(FakeSocket):
        async def close(self, code=1000, reason=""):
            raise RuntimeError("synthetic ASGI close failure")
    socket = BrokenClose()
    await manager._ensure_presence_table()
    await w.connect(manager, socket)
    state = manager._sessions[socket]
    try:
        with pytest.raises(RuntimeError, match="synthetic ASGI"):
            await manager.close(socket)
        await asyncio.wait_for(asyncio.gather(state.watchdog, state.deadline, return_exceptions=True), 5)
        assert manager._sessions == {} and manager._meta == {} and manager._online == {}
        assert manager._drain_failed
        async with w.factory() as db:
            assert await db.scalar(text("SELECT count(*) FROM chat_ws_presence WHERE worker_id = :worker"),
                                   {"worker": manager._instance_id}) == 0
            assert (await db.get(User, w.user.id)).last_seen_at is not None
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.stop()
    finally:
        w.managers.remove(manager)


@pytest.mark.parametrize("mutation", ["participant", "inactive", "chat-scope", "cross-company"])
async def test_queued_personal_preview_rechecks_ordinary_room(native_world, mutation):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    # No room subscription: queued mention is delivered on the user's channel.
    async with w.factory() as db:
        if mutation == "participant":
            await db.delete(await db.scalar(select(ChatParticipant).where(
                ChatParticipant.user_id == w.user.id, ChatParticipant.room_id == w.room.id)))
        elif mutation == "inactive": (await db.get(ChatRoom, w.room.id)).is_active = False
        elif mutation == "cross-company": (await db.get(ChatRoom, w.room.id)).company_id = w.b.id
        else:
            role = CompanyRole(id=uuid.uuid4(), company_id=w.a.id, name="Synthetic scoped", chat_scope="support")
            db.add(role); await db.flush()
            (await db.get(UserCompany, (w.user.id, w.a.id))).role_id = role.id
        await db.commit()
    await manager._broadcast_local(f"user:{w.user.id}", {"type": "chat:mention",
        "roomId": str(w.room.id), "preview": "Synthetic private preview"})
    assert socket.messages == []
    assert manager.is_subscribed(socket, f"user:{w.user.id}")


async def test_personal_payload_uses_recipient_context_and_selected_tenant(native_world, monkeypatch):
    from app.scope import (current_object_scope, current_organization,
                           set_request_scope, set_request_organization)
    w = native_world
    async with w.factory() as db:
        db.add(UserCompany(user_id=w.user.id, company_id=w.b.id, role="user", modules=["docs"]))
        room_b = ChatRoom(id=uuid.uuid4(), company_id=w.b.id, type="group", name="Synthetic B", is_active=True)
        db.add(room_b); await db.flush()
        db.add(ChatParticipant(room_id=room_b.id, user_id=w.user.id, role="member"))
        await db.commit()
    manager, a, b = chat_ws.ChatConnectionManager(), FakeSocket(), FakeSocket()
    await w.connect(manager, a, selector=str(w.a.id))
    await w.connect(manager, b, selector=str(w.b.id))
    seen = []
    original = ticket_communications.recipient_allowed
    async def observe(db, room, uid):
        seen.append((room.company_id, auth.current_token_claims()["sub"], auth.visit_company(),
                     await scope_company_id(await db.get(User, uuid.UUID(uid)), db),
                     current_object_scope(), current_organization()))
        return await original(db, room, uid)
    monkeypatch.setattr(ticket_communications, "recipient_allowed", observe)
    parent_objects, parent_org = current_object_scope(), current_organization()
    sentinel_org = uuid.uuid4()
    await capture_company_header(str(w.b.id))
    set_request_scope(["publisher-only"]); set_request_organization(sentinel_org)
    try:
        with auth.native_claims_context({"sub": "publisher-only"}, w.b.id):
            await asyncio.gather(manager._broadcast_local(f"user:{w.user.id}",
                {"type": "chat:mention", "roomId": str(w.room.id)}),
                manager._broadcast_local(f"user:{w.user.id}",
                {"type": "chat:mention", "roomId": str(room_b.id)}))
            assert auth.current_token_claims() == {"sub": "publisher-only"}
            assert auth.visit_company() == w.b.id
            assert current_object_scope() == ["publisher-only"]
            assert current_organization() == sentinel_org
            async with w.factory() as db:
                assert await scope_company_id(w.user, db) == w.b.id
    finally:
        await capture_company_header(None)
        set_request_scope(parent_objects); set_request_organization(parent_org)
    assert len(a.messages) == len(b.messages) == 1
    assert a.messages[0]["roomId"] == str(w.room.id)
    assert b.messages[0]["roomId"] == str(room_b.id)
    assert {cid for cid, *_ in seen} == {w.a.id, w.b.id}
    assert all(sub == str(w.user.id) and visit is None and cid == selected
               and objects is None and org is None for cid, sub, visit, selected, objects, org in seen)


@pytest.mark.parametrize("case", ["non-chat", "missing", "opaque-chat", "opaque-personal"])
async def test_legacy_delivery_early_returns_never_construct_session(monkeypatch, case):
    def forbidden():
        pytest.fail("Legacy early allow constructed a database session")
    monkeypatch.setattr(database, "async_session_factory", forbidden)
    channel, payload = {
        "non-chat": ("user:synthetic", {"type": "presence", "roomId": str(uuid.uuid4())}),
        "missing": ("user:synthetic", {"type": "chat:mention"}),
        "opaque-chat": ("chat:opaque", {"type": "chat:message"}),
        "opaque-personal": ("user:synthetic", {"type": "chat:mention", "roomId": "opaque"}),
    }[case]
    assert await ticket_communications.delivery_allowed(channel, payload, "synthetic")


@pytest.mark.parametrize("reference", [None, "opaque", ""], ids=["missing", "opaque", "blank"])
async def test_native_personal_room_reference_is_fail_closed(native_world, reference):
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await native_world.connect(manager, socket)
    assert not await manager.send(socket, {"type": "chat:mention", "roomId": reference})
    assert socket.messages == []


@pytest.mark.parametrize("action", ["cancel", "shutdown", "body-timeout"])
async def test_preaccept_real_pg_check_is_owned_and_reaped(native_world, monkeypatch, action):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    w.managers.append(manager)
    entered = asyncio.Event()
    original = auth.native_user_from_claims
    async def paused(*args):
        user = await original(*args)  # hold a real PG transaction, not an auth stub
        entered.set()
        await asyncio.Event().wait()
        return user
    monkeypatch.setattr(auth, "native_user_from_claims", paused)
    task = asyncio.create_task(manager.admit(auth.decode_token(auth.token_for(w.user)), ws=socket))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert any(t.get_name() == "chat-ws-admission" and not t.done() for t in manager._owned_tasks)
        assert manager._sessions == {} and manager._meta == {}
        assert not socket.accepted and w.engine.pool.checkedout() == 1
        if action == "shutdown":
            await manager.stop()
        elif action == "cancel":
            task.cancel()
        if action == "body-timeout":
            with pytest.raises(policy.SessionDenied) as exc:
                await asyncio.wait_for(task, policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 1)
            assert not exc.value.cleanup_failed
            assert socket.close_args == (1013, "temporarily_unavailable")
        else:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, policy.DRAIN_TIMEOUT + 1)
            assert socket.close_args == (1001, "server_shutdown")
        assert not socket.accepted and socket.messages == []
        assert not manager._drain_failed and w.engine.pool.checkedout() == 0
        assert not [t for t in manager._owned_tasks if not t.done()]
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("action", ["close-timeout", "cancel-close"])
async def test_preaccept_db_cleanup_failure_survives_without_socket_metadata(native_world, monkeypatch, action):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    w.managers.append(manager)
    entered, real = asyncio.Event(), []
    class PausedClose:
        def __init__(self): self.db = w.factory(); real.append(self.db)
        def __getattr__(self, name): return getattr(self.db, name)
        async def close(self): entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(policy, "async_session_factory", PausedClose)
    task = asyncio.create_task(manager.admit(auth.decode_token(auth.token_for(w.user)), ws=socket))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if action == "cancel-close": task.cancel()
        with pytest.raises(policy.SessionDenied) as exc:
            await asyncio.wait_for(task, policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 1)
        assert exc.value.cleanup_failed
        assert socket.close_args == (1013, "temporarily_unavailable")
        assert not socket.accepted and manager._sessions == {} and manager._meta == {}
        assert manager._drain_failed
        assert w.engine.pool.checkedout() == 1  # sampled before manual fixture-only repair
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for db in real: await db.close()
        w.managers.remove(manager)
    assert w.engine.pool.checkedout() == 0


@pytest.mark.parametrize("stage", ["current-denial", "decode-denial"])
async def test_preaccept_transport_close_failure_is_lifecycle_failure(native_world, stage):
    w = native_world
    manager = chat_router.manager
    class BrokenClose(FakeSocket):
        async def close(self, code=1000, reason=""):
            raise RuntimeError("synthetic preaccept ASGI close failure")
    socket = BrokenClose()
    token = auth.token_for(w.user)
    if stage == "current-denial":
        async with w.factory() as db:
            (await db.get(User, w.user.id)).token_version += 1
            await db.commit()
    else: token = "synthetic-invalid-signature"
    try:
        with pytest.raises(RuntimeError, match="synthetic preaccept"):
            await chat_router._ws_user(token, ws=socket)
        assert not socket.accepted and manager._sessions == {} and manager._meta == {}
        assert manager._drain_failed and w.engine.pool.checkedout() == 0
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
    finally:
        w.managers.remove(manager)


async def test_stopped_manager_rejects_late_admission_without_accept(native_world):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    w.managers.append(manager)
    await manager.stop()
    with pytest.raises(policy.SessionDenied):
        await manager.admit(auth.decode_token(auth.token_for(w.user)), ws=socket)
    assert not socket.accepted and socket.messages == []
    assert socket.close_args == (1001, "server_shutdown")
    assert manager._sessions == {} and w.engine.pool.checkedout() == 0


@pytest.mark.parametrize("owner", ["start", "ensure", "online", "is-online", "publish",
                                   "connect-presence", "disconnect", "finish", "heartbeat", "stop"])
async def test_every_manager_db_owner_retains_failed_public_close(native_world, monkeypatch, owner):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    w.managers.append(manager)
    if owner not in {"start", "ensure"}:
        await manager._ensure_presence_table()
    if owner in {"disconnect", "finish"}:
        await w.connect(manager, socket)
    real = []
    class BlockedClose:
        def __init__(self): self.db = w.factory(); real.append(self.db)
        def __getattr__(self, name): return getattr(self.db, name)
        async def close(self): await asyncio.Event().wait()
    async def operation():
        if owner == "start": await manager.start(os.environ["DATABASE_URL"])
        elif owner == "ensure": await manager._ensure_presence_table()
        elif owner == "online": await manager.online_user_ids()
        elif owner == "is-online": await manager.is_online(str(w.user.id))
        elif owner == "publish": await manager._publish(f"user:{w.user.id}", {"type": "presence"})
        elif owner == "connect-presence":
            await manager._connect_presence(str(w.user.id), str(uuid.uuid4()), True)
        elif owner == "disconnect": await manager.disconnect(socket)
        elif owner == "finish": await manager.close(socket)
        elif owner == "stop": await manager.stop()
        else:
            manager._presence_task = manager._track(asyncio.create_task(manager._heartbeat_presence()))
            await manager._presence_task  # real existing 20s cadence, no shortened timer
    try:
        with monkeypatch.context() as patch:
            patch.setattr(chat_ws, "async_session_factory", BlockedClose)
            budget = policy.DRAIN_TIMEOUT + 2 + (chat_ws._PRESENCE_HEARTBEAT_SECONDS if owner == "heartbeat" else 0)
            if owner == "publish":
                await asyncio.wait_for(operation(), budget)  # existing best-effort delivery return
            else:
                with pytest.raises((policy.DbCleanupFailed, RuntimeError, TimeoutError)):
                    await asyncio.wait_for(operation(), budget)
        assert manager._drain_failed
        # A committed writer may already return its connection before close;
        # that zero is not proof of public Session.close completing.
        before_fixture_cleanup = w.engine.pool.checkedout()
        assert before_fixture_cleanup == (1 if owner in {"online", "is-online"} else 0)
        if owner == "start":
            assert manager._presence_task is None and manager._listener_task is None
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
        # Fault fixture explicitly owns/reaps these real sessions. Manager failure
        # remains sticky even after this synthetic test repairs its own resource.
        for db in real: await db.close()
        assert w.engine.pool.checkedout() == 0
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.stop()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
    finally:
        for db in real: await db.close()
        w.managers.remove(manager)


@pytest.mark.parametrize("owner", ["start", "online", "publish"])
async def test_ordinary_pg_body_failure_keeps_best_effort_presence(native_world, monkeypatch, owner):
    w = native_world
    manager = chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    await manager._ensure_presence_table()
    class FailingBody:
        def __init__(self): self.db = w.factory()
        def __getattr__(self, name): return getattr(self.db, name)
        async def execute(self, *args, **kwargs):
            return await self.db.execute(text("SELECT 1 / 0"))  # real PG body error
        async def scalars(self, *args, **kwargs):
            return await self.db.scalars(text("SELECT 1 / 0"))
        async def close(self): await self.db.close()
    with monkeypatch.context() as patch:
        patch.setattr(chat_ws, "async_session_factory", FailingBody)
        if owner == "start": await manager.start(os.environ["DATABASE_URL"])
        elif owner == "online": assert await manager.online_user_ids() == set()
        else: await manager._publish(f"user:{w.user.id}", {"type": "presence"})
    assert not manager._drain_failed
    await manager.stop()
    assert w.engine.pool.checkedout() == 0


async def test_received_peer_disconnect_skips_rejected_asgi_close_and_cleans_pg(native_world):
    w, manager = native_world, chat_router.manager
    await manager._ensure_presence_table()
    app = FastAPI(); app.include_router(chat_router.router, prefix="/api")
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    peer_terminal, redundant = False, []
    async def receive():
        nonlocal peer_terminal
        event = await incoming.get()
        if event["type"] == "websocket.disconnect": peer_terminal = True
        return event
    async def send(event):
        if event["type"] == "websocket.close" and peer_terminal:
            redundant.append(event["type"])
            raise RuntimeError("synthetic ASGI already received peer terminal")
        await outgoing.put(event)
    scope = {"type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.5"},
             "scheme": "ws", "path": "/api/chat/ws", "raw_path": b"/api/chat/ws",
             "query_string": f"token={auth.token_for(w.user)}&company_id={w.a.id}".encode(),
             "headers": [], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2), "subprotocols": []}
    await incoming.put({"type": "websocket.connect"})
    task = asyncio.create_task(app(scope, receive, send), context=contextvars.Context())
    try:
        assert (await asyncio.wait_for(outgoing.get(), 5))["type"] == "websocket.accept"
        import json
        assert json.loads((await asyncio.wait_for(outgoing.get(), 5))["text"])["type"] == "connected"
        await incoming.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(task, 5)
        assert peer_terminal and redundant == [] and not manager._drain_failed
        assert manager._sessions == {} and manager._meta == {} and manager._online == {}
        async with w.factory() as db:
            assert await db.scalar(text("SELECT count(*) FROM chat_ws_presence WHERE worker_id = :worker"),
                                   {"worker": manager._instance_id}) == 0
            assert (await db.get(User, w.user.id)).last_seen_at is not None
        assert w.engine.pool.checkedout() == 0
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_failed_public_listener_close_retains_resource_and_blocks_restart(native_world):
    w, manager = native_world, chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    await manager.start(os.environ["DATABASE_URL"])
    real = manager._listener
    class FailedClose:
        def __getattr__(self, name): return getattr(real, name)
        async def close(self): raise RuntimeError("synthetic public listener close failure")
    failed = manager._listener = FailedClose()
    try:
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        assert manager._drain_failed and manager._listener is failed
        assert not real.is_closed()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
    finally:
        await real.close()  # public close; the failure fixture owns this resource
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        w.managers.remove(manager)
    assert real.is_closed() and w.engine.pool.checkedout() == 0


@pytest.mark.parametrize("action", ["timeout", "cancel-caller"])
async def test_payload_close_failure_survives_cancelled_delivery_waiter(native_world, monkeypatch, action):
    w = native_world
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    await manager.subscribe_current(socket, w.channel, chat_router._ws_can_subscribe)
    entered, real = asyncio.Event(), []
    class PausedClose:
        def __init__(self): self.db = w.factory(); real.append(self.db)
        def __getattr__(self, name): return getattr(self.db, name)
        async def close(self): entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(policy, "async_session_factory", PausedClose)
    cleanup_entered, cleanup_release = cleanup_update_barrier(w, monkeypatch)
    delivery = asyncio.create_task(manager.send(socket, {"type": "chat:message"}, channel=w.channel))
    try:
        async with asyncio.timeout(policy.CHECK_TIMEOUT + policy.DRAIN_TIMEOUT + 2):
            await asyncio.wait_for(entered.wait(), 5)
            check = next(iter(manager._sessions[socket].payload_checks))
            if action == "cancel-caller":
                delivery.cancel()
                with pytest.raises(asyncio.CancelledError): await delivery
            await asyncio.wait_for(cleanup_entered.wait(), policy.DRAIN_TIMEOUT + 1)
            if action == "timeout": assert not delivery.done()
            await join_late_cleanup(manager, socket, cleanup_entered, cleanup_release)
            if action != "cancel-caller":
                assert not await asyncio.wait_for(delivery, policy.DRAIN_TIMEOUT + 2)
        await asyncio.wait_for(asyncio.gather(check, return_exceptions=True), policy.DRAIN_TIMEOUT + 1)
        await asyncio.wait_for(socket.closed.wait(), policy.SEND_TIMEOUT + 1)
        assert socket.messages == [] and socket.close_args == (1013, "temporarily_unavailable")
        assert manager._drain_failed and not manager.is_live(socket)
        assert w.engine.pool.checkedout() == 1  # before explicit test-owned physical close
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
        for db in real: await db.close()
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
    finally:
        cleanup_release.set()
        if not delivery.done(): delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)
        for db in real: await db.close()
        w.managers.remove(manager)
    assert w.engine.pool.checkedout() == 0


async def test_direct_room_personal_preview_drops_revoked_participant(native_world):
    w = native_world
    async with w.factory() as db:
        room = await db.get(ChatRoom, w.room.id)
        room.type = "direct"  # existing schema keeps company_id NOT NULL; ACL uses participants
        await db.commit()
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    event = {"type": "chat:mention", "roomId": str(w.room.id), "preview": "Synthetic direct preview"}
    await manager._broadcast_local(f"user:{w.user.id}", event)
    assert socket.messages == [{**event, "channel": f"user:{w.user.id}"}]
    socket.messages.clear()
    async with w.factory() as db:
        await db.delete(await db.scalar(select(ChatParticipant).where(
            ChatParticipant.user_id == w.user.id, ChatParticipant.room_id == w.room.id)))
        await db.commit()
    await manager._broadcast_local(f"user:{w.user.id}", event)
    assert not await manager.send(socket, event)  # same payload guard on a direct manager frame
    assert socket.messages == []
    assert manager.is_subscribed(socket, f"user:{w.user.id}")


@pytest.mark.parametrize("case", ["old-reply", "old-message", "old-pin", "current", "acl-revoked"])
async def test_manager_personal_ticket_payload_preserves_history_and_live_acl(native_world, monkeypatch, case):
    w = native_world
    calls = []
    async def external_support(db, cid, user, tid, **kwargs):
        calls.append((cid, user.id, tid))
        return {"canStaffChat": case != "acl-revoked"}
    # Synthetic external RPC boundary only: native identity, staff participant,
    # selected tenant and authoritative in-session history SQL remain real.
    monkeypatch.setattr(ticket_communications, "access", external_support)
    now = datetime.now(timezone.utc)
    async with w.factory() as db:
        room = await db.get(ChatRoom, w.room.id)
        room.scope_ticket_id = uuid.uuid4(); room.scope_product = "support"
        room.scope_purpose = "support_staff"; room.audience = "internal"
        participant = await db.scalar(select(ChatParticipant).where(
            ChatParticipant.room_id == room.id, ChatParticipant.user_id == w.user.id))
        participant.history_from = now
        old, current = [ChatMessage(id=uuid.uuid4(), room_id=room.id, user_id=w.other.id,
            user_name="Synthetic", content="Synthetic ticket", type="text", created_at=stamp)
            for stamp in (now - timedelta(days=1), now + timedelta(seconds=1))]
        db.add_all([old, current]); await db.commit()
    manager, socket = chat_ws.ChatConnectionManager(), FakeSocket()
    await w.connect(manager, socket)
    event = {"type": "chat:mention", "roomId": str(w.room.id)}
    if case == "old-reply": event["replyTo"] = str(old.id)
    elif case == "old-pin": event["pinnedMessage"] = {"id": str(old.id)}
    else:
        event.update(type="chat:message", id=str(current.id if case == "current" else old.id))
    await manager._broadcast_local(f"user:{w.user.id}", event)
    if case == "current":
        assert socket.messages == [{**event, "channel": f"user:{w.user.id}"}]
    else:
        assert socket.messages == []
    assert calls and all(cid == w.a.id and uid == w.user.id for cid, uid, _ in calls)
    assert manager.is_subscribed(socket, f"user:{w.user.id}") and not manager._drain_failed


@pytest.mark.parametrize("case", ["cancel-setup", "setup-error", "setup-close-error",
                                   "close-timeout", "cancel-close", "stop-setup"])
async def test_real_pg_listener_setup_owns_acquisition_and_cleanup(native_world, monkeypatch, case):
    w, manager = native_world, chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    manager._dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    original = chat_ws.asyncpg.connect
    acquired, proxies = [], []
    setup_entered, close_entered, release_setup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class SetupConnection:
        def __init__(self, raw): self.raw = raw
        def __getattr__(self, name): return getattr(self.raw, name)
        async def add_listener(self, *args):
            await self.raw.add_listener(*args)  # actual PG LISTEN completed first
            setup_entered.set()
            await release_setup.wait()
            raise RuntimeError("synthetic listener setup failure")
        async def close(self):
            close_entered.set()
            if case == "setup-close-error":
                raise RuntimeError("synthetic listener cleanup failure")
            if case in {"close-timeout", "cancel-close"}: await asyncio.Event().wait()
            await self.raw.close()
    async def connect(*args, **kwargs):
        raw = await original(*args, **kwargs)
        acquired.append(raw)
        proxy = SetupConnection(raw); proxies.append(proxy)
        return proxy
    monkeypatch.setattr(chat_ws.asyncpg, "connect", connect)
    task = asyncio.create_task(manager._connect_listener())
    failed_close = case in {"setup-close-error", "close-timeout", "cancel-close"}
    try:
        await asyncio.wait_for(setup_entered.wait(), 5)
        assert manager._listener is proxies[0] and not acquired[0].is_closed()
        assert any(t.get_name() == "chat-ws-listener-setup" and not t.done() for t in manager._owned_tasks)
        if case == "cancel-setup": task.cancel()
        elif case == "stop-setup": await manager.stop()
        else:
            release_setup.set()
            if case == "cancel-close":
                await asyncio.wait_for(close_entered.wait(), 5)
                task.cancel()
        if case in {"cancel-setup", "cancel-close", "stop-setup"}:
            with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, policy.DRAIN_TIMEOUT + 2)
        elif case == "close-timeout":
            with pytest.raises(TimeoutError): await asyncio.wait_for(task, policy.DRAIN_TIMEOUT + 2)
        else:
            with pytest.raises(RuntimeError, match="synthetic listener"):
                await asyncio.wait_for(task, policy.DRAIN_TIMEOUT + 2)
        assert close_entered.is_set()
        # Raw listener is separate from SQLAlchemy pool: inspect its real public
        # terminal state BEFORE any fixture close, never infer it from pool0.
        assert acquired[0].is_closed() is (not failed_close)
        assert manager._drain_failed is failed_close
        if failed_close:
            assert manager._listener is proxies[0]
            with pytest.raises(RuntimeError, match="cleanup failed"):
                await manager.start(os.environ["DATABASE_URL"])
            with pytest.raises(RuntimeError, match="cleanup failed"):
                await manager._connect_listener()
            assert len(acquired) == 1 and manager._listener is proxies[0]
        else:
            assert manager._listener is None
            await manager.stop()
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for raw in acquired: await raw.close()  # explicit fixture-only repair
        if failed_close:
            with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        else: await manager.stop()
        w.managers.remove(manager)
    assert all(raw.is_closed() for raw in acquired)


async def test_listener_replacement_does_not_overwrite_unproved_old_resource(native_world, monkeypatch):
    w, manager = native_world, chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    manager._dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    await manager._connect_listener()
    raw = manager._listener
    original, replacements = chat_ws.asyncpg.connect, []
    async def counted(*args, **kwargs):
        replacements.append(1)
        return await original(*args, **kwargs)
    monkeypatch.setattr(chat_ws.asyncpg, "connect", counted)
    class FailedOldClose:
        def __getattr__(self, name): return getattr(raw, name)
        async def close(self): raise RuntimeError("synthetic old listener close failure")
    failed = manager._listener = FailedOldClose()
    try:
        with pytest.raises(RuntimeError, match="synthetic old listener"):
            await manager._connect_listener()
        assert manager._listener is failed and not raw.is_closed()
        assert replacements == [] and manager._drain_failed
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.start(os.environ["DATABASE_URL"])
    finally:
        await raw.close()  # fixture repair, not manager release evidence
        with pytest.raises(RuntimeError, match="cleanup failed"): await manager.stop()
        w.managers.remove(manager)
    assert raw.is_closed()


@pytest.mark.parametrize("action", ["stop-suspended", "cancel-suspended", "stop-at-setup-return"])
async def test_real_pg_startup_stop_cannot_create_late_listener_task(native_world, monkeypatch, action):
    w, manager = native_world, chat_ws.ChatConnectionManager()
    w.managers.append(manager)
    original = chat_ws.asyncpg.connect
    acquired, entered, release = [], asyncio.Event(), asyncio.Event()
    class BarrierConnection:
        def __init__(self, raw): self.raw = raw
        def __getattr__(self, name): return getattr(self.raw, name)
        async def add_listener(self, *args):
            await self.raw.add_listener(*args)  # real PG registration before barrier
            entered.set()
            await release.wait()
    async def connect(*args, **kwargs):
        raw = await original(*args, **kwargs); acquired.append(raw)
        return BarrierConnection(raw)
    monkeypatch.setattr(chat_ws.asyncpg, "connect", connect)
    startup = asyncio.create_task(manager.start(os.environ["DATABASE_URL"]))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert len(acquired) == 1 and not acquired[0].is_closed()
        assert {"chat-ws-startup", "chat-ws-listener-setup"} <= {
            t.get_name() for t in manager._owned_tasks if not t.done()}
        if action == "cancel-suspended": startup.cancel()
        else:
            if action == "stop-at-setup-return": release.set()
            await manager.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(startup, policy.DRAIN_TIMEOUT + 2)
        # Release after stop/cancel must never revive an old startup generation.
        release.set()
        await asyncio.sleep(0)
        assert acquired[0].is_closed()  # manager close, BEFORE manual fixture repair
        assert manager._listener is None and manager._listener_task is None
        assert manager._presence_task is None and manager._startup_task is None
        assert not manager._drain_failed and not [t for t in manager._owned_tasks if not t.done()]
        assert w.engine.pool.checkedout() == 0
    finally:
        release.set()
        if not startup.done(): startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
        for raw in acquired: await raw.close()  # idempotent fixture cleanup, not the above proof
        await manager.stop()
        w.managers.remove(manager)
