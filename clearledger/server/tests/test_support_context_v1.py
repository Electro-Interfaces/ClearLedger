"""Настоящие TCP HTTP, подписи RS256/ES256 и отдельная PostgreSQL.

Node/Support здесь — ограниченный HTTP protocol peer с проверкой реальных
service JWT, не mock claims и не подмена транспорта Core. Сквозную бизнес-
транзакцию Support и браузер проверяет независимый V20.
"""
import asyncio
import base64
import copy
import hashlib
import json
import secrets
import socket
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import jwt
import pytest
import pytest_asyncio
import uvicorn
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select

from app.auth import token_for
from app.main import app
from app.models import App, AppCompanyLink, Company, CompanyApp, SpaceInboundKey, User, UserCompany
from app.services import app_registry, sso
from app.services.support_context import PREFIX, envelope
from app.services.support_context_models import ContextBinding, ContextGrant, ContextReplay
from app.services.support_context_protocol import thumbprint
from tests.test_voice_tokens import sso_key  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")
ALL_ACTIONS = ["context.read", "context.details", "context.select", "context.clarify",
               "ticket.create", "ticket.append"]


def now():
    return datetime.now(timezone.utc).isoformat()


def dpop(key, path, *, token=None, jti=None, iat=None, **overrides):
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    claims = {"htm": "POST", "htu": path, "iat": int(time.time()) if iat is None else iat,
              "jti": jti or uuid.uuid4().hex}
    if token:
        claims["ath"] = base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()).decode().rstrip("=")
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": jwk})


@pytest_asyncio.fixture(loop_scope="session")
async def core_http(setup_database):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    server.install_signal_handlers = lambda: None
    task = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        if task.done():
            await task
        await asyncio.sleep(.01)
    try:
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as client:
            yield client, origin
    finally:
        server.should_exit = True
        await task
        listener.close()


class Peer:
    def __init__(self, public_key):
        self.public_key = public_key
        self.tenants = {}
        self.requests = []
        self.status = 200
        self.bad_body = None
        self.delay = 0
        self.errors = []
        self.on_status = None
        self.on_consume = None
        self.on_actor_resolve = None
        self.used_codes = set()

    @asynccontextmanager
    async def running(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    length = int(self.headers["Content-Length"])
                    body = json.loads(self.rfile.read(length))
                    token = self.headers["Authorization"].removeprefix("Bearer ")
                    audience = "node-support-admission" if "/admission/" in self.path else "support-context"
                    c = jwt.decode(token, owner.public_key, algorithms=["RS256"],
                                   audience=audience, issuer=sso.settings.sso_issuer,
                                   options={"strict_aud": True})
                    assert c["version"] == "support-context/1" and c["exp"] - c["iat"] <= 120
                    assert jwt.get_unverified_header(token)["typ"] == "at+jwt"
                    tenant = owner.tenants[c["coreCid"]]
                    assert c["cid"] == tenant["cid"]
                    if "callRef" in c:
                        assert c["callRef"] == tenant["callRef"]
                    owner.requests.append((self.path, c, body))
                    if self.path.endswith("/prepare"):
                        assert c["svc"] == "support-context.prepare"
                        assert body["callRef"] == c["callRef"] and "phone" in body
                        result = tenant["prepare"]
                    elif self.path.endswith("/actor-resolve"):
                        assert c["svc"] == "support-context.actor-resolve"
                        assert body["contextRef"] == tenant["contextRef"]
                        assert body["act"] == tenant["node"]["act"]
                        if owner.on_actor_resolve:
                            owner.on_actor_resolve()
                        result = tenant["actor"]
                    elif self.path.endswith("/consume"):
                        assert c["svc"] == "support-context.admission"
                        code = body["admissionCode"]
                        if code != tenant["code"] or code in owner.used_codes:
                            self.send_response(409)
                            self.send_header("Content-Length", "2")
                            self.end_headers()
                            self.wfile.write(b'{}')
                            return
                        assert body["jkt"] == tenant["jkt"]
                        owner.used_codes.add(code)
                        if owner.on_consume:
                            owner.on_consume()
                        result = tenant["node"]
                    elif self.path.endswith("/status"):
                        assert c["svc"] == "support-context.admission"
                        if owner.on_status:
                            owner.on_status()
                        result = tenant["node"]
                    else:
                        raise AssertionError(self.path)
                    if owner.delay:
                        time.sleep(owner.delay)
                    raw = json.dumps(result if owner.bad_body is None else owner.bad_body).encode()
                    self.send_response(owner.status)
                except Exception as e:
                    owner.errors.append(repr(e))
                    raw = b'{}'
                    self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except BrokenPipeError:
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            await asyncio.to_thread(self.server.shutdown)
            self.server.server_close()
            thread.join(timeout=1)


@pytest_asyncio.fixture(loop_scope="session")
async def env(db, core_http, sso_key):
    client, origin = core_http
    await app_registry.seed_apps(db)
    apps = {a.code: a for a in (await db.scalars(select(App).where(App.code.in_(["support", "voice"])))).all()}
    async with Peer(sso_key).running() as peer:
        tenants = []
        for index in range(2):
            company = Company(name=f"Синтетическая компания I11 {index}", slug="i11-" + uuid.uuid4().hex,
                              profile_id="default")
            db.add(company)
            await db.flush()
            user = User(email=f"{uuid.uuid4().hex}@example.invalid", name="Вымышленный оператор",
                        password_hash="synthetic-unusable-login", company_id=company.id, token_version=0)
            db.add(user)
            await db.flush()
            member = UserCompany(user_id=user.id, company_id=company.id, role="admin")
            db.add(member)
            keys = []
            for scope in ("support-context.prepare", "support-context.introspect", "voice.identify"):
                raw = secrets.token_urlsafe(32)
                key = SpaceInboundKey(company_id=company.id, consumer="Синтетический I11",
                                      key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:8], scopes=[scope])
                db.add(key)
                await db.flush()
                keys.append((raw, key))
            cid = str(uuid.uuid4())
            db.add(AppCompanyLink(app_id=apps["support"].id, company_id=company.id, external_company_id=cid))
            call = {"nodeId": "synthetic-node-" + uuid.uuid4().hex,
                    "connectorId": str(uuid.uuid4()), "nodeContactId": "synthetic-call-" + uuid.uuid4().hex}
            config = {"enabled": True, "publicOrigin": origin, "introspectionKeyId": str(keys[1][1].id),
                      "nodes": [{"nodeId": call["nodeId"], "connectorId": call["connectorId"],
                                 "admissionBaseUrl": peer.base, "prepareKeyId": str(keys[0][1].id)}]}
            voice = CompanyApp(company_id=company.id, app_id=apps["voice"].id,
                               enabled=True, config={"supportContext": config})
            support = CompanyApp(company_id=company.id, app_id=apps["support"].id,
                                 enabled=True, config={"internalUrl": peer.base})
            db.add_all([voice, support])
            await db.commit()
            key = ec.generate_private_key(ec.SECP256R1())
            jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
            context_ref = "scx_" + secrets.token_urlsafe(32)
            common = {"coreCid": str(company.id), "cid": cid, "callRef": call, "contextRef": context_ref}
            t = {**common, "company": company, "user": user, "member": member, "keys": keys,
                 "voice": voice, "support": support, "config": config, "key": key, "jwk": jwk,
                 "jkt": thumbprint(jwk), "code": secrets.token_urlsafe(32)}
            identity = {"callRef": call, "contextRef": context_ref}
            t["node"] = envelope(**identity, admissionRef="adm-" + uuid.uuid4().hex, jkt=t["jkt"],
                                 connectionId="synthetic-connection",
                                 act={"iss": "https://cc.example.invalid", "sub": "synthetic-operator"},
                                 assignmentVersion=1, phase="connected", allowedActions=ALL_ACTIONS,
                                 amr=["pwd", "otp"], phaseDeadline=None, endedAt=None, active=True, revoked=False)
            t["actor"] = envelope(**identity, connectionId="synthetic-connection", coreActorSub=str(user.id),
                                  bindingRef="synthetic-binding", supportUserRef=str(uuid.uuid4()), bindingVersion=1,
                                  permissionsVersion=1, capabilities=ALL_ACTIONS, fieldMask="operator",
                                  active=True, membership=True, ticketRefs=[])
            t["prepare"] = envelope(contextRef=context_ref, callRef=call, contextVersion=1,
                                    state="preparing", preparedAt=now(),
                                    expiresAt=(datetime.now(timezone.utc) + timedelta(hours=23)).isoformat(), retryAfterMs=100)
            peer.tenants[str(company.id)] = t
            tenants.append(t)
        yield client, origin, peer, tenants
        assert not peer.errors, peer.errors


async def prepared(env, index=0):
    client, _origin, _peer, tenants = env
    t = tenants[index]
    payload = envelope(callRef=t["callRef"], phone="+79990000001", startedAt=now(), direction="inbound")
    r = await client.post(PREFIX + "/prepare", json=payload,
                          headers={"X-Cloud-API-Key": t["keys"][0][0]})
    assert r.status_code == 202, r.text
    return t


async def admitted(env, index=0):
    t = await prepared(env, index)
    client, origin, _peer, _tenants = env
    body = envelope(nodeId=t["callRef"]["nodeId"], admissionCode=t["code"])
    r = await client.post(PREFIX + "/admit", json=body,
                          headers={"DPoP": dpop(t["key"], origin + PREFIX + "/admit")})
    assert r.status_code == 200, r.text
    t["grant"] = r.json()["token"]
    t["claims"] = jwt.decode(t["grant"], env[2].public_key, algorithms=["RS256"], audience="support-context")
    return t


async def introspect(env, t, *, token=None, service=None):
    client, _origin, _peer, _tenants = env
    if service is None:
        issued = await client.post(PREFIX + "/service-token", json=envelope(),
                                   headers={"X-Cloud-API-Key": t["keys"][1][0]})
        assert issued.status_code == 200, issued.text
        service = issued.json()["token"]
    return await client.post(PREFIX + "/introspect", json=envelope(token=token or t["grant"],
                                                                 contextRef=t["contextRef"], callRef=t["callRef"]),
                             headers={"Authorization": "Bearer " + service})


def live_phase(t, phase, *, mask=None):
    t["node"].update(phase=phase, phaseDeadline=(
        datetime.now(timezone.utc) + timedelta(seconds=50)).isoformat()
        if phase in ("offering", "wrapup") else None)
    t["actor"]["fieldMask"] = mask or ("consult" if phase in ("offering", "consult") else "operator")


async def renew_grant(env, t, *, code=None, key=None, proof=None):
    client, origin, _peer, _tenants = env
    return await client.post(PREFIX + "/renew", json=envelope(
        nodeId=t["callRef"]["nodeId"], grantId=t["claims"]["grantId"],
        admissionCode=code or t["code"]), headers={
            "Authorization": "DPoP " + t["grant"],
            "DPoP": proof or dpop(key or t["key"], origin + PREFIX + "/renew", token=t["grant"]),
        })


@pytest.mark.parametrize("source,target", [("offering", "connected"), ("connected", "wrapup"),
                                          ("consult", "connected"), ("connected", "consult")])
async def test_renew_phase_issues_fresh_rights_without_upgrading_old_token(env, db, source, target):
    t = env[3][0]
    live_phase(t, source)
    t = await admitted(env)
    old_claims = t["claims"]
    r = await introspect(env, t)
    assert r.status_code == 200, r.text
    if source in ("offering", "consult"):
        assert r.json()["actions"] == ["context.details", "context.read"]
    live_phase(t, target)
    t["code"] = secrets.token_urlsafe(32)  # новый Node admission, не повтор /admit
    r = await introspect(env, t)
    assert r.status_code == 409 and r.json()["error"]["code"] == "phase_changed", r.text
    offset = len(env[2].requests)
    r = await renew_grant(env, t)
    assert r.status_code == 200, r.text
    assert [p.rsplit("/", 1)[1] for p, _c, _b in env[2].requests[offset:]] == [
        "status", "actor-resolve", "consume", "actor-resolve"]
    token = r.json()["token"]
    c = jwt.decode(token, env[2].public_key, algorithms=["RS256"], audience="support-context")
    assert c["phase"] == target and c["grantId"] != old_claims["grantId"]
    for name in ("sub", "act", "cnf", "callRef", "contextRef", "assignmentVersion",
                 "bindingVersion", "permissionsVersion"):
        assert c[name] == old_claims[name]
    expected = sorted(ALL_ACTIONS) if target in ("connected", "wrapup") else ["context.details", "context.read"]
    assert c["actions"] == expected
    if target == "wrapup":
        assert c["exp"] <= int(datetime.fromisoformat(t["node"]["phaseDeadline"]).timestamp())
    old = await db.get(ContextGrant, old_claims["grantId"], populate_existing=True)
    assert old.revoked_at
    r = await introspect(env, t)
    assert r.status_code == 403, r.text
    r = await introspect(env, t, token=token)
    assert r.status_code == 200 and r.json()["actions"] == expected, r.text
    assert r.json()["fieldMask"] == t["actor"]["fieldMask"]
    # Отзыв после успешного renewal виден следующей операции без positive cache.
    t["actor"]["active"] = False
    assert (await introspect(env, t, token=token)).status_code == 403


@pytest.mark.parametrize("change", ["revoke", "node_revoke", "inactive", "assignment", "act",
    "connection", "jkt", "binding", "binding_ref", "support_user", "permissions", "actor",
    "membership", "actor_active", "core_session", "mask_same_phase", "vendor", "assigned_ticket"])
async def test_renew_phase_keeps_identity_versions_revoke_and_mask_checks(env, db, change):
    t = env[3][0]
    live_phase(t, "offering")
    t = await admitted(env)
    live_phase(t, "connected")
    t["code"] = secrets.token_urlsafe(32)
    if change == "revoke":
        row = await db.get(ContextGrant, t["claims"]["grantId"])
        row.revoked_at = datetime.now(timezone.utc)
    elif change == "node_revoke":
        t["node"]["revoked"] = True
    elif change == "inactive":
        t["node"]["active"] = False
    elif change == "assignment":
        t["node"]["assignmentVersion"] += 1
    elif change == "act":
        t["node"]["act"] = {"iss": "https://foreign.invalid", "sub": "foreign"}
    elif change == "connection":
        t["node"]["connectionId"] = "foreign"
    elif change == "jkt":
        t["node"]["jkt"] = "x" * 43
    elif change == "binding":
        t["actor"]["bindingVersion"] += 1
    elif change == "binding_ref":
        t["actor"]["bindingRef"] = "foreign"
    elif change == "support_user":
        t["actor"]["supportUserRef"] = str(uuid.uuid4())
    elif change == "permissions":
        t["actor"]["permissionsVersion"] += 1
    elif change == "actor":
        t["actor"]["coreActorSub"] = str(uuid.uuid4())
    elif change == "membership":
        t["actor"]["membership"] = False
    elif change == "actor_active":
        t["actor"]["active"] = False
    elif change == "core_session":
        t["user"].token_version += 1
    elif change == "mask_same_phase":
        live_phase(t, "offering", mask="operator")  # валидный deadline, прежняя фаза
    else:
        t["actor"]["fieldMask"] = change
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    offset = len(env[2].requests)
    r = await renew_grant(env, t)
    assert r.status_code == 403, r.text
    assert not any(p.endswith("/consume") for p, _c, _b in env[2].requests[offset:])
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before


@pytest.mark.parametrize("change", ["bindingRef", "supportUserRef", "bindingVersion", "permissionsVersion"])
async def test_renew_rechecks_stable_binding_after_fresh_consume(env, db, change):
    t = env[3][0]
    live_phase(t, "offering")
    t = await admitted(env)
    live_phase(t, "connected")
    t["code"] = secrets.token_urlsafe(32)
    def mutate():
        value = t["actor"][change]
        t["actor"][change] = value + 1 if isinstance(value, int) else "foreign"
    env[2].on_consume = mutate
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await renew_grant(env, t)
    assert r.status_code == 403, r.text
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before
    old = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    assert old.revoked_at is None


async def test_renew_transition_denies_stolen_proof_and_replayed_code(env, db):
    t = env[3][0]
    live_phase(t, "offering")
    t = await admitted(env)
    used = t["code"]
    live_phase(t, "connected")
    t["code"] = secrets.token_urlsafe(32)
    r = await renew_grant(env, t, key=ec.generate_private_key(ec.SECP256R1()))
    assert r.status_code == 401, r.text
    for invalid_code in (used, secrets.token_urlsafe(32)):
        r = await renew_grant(env, t, code=invalid_code)
        assert r.status_code == 409, r.text
    proof = dpop(t["key"], env[1] + PREFIX + "/renew", token=t["grant"])
    r = await renew_grant(env, t, proof=proof)
    assert r.status_code == 200, r.text
    replacement = r.json()["token"]
    r = await renew_grant(env, t, proof=proof)
    assert r.status_code == 401 and r.json()["error"]["code"] == "replay", r.text
    t["grant"], t["claims"] = replacement, jwt.decode(
        replacement, env[2].public_key, algorithms=["RS256"], audience="support-context")
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await renew_grant(env, t)  # уже consumed code, но новый валидный proof
    assert r.status_code == 409, r.text
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before


async def test_real_http_two_companies_scoped_grants_and_opaque_prepare(env, db):
    client, _origin, peer, tenants = env
    for i in range(2):
        t = await admitted(env, i)
        c = t["claims"]
        assert c["sub"] == str(t["user"].id) and c["act"]["sub"] == "synthetic-operator"
        assert c["cid"] == t["cid"] and c["coreCid"] != c["cid"]
        assert c["exp"] - c["iat"] <= 120 and c["cnf"]["jkt"] == t["jkt"]
        assert "email" not in c and "phone" not in c
        r = await introspect(env, t)
        assert r.status_code == 200, r.text
        assert r.json()["active"] and r.json()["actions"] == sorted(ALL_ACTIONS)
        assert r.headers["Cache-Control"] == "private, no-store"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        row = await db.get(ContextGrant, c["grantId"])
        assert row and "+7999" not in json.dumps(row.claims)
    # Источник grant Б не даёт service клиента А introspection к Б.
    issued = await client.post(PREFIX + "/service-token", json=envelope(),
                               headers={"X-Cloud-API-Key": tenants[0]["keys"][1][0]})
    r = await introspect(env, tenants[1], service=issued.json()["token"])
    assert r.status_code == 403
    assert all("phone" not in json.dumps(b) for p, _c, b in peer.requests if not p.endswith("/prepare"))


@pytest.mark.parametrize("field,value,status", [
    ("act", {"iss": "https://foreign.invalid", "sub": "synthetic-operator"}, 403),
    ("assignmentVersion", 2, 403), ("active", False, 403),
    ("amr", ["pwd"], 403),
    ("contextRef", "scx_" + "x" * 43, 403),
    ("phase", "ended", 403), ("jkt", "x" * 43, 403),
])
async def test_live_assignment_revoke_mfa_and_foreign_context(env, field, value, status):
    t = await admitted(env)
    t["node"][field] = value
    # actor peer remains exact to new node act; Core must catch assignment mismatch first.
    r = await introspect(env, t)
    assert r.status_code == status, r.text


@pytest.mark.parametrize("change", ["session", "membership", "module", "object_scope", "locked", "support_active", "binding", "permissions"])
async def test_current_core_and_support_rights_are_not_cached(env, db, change):
    t = await admitted(env)
    if change == "session":
        t["user"].token_version += 1
    elif change == "membership":
        await db.delete(t["member"])
    elif change == "module":
        t["member"].role, t["member"].modules = "user", []
    elif change == "object_scope":
        t["member"].role, t["member"].object_scope = "user", ["synthetic-object"]
    elif change == "locked":
        t["user"].locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    elif change == "support_active":
        t["actor"]["active"] = False
    elif change == "binding":
        t["actor"]["bindingVersion"] += 1
    elif change == "permissions":
        t["actor"]["permissionsVersion"] += 1
    await db.commit()
    r = await introspect(env, t)
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("mutation", ["kid", "aud", "iss", "scope", "expiry", "company", "call", "actor", "context", "service"])
async def test_real_signed_wrong_tokens_never_fallback(env, mutation):
    t = await admitted(env)
    c = copy.deepcopy(t["claims"])
    headers = {"kid": sso.settings.sso_kid, "typ": "at+jwt"}
    if mutation == "kid":
        headers["kid"] = "foreign-kid"
    elif mutation == "aud":
        c["aud"] = "support"
    elif mutation == "iss":
        c["iss"] = "foreign-core"
    elif mutation == "scope":
        c["scp"] = "admin"
    elif mutation == "expiry":
        c.update(iat=int(time.time()) - 200, nbf=int(time.time()) - 200, exp=int(time.time()) - 80)
    elif mutation == "company":
        c["coreCid"] = env[3][1]["coreCid"]
    elif mutation == "call":
        c["callRef"]["nodeContactId"] = "foreign-call"
    elif mutation == "actor":
        c["sub"] = str(uuid.uuid4())
    elif mutation == "context":
        c["contextRef"] = env[3][1]["contextRef"]
    elif mutation == "service":
        c["sub"], c["svc"] = "service:support-context.prepare", "support-context.prepare"
    token = jwt.encode(c, sso._private_key(), algorithm="RS256", headers=headers)
    r = await introspect(env, t, token=token)
    assert r.status_code in (401, 403, 404), r.text


async def test_dpop_real_proofs_replay_durable_renew_and_host_binding(env, db):
    t = await admitted(env)
    t["code"] = secrets.token_urlsafe(32)
    client, origin, _peer, _tenants = env
    path = origin + PREFIX + "/renew"
    body = envelope(grantId=t["claims"]["grantId"], nodeId=t["callRef"]["nodeId"], admissionCode=t["code"])
    async def renew(proof, token=None):
        return await client.post(PREFIX + "/renew", json=body,
                                  headers={"Authorization": "DPoP " + (token or t["grant"]), "DPoP": proof})
    wrong = ec.generate_private_key(ec.SECP256R1())
    for invalid in [dpop(wrong, path, token=t["grant"]),
                    dpop(t["key"], "https://attacker.invalid" + PREFIX + "/renew", token=t["grant"]),
                    dpop(t["key"], path, token=t["grant"], ath="wrong"),
                    dpop(t["key"], path, token=t["grant"], htm="GET"),
                    dpop(t["key"], path, token=t["grant"], iat=int(time.time()) - 90)]:
        r = await renew(invalid)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "DPoP", r.text
    proof = dpop(t["key"], path, token=t["grant"])
    r = await renew(proof)
    assert r.status_code == 200, r.text
    replacement = r.json()["token"]
    assert replacement != t["grant"]
    r = await renew(proof)
    assert r.status_code == 401 and r.json()["error"]["code"] == "replay"
    r = await introspect(env, t)
    assert r.status_code == 403
    r = await introspect(env, t, token=replacement)
    assert r.status_code == 200
    assert (await db.scalar(select(func.count()).select_from(ContextReplay))) > 0
    # Новый интерпретатор/engine: replay не зависит от памяти ASGI worker.
    from app.services.support_context_protocol import digest
    proof_id = jwt.decode(proof, options={"verify_signature": False})["jti"]
    replay_key = digest(t["jkt"] + ":" + proof_id)
    script = """
import asyncio, os, sys
os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
from fastapi import HTTPException
from app.database import async_session_factory, engine
from app.services.support_context import replay
async def main():
    async with async_session_factory() as db:
        try:
            await replay(db, sys.argv[1])
        except HTTPException as e:
            assert e.status_code == 401
            print('durable-replay-denied')
        else:
            raise AssertionError('replay accepted by second process')
    await engine.dispose()
asyncio.run(main())
"""
    child = await asyncio.create_subprocess_exec(sys.executable, "-c", script, replay_key,
                                                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await child.communicate()
    assert child.returncode == 0, stderr.decode()
    assert stdout.decode().strip() == "durable-replay-denied"


@pytest.mark.parametrize("phase,seconds,expected", [("offering", 40, 200), ("consult", 0, 200),
    ("wrapup", 40, 200), ("wrapup", -1, 403), ("ended", 40, 403), ("postcall", 4000, 403)])
async def test_phase_limits_and_ticket_specific_postcall(env, phase, seconds, expected):
    t = env[3][0]
    t["node"]["phase"] = phase
    if phase in ("wrapup", "offering"):
        t["node"]["phaseDeadline"] = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    t = await prepared(env)
    client, origin, _peer, _tenants = env
    r = await client.post(PREFIX + "/admit",
                          json=envelope(nodeId=t["callRef"]["nodeId"], admissionCode=t["code"]),
                          headers={"DPoP": dpop(t["key"], origin + PREFIX + "/admit")})
    assert r.status_code == expected, r.text
    if expected == 200:
        claims = jwt.decode(r.json()["token"], env[2].public_key, algorithms=["RS256"], audience="support-context")
        if phase in ("offering", "consult"):
            assert claims["actions"] == ["context.details", "context.read"]
        if phase == "postcall":
            assert claims["actions"] == ["ticket.append"] and claims["ticketRefs"] == ["synthetic-own-ticket"]
        if phase == "wrapup":
            assert claims["exp"] <= int(datetime.fromisoformat(t["node"]["phaseDeadline"]).timestamp())


async def test_prepare_key_scope_idempotency_and_response_allowlist(env, db):
    t = await prepared(env)
    client, _origin, peer, _tenants = env
    peer.tenants[t["coreCid"]]["prepare"]["secret"] = "synthetic-must-never-relay"
    t = await prepared(env)
    assert await db.scalar(select(func.count()).select_from(ContextBinding).where(
        ContextBinding.core_cid == t["coreCid"])) == 1
    payload = envelope(callRef=t["callRef"], phone="+79990000001", startedAt=now(), direction="inbound")
    for key in [t["keys"][1][0], t["keys"][2][0], env[3][1]["keys"][0][0]]:
        r = await client.post(PREFIX + "/prepare", json=payload, headers={"X-Cloud-API-Key": key})
        assert r.status_code in (403, 404), r.text
    for invalid, expected in [({**payload, "ticketRef": "foreign"}, 422),
                              ({**payload, "version": "future"}, 426), ({}, 428)]:
        r = await client.post(PREFIX + "/prepare", json=invalid, headers={"X-Cloud-API-Key": t["keys"][0][0]})
        assert r.status_code == expected and "phone" not in r.text
    r = await client.post(PREFIX + "/prepare", content=b"x" * (65536 + 1))
    assert r.status_code == 413


@pytest.mark.parametrize("state", ["preparing", "ready", "partial", "unavailable"])
@pytest.mark.parametrize("lost_binding", [False, True])
async def test_prepare_replay_accepts_current_state_without_new_binding_or_ttl(env, db, state, lost_binding):
    client, _origin, _peer, tenants = env
    t = tenants[0]
    payload = envelope(callRef=t["callRef"], phone="+79990000001", startedAt=now(), direction="inbound")
    headers = {"X-Cloud-API-Key": t["keys"][0][0]}
    initial = await client.post(PREFIX + "/prepare", json=payload, headers=headers)
    assert initial.status_code == 202, initial.text
    if lost_binding:
        # Support уже сохранил context; Core не успел записать binding до обрыва.
        row = await db.get(ContextBinding, t["contextRef"])
        await db.delete(row)
        await db.commit()
    t["prepare"].update(state=state, contextVersion=2, phone="synthetic-private", blocks={"private": True})
    r = await client.post(PREFIX + "/prepare", json=payload, headers=headers)
    assert r.status_code == 202, r.text
    result = r.json()
    assert result["state"] == state and result["contextVersion"] == 2
    for name in ("contextRef", "callRef", "preparedAt", "expiresAt"):
        assert result[name] == initial.json()[name]
    assert set(result) == set(initial.json()) and "synthetic-private" not in r.text
    assert await db.scalar(select(func.count()).select_from(ContextBinding).where(
        ContextBinding.core_cid == t["coreCid"])) == 1
    row = await db.get(ContextBinding, t["contextRef"], populate_existing=True)
    assert row.expires_at == datetime.fromisoformat(initial.json()["expiresAt"])


@pytest.mark.parametrize("mutation", [
    {"state": "expired"}, {"state": "future"}, {"state": None}, {"state": 1},
    {"state": True}, {"state": []}, {"state": {}}, {"state": ""},
    {"schemaVersion": True}, {"schemaVersion": 2}, {"version": "future"},
    {"contextVersion": True}, {"contextVersion": 0}, {"contextVersion": 1.5},
    {"contextRef": "foreign"}, {"preparedAt": "invalid"},
    {"preparedAt": "2026-10-20T00:00:00"}, {"expiresAt": "2000-01-01T00:00:00+00:00"},
    {"retryAfterMs": True}, {"retryAfterMs": 60001},
])
async def test_prepare_replay_rejects_malformed_or_expired_receipt(env, db, mutation):
    t = await prepared(env)
    t["prepare"].update(state="partial", contextVersion=2)
    t["prepare"].update(mutation)
    before = await db.get(ContextBinding, t["contextRef"])
    expiry = before.expires_at
    client = env[0]
    r = await client.post(PREFIX + "/prepare", json=envelope(
        callRef=t["callRef"], phone="+79990000001", startedAt=now(), direction="inbound"),
        headers={"X-Cloud-API-Key": t["keys"][0][0]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_invalid", r.text
    assert "phone" not in r.text and "synthetic-private" not in r.text
    row = await db.get(ContextBinding, t["contextRef"], populate_existing=True)
    assert row.expires_at == expiry


@pytest.mark.parametrize("mutation,status", [("ref", 409), ("expiry", 409), ("call", 503), ("ttl", 503)])
async def test_prepare_replay_rejects_conflicting_binding_or_extended_ttl(env, db, mutation, status):
    t = await prepared(env)
    initial = copy.deepcopy(t["prepare"])
    t["prepare"].update(state="ready", contextVersion=2)
    if mutation == "ref":
        t["prepare"]["contextRef"] = "scx_" + secrets.token_urlsafe(32)
    elif mutation == "expiry":
        t["prepare"]["expiresAt"] = (datetime.fromisoformat(initial["expiresAt"]) + timedelta(minutes=1)).isoformat()
    elif mutation == "call":
        t["prepare"]["callRef"] = {**t["callRef"], "nodeContactId": "foreign"}
    else:
        t["prepare"]["expiresAt"] = (datetime.fromisoformat(initial["preparedAt"]) + timedelta(hours=25)).isoformat()
    r = await env[0].post(PREFIX + "/prepare", json=envelope(
        callRef=t["callRef"], phone="+79990000001", startedAt=now(), direction="inbound"),
        headers={"X-Cloud-API-Key": t["keys"][0][0]})
    assert r.status_code == status, r.text
    assert await db.scalar(select(func.count()).select_from(ContextBinding).where(
        ContextBinding.core_cid == t["coreCid"])) == 1
    row = await db.get(ContextBinding, t["contextRef"], populate_existing=True)
    assert row.expires_at == datetime.fromisoformat(initial["expiresAt"])


@pytest.mark.parametrize("bad,status", [(None, 500), ([], 200), ({}, 200), ({"version": "future"}, 200)])
async def test_upstream_failure_is_explicit_and_no_retry_recursion(env, bad, status):
    t = await admitted(env)
    _client, _origin, peer, _tenants = env
    before = len(peer.requests)
    peer.bad_body, peer.status = bad, status
    r = await introspect(env, t)
    assert r.status_code == 503, r.text
    assert len(peer.requests) - before == 1


async def test_trust_config_uses_existing_admin_api_and_no_foreign_keys(env):
    client, _origin, _peer, tenants = env
    t = tenants[0]
    headers = {"Authorization": "Bearer " + token_for(t["user"])}
    r = await client.put(PREFIX + "/config", params={"company_id": t["coreCid"]},
                          json=envelope(config=t["config"]), headers=headers)
    assert r.status_code == 200, r.text
    cfg = copy.deepcopy(t["config"])
    cfg["introspectionKeyId"] = str(tenants[1]["keys"][1][1].id)
    r = await client.put(PREFIX + "/config", params={"company_id": t["coreCid"]}, json=envelope(config=cfg), headers=headers)
    assert r.status_code == 403, r.text
    r = await client.put(PREFIX + "/config", params={"company_id": tenants[1]["coreCid"]},
                          json=envelope(config=tenants[1]["config"]), headers=headers)
    assert r.status_code == 403, r.text


async def test_revoke_before_introspection_response_and_no_positive_cache(env, db):
    t = await admitted(env)
    peer = env[2]
    entered = threading.Event()
    release = threading.Event()
    def barrier():
        entered.set()
        assert release.wait(5)
    peer.on_status = barrier
    operation = asyncio.create_task(introspect(env, t))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        t["user"].token_version += 1
        await db.commit()
    finally:
        release.set()
    r = await operation
    assert r.status_code == 403, r.text
    peer.on_status = None
    # Новая операция после revoke также отвергается; не остаётся active=True cache.
    r = await introspect(env, t)
    assert r.status_code == 403


async def test_grant_and_bootstrap_revocation_and_feature_off(env, db):
    t = await admitted(env)
    r = await introspect(env, t)
    assert r.status_code == 200
    client = env[0]
    service = await client.post(PREFIX + "/service-token", json=envelope(),
                                headers={"X-Cloud-API-Key": t["keys"][1][0]})
    t["keys"][1][1].revoked_at = datetime.now(timezone.utc)
    await db.commit()
    r = await introspect(env, t, service=service.json()["token"])
    assert r.status_code == 403
    t["keys"][1][1].revoked_at = None
    await db.commit()
    revoke = await client.post(PREFIX + "/revoke", headers={"Authorization": "Bearer " + token_for(t["user"])},
                               json=envelope(grantId=t["claims"]["grantId"]))
    assert revoke.status_code == 200, revoke.text
    r = await introspect(env, t)
    assert r.status_code == 403
    t["voice"].config = {**t["voice"].config, "supportContext": {**t["config"], "enabled": False}}
    await db.commit()
    r = await client.post(PREFIX + "/service-token", json=envelope(),
                          headers={"X-Cloud-API-Key": t["keys"][1][0]})
    assert r.status_code == 403


async def test_prepare_timeout_or_admission_replayed_does_not_issue_grant(env, db):
    t = await prepared(env)
    client, origin, peer, _tenants = env
    peer.status = 409
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await client.post(PREFIX + "/admit", json=envelope(nodeId=t["callRef"]["nodeId"], admissionCode=t["code"]),
                          headers={"DPoP": dpop(t["key"], origin + PREFIX + "/admit")})
    assert r.status_code == 409, r.text
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before


async def postcall_ready(env, db, *, expired_source=False):
    t = await admitted(env)
    t["node"].update(phase="ended", active=False, allowedActions=[],
                     endedAt=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())
    t["actor"].update(fieldMask="assigned_ticket", ticketRefs=["synthetic-own-ticket"],
                      capabilities=["ticket.read", "ticket.append"])
    if expired_source:
        from app.services.support_context_protocol import digest
        c = {**t["claims"], "iat": int(time.time()) - 300, "nbf": int(time.time()) - 300,
             "exp": int(time.time()) - 180}
        t["grant"] = jwt.encode(c, sso._private_key(), algorithm="RS256",
                                headers={"kid": sso.settings.sso_kid, "typ": "at+jwt"})
        row = await db.get(ContextGrant, c["grantId"])
        row.claims, row.digest = c, digest(t["grant"])
        row.expires_at = datetime.fromtimestamp(c["exp"], timezone.utc)
        await db.commit()
    return t


async def postcall_request(env, t, ticket="synthetic-own-ticket", key=None):
    client, origin, _peer, _tenants = env
    return await client.post(PREFIX + "/postcall", json=envelope(grantId=t["claims"]["grantId"], ticketRef=ticket),
                             headers={"DPoP": dpop(key or t["key"], origin + PREFIX + "/postcall")})


async def postcall_wrapup(env):
    t = env[3][0]
    live_phase(t, "wrapup")
    t = await admitted(env)
    t["actor"].update(fieldMask="assigned_ticket", ticketRefs=["synthetic-own-ticket"],
                      capabilities=["ticket.read", "ticket.append"])
    return t


def boundary_evidence(name, data):
    import os
    from pathlib import Path
    if prefix := os.environ.get("R26_EVIDENCE_PREFIX"):
        Path(prefix + "-" + name + ".json").write_text(json.dumps(data, indent=2) + "\n")


async def test_postcall_pending_crosses_live_deadline_during_actor_http(env, db):
    t = await postcall_wrapup(env)
    client, origin, peer, _tenants = env
    from app.database import async_session_factory
    loop = asyncio.get_running_loop()
    trace = {}

    def on_status():
        # Node status законно подтверждает wrapup до deadline. Только реальное
        # время HTTP actor-resolve пересекает его; SQL/часы не подменяются.
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1)
        t["node"]["phaseDeadline"] = deadline.isoformat()
        trace["nodeDeadline"] = deadline.isoformat()

    async def barrier():
        trace["actorHttpStartedAt"] = now()
        assert datetime.fromisoformat(trace["actorHttpStartedAt"]) < datetime.fromisoformat(trace["nodeDeadline"])
        async with async_session_factory() as other:
            root = await other.scalar(select(ContextGrant).where(
                ContextGrant.grant_id == t["claims"]["grantId"]).with_for_update(nowait=True))
            assert root.revoked_at is None
            trace["rootLockNowaitAcquired"] = True
            await other.commit()
        await asyncio.sleep(max(0, datetime.fromisoformat(trace["nodeDeadline"]).timestamp() - time.time() + .02))
        trace["actorHttpFinishedAt"] = now()

    peer.on_status = on_status
    peer.on_actor_resolve = lambda: asyncio.run_coroutine_threadsafe(barrier(), loop).result(timeout=2.5)
    row = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    original = (copy.deepcopy(row.claims), copy.deepcopy(row.authority), row.expires_at, row.revoked_at)
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    proof = dpop(t["key"], origin + PREFIX + "/postcall")
    body = envelope(grantId=t["claims"]["grantId"], ticketRef="synthetic-own-ticket")
    r = await client.post(PREFIX + "/postcall", json=body, headers={"DPoP": proof})
    row = await db.get(ContextGrant, row.grant_id, populate_existing=True)
    trace.update(status=r.status_code, error=r.json().get("error"),
                 sourceUnchanged=(row.claims, row.authority, row.expires_at, row.revoked_at) == original,
                 grantCountUnchanged=await db.scalar(select(func.count()).select_from(ContextGrant)) == before)
    boundary_evidence("actor-deadline-crossing", trace)
    assert datetime.fromisoformat(trace["actorHttpFinishedAt"]) > datetime.fromisoformat(trace["nodeDeadline"])
    assert trace["sourceUnchanged"] and trace["grantCountUnchanged"]
    assert r.status_code == 409, r.text
    assert r.json()["error"] == {"code": "postcall_pending", "retryable": True}
    assert set(r.json()) == {"version", "schemaVersion", "error", "requestRef"}
    r = await client.post(PREFIX + "/postcall", json=body, headers={"DPoP": proof})
    assert r.status_code == 401 and r.json()["error"]["code"] == "replay", r.text


async def test_postcall_pending_context_ttl_crossing_during_actor_http_is_denied(env, db):
    t = await postcall_wrapup(env)
    client, origin, peer, _tenants = env
    # Context TTL остаётся самостоятельной границей, даже когда expired live
    # projection допустима лишь для ожидания ended.
    context_exp = datetime.now(timezone.utc) + timedelta(seconds=1.5)
    bound = await db.get(ContextBinding, t["contextRef"])
    bound.expires_at = context_exp
    await db.commit()
    t["node"].update(active=False, phaseDeadline=(
        datetime.now(timezone.utc) - timedelta(milliseconds=8)).isoformat())
    trace = {"contextExpiresAt": context_exp.isoformat()}

    def barrier():
        trace["actorHttpStartedAt"] = now()
        assert datetime.now(timezone.utc) < context_exp
        time.sleep(max(0, context_exp.timestamp() - time.time() + .02))
        trace["actorHttpFinishedAt"] = now()

    peer.on_actor_resolve = barrier
    row = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    original = (copy.deepcopy(row.claims), copy.deepcopy(row.authority), row.expires_at, row.revoked_at)
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await postcall_request(env, t)
    row = await db.get(ContextGrant, row.grant_id, populate_existing=True)
    trace.update(status=r.status_code, error=r.json().get("error"),
                 sourceUnchanged=(row.claims, row.authority, row.expires_at, row.revoked_at) == original,
                 grantCountUnchanged=await db.scalar(select(func.count()).select_from(ContextGrant)) == before)
    boundary_evidence("context-ttl-crossing", trace)
    assert trace["sourceUnchanged"] and trace["grantCountUnchanged"]
    assert r.status_code == 403 and r.json()["error"] == {"code": "context_expired", "retryable": False}, r.text


@pytest.mark.parametrize("active", [True, False])
async def test_postcall_pending_expired_live_projection_then_ended(env, db, active):
    t = await postcall_wrapup(env)
    deadline = datetime.now(timezone.utc) - timedelta(milliseconds=8)
    t["node"].update(phase="wrapup", active=active, phaseDeadline=deadline.isoformat())
    row = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    original = (copy.deepcopy(row.claims), copy.deepcopy(row.authority), row.expires_at, row.revoked_at)
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await postcall_request(env, t)
    row = await db.get(ContextGrant, row.grant_id, populate_existing=True)
    trace = dict(nodePhase="wrapup", active=active, revoked=False, liveDeadline=deadline.isoformat(),
                 responseAt=now(), status=r.status_code, error=r.json().get("error"),
                 sourceUnchanged=(row.claims, row.authority, row.expires_at, row.revoked_at) == original,
                 grantCountUnchanged=await db.scalar(select(func.count()).select_from(ContextGrant)) == before)
    boundary_evidence("expired-live-" + str(active).lower(), trace)
    assert trace["sourceUnchanged"] and trace["grantCountUnchanged"]
    assert r.status_code == 409, r.text
    assert r.json()["error"] == {"code": "postcall_pending", "retryable": True}
    # Это не допускает действия через прежний live token даже до его JWT exp.
    assert (await introspect(env, t)).status_code == 403
    ended = datetime.now(timezone.utc)
    t["node"].update(phase="ended", active=False, allowedActions=[], endedAt=ended.isoformat())
    r = await postcall_request(env, t)  # свежий proof, обязательное ended
    assert r.status_code == 200, r.text
    c = jwt.decode(r.json()["token"], env[2].public_key, algorithms=["RS256"], audience="support-context")
    assert c["scp"] == "ticket_postcall" and c["ticketRefs"] == ["synthetic-own-ticket"]
    assert c["actions"] == ["ticket.append", "ticket.read"] and c["exp"] - c["iat"] <= 120
    granted = await db.get(ContextGrant, c["grantId"], populate_existing=True)
    assert datetime.fromisoformat(granted.authority["postcallDeadline"]) == ended + timedelta(seconds=3600)
    trace.update(endedStatus=r.status_code, endedAt=ended.isoformat(), actions=c["actions"],
                 ticketRefs=c["ticketRefs"], hardDeadline=granted.authority["postcallDeadline"])
    boundary_evidence("expired-live-" + str(active).lower(), trace)


async def test_postcall_initial_wrapup_pending_then_ended_with_new_proof(env, db):
    t = env[3][0]
    # Настоящий exp округляется вниз; ждём его истечения, оставляя дробную
    # часть допустимого wrapup. Ни JWT/SQL phase, ни часы Core не подменяются.
    live_phase(t, "wrapup")
    phase_deadline = datetime.fromtimestamp(int(time.time()) + 3.95, timezone.utc)
    t["node"]["phaseDeadline"] = phase_deadline.isoformat()
    t = await admitted(env)
    t["actor"].update(fieldMask="assigned_ticket", ticketRefs=["synthetic-own-ticket"],
                      capabilities=["ticket.read", "ticket.append"])
    assert t["claims"]["exp"] == int(phase_deadline.timestamp())
    source = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    original = (copy.deepcopy(source.claims), copy.deepcopy(source.authority), source.expires_at)
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    await asyncio.sleep(max(0, t["claims"]["exp"] - time.time() + .01))
    assert datetime.now(timezone.utc) < phase_deadline
    assert (await introspect(env, t)).status_code == 401
    client, origin, peer, _tenants = env
    proof = dpop(t["key"], origin + PREFIX + "/postcall")
    body = envelope(grantId=t["claims"]["grantId"], ticketRef="synthetic-own-ticket")
    offset = len(peer.requests)
    r = await client.post(PREFIX + "/postcall", json=body, headers={"DPoP": proof})
    assert r.status_code == 409, r.text
    assert r.json()["error"] == {"code": "postcall_pending", "retryable": True}
    assert set(r.json()) == {"version", "schemaVersion", "error", "requestRef"}
    assert r.headers["Cache-Control"] == "private, no-store"
    assert [p.rsplit("/", 1)[1] for p, _c, _b in peer.requests[offset:]] == ["status", "actor-resolve"]
    assert peer.requests[-1][2]["phase"] == "postcall"
    assert peer.requests[-1][2]["ticketRefs"] == ["synthetic-own-ticket"]
    assert peer.requests[-1][2]["expectedBindingVersion"] == t["claims"]["bindingVersion"]
    assert peer.requests[-1][2]["expectedPermissionsVersion"] == t["claims"]["permissionsVersion"]
    source = await db.get(ContextGrant, source.grant_id, populate_existing=True)
    assert (source.claims, source.authority, source.expires_at) == original
    assert source.revoked_at is None and "postcallDeadline" not in source.authority
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before
    # Ошибка тоже расходует DPoP: durable replay, а не повтор права.
    r = await client.post(PREFIX + "/postcall", json=body, headers={"DPoP": proof})
    assert r.status_code == 401 and r.json()["error"]["code"] == "replay", r.text
    assert (await introspect(env, t)).status_code == 401
    # Peer подтверждает ended только после реального истечения своего deadline.
    await asyncio.sleep(max(0, phase_deadline.timestamp() - time.time() + .01))
    ended = datetime.now(timezone.utc)
    t["node"].update(phase="ended", active=False, allowedActions=[], endedAt=ended.isoformat())
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    c = jwt.decode(token, peer.public_key, algorithms=["RS256"], audience="support-context")
    assert c["scp"] == "ticket_postcall" and c["phase"] == "postcall"
    assert c["ticketRefs"] == ["synthetic-own-ticket"]
    assert c["actions"] == ["ticket.append", "ticket.read"]
    assert c["exp"] - c["iat"] <= 120
    granted = await db.get(ContextGrant, c["grantId"], populate_existing=True)
    hard = granted.authority["postcallDeadline"]
    assert datetime.fromisoformat(hard) == ended + timedelta(seconds=3600)
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before + 1
    r = await introspect(env, t, token=token)
    assert r.status_code == 200 and r.json()["actions"] == ["ticket.append", "ticket.read"], r.text
    assert r.json()["fieldMask"] == "assigned_ticket"
    # Сдвиг endedAt от peer не продлевает уже закреплённый hard deadline.
    t["node"]["endedAt"] = now()
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    again = await db.get(ContextGrant, r.json()["grantId"], populate_existing=True)
    assert again.authority["postcallDeadline"] == hard


@pytest.mark.parametrize("reason", [
    "node_revoke", "source_revoke", "assignment", "act", "connection", "jkt",
    "admission", "call", "context", "mfa", "connected",
    "binding", "binding_ref", "support_user", "permissions", "actor", "membership",
    "actor_active", "unassigned", "wrong_ticket", "mask", "no_capabilities",
    "core_session", "core_membership", "core_module", "core_scope", "context_expired",
    "existing_deadline", "expired_hard_deadline", "policy_disabled",
])
async def test_postcall_pending_never_masks_permanent_denial(env, db, reason):
    t = await postcall_wrapup(env)
    # Даже при задержавшейся expired/inactive live-проекции все настоящие
    # отказы остаются окончательными по уточнённому sidecar R26.
    t["node"].update(active=False, phaseDeadline=(
        datetime.now(timezone.utc) - timedelta(milliseconds=8)).isoformat())
    row = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    original_authority = copy.deepcopy(row.authority)
    if reason == "node_revoke":
        t["node"]["revoked"] = True
    elif reason == "source_revoke":
        row.revoked_at = datetime.now(timezone.utc)
    elif reason == "assignment":
        t["node"]["assignmentVersion"] += 1
    elif reason == "act":
        t["node"]["act"] = {**t["node"]["act"], "sub": "synthetic-other-operator"}
    elif reason == "connection":
        t["node"]["connectionId"] = "synthetic-other-connection"
    elif reason == "jkt":
        t["node"]["jkt"] = "synthetic-other-key"
    elif reason == "admission":
        t["node"]["admissionRef"] = "synthetic-other-admission"
    elif reason == "call":
        t["node"]["callRef"] = {**t["callRef"], "nodeContactId": "synthetic-other-call"}
    elif reason == "context":
        t["node"]["contextRef"] = "scx_" + secrets.token_urlsafe(32)
    elif reason == "mfa":
        t["node"]["amr"] = ["pwd"]
    elif reason == "connected":
        t["node"]["phase"] = "connected"
    elif reason == "binding":
        t["actor"]["bindingVersion"] += 1
    elif reason == "binding_ref":
        t["actor"]["bindingRef"] = "synthetic-other-binding"
    elif reason == "support_user":
        t["actor"]["supportUserRef"] = str(uuid.uuid4())
    elif reason == "permissions":
        t["actor"]["permissionsVersion"] += 1
    elif reason == "actor":
        t["actor"]["coreActorSub"] = str(uuid.uuid4())
    elif reason == "membership":
        t["actor"]["membership"] = False
    elif reason == "actor_active":
        t["actor"]["active"] = False
    elif reason == "unassigned":
        t["actor"]["ticketRefs"] = []
    elif reason == "mask":
        t["actor"]["fieldMask"] = "operator"
    elif reason == "no_capabilities":
        t["actor"]["capabilities"] = []
    elif reason == "core_session":
        t["user"].token_version += 1
    elif reason == "core_membership":
        await db.delete(t["member"])
    elif reason == "core_module":
        t["member"].role, t["member"].modules = "user", ["voice"]
    elif reason == "core_scope":
        t["member"].object_scope = ["synthetic-other-object"]
    elif reason == "context_expired":
        bound = await db.get(ContextBinding, t["contextRef"])
        bound.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif reason == "policy_disabled":
        t["voice"].config = {"supportContext": {**t["config"], "postcallMaxSec": 0}}
    elif reason in ("existing_deadline", "expired_hard_deadline"):
        hard = datetime.now(timezone.utc) + timedelta(seconds=60 if reason == "existing_deadline" else -1)
        row.authority = {**row.authority, "postcallDeadline": hard.isoformat()}
        original_authority = copy.deepcopy(row.authority)
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await postcall_request(env, t, ticket="synthetic-foreign-ticket" if reason == "wrong_ticket"
                               else "synthetic-own-ticket")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] != "postcall_pending"
    assert r.json()["error"]["retryable"] is False
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before
    row = await db.get(ContextGrant, row.grant_id, populate_existing=True)
    assert row.authority == original_authority


@pytest.mark.parametrize("bad_deadline", ["missing", None, "not-a-date", "2026-10-21T01:00:00", 0, "1792542170", {}])
async def test_postcall_pending_rejects_malformed_wrapup_projection(env, db, bad_deadline):
    t = await postcall_wrapup(env)
    t["node"]["active"] = False
    if bad_deadline == "missing":
        del t["node"]["phaseDeadline"]
    else:
        t["node"]["phaseDeadline"] = bad_deadline
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    offset = len(env[2].requests)
    r = await postcall_request(env, t)
    assert r.status_code == 503 and r.json()["error"]["code"] == "node_invalid", r.text
    assert not any(path.endswith("/actor-resolve") for path, _c, _b in env[2].requests[offset:])
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before
    root = await db.get(ContextGrant, t["claims"]["grantId"], populate_existing=True)
    assert not root.revoked_at and "postcallDeadline" not in root.authority


@pytest.mark.parametrize("change", ["revoke", "core_membership", "core_session", "core_scope", "deadline"])
async def test_postcall_pending_rechecks_core_after_peer_http_without_lock(env, db, change):
    t = await postcall_wrapup(env)
    grant_id = t["claims"]["grantId"]
    from app.database import async_session_factory
    loop = asyncio.get_running_loop()

    async def mutate():
        async with async_session_factory() as other:
            if change in ("revoke", "deadline"):
                row = await other.scalar(select(ContextGrant).where(
                    ContextGrant.grant_id == grant_id).with_for_update(nowait=True))
                if change == "revoke":
                    row.revoked_at = datetime.now(timezone.utc)
                else:
                    row.authority = {**row.authority, "postcallDeadline": (
                        datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}
            elif change == "core_membership":
                row = await other.get(UserCompany, (t["user"].id, t["company"].id))
                await other.delete(row)
            elif change == "core_session":
                row = await other.get(User, t["user"].id)
                row.token_version += 1
            else:
                row = await other.get(UserCompany, (t["user"].id, t["company"].id))
                row.object_scope = ["synthetic-new-scope"]
            await other.commit()

    def on_status():
        asyncio.run_coroutine_threadsafe(mutate(), loop).result(timeout=2)

    env[2].on_status = on_status
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    r = await postcall_request(env, t)
    assert r.status_code == 403 and r.json()["error"]["code"] != "postcall_pending", r.text
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before


async def test_postcall_existing_grant_phase_rollback_is_strict(env, db):
    t = await postcall_ready(env, db)
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    postcall_grant = r.json()
    live_phase(t, "wrapup")
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    for grant_id in (t["claims"]["grantId"], postcall_grant["grantId"]):
        r = await env[0].post(PREFIX + "/postcall", json=envelope(
            grantId=grant_id, ticketRef="synthetic-own-ticket"), headers={
                "DPoP": dpop(t["key"], env[1] + PREFIX + "/postcall")})
        assert r.status_code == 403 and r.json()["error"]["code"] == "postcall_revoked", r.text
    r = await introspect(env, t, token=postcall_grant["token"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "postcall_revoked", r.text
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before


async def test_postcall_expired_live_access_gets_only_assigned_ticket_and_fixed_deadline(env, db):
    t = await postcall_ready(env, db, expired_source=True)
    r = await introspect(env, t)
    assert r.status_code == 401, r.text
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    c = jwt.decode(token, env[2].public_key, algorithms=["RS256"], audience="support-context")
    assert c["scp"] == "ticket_postcall" and c["phase"] == "postcall"
    assert c["ticketRefs"] == ["synthetic-own-ticket"] and c["actions"] == ["ticket.append", "ticket.read"]
    r = await introspect(env, t, token=token)
    assert r.status_code == 200 and r.json()["fieldMask"] == "assigned_ticket", r.text
    assert "context.read" not in r.json()["actions"]
    row = await db.get(ContextGrant, c["grantId"])
    hard = row.authority["postcallDeadline"]
    # Новый запрос не переоткрывает час от последнего обращения.
    t["node"]["endedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    second = await db.get(ContextGrant, r.json()["grantId"])
    assert second.authority["postcallDeadline"] == hard
    r = await postcall_request(env, t, ticket="synthetic-foreign-ticket")
    assert r.status_code == 403
    r = await postcall_request(env, t, key=ec.generate_private_key(ec.SECP256R1()))
    assert r.status_code == 401


@pytest.mark.parametrize("reason", ["node_revoke", "source_revoke", "binding", "deadline", "session", "transfer"])
async def test_postcall_denies_real_revocation_foreign_operator_and_expiry(env, db, reason):
    t = await postcall_ready(env, db, expired_source=True)
    if reason == "node_revoke":
        t["node"]["revoked"] = True
    elif reason == "source_revoke":
        row = await db.get(ContextGrant, t["claims"]["grantId"])
        row.revoked_at = datetime.now(timezone.utc)
    elif reason == "binding":
        t["actor"]["bindingVersion"] += 1
    elif reason == "deadline":
        t["node"]["endedAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    elif reason == "session":
        t["user"].token_version += 1
    elif reason == "transfer":
        t["node"]["assignmentVersion"] += 1
    await db.commit()
    r = await postcall_request(env, t)
    assert r.status_code == 403, r.text


async def test_postcall_vendor_receives_only_own_technical_ticket(env, db):
    t = await postcall_ready(env, db)
    t["actor"].update(fieldMask="vendor", capabilities=["ticket.read"])
    r = await postcall_request(env, t)
    assert r.status_code == 200, r.text
    r = await introspect(env, t, token=r.json()["token"])
    assert r.status_code == 200 and r.json()["actions"] == ["ticket.read"], r.text
    assert r.json()["fieldMask"] == "vendor"
    r = await postcall_request(env, t, ticket="synthetic-other-vendor-ticket")
    assert r.status_code == 403


async def test_restricted_core_actor_keeps_own_object_scope(env, db):
    t = env[3][0]
    t["member"].role = "user"
    t["member"].modules = None
    t["member"].object_scope = ["synthetic-permitted-object"]
    await db.commit()
    t = await admitted(env)
    r = await introspect(env, t)
    assert r.status_code == 200, r.text
    assert r.json()["objectScope"] == ["synthetic-permitted-object"]
    assert r.json()["ownOrganizationId"] is None


async def test_upstream_timeout_is_bounded_and_issues_no_grant(env, db):
    t = await prepared(env)
    client, origin, peer, _tenants = env
    peer.delay = 4
    before = await db.scalar(select(func.count()).select_from(ContextGrant))
    started = time.monotonic()
    r = await client.post(PREFIX + "/admit", json=envelope(nodeId=t["callRef"]["nodeId"], admissionCode=t["code"]),
                          headers={"DPoP": dpop(t["key"], origin + PREFIX + "/admit")})
    assert r.status_code == 504, r.text
    assert time.monotonic() - started < 4
    assert await db.scalar(select(func.count()).select_from(ContextGrant)) == before
