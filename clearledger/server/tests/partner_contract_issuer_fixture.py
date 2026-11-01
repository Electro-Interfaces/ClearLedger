"""AUTHOR ONLY / NOTRUN, including imports/collection.

ROOT injects partner_contract_issuer_factory after its separate preimport/target/
schema4/Core/READ COMMITTED admission. No URL/env, provision, DROP, target selector
or runner here. Rows are exact synthetic UUIDs/opaque strings; ROOT retains the
returned owned IDs for bounded cleanup in its own admitted lifecycle.
"""
import base64
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.auth import token_for
from app.database import get_db
from app.models import (App, AuditEvent, Company, CompanyApp, CompanyRole, Contract,
    ContractLocation, Counterparty, Organization, ServiceLocation, User, UserCompany)
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant,
    PartnerInstallation, PartnerInstallationLocation, PartnerResourceItem, PartnerResourceScope)
from app.models_partner_contracts import (PartnerContractCreateProfile as Profile,
    PartnerContractCreatePrincipal as Principal, PartnerContractCreateRef as Ref,
    PartnerContractCreateType as Type, PartnerContractSuccessIntent as Intent,
    PartnerContractIntentLocation as IntentLocation)
from app.product_api.contract_create_body import ContractCreateBody
from app.routers import partner_oauth_router
from app.services import partner_identity as identity

REDIRECT = "https://issuer.synthetic.invalid/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


async def issue_machine(w, *, grant_id=None, secret=None, scope="contracts:create"):
    response = await w.http.post("/api/oauth2/token", auth=(w.client_id, secret or w.secret),
        data={"grant_type": "client_credentials", "grant_id": str(grant_id or w.machine_grant), "scope": scope})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def issue_user(w):
    response = await w.http.get("/api/oauth2/authorize", params={"client_id": w.client_id,
        "response_type": "code", "redirect_uri": REDIRECT, "scope": "contracts:create",
        "state": uuid4().hex, "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    assert response.status_code == 302, response.text
    rid = parse_qs(urlsplit(response.headers["location"]).query)["requestId"][0]
    headers = {"Authorization": "Bearer " + w.native}
    response = await w.http.get("/api/developer/authorization-requests/" + rid, headers=headers)
    assert response.status_code == 200, response.text
    response = await w.http.post("/api/developer/authorization-requests/" + rid + "/approve",
        headers=headers, json={"companyId": str(w.company), "scopes": ["contracts:create"]})
    assert response.status_code == 200, response.text
    code = parse_qs(urlsplit(response.json()["redirectUrl"]).query)["code"][0]
    response = await w.http.post("/api/oauth2/token", auth=(w.client_id, w.secret), data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": VERIFIER})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def make_body(w, **changes):
    raw = dict(kind="contract-card", creationKey=str(uuid4()), number="Synthetic " + uuid4().hex,
        date="2026-11-01", type="Synthetic contract", typeCode=w.code,
        organizationId=str(w.org), counterpartyId=str(w.cp),
        coverage={"kind": "locations", "locationIds": [w.loc]}, validUntil=None, comment=None)
    raw.update(changes)
    return ContractCreateBody.model_validate(raw)


async def state(w):
    """Independent fresh reader; no ORM identity-map/spy substitute for SQL."""
    async with w.factory() as db:
        ids = tuple(await db.scalars(select(Intent.id).where(Intent.company_id == w.company)))
        return tuple([await db.scalar(select(func.count()).select_from(model).where(model.company_id == w.company))
                      for model in (Contract, ContractLocation, Intent, AuditEvent)] + [
            await db.scalar(select(func.count()).select_from(IntentLocation).where(IntentLocation.intent_id.in_(ids)))])


@pytest_asyncio.fixture(loop_scope="session")
async def issuer_world(partner_contract_issuer_factory, monkeypatch):
    factory = partner_contract_issuer_factory  # Sole ROOT-owned actual factory.
    partner_oauth_router._hits.clear()  # Independent synthetic HTTP client budget.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    for name, value in {"partner_oauth_enabled": True,
            "partner_oauth_issuer": "https://issuer.synthetic.invalid",
            "partner_oauth_audience": "urn:synthetic:contract-issuer",
            "partner_oauth_kid": "synthetic/issuer", "partner_oauth_signing_key": base64.b64encode(pem).decode()}.items():
        monkeypatch.setattr(identity.settings, name, value)
    suffix = uuid4().hex
    async with factory() as db:
        assert await db.scalar(text("SHOW transaction_isolation")) == "read committed"
        assert await db.scalar(text("SELECT current_schema()")) == "core"
        company = Company(id=uuid4(), name="Synthetic issuer", slug="issuer-"+suffix, profile_id="energy")
        other = Company(id=uuid4(), name="Synthetic foreign home", slug="other-"+suffix, profile_id="energy")
        db.add_all([company, other]); await db.flush()
        user = User(id=uuid4(), company_id=other.id, name="Synthetic references user",
            email=suffix+"@issuer.invalid", password_hash="synthetic", is_superadmin=False)
        db.add(user); await db.flush()
        role = CompanyRole(id=uuid4(), company_id=company.id, name="Synthetic references", modules=["references"])
        db.add(role); await db.flush()
        org = Organization(id=uuid4(), company_id=company.id, name="Synthetic own", inn="", prefix="S")
        cp = Counterparty(id=uuid4(), company_id=company.id, name="Synthetic CP", aliases=[])
        foreign_cp = Counterparty(id=uuid4(), company_id=other.id, name="Synthetic foreign CP", aliases=[])
        loc = ServiceLocation(id="  ОПАК:"+suffix[:16]+"  ", company_id=company.id,
            code="issuer-"+suffix, name="Synthetic object", source_bindings=[])
        db.add_all([org, cp, foreign_cp, loc]); await db.flush()
        db.add(UserCompany(user_id=user.id, company_id=company.id, role="user", modules=[],
            role_id=role.id, own_organization_id=org.id, object_scope=[loc.id]))
        app = App(id=uuid4(), code="issuer-"+suffix, name="Synthetic issuer", kind="partner", is_active=True)
        db.add(app); await db.flush()
        client_id, secret = "issuer-"+suffix, uuid4().hex+uuid4().hex
        db.add(PartnerClient(id=client_id, app_id=app.id, owner_company_id=other.id,
            auth_method="client_secret_basic", enabled=True, redirect_uris=[REDIRECT],
            allowed_scopes=["contracts:create", "contracts:read"]))
        await db.flush()
        iid = uuid4()
        db.add(CompanyApp(id=iid, company_id=company.id, app_id=app.id, enabled=True)); await db.flush()
        db.add(PartnerInstallation(id=iid, client_id=client_id, company_id=company.id,
            approved=True, all_locations=False, scopes=["contracts:create", "contracts:read"]))
        await db.flush()
        credential = PartnerCredential(id=uuid4(), client_id=client_id,
            secret_hash=identity.digest(secret), enabled=True, expires_at=identity.now()+timedelta(hours=1))
        grant = PartnerGrant(id=uuid4(), installation_id=iid, client_id=client_id, company_id=company.id,
            kind="machine", user_id=None, approved=True, scopes=["contracts:create", "contracts:read"])
        db.add_all([credential, grant, PartnerInstallationLocation(installation_id=iid, location_id=loc.id)])
        db.add_all([PartnerResourceScope(installation_id=iid, kind="objects", mode="SET"),
            PartnerResourceScope(installation_id=iid, kind="counterparties", mode="SET"),
            PartnerResourceScope(installation_id=iid, kind="contracts", mode="EMPTY")])
        await db.flush()
        db.add_all([PartnerResourceItem(installation_id=iid, kind="objects", object_id=loc.id),
            PartnerResourceItem(installation_id=iid, kind="counterparties", counterparty_id=cp.id)])
        code = "issuer-"+suffix
        await db.execute(text("INSERT INTO core.contract_types(code,label,is_active) VALUES (:c,'Synthetic',true)"), {"c": code})
        profile = Profile(id=uuid4(), installation_id=iid, client_id=client_id, company_id=company.id,
            user_enabled=True, service_enabled=True, revoked=False, policy_generation=1)
        db.add(profile); await db.flush()  # Actual SQL enablement, not a positive ACL mock.
        db.add_all([Principal(id=uuid4(), profile_id=profile.id, actor_kind="user", user_id=user.id),
            Principal(id=uuid4(), profile_id=profile.id, actor_kind="machine", machine_grant_id=grant.id),
            Ref(id=uuid4(), profile_id=profile.id, kind="organization", organization_id=org.id),
            Ref(id=uuid4(), profile_id=profile.id, kind="counterparty", counterparty_id=cp.id),
            Ref(id=uuid4(), profile_id=profile.id, kind="location", location_id=loc.id),
            Type(profile_id=profile.id, type_code=code)])
        await db.commit()
        w = SimpleNamespace(factory=factory, company=company.id, other=other.id, user=user.id,
            role=role.id, app_id=app.id, client_id=client_id, secret=secret, credential=credential.id,
            iid=iid, machine_grant=grant.id, profile=profile.id, org=org.id, cp=cp.id,
            foreign_cp=foreign_cp.id, loc=loc.id, code=code,
            native=token_for(user, expires_at=identity.now()+timedelta(minutes=20)))
        w.owned = {"companies": (w.company, w.other), "users": (w.user,), "apps": (w.app_id,),
            "installations": (w.iid,), "profiles": (w.profile,), "type_codes": (w.code,)}
    app = FastAPI()
    app.include_router(partner_oauth_router.router, prefix="/api")
    app.include_router(partner_oauth_router.consent_router, prefix="/api")
    async def sessions():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = sessions  # Only actual factory; auth is original.
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True),
                           base_url="https://issuer.synthetic.invalid") as http:
        w.http = http
        w.machine = await issue_machine(w)
        w.bearer = await issue_user(w)
        async with factory() as db:
            verified = await db.run_sync(identity.verify_access, w.bearer)
            assert verified.user_id == w.user and "contracts:create" in verified.scopes
            w.user_grant = verified.grant_id
        w.body = make_body(w)
        yield w
