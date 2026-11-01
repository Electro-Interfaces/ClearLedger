"""Source-only native acceptance; runtime NOT RUN.

An external --noconftest admission owns native schema, target, pools and disposal.
Business access below uses actual issued Authlib tokens, never bootstrap JWTs.
"""
import os
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

FLAG = "RUN_RUSHYDRO_PRODUCT_READS_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip("Explicit native READ admission required", allow_module_level=True)
from tests.partner_test_safety import partner_test_safety_error
if partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError("Native READ pre-import safety refused")
_target = urlsplit(os.environ["TEST_DATABASE_URL"])
if (os.environ.get("ROOT_APPROVED_RUSHYDRO_PRODUCT_READS") != "1"
        or os.environ.get("APP_ENV") != "test"
        or os.environ.get("DATABASE_URL") != os.environ.get("TEST_DATABASE_URL")
        or (_target.hostname, _target.port, _target.path, _target.username) != (
            "127.0.0.1", 5432, "/api_rushydro_reads25_test_20261101", "clearledger")):
    raise pytest.UsageError("Exact external native READ admission required")
# These literals express intent; ROOT preflight establishes role/OID/namespace
# ownership before loading any application modules. No provider ships here.

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import tempfile
from types import SimpleNamespace
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest_asyncio
from sqlalchemy import select, text

from app.auth import token_for
from app.config import get_settings
from app.database import get_db
from app.models import (App, ChargeSession, Company, CompanyApp, CompanyRole,
    Contract, ContractLocation, Counterparty, DocCard, DocKind, DocRelation,
    DocVersion, EzsEquipmentUnit, Organization, ServiceLocation, SourceFile,
    User, UserCompany)
from app.models_partner import (PartnerAuthorizationRequest, PartnerClient,
    PartnerCode, PartnerCredential, PartnerGrant, PartnerInstallation,
    PartnerResourceItem, PartnerResourceScope, PartnerToken, PartnerTokenFamily)
from app.product_api import create_product_api
from app.routers import partner_oauth_router
from app.services import partner_identity as identity

pytestmark = pytest.mark.asyncio(loop_scope="session")

ORIGIN = "https://reads.synthetic.invalid"
CALLBACK = ORIGIN + "/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
SCOPES = ["openid", "objects:read", "monitoring:read", "equipment:read",
          "counterparties:read", "contracts:read", "documents:read", "documents.files:download"]
MACHINE_SCOPES = ["contracts:read"]
O1 = "Учебная Ё O1"
O2 = "Скрытая Ё O2"
OF = "Чужая Ё O3"
E1 = "30000000-0000-4000-8000-000000000001"
E2 = "30000000-0000-4000-8000-000000000002"
EF = "30000000-0000-4000-8000-000000000003"
P1 = "40000000-0000-4000-8000-000000000001"
P2 = "40000000-0000-4000-8000-000000000002"
PF = "40000000-0000-4000-8000-000000000003"
C1 = "50000000-0000-4000-8000-000000000001"
C2 = "50000000-0000-4000-8000-000000000002"
CF = "50000000-0000-4000-8000-000000000003"
D1 = "60000000-0000-4000-8000-000000000001"
D2 = "60000000-0000-4000-8000-000000000002"
DF = "60000000-0000-4000-8000-000000000003"
V1 = "70000000-0000-4000-8000-000000000001"
TYPE = "synthetic-native-read"
FILE_BYTES = b"Synthetic native read bytes\x00\xff"

# Literal rows are AST-countable without importing or collecting this module.
# case ID, method key, wire template, literal query, expected projection key.
USER_CASES = [
    ("user-objects", "GET /objects", "/objects", {}, "objects"),
    ("user-object", "GET /objects/{objectId}", "/objects/{o1}", {}, "object"),
    ("user-monitoring", "GET /objects/{objectId}/monitoring", "/objects/{o1}/monitoring", {}, "monitoring"),
    ("user-equipment-list", "GET /equipment", "/equipment", {}, "equipment-list"),
    ("user-equipment", "GET /equipment/{equipmentId}", "/equipment/{e1}", {}, "equipment"),
    ("user-counterparties", "GET /counterparties", "/counterparties", {}, "counterparties"),
    ("user-counterparty", "GET /counterparties/{counterpartyId}", "/counterparties/{p1}", {}, "counterparty"),
    ("user-contracts", "GET /contracts", "/contracts", {}, "contracts"),
    ("user-contract-type", "GET /contract-types", "/contract-types", {"typeCode": "synthetic-native-read"}, "contract-type"),
    ("user-contract", "GET /contracts/{contractId}", "/contracts/{c1}", {}, "contract"),
    ("user-contract-objects", "GET /contracts/{contractId}/objects", "/contracts/{c1}/objects", {}, "contract-objects"),
    ("user-contract-documents", "GET /contracts/{contractId}/documents", "/contracts/{c1}/documents", {}, "contract-documents"),
    ("user-documents", "GET /documents", "/documents", {}, "documents"),
    ("user-document", "GET /documents/{docId}", "/documents/{d1}", {}, "document"),
    ("user-download", "GET /documents/{docId}/versions/{versionId}/content", "/documents/{d1}/versions/{v1}/content", {}, "download"),
]
MACHINE_CASES = [
    ("machine-contract-documents", "GET /contracts/{contractId}/documents", "/contracts/{c1}/documents", 403, "access_denied"),
    ("machine-documents", "GET /documents", "/documents", 403, "access_denied"),
    ("machine-document", "GET /documents/{docId}", "/documents/{d1}", 403, "access_denied"),
    ("machine-download", "GET /documents/{docId}/versions/{versionId}/content", "/documents/{d1}/versions/{v1}/content", 403, "access_denied"),
]
# Each case checks both same-company hidden and foreign detail, with one case ID.
HIDDEN_CASES = [
    ("hidden-object", "GET /objects/{objectId}", "/objects/{o2}", "/objects/{of}", 404, "not_found"),
    ("hidden-equipment", "GET /equipment/{equipmentId}", "/equipment/{e2}", "/equipment/{ef}", 404, "not_found"),
    ("hidden-counterparty", "GET /counterparties/{counterpartyId}", "/counterparties/{p2}", "/counterparties/{pf}", 404, "not_found"),
    ("hidden-contract", "GET /contracts/{contractId}", "/contracts/{c2}", "/contracts/{cf}", 404, "not_found"),
    ("hidden-document", "GET /documents/{docId}", "/documents/{d2}", "/documents/{df}", 404, "not_found"),
]
MONITORING_CASES = [
    ("monitoring-msk-round-after-sum", "GET /objects/{objectId}/monitoring", "/objects/{o1}/monitoring", {"days": 2, "asOf": "2026-10-16"}),
]

# Exact independent expected IDs/values; these do not call a DTO or Query oracle.
OBJECT = {"id": "Учебная Ё O1", "level": "servicePoint", "code": "SYN-1",
          "name": "Учебная станция", "type": "ev_charging", "status": "active",
          "address": "Учебный адрес", "latitude": 55.0, "longitude": 37.0}
EQUIPMENT = {"id": "30000000-0000-4000-8000-000000000001", "level": "station",
             "vendor": "Synthetic", "model": "Model A", "serialNumber": "SYN-001",
             "powerKw": 22.0, "state": "in_operation", "objectId": "Учебная Ё O1"}
PARTY = {"id": "40000000-0000-4000-8000-000000000001", "name": "Учебный контрагент",
         "inn": None, "kpp": None}
CONTRACT = {"id": "50000000-0000-4000-8000-000000000001", "number": "SYN-001",
            "date": "2026-10-01", "title": "Учебный договор", "isClosed": False,
            "scopeType": "locations", "typeCode": "synthetic-native-read", "validUntil": "2030-12-31",
            "counterpartyId": "40000000-0000-4000-8000-000000000001"}
DOCUMENT = {"id": "60000000-0000-4000-8000-000000000001", "title": "Учебный документ",
            "status": "draft", "registrationNumber": None, "registrationDate": None,
            "currentRevision": 1, "objectId": "Учебная Ё O1", "counterpartyId": None}
VERSION = {"id": "70000000-0000-4000-8000-000000000001", "revision": 1,
           "role": "body", "fileName": "synthetic.bin", "mimeType": "application/octet-stream", "sizeBytes": 29}


def bearer(access):
    return {"Authorization": "Bearer " + access}


async def wire(w, method, path, **kwargs):
    """Real in-process HTTP including streaming; always close the response."""
    async with asyncio.timeout(15):
        async with w.http.stream(method, path, **kwargs) as response:
            await response.aread()
            return response


async def issue_user(w, bootstrap):
    state, nonce = uuid4().hex, uuid4().hex
    response = await wire(w, "GET", "/api/oauth2/authorize", params={
        "response_type": "code", "client_id": w.clients[0], "redirect_uri": CALLBACK,
        "scope": " ".join(SCOPES), "state": state, "nonce": nonce,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "prompt": "consent"})
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.path == "/developer/authorize" and not location.netloc
    rid = parse_qs(location.query)["requestId"][0]
    response = await wire(w, "GET", "/api/developer/authorization-requests/" + rid, headers=bearer(bootstrap))
    assert response.status_code == 200
    assert response.json()["companies"] == [{"id": str(w.companies[0]), "name": "Учебный tenant A",
                                             "eligibleScopes": sorted(SCOPES)}]
    response = await wire(w, "POST", "/api/developer/authorization-requests/" + rid + "/approve",
                          headers=bearer(bootstrap), json={"companyId": str(w.companies[0]), "scopes": SCOPES})
    assert response.status_code == 200
    callback = urlsplit(response.json()["redirectUrl"])
    assert (callback.scheme, callback.netloc, callback.path) == ("https", "reads.synthetic.invalid", "/callback")
    query = parse_qs(callback.query)
    assert set(query) == {"state", "code"} and query["state"] == [state]
    code = query["code"][0]
    response = await wire(w, "POST", "/api/oauth2/token", data={"grant_type": "authorization_code",
        "client_id": w.clients[0], "redirect_uri": CALLBACK, "code": code, "code_verifier": VERIFIER})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    payload = response.json()
    granted_scopes = set(payload["scope"].split())
    assert granted_scopes == set(SCOPES)
    async with w.factory() as db:
        employee = await db.get(User, w.user)
        member = await db.get(UserCompany, (w.user, w.companies[0]))
        role = await db.get(CompanyRole, w.role)
        assert employee.role == member.role == "user" and employee.is_superadmin is False
        assert member.role_id == role.id and member.object_scope == ["Учебная Ё O1"]
        assert member.own_organization_id == w.orgs[0]
        assert role.modules == ["equipment", "references", "docs", "ops:ops_state"]
        row = await db.get(PartnerCode, identity.digest(code))
        assert row is not None and row.consumed
        assert row.code_challenge == CHALLENGE and row.code_challenge_method == "S256" and row.nonce == nonce
        grant = await db.get(PartnerGrant, row.grant_id)
        request = await db.get(PartnerAuthorizationRequest, UUID(rid))
        assert request.finished and request.user_id == w.user
        assert grant.approved and grant.kind == "user" and grant.user_id == w.user
        assert grant.client_id == w.clients[0] and grant.company_id == w.companies[0]
        token = await db.scalar(select(PartnerToken).where(PartnerToken.access_hash == identity.digest(payload["access_token"])))
        assert token is not None
        family = await db.get(PartnerTokenFamily, token.family_id)
        assert family.grant_id == grant.id
    return bearer(payload["access_token"])


async def issue_machine(w, secret):
    # Issuer rejects document scopes for machines. This proves the current
    # effective denial boundary, not isolated principal-kind policy precedence.
    response = await wire(w, "POST", "/api/oauth2/token", auth=(w.clients[1], secret), data={
        "grant_type": "client_credentials", "grant_id": str(w.machine_grant), "scope": "contracts:read"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    payload = response.json()
    granted_scopes = payload["scope"].split()
    assert granted_scopes == ["contracts:read"] and "id_token" not in payload
    async with w.factory() as db:
        grant = await db.get(PartnerGrant, w.machine_grant)
        token = await db.scalar(select(PartnerToken).where(PartnerToken.access_hash == identity.digest(payload["access_token"])))
        assert token is not None
        family = await db.get(PartnerTokenFamily, token.family_id)
        assert grant.approved and grant.kind == "machine" and grant.user_id is None
        assert grant.client_id == w.clients[1] and grant.scopes == ["contracts:read"]
        assert family.grant_id == grant.id and family.credential_id == w.credential
    return bearer(payload["access_token"])


async def seed(w, path):
    """Fixture DML only, before any business-read snapshot. Native FK order."""
    now = datetime.now(timezone.utc)
    at = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    ca, cb = w.companies
    oa, oh, ob = w.orgs
    secret = uuid4().hex + uuid4().hex
    async with w.factory() as db:
        db.add_all([Company(id=ca, name="Учебный tenant A", slug="read-a-" + w.suffix, profile_id="energy"),
                    Company(id=cb, name="Учебный tenant B", slug="read-b-" + w.suffix, profile_id="energy")])
        await db.flush()
        db.add_all([Organization(id=oa, company_id=ca, name="Учебное юрлицо A", inn="0000000001"),
                    Organization(id=oh, company_id=ca, name="Учебное юрлицо A2", inn="0000000002"),
                    Organization(id=ob, company_id=cb, name="Учебное юрлицо B", inn="0000000003"),
                    CompanyRole(id=w.role, company_id=ca, name="Учебный читатель",
                        modules=["equipment", "references", "docs", "ops:ops_state"]),
                    User(id=w.user, company_id=ca, email=w.suffix + "@reader.invalid", name="Учебный читатель",
                        password_hash="unused-no-password-login", role="user", is_superadmin=False,
                        mail_only=False, last_seen_at=now, token_version=0)])
        await db.flush()
        db.add(UserCompany(user_id=w.user, company_id=ca, role="user", role_id=w.role,
                           object_scope=[O1], own_organization_id=oa, modules=[]))
        for identifier, company, code, name in ((O1, ca, "SYN-1", "Учебная станция"),
                (O2, ca, "HIDDEN", "Скрытая станция"), (OF, cb, "FOREIGN", "Чужая станция")):
            db.add(ServiceLocation(id=identifier, company_id=company, code=code, name=name,
                type="ev_charging", status="active", operational_status="working", address="Учебный адрес",
                latitude=55.0, longitude=37.0, created_at=at, extra_metadata={"private": "NEVER-EXPOSE"}))
        for identifier, company, name in ((P1, ca, "Учебный контрагент"), (P2, ca, "Скрытый контрагент"),
                                         (PF, cb, "Чужой контрагент")):
            db.add(Counterparty(id=UUID(identifier), company_id=company, name=name, is_group=False,
                                created_at=at, raw={"private": "NEVER-EXPOSE"}))
        await db.flush()
        # The native legacy classifier may be a real FK although absent from ORM.
        await db.execute(text("INSERT INTO contract_types (code,label,gk_basis,direction,is_active) "
                              "VALUES (:code,:label,NULL,:direction,false)"),
                         {"code": TYPE, "label": "Учебный тип", "direction": "in"})
        for identifier, company, org, party, obj in ((C1, ca, oa, P1, O1), (C2, ca, oh, P2, O2), (CF, cb, ob, PF, OF)):
            db.add(Contract(id=UUID(identifier), company_id=company, organization_id=org,
                counterparty_id=UUID(party), number="SYN-001", date="2026-10-01", type="service",
                type_code=TYPE, title="Учебный договор", scope_type="locations", is_closed=False,
                valid_until="2030-12-31", created_at=at, raw={"private": "NEVER-EXPOSE"}))
        for identifier, company, obj in ((E1, ca, O1), (E2, ca, O2), (EF, cb, OF)):
            db.add(EzsEquipmentUnit(id=UUID(identifier), company_id=company, kind="station", vendor="Synthetic",
                model="Model A", serial_number={E1: "SYN-001", E2: "SYN-HIDDEN", EF: "SYN-FOREIGN"}[identifier],
                power_kwt=22.0, state="in_operation",
                current_location_id=obj, created_at=at, extra={"private": "NEVER-EXPOSE"}))
        kinds = (uuid4(), uuid4())
        db.add_all([DocKind(id=kid, company_id=company, code="synthetic-read", name="Учебный вид", fields=[], route=[])
                    for kid, company in zip(kinds, w.companies)])
        await db.flush()
        db.add_all([ContractLocation(company_id=company, contract_id=UUID(contract), location_id=obj)
                    for company, contract, obj in ((ca, C1, O1), (ca, C1, O2), (ca, C2, O2), (cb, CF, OF))])
        # Visible paper points to a hidden party: projection must redact its ID.
        for identifier, company, kind, org, obj, party, contract in (
                (D1, ca, kinds[0], oa, O1, P2, C1), (D2, ca, kinds[0], oh, O2, P2, C2),
                (DF, cb, kinds[1], ob, OF, PF, CF)):
            db.add(DocCard(id=UUID(identifier), company_id=company, kind_id=kind, title="Учебный документ",
                object_id=obj, organization_id=org, counterparty_id=UUID(party), subject_ref="contract:" + contract,
                confidentiality="company", status="draft", current_revision=1 if identifier == D1 else 0,
                created_at=at, attrs={"private": "NEVER-EXPOSE"}, source_ref="NEVER-EXPOSE"))
        await db.flush()
        # Subject and graph are both real; duplicate linkage must not duplicate output.
        db.add(DocRelation(company_id=ca, doc_id=UUID(D1), kind="annex_of", target_ref="contract:" + C1))
        db.add(DocRelation(company_id=ca, doc_id=UUID(D2), kind="related", target_ref="contract:" + C1))
        db.add(SourceFile(id=w.source, company_id=ca, file_name="synthetic.bin", mime_type="application/octet-stream",
            size=29, storage_path=str(path), fingerprint=hashlib.sha256(FILE_BYTES).hexdigest()))
        await db.flush()
        db.add(DocVersion(id=UUID(V1), company_id=ca, doc_id=UUID(D1), revision=1, role="body",
            file_id=w.source, file_name="synthetic.bin", mime="application/octet-stream", size_bytes=29,
            sha256=hashlib.sha256(FILE_BYTES).hexdigest(), is_current=True))
        # Three attempts / two visits / one successful visit; fourth is after asOf.
        for index, company, obj, stamp, visit, energy in (
                (0, ca, O1, datetime(2026, 10, 16, 10), "visit-a", "0.04"),
                (1, ca, O1, datetime(2026, 10, 16, 10, 1), "visit-a", "0.04"),
                (2, ca, O1, datetime(2026, 10, 16, 11), "visit-b", "0"),
                (3, ca, O1, datetime(2026, 10, 17, 12), "later", "0"),
                (4, ca, O2, datetime(2030, 1, 1), "hidden", "999"),
                (5, cb, OF, datetime(2040, 1, 1), "foreign", "999")):
            db.add(ChargeSession(company_id=company, session_ext_id="read-" + w.suffix + str(index),
                location_id=obj, started_at=stamp, visit_key=visit, energy_kwh=Decimal(energy),
                user_id="NEVER-PHONE", amount=987654, result="CompleteError"))
        for index in range(2):
            db.add(App(id=w.apps[index], code="read-" + str(index) + "-" + w.suffix,
                       name="Учебное приложение", kind="partner", is_active=True))
        await db.flush()
        for index in range(2):
            db.add(PartnerClient(id=w.clients[index], app_id=w.apps[index], owner_company_id=ca,
                redirect_uris=[CALLBACK] if index == 0 else [],
                auth_method="none" if index == 0 else "client_secret_basic", enabled=True,
                allowed_scopes=SCOPES if index == 0 else MACHINE_SCOPES))
            db.add(CompanyApp(id=w.installations[index], company_id=ca, app_id=w.apps[index], enabled=True))
        await db.flush()
        for index in range(2):
            db.add(PartnerInstallation(id=w.installations[index], client_id=w.clients[index], company_id=ca,
                approved=True, all_locations=True, scopes=SCOPES if index == 0 else MACHINE_SCOPES))
        await db.flush()
        # Each typed SET is narrow, native and FK-backed. Domain ceilings still
        # independently hide local O2/A2 records; foreign resources are ungranted.
        for index in range(2):
            for kind in ("objects", "equipment", "counterparties", "contracts", "documents"):
                db.add(PartnerResourceScope(installation_id=w.installations[index], kind=kind, mode="SET"))
        await db.flush()
        for index in range(2):
            for kind, column, values in (("objects", "object_id", (O1, O2)), ("equipment", "equipment_id", (E1, E2)),
                    ("counterparties", "counterparty_id", (P1, P2)), ("contracts", "contract_id", (C1, C2)),
                    ("documents", "document_id", (D1, D2))):
                for value in values:
                    db.add(PartnerResourceItem(installation_id=w.installations[index], kind=kind,
                        **{column: value if kind == "objects" else UUID(value)}))
        db.add(PartnerCredential(id=w.credential, client_id=w.clients[1], secret_hash=identity.digest(secret),
                                enabled=True, expires_at=now + timedelta(minutes=20)))
        db.add(PartnerGrant(id=w.machine_grant, installation_id=w.installations[1], client_id=w.clients[1],
                           company_id=ca, user_id=None, kind="machine", approved=True, scopes=MACHINE_SCOPES))
        await db.commit()
        employee = await db.get(User, w.user)
        bootstrap = token_for(employee, expires_at=now + timedelta(minutes=20))
    return bootstrap, secret


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def read_world(rushydro_read_factory):
    """External actual async_sessionmaker; ROOT owns preflight and pool disposal."""
    # Pytest registers an imported fixture once per module's fixture namespace.
    # Both modules must share this one real seed/client for the same factory.
    cache_key = "_rushydro_native_reads_world"
    cached = getattr(rushydro_read_factory, cache_key, None)
    if cached is not None:
        assert cached.factory is rushydro_read_factory and not cached.http.is_closed
        yield cached
        return
    suffix = uuid4().hex
    w = SimpleNamespace(factory=rushydro_read_factory, suffix=suffix,
        companies=(uuid4(), uuid4()), orgs=(uuid4(), uuid4(), uuid4()), role=uuid4(), user=uuid4(),
        apps=(uuid4(), uuid4()), clients=("read-" + suffix, "machine-read-" + suffix),
        installations=(uuid4(), uuid4()), source=uuid4(), credential=uuid4(), machine_grant=uuid4())
    patch = pytest.MonkeyPatch()
    try:
        signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key = base64.b64encode(signer.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
        for name, value in {"partner_oauth_enabled": True, "partner_api_enabled": True,
                "partner_api_budget_enabled": False, "partner_oauth_issuer": ORIGIN,
                "partner_oauth_audience": "urn:synthetic:reads", "partner_oauth_signing_key": key,
                "secret_key": uuid4().hex + uuid4().hex}.items():
            patch.setattr(get_settings(), name, value)
        with tempfile.TemporaryDirectory(prefix="rushydro_reads_test_", dir=os.environ["UPLOAD_DIR"]) as temporary:
            w.path = Path(temporary) / "synthetic.bin"
            w.path.write_bytes(FILE_BYTES)
            bootstrap, secret = await seed(w, w.path)
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            app.add_exception_handler(identity.PartnerProblem, identity.problem_handler)
            app.include_router(partner_oauth_router.router, prefix="/api")
            app.include_router(partner_oauth_router.consent_router, prefix="/api")
            async def actual_database():
                async with w.factory() as db:
                    yield db
            app.dependency_overrides[get_db] = actual_database
            try:
                product = create_product_api(session_factory=w.factory, enabled=True, issuer=ORIGIN,
                                             upload_dir=temporary, source_revision="synthetic-read-source")
                app.mount("/api/v1", product)
                async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True),
                                       base_url=ORIGIN, follow_redirects=False, timeout=15) as http:
                    w.http = http
                    w.user_headers = await issue_user(w, bootstrap)
                    w.machine_headers = await issue_machine(w, secret)
                    del bootstrap, secret
                    setattr(rushydro_read_factory, cache_key, w)
                    try:
                        yield w
                    finally:
                        delattr(rushydro_read_factory, cache_key)
            finally:
                app.dependency_overrides.clear()
    finally:
        patch.undo()
    # No per-table DROP/DELETE: ROOT disposes the entire owned DB even on error.


# Explicit selected-column inventory, only the two owned synthetic companies.
# Authentication tables/usage are deliberately outside this business snapshot.
SNAPSHOT_COLUMNS = (
    (Company, ("id", "name", "slug", "profile_id", "tz", "customization")),
    (Organization, ("id", "company_id", "name", "inn")),
    (ServiceLocation, ("id", "company_id", "code", "name", "type", "status", "operational_status",
                       "address", "latitude", "longitude", "extra_metadata", "created_at")),
    (EzsEquipmentUnit, ("id", "company_id", "kind", "vendor", "model", "serial_number", "power_kwt",
                       "state", "current_location_id", "extra", "created_at", "updated_at")),
    (Counterparty, ("id", "company_id", "name", "inn", "kpp", "is_group", "raw", "created_at", "updated_at")),
    (Contract, ("id", "company_id", "organization_id", "counterparty_id", "number", "date", "type",
                "type_code", "title", "scope_type", "valid_until", "is_closed", "raw", "created_at", "updated_at")),
    (ContractLocation, ("id", "company_id", "contract_id", "location_id", "note", "created_at")),
    (DocKind, ("id", "company_id", "code", "name", "fields", "route")),
    (DocCard, ("id", "company_id", "kind_id", "title", "status", "object_id", "organization_id",
               "counterparty_id", "subject_ref", "confidentiality", "attrs", "source_ref", "current_revision",
               "reg_number", "reg_date", "retention_state", "created_at", "updated_at")),
    (DocRelation, ("id", "company_id", "doc_id", "kind", "target_ref", "target_doc_id", "meta")),
    (DocVersion, ("id", "company_id", "doc_id", "revision", "role", "file_id", "file_name", "mime",
                  "size_bytes", "sha256", "is_current", "tombstoned_at", "archive_purged_at")),
    (SourceFile, ("id", "company_id", "file_name", "mime_type", "size", "storage_path", "fingerprint")),
    (ChargeSession, ("id", "company_id", "session_ext_id", "location_id", "started_at", "visit_key",
                     "energy_kwh", "user_id", "amount", "result")),
)


async def business_snapshot(w):
    # A new actual session on each side of each GET, never the seed identity map.
    result = {}
    async with w.factory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        readonly = await db.scalar(text("SHOW transaction_read_only"))
        assert readonly == "on"
        for model, names in SNAPSHOT_COLUMNS:
            columns = [getattr(model, name) for name in names]
            owned = model.id.in_(w.companies) if model is Company else model.company_id.in_(w.companies)
            result[model.__tablename__] = [tuple(row) for row in (
                await db.execute(select(*columns).where(owned).order_by(model.id))).all()]
        result["contract_types"] = [tuple(row) for row in (await db.execute(text(
            "SELECT code,label,gk_basis,direction,is_active FROM contract_types WHERE code=:code"),
            {"code": TYPE})).all()]
    result["owned_file"] = w.path.read_bytes()
    return result


def path_for(template):
    values = {"o1": O1, "o2": O2, "of": OF, "e1": E1, "e2": E2, "ef": EF,
              "p1": P1, "p2": P2, "pf": PF, "c1": C1, "c2": C2, "cf": CF,
              "d1": D1, "d2": D2, "df": DF, "v1": V1}
    return "/api/v1" + template.format(**{k: quote(v, safe="") for k, v in values.items()})


async def business_get(w, template, headers, params=None):
    before = await business_snapshot(w)
    try:
        response = await wire(w, "GET", path_for(template), headers=headers, params=params)
    finally:
        after = await business_snapshot(w)
        assert before == after  # Selected owned rows/columns and one file only.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]
    # Exact JSON assertions below also reject arbitrary keys, not just markers.
    for forbidden in (b"NEVER-EXPOSE", b"NEVER-PHONE", b"987654", b"extra_metadata", b"extraMetadata",
                      b"password", PF.encode(), EF.encode(), CF.encode(), DF.encode()):
        assert forbidden not in response.content
    return response


def problem(response, status, code):
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    if status == 403:
        assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json() == {
        "type": "about:blank", "title": "Forbidden" if status == 403 else "Not Found", "status": status,
        "code": code, "requestId": response.headers["x-request-id"],
        "detail": "Access is denied" if status == 403 else "Resource was not found"}


def assert_monitoring(data, *, historical):
    assert set(data) == {"pointId", "status", "window", "totals", "lastSeenAt", "provenance"}
    assert data["pointId"] == "Учебная Ё O1" and data["status"] == "working"
    if historical:
        assert data["totals"] == {"sessions": 3, "visits": 2, "successfulVisits": 1,
                                  "unsuccessfulVisits": 1, "energyKwh": 0.1}
        assert data["window"] == {"days": 2, "start": "2026-10-14T23:59:59.999999+03:00",
                                  "end": "2026-10-16T23:59:59.999999+03:00",
                                  "timeZone": "Europe/Moscow", "interval": "inclusive"}
        assert data["lastSeenAt"] == "2026-10-16T11:00:00+03:00"
        endpoint, requested = "2026-10-16T23:59:59.999999+03:00", "2026-10-16"
    else:
        assert data["totals"] == {"sessions": 4, "visits": 3, "successfulVisits": 1,
                                  "unsuccessfulVisits": 2, "energyKwh": 0.1}
        assert data["window"] == {"days": 90, "start": "2026-07-19T12:00:00+03:00",
                                  "end": "2026-10-17T12:00:00+03:00",
                                  "timeZone": "Europe/Moscow", "interval": "inclusive"}
        assert data["lastSeenAt"] == "2026-10-17T12:00:00+03:00"
        endpoint, requested = "2026-10-17T12:00:00+03:00", None
    provenance = data["provenance"]
    assert set(provenance) == {"asOf", "dataThrough", "dataLagHours", "requestedDate", "catalogMode",
                               "snapshotNote", "boundaryScope", "source", "visitSuccess"}
    # Wall-clock lag varies, while the object watermark and calendar are literal.
    lag = provenance["dataLagHours"]
    assert type(lag) in (int, float) and lag >= 0
    assert {**provenance, "dataLagHours": 0.0} == {
        "asOf": endpoint, "dataThrough": "2026-10-17T12:00:00+03:00", "dataLagHours": 0.0,
        "requestedDate": requested, "catalogMode": "current", "boundaryScope": "object",
        "source": "charge_sessions", "visitSuccess": "any attempt energy_kwh > 0",
        "snapshotNote": "Сессии — на выбранный день (МСК). Состав парка и паспортные статусы — текущие; история состава не восстановлена."}


@pytest.mark.parametrize("case", USER_CASES, ids=[row[0] for row in USER_CASES])
async def test_user_read(read_world, case):
    _, _, template, params, projection = case
    response = await business_get(read_world, template, read_world.user_headers, params)
    assert response.status_code == 200
    if projection == "download":
        assert response.content == b"Synthetic native read bytes\x00\xff"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''synthetic.bin"
        assert response.headers["x-content-type-options"] == "nosniff"
        return
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    if projection == "monitoring":
        assert_monitoring(data, historical=False)
        return
    expected = {
        "objects": {"items": [OBJECT], "total": 1, "nextCursor": None}, "object": OBJECT,
        "equipment-list": {"items": [EQUIPMENT], "total": 1, "nextCursor": None}, "equipment": EQUIPMENT,
        "counterparties": {"items": [PARTY], "total": 1, "nextCursor": None}, "counterparty": PARTY,
        "contracts": {"items": [CONTRACT], "total": 1, "nextCursor": None}, "contract": CONTRACT,
        "contract-type": {"typeCode": "synthetic-native-read", "label": "Учебный тип", "gkBasis": None,
                          "direction": "in", "isActive": False},
        "contract-objects": {"contractId": "50000000-0000-4000-8000-000000000001", "scopeType": "locations",
                             "items": [{"objectId": "Учебная Ё O1"}], "total": 1, "nextCursor": None},
        "contract-documents": {"contractId": "50000000-0000-4000-8000-000000000001",
                               "items": [{"documentId": "60000000-0000-4000-8000-000000000001"}],
                               "total": 1, "nextCursor": None},
        "documents": {"items": [DOCUMENT], "total": 1, "nextCursor": None},
        "document": {**DOCUMENT, "versions": [VERSION], "versionsTruncated": False},
    }
    assert data == expected[projection]


@pytest.mark.parametrize("case", MACHINE_CASES, ids=[row[0] for row in MACHINE_CASES])
async def test_machine_document_denial(read_world, case):
    _, _, template, status, code = case
    response = await business_get(read_world, template, read_world.machine_headers)
    problem(response, status, code)


@pytest.mark.parametrize("case", HIDDEN_CASES, ids=[row[0] for row in HIDDEN_CASES])
async def test_hidden_and_foreign_detail(read_world, case):
    _, _, hidden, foreign, status, code = case
    for template in (hidden, foreign):
        response = await business_get(read_world, template, read_world.user_headers)
        problem(response, status, code)


@pytest.mark.parametrize("case", MONITORING_CASES, ids=[row[0] for row in MONITORING_CASES])
async def test_monitoring_golden(read_world, case):
    _, _, template, params = case
    response = await business_get(read_world, template, read_world.user_headers, params)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert_monitoring(response.json(), historical=True)
