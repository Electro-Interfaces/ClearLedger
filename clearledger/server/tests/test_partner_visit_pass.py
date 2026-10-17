"""Пропуск инженера поставщика в пространство клиента (`/eco/partner/visit`).

Ловим:
  * пропуск предъявляется второй раз (перехваченная ссылка входит наравне с хозяином);
  * пропуск без `kid`, от чужого издателя или на долгий срок принимается;
  * запись о поставщике ищется среди всех компаний контейнера, а не у той, куда пропуск;
  * сессия по пропуску открывает другие компании, где эта учётка тоже гость,
    переживает отключение связи и продлением становится обычной;
  * пропуск входит под здешней учёткой с тем же адресом (сотрудник, суперадмин).

Любой отказ — одним ответом `VISIT_REFUSED` (аудит 07.10.2026): подробности помогают
подбирать пропуск, поэтому тесты сверяют только код ответа.
"""
import contextlib
import json
import time
import uuid
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, PartnerSpace
from app.services import partner_bridge, sso

pytestmark = pytest.mark.asyncio(loop_scope="session")

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWK = json.loads(RSAAlgorithm.to_jwk(KEY.public_key()))
_JWK["kid"] = sso.settings.sso_kid
JWKS = {"keys": [_JWK]}


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


def _pass(code: str, slug: str, email: str, *, kid=sso.settings.sso_kid, **over) -> str:
    now = int(time.time())
    claims = {"iss": sso.settings.sso_issuer, "aud": f"space:{slug}", "sub": str(uuid.uuid4()),
              "email": email, "name": "Инженер Поддержки", "space": code,
              "jti": uuid.uuid4().hex, "iat": now, "nbf": now - 10, "exp": now + 120}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": kid} if kid else None)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def vendor(db: AsyncSession, monkeypatch):
    """Поставщик с одним кодом заведён у двух компаний контейнера."""
    code = f"elsy-{uuid.uuid4().hex[:6]}"
    ids = {}
    for slug in ("rushydro", "gig"):
        cid = (await db.execute(select(Company.id).where(Company.slug == slug))).scalar_one()
        p = PartnerSpace(company_id=cid, role="vendor", code=code, name="Поддержка ElsyPlus",
                         base_url=f"https://{slug}-vendor.test", is_active=True)
        db.add(p)
        await db.flush()
        ids[slug] = p.id
    await db.commit()
    jwks = AsyncMock(return_value=JWKS)
    monkeypatch.setattr(partner_bridge, "partner_jwks", jwks)
    return code, ids, jwks


async def test_pass_is_one_company_and_once(client: AsyncClient, db: AsyncSession, vendor):
    code, ids, jwks = vendor
    tag = uuid.uuid4().hex[:6]
    email = f"engineer-{tag}@elsyplus.ru"
    # Тот же инженер уже бывал гостем в другой компании контейнера (gig).
    r = await client.post("/api/eco/partner/visit", json={
        "token": _pass(code, "gig", email), "space": code})
    assert r.status_code == 200, r.text

    token = _pass(code, "rushydro", email)
    r = await client.post("/api/eco/partner/visit", json={"token": token, "space": code})
    assert r.status_code == 200, r.text
    assert jwks.await_args.args[0].id == ids["rushydro"], "ключи — у записи компании пропуска"
    session = r.json()["access_token"]
    claims = jwt.decode(session, options={"verify_signature": False})
    assert claims["scp"] == "visit" and claims["pvs"] == str(ids["rushydro"])
    assert claims["exp"] - time.time() <= 3600 + 5

    # Второй раз тот же пропуск не входит.
    again = await client.post("/api/eco/partner/visit", json={"token": token, "space": code})
    assert again.status_code == 403, again.text

    # Сессия видит только компанию пропуска, хотя учётка — гость и в gig.
    me = await client.get("/api/auth/me", headers=_h(session))
    assert me.status_code == 200, me.text
    assert [c["slug"] for c in me.json()["companies"]] == ["rushydro"]
    assert (await client.get("/api/inbound-keys", params={"company_id": "gig"},
                             headers=_h(session))).status_code == 403
    assert (await client.get("/api/voice/keys", params={"company_id": "gig"},
                             headers=_h(session))).status_code == 403

    # Продление сохраняет область и срок.
    ref = await client.post("/api/auth/refresh", headers=_h(session))
    assert ref.status_code == 200, ref.text
    renewed = jwt.decode(ref.json()["access_token"], options={"verify_signature": False})
    assert renewed["scp"] == "visit" and renewed["cid"] == claims["cid"]
    assert renewed["exp"] == claims["exp"]

    # Связь выключили — открытая сессия закрылась.
    partner = await db.get(PartnerSpace, ids["rushydro"])
    partner.is_active = False
    await db.commit()
    assert (await client.get("/api/auth/me", headers=_h(session))).status_code == 401
    partner.is_active = True
    await db.commit()


async def test_pass_goes_to_its_company_record(client: AsyncClient, vendor):
    code, ids, jwks = vendor
    r = await client.post("/api/eco/partner/visit", json={
        "token": _pass(code, "gig", f"e-{uuid.uuid4().hex[:6]}@elsyplus.ru"), "space": code})
    assert r.status_code == 200, r.text
    assert jwks.await_args.args[0].id == ids["gig"]
    assert r.json()["space"] == "gig"


@pytest.mark.parametrize("change", [
    {"kid": None},
    {"kid": "other/9"},
    {"iss": "someone"},
    {"exp": int(time.time()) + 3600},
    {"jti": None},
    {"space": "other"},
    {"aud": "space:nowhere"},
    {"exp": int(time.time()) - 60},
])
async def test_bad_passes_rejected(client: AsyncClient, vendor, change):
    from app.routers.space_bridge_router import VISIT_REFUSED

    code, _ids, _jwks = vendor
    token = _pass(code, "rushydro", f"bad-{uuid.uuid4().hex[:6]}@elsyplus.ru", **change)
    r = await client.post("/api/eco/partner/visit", json={"token": token, "space": code})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == VISIT_REFUSED, r.json()


async def test_local_account_does_not_enter_by_pass(client: AsyncClient, vendor):
    """Адрес из пропуска совпал со здешней учёткой — суперадмином или сотрудником."""
    code, _ids, _jwks = vendor
    r = await client.post("/api/eco/partner/visit", json={
        "token": _pass(code, "rushydro", "admin@clearledger.ru"), "space": code})
    assert r.status_code == 409, r.text


async def test_used_pass_is_fixed_before_reply(client: AsyncClient, vendor):
    """Отметка пропуска фиксируется до ответа: повтор не проходит и в окне до фиксации get_db."""
    code, _ids, _jwks = vendor
    token = _pass(code, "rushydro", f"once-{uuid.uuid4().hex[:6]}@elsyplus.ru")
    async with without_late_commit():
        first = await client.post("/api/eco/partner/visit", json={"token": token, "space": code})
        assert first.status_code == 200, first.text
        again = await client.post("/api/eco/partner/visit", json={"token": token, "space": code})
        assert again.status_code == 403, again.text
        me = await client.get("/api/auth/me", headers=_h(first.json()["access_token"]))
        assert me.status_code == 200, "гость и членство зафиксированы до ответа"
