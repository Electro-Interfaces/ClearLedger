"""Токены Ядра для «Телефонии» (Я-10) и ключи систем для API узла.

Ловим:
  * в токене нет роли в приложении — узел пускает по роли в пространстве, и
    «Телефония» достаётся всем администраторам чего угодно;
  * суперадмин платформы получает роль в «Телефонии» — записи и номера это данные
    заказчика;
  * у токенов нет `jti` — узлу нечем отсечь повтор и найти выдачу в журнале;
  * ключ системы открывает больше своей области, живёт после отзыва или
    выдаётся не администратором.
"""
import base64
import contextlib
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, Company, SpaceInboundKey, User, UserCompany
from app.services import app_registry, sso

pytestmark = pytest.mark.asyncio(loop_scope="session")


@contextlib.asynccontextmanager
async def without_late_commit():
    """Запросы без фиксации из get_db: на стенде она идёт уже после отправки ответа.

    Всё, что ручка обещает ответом (ключ работает, пропуск сгорел, ключ отозван), должно
    быть зафиксировано ею самой до ответа. Здесь get_db в конце откатывает, а не
    коммитит, и запись, оставленная на его фиксацию, теряется так же, как в том окне.
    """
    import app.database as _db
    from app.database import get_db
    from app.main import app

    async def _rollback_db():
        async with _db.async_session_factory() as s:
            try:
                yield s
            finally:
                await s.rollback()

    app.dependency_overrides[get_db] = _rollback_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def sso_key(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    monkeypatch.setattr(sso.settings, "sso_signing_key", base64.b64encode(pem).decode())
    return key.public_key()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str, password: str = "secret12345") -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _user(client: AsyncClient, email: str, company: str, role: str) -> str:
    admin = await _login(client, "admin@clearledger.ru", "admin123")
    r = await client.post("/api/users", headers=_h(admin), json={
        "company_id": company, "email": email, "name": email.split("@")[0],
        "password": "secret12345", "role": role})
    assert r.status_code in (200, 201), r.text
    return await _login(client, email)


async def _voice(db: AsyncSession, slug: str, enabled: bool = True) -> uuid.UUID:
    await app_registry.seed_apps(db)
    cid = (await db.execute(select(Company.id).where(Company.slug == slug))).scalar_one()
    app_id = (await db.execute(select(App.id).where(App.code == "voice"))).scalar_one()
    await app_registry.set_app(db, cid, app_id, enabled)
    return cid


def _claims(token: str, pub) -> dict:
    return jwt.decode(token, pub, algorithms=["RS256"], audience="voice")


async def test_voice_token_carries_role_and_jti(client: AsyncClient, db: AsyncSession, sso_key):
    await _voice(db, "rushydro")
    tag = uuid.uuid4().hex[:6]
    admin = await _user(client, f"voice-admin-{tag}@test.ru", "rushydro", "admin")
    plain = await _user(client, f"voice-user-{tag}@test.ru", "rushydro", "user")
    named = await _user(client, f"voice-named-{tag}@test.ru", "rushydro", "user")
    uid = (await db.execute(select(User.id).where(User.email == f"voice-named-{tag}@test.ru"))).scalar_one()
    cid = (await db.execute(select(Company.id).where(Company.slug == "rushydro"))).scalar_one()
    m = await db.get(UserCompany, (uid, cid))
    m.app_roles = {"voice": "admin"}
    await db.commit()

    seen = set()
    for token, roles in ((admin, ["admin"]), (plain, []), (named, ["admin"])):
        r = await client.get("/api/sso/token", params={"app": "voice", "company_id": "rushydro"},
                             headers=_h(token))
        assert r.status_code == 200, r.text
        assert r.json()["roles"] == roles
        c = _claims(r.json()["token"], sso_key)
        assert c["roles"] == roles and c["cid"] == str(cid)
        assert len(c["jti"]) == 32 and c["jti"] not in seen
        seen.add(c["jti"])

    # Суперадмин роли в «Телефонии» не получает, даже состоя в компании.
    sa = await _login(client, "admin@clearledger.ru", "admin123")
    r = await client.get("/api/sso/token", params={"app": "voice", "company_id": "rushydro"},
                         headers=_h(sa))
    if r.status_code == 200:
        assert r.json()["roles"] == []


async def test_service_tokens_have_jti_and_scope(sso_key):
    tok = sso.sign_voice_service_token(scope="voice.stats", company_id=str(uuid.uuid4()))
    c = _claims(tok, sso_key)
    assert c["svc"] == "voice.stats" and c["exp"] - c["iat"] == 120 and c["jti"]
    with pytest.raises(ValueError):
        sso.sign_voice_service_token(scope="voice.calls", company_id=str(uuid.uuid4()))
    with pytest.raises(ValueError):
        sso.sign_voice_service_token(scope="voice.stats", company_id="")
    user = type("U", (), {"id": uuid.uuid4(), "email": "x@test.ru", "name": "X"})()
    one = jwt.decode(sso.sign_sso_token(user=user, company_id=None, companies=[], aud="a"),
                     sso_key, algorithms=["RS256"], audience="a")
    assert one["jti"] and "roles" not in one


async def test_system_keys_and_exchange(client: AsyncClient, db: AsyncSession, sso_key):
    cid = await _voice(db, "rushydro")
    tag = uuid.uuid4().hex[:6]
    admin = await _user(client, f"keys-admin-{tag}@test.ru", "rushydro", "admin")
    plain = await _user(client, f"keys-user-{tag}@test.ru", "rushydro", "user")

    body = {"company_id": "rushydro", "consumer": "Мониторинг заказчика", "scopes": ["voice.stats"]}
    assert (await client.post("/api/voice/keys", json=body, headers=_h(plain))).status_code == 403
    bad = await client.post("/api/voice/keys", json={**body, "scopes": ["voice.identify"]},
                            headers=_h(admin))
    assert bad.status_code == 422
    r = await client.post("/api/voice/keys", json=body, headers=_h(admin))
    assert r.status_code == 201, r.text
    issued = r.json()
    assert issued["scopes"] == ["voice.stats"] and issued["key"].startswith(issued["prefix"])

    listed = (await client.get("/api/voice/keys", params={"company_id": "rushydro"},
                               headers=_h(admin))).json()["keys"]
    row = next(k for k in listed if k["id"] == issued["id"])
    assert "key" not in row and row["last_used_at"] is None and row["revoked_at"] is None

    hdr = {"X-Cloud-API-Key": issued["key"]}
    r = await client.post("/api/eco/voice/token", json={}, headers=hdr)
    assert r.status_code == 200, r.text
    c = _claims(r.json()["token"], sso_key)
    assert c["svc"] == "voice.stats" and c["cid"] == str(cid) and c["jti"]
    assert c["actor"] == "Мониторинг заказчика" and c["exp"] - c["iat"] <= 120
    assert (await client.post("/api/eco/voice/token", json={"scope": "voice.audit"},
                              headers=hdr)).status_code == 403
    # Ключ системы не открывает ни опознание, ни общие машинные ручки.
    assert (await client.post("/api/eco/identify", json={"value": "+79001234567"},
                              headers=hdr)).status_code == 403
    assert (await client.post("/api/eco/events", json={"type": "ping"},
                              headers=hdr)).status_code == 403

    listed = (await client.get("/api/voice/keys", params={"company_id": "rushydro"},
                               headers=_h(admin))).json()["keys"]
    assert next(k for k in listed if k["id"] == issued["id"])["last_used_at"]

    # Общий ключ через экран «Телефонии» не отзывается и в список не попадает.
    general = SpaceInboundKey(company_id=cid, consumer="Общий", key_hash=uuid.uuid4().hex * 2,
                              key_prefix="gen")
    db.add(general)
    await db.commit()
    assert (await client.delete(f"/api/voice/keys/{general.id}", params={"company_id": "rushydro"},
                                headers=_h(admin))).status_code == 404

    r = await client.delete(f"/api/voice/keys/{issued['id']}", params={"company_id": "rushydro"},
                            headers=_h(admin))
    assert r.status_code == 204
    assert (await client.post("/api/eco/voice/token", json={}, headers=hdr)).status_code == 401
    listed = (await client.get("/api/voice/keys", params={"company_id": "rushydro"},
                               headers=_h(admin))).json()["keys"]
    assert next(k for k in listed if k["id"] == issued["id"])["revoked_at"]
    assert all(k["id"] != str(general.id) for k in listed)


async def test_exchange_needs_voice_enabled(client: AsyncClient, db: AsyncSession, sso_key):
    cid = await _voice(db, "gig")
    tag = uuid.uuid4().hex[:6]
    admin = await _user(client, f"gig-admin-{tag}@test.ru", "gig", "admin")
    r = await client.post("/api/voice/keys", headers=_h(admin), json={
        "company_id": "gig", "consumer": "BI", "scopes": ["voice.audit", "voice.stats"]})
    assert r.status_code == 201, r.text
    hdr = {"X-Cloud-API-Key": r.json()["key"]}
    assert (await client.post("/api/eco/voice/token", json={}, headers=hdr)).status_code == 422
    assert (await client.post("/api/eco/voice/token", json={"scope": "voice.audit"},
                              headers=hdr)).status_code == 200
    await _voice(db, "gig", False)
    assert (await client.post("/api/eco/voice/token", json={"scope": "voice.audit"},
                              headers=hdr)).status_code == 403
    assert (await client.get("/api/voice/keys", params={"company_id": "gig"},
                             headers=_h(admin))).status_code == 403


async def test_keys_are_fixed_before_reply(client: AsyncClient, db: AsyncSession, sso_key):
    """Выдача, обмен и отзыв ключа фиксируются до ответа (на стенде get_db коммитит после него).

    Ловим: отозванный ключ ещё меняется на токен следующим же запросом, только что
    выданный — не меняется, время обмена не появляется в списке."""
    await _voice(db, "rushydro")
    admin = await _user(client, f"late-admin-{uuid.uuid4().hex[:6]}@test.ru", "rushydro", "admin")
    async with without_late_commit():
        r = await client.post("/api/voice/keys", headers=_h(admin), json={
            "company_id": "rushydro", "consumer": "Мониторинг", "scopes": ["voice.stats"]})
        assert r.status_code == 201, r.text
        issued = r.json()
        hdr = {"X-Cloud-API-Key": issued["key"]}
        assert (await client.post("/api/eco/voice/token", json={}, headers=hdr)).status_code == 200
        row = next(k for k in (await client.get("/api/voice/keys", params={"company_id": "rushydro"},
                                                headers=_h(admin))).json()["keys"]
                   if k["id"] == issued["id"])
        assert row["last_used_at"], "время обмена зафиксировано"
        assert (await client.delete(f"/api/voice/keys/{issued['id']}", params={"company_id": "rushydro"},
                                    headers=_h(admin))).status_code == 204
        assert (await client.post("/api/eco/voice/token", json={}, headers=hdr)).status_code == 401

        # Ключ узла из «Управления» — так же: выдан и сразу работает, отозван и сразу нет.
        r = await client.post("/api/inbound-keys", headers=_h(admin), json={
            "company_id": "rushydro", "consumer": "Узел", "actor_kind": "agent",
            "scopes": ["voice.identify"]})
        assert r.status_code == 201, r.text
        node = {"X-Cloud-API-Key": r.json()["key"]}
        assert (await client.post("/api/eco/identify", json={"value": "+79001234567"},
                                  headers=node)).status_code == 200
        assert (await client.delete(f"/api/inbound-keys/{r.json()['id']}", params={"company_id": "rushydro"},
                                    headers=_h(admin))).status_code == 204
        assert (await client.post("/api/eco/identify", json={"value": "+79001234567"},
                                  headers=node)).status_code == 401
