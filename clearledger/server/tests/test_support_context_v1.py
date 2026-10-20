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
                        result = tenant["actor"]
                    elif self.path.endswith("/consume"):
                        assert c["svc"] == "support-context.admission"
                        assert body["admissionCode"] == tenant["code"]
                        assert body["jkt"] == tenant["jkt"]
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
