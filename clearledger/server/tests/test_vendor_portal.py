import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.algorithms import RSAAlgorithm

from app.routers import vendor_router as vendor
from app.routers.space_bridge_router import _verify_visit
from app.services import app_registry, sso


@pytest.fixture
def signed_actor(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(sso, "_private_key", lambda: key)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = sso.settings.sso_kid
    user = SimpleNamespace(id=uuid.uuid4(), email="person@example.test")
    values = dict(user=user, company_id=str(uuid.uuid4()), self_code="customer",
                  vendor_code="supplier", operation="demo", demo_id="monitor")
    return key, {"keys": [jwk]}, values


def test_vendor_ticket_is_not_a_login_ticket(signed_actor):
    _, keys, values = signed_actor
    token = sso.sign_vendor_token(**values)
    claims = _verify_visit(token, keys, audience="vendor:supplier")
    assert claims["sub"] == str(values["user"].id)
    assert claims["operation"] == "demo"
    assert claims["demo_id"] == "monitor"
    assert claims["exp"] - claims["iat"] == 120
    with pytest.raises(HTTPException):
        _verify_visit(token, keys, audience="space:supplier")


@pytest.mark.parametrize("change", [{"exp": 1}, {"aud": "vendor:other"}])
def test_expired_or_wrong_recipient_rejected(signed_actor, change):
    key, keys, values = signed_actor
    claims = jwt.decode(sso.sign_vendor_token(**values), options={"verify_signature": False})
    claims.update(change)
    token = jwt.encode(claims, key, algorithm="RS256")
    with pytest.raises(HTTPException):
        _verify_visit(token, keys, audience="vendor:supplier")


@pytest.mark.parametrize("profile", [None, "fuel", "energy", "office", "retail", "unknown"])
def test_portal_never_appears_by_default(profile):
    assert not app_registry._default_app_on("elsy", profile)


@pytest.mark.asyncio
async def test_disabled_portal_rejects_even_full_access_user(monkeypatch):
    cid = uuid.uuid4()
    check = AsyncMock(return_value=cid)
    monkeypatch.setattr(vendor, "assert_company_product", check)
    partner = AsyncMock()
    monkeypatch.setattr(vendor.partner_bridge, "get_partner", partner)
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: None)))
    with pytest.raises(HTTPException) as error:
        await vendor._vendor(db, str(cid), "supplier", SimpleNamespace())
    assert error.value.status_code == 404
    assert check.call_args.args[3] == "elsy"
    partner.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"operation": "catalog"}, {"space": "other"}, {"sub": ""}, {"email": ""}])
async def test_actor_scope_checked_before_account_lookup(monkeypatch, signed_actor, change):
    key, keys, values = signed_actor
    claims = jwt.decode(sso.sign_vendor_token(**values), options={"verify_signature": False})
    claims.update(change)
    partner = SimpleNamespace(code="customer", counterparty_id=uuid.uuid4())
    monkeypatch.setattr(vendor.partner_bridge, "get_partner", AsyncMock(return_value=partner))
    monkeypatch.setattr(vendor.partner_bridge, "partner_jwks", AsyncMock(return_value=keys))
    db = SimpleNamespace(execute=AsyncMock())
    payload = vendor.VendorRequest(space="customer", token=jwt.encode(claims, key, algorithm="RS256"))
    with pytest.raises(HTTPException) as error:
        await vendor._client(db, SimpleNamespace(id=uuid.uuid4(), slug="supplier"), payload, "demo")
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_lookup_bound_to_relationship(monkeypatch, signed_actor):
    _, keys, values = signed_actor
    cid, counterparty = uuid.uuid4(), uuid.uuid4()
    partner = SimpleNamespace(code="customer", counterparty_id=counterparty)
    monkeypatch.setattr(vendor.partner_bridge, "get_partner", AsyncMock(return_value=partner))
    monkeypatch.setattr(vendor.partner_bridge, "partner_jwks", AsyncMock(return_value=keys))
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=lambda: None)))
    payload = vendor.VendorRequest(space="customer", token=sso.sign_vendor_token(**values))
    _, _, account = await vendor._client(db, SimpleNamespace(id=cid, slug="supplier"), payload, "demo")
    query = db.execute.call_args.args[0].compile()
    assert cid in query.params.values()
    assert counterparty in query.params.values()
    assert values["user"].email in query.params.values()
    assert "is_active IS true" in str(query)
    assert account is None
    assert not vendor._allowed(account, "monitor")


@pytest.mark.asyncio
async def test_revoked_demo_never_reaches_website(monkeypatch):
    monkeypatch.setattr(vendor, "_client", AsyncMock(return_value=(None, {"demo_id": "monitor"}, None)))
    call = AsyncMock()
    monkeypatch.setattr(vendor, "_call", call)
    with pytest.raises(HTTPException) as error:
        await vendor.provide_demo(vendor.VendorRequest(space="customer", token="token"), SimpleNamespace(), None)
    assert error.value.status_code == 403
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["https://other.test/demo-run/monitor/", "//other.test/", "/demo-run/support/"])
async def test_demo_redirect_cannot_leave_configured_site(monkeypatch, path):
    account = SimpleNamespace(email="person@example.test", demos=["monitor"])
    monkeypatch.setattr(vendor, "_client", AsyncMock(return_value=(None, {"demo_id": "monitor"}, account)))
    monkeypatch.setattr(vendor, "_call", AsyncMock(return_value={
        "connected": True, "url": "https://site.example.test", "data": {"url": path}}))
    with pytest.raises(HTTPException) as error:
        await vendor.provide_demo(vendor.VendorRequest(space="customer", token="token"), SimpleNamespace(id=uuid.uuid4()), None)
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_demo_returns_website_one_time_ticket(monkeypatch):
    account = SimpleNamespace(email="person@example.test", demos=["monitor"])
    monkeypatch.setattr(vendor, "_client", AsyncMock(return_value=(None, {"demo_id": "monitor"}, account)))
    call = AsyncMock(return_value={"connected": True, "url": "https://site.example.test",
        "data": {"url": "/demo-run/monitor/?t=one-time", "expires_in": 60}})
    monkeypatch.setattr(vendor, "_call", call)
    result = await vendor.provide_demo(vendor.VendorRequest(space="customer", token="token"), SimpleNamespace(id=uuid.uuid4()), None)
    assert result["url"] == "https://site.example.test/demo-run/monitor/?t=one-time"
    assert call.call_args.kwargs["json_body"] == {"email": account.email, "demo_id": "monitor"}
