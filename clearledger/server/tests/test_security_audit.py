"""Исправления аудита безопасности 07.10.2026: отзыв входа, пропуск партнёра, пути, секреты."""
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from app import auth, rate_limit
from app.config import Settings
from app.routers import reconcile_router, space_bridge_router, station_console_router


def user(tv=0):
    return SimpleNamespace(id="u1", email="a@x.ru", token_version=tv)


def test_версия_входа_гасит_старые_токены():
    tok = auth.create_access_token("u1", "a@x.ru", tv=0)
    payload = auth.decode_token(tok)
    assert auth.session_valid(payload, user(0))
    assert not auth.session_valid(payload, user(1))  # пароль сменили — старый токен мёртв


def test_продление_не_дальше_предела_сессии():
    old = int(datetime.now(timezone.utc).timestamp()) - (auth.MAX_SESSION_DAYS + 1) * 86400
    payload = auth.decode_token(auth.create_access_token("u1", "a@x.ru", tv=0, auth_time=old))
    assert payload["at"] == old  # продление сохраняет момент входа
    assert not auth.session_valid(payload, user(0))


def test_путь_консоли_без_выхода_наверх():
    ok = station_console_router._path_ok
    for p in ("index.html", "api/prices", "static/app.js"):
        assert ok(p), p
    for p in ("../x", "a/../../x", "%2e%2e/x", "%252e%252e/x", "..%2fx", "a//b", "a\\b", "/etc"):
        assert not ok(p), p


def test_сверка_ходит_только_на_разрешённые_узлы():
    reconcile_router._check_external_url("https://pos.autooplata.ru/tms")
    for bad in ("http://pos.autooplata.ru/tms", "https://10.10.70.52/", "https://localhost/", "https://evil.example/"):
        with pytest.raises(HTTPException):
            reconcile_router._check_external_url(bad)


def test_слабый_секрет_опознаётся():
    assert Settings(SECRET_KEY="clearledger-dev-secret").secret_is_insecure
    assert Settings(SECRET_KEY="short").secret_is_insecure
    assert not Settings(SECRET_KEY="x" * 64).secret_is_insecure


def test_общий_ключ_хранится_хешем():
    v = auth.legacy_key_value("abc")
    assert v.startswith("sha256:") and "abc" not in v and len(v) == 71


def test_новые_публичные_ручки_под_лимитом():
    for path in ("/api/eco/partner/visit", "/api/auth/demo-session", "/api/work/calendar/feed/x.ics",
                 "/api/conf/recordings/ingest", "/api/site/pull/news"):
        assert rate_limit._group(path), path


@pytest.fixture()
def keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    jwk["kid"] = "k1"
    return priv, {"keys": [jwk]}


def visit(priv, **claims):
    now = int(time.time())
    base = {"aud": "space:rushydro", "email": "eng@desk.ru", "space": "desk", "iat": now, "exp": now + 120}
    base.update(claims)
    return jwt.encode({k: v for k, v in base.items() if v is not None}, priv, algorithm="RS256", headers={"kid": "k1"})


def test_пропуск_партнёра_срок_и_повтор(keys):
    priv, jwks = keys
    space_bridge_router._seen_visits.clear()
    tok = visit(priv)
    assert space_bridge_router._verify_visit(tok, jwks, audience="space:rushydro")["email"] == "eng@desk.ru"
    with pytest.raises(HTTPException):  # второй раз тот же пропуск — нет
        space_bridge_router._verify_visit(tok, jwks, audience="space:rushydro")
    now = int(time.time())
    for bad in (visit(priv, exp=None), visit(priv, iat=now, exp=now + 3600),
                visit(priv, aud="space:gig")):
        with pytest.raises(HTTPException) as e:
            space_bridge_router._verify_visit(bad, jwks, audience="space:rushydro")
        assert e.value.detail == space_bridge_router.VISIT_REFUSED  # без подробностей


@pytest.mark.asyncio
async def test_пропуск_не_входит_под_здешней_учёткой():
    class DB:
        def __init__(self, kinds):
            self.kinds = kinds

        async def execute(self, _q):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.kinds))
    guest = SimpleNamespace(id="g", is_superadmin=False)
    assert await space_bridge_router._bridge_guest(guest, DB(["vendor"]))
    assert not await space_bridge_router._bridge_guest(guest, DB(["vendor", "staff"]))
    assert not await space_bridge_router._bridge_guest(SimpleNamespace(id="s", is_superadmin=True), DB(["vendor"]))
