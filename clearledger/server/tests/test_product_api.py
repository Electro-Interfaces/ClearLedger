"""HTTP + PostgreSQL synthetic acceptance. Verifier is fake, not an OIDC test."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
import sys
from types import MappingProxyType, ModuleType, SimpleNamespace
import uuid

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_PRODUCT_API_TESTS") != "1":
    pytest.skip("Opt in with RUN_PRODUCT_API_TESTS=1", allow_module_level=True)
_safety_error = partner_test_safety_error(os.environ, flag="RUN_PRODUCT_API_TESTS")
if _safety_error:
    raise pytest.UsageError("Refusing product test database: " + _safety_error)

from app.models import (Company, Contract, ContractLocation, Counterparty, DocAccessGrant,
    DocCard, DocKind, DocVersion, EzsEquipmentUnit, Organization, ServiceLocation, SourceFile, User, UserCompany)
from app.product_api import create_product_api, curated_openapi, export_runtime_registry


RESOURCES = ("objects", "equipment", "counterparties", "contracts", "documents")
SCOPES = frozenset({f"{key}:read" for key in RESOURCES} | {"documents.files:download"})


def grants(**overrides):
    return MappingProxyType({key: MappingProxyType(overrides.get(key, {"mode": "ALL", "ids": frozenset()})) for key in RESOURCES})


@dataclass(frozen=True)
class VerifiedFixture:
    client_id: str
    app_id: uuid.UUID
    installation_id: uuid.UUID
    company_id: uuid.UUID
    grant_id: uuid.UUID
    user_id: uuid.UUID | None
    scopes: frozenset
    subject: str
    token_id: uuid.UUID
    expires_at: datetime
    is_machine: bool
    resource_scopes: object
    own_organization_id: uuid.UUID | None = None
    location_ids: frozenset | None = None


@pytest_asyncio.fixture
async def api(db, tmp_path):
    # The shared guard validates explicit synthetic targets before DB fixtures.
    assert partner_test_safety_error(os.environ, flag="RUN_PRODUCT_API_TESTS") is None
    suffix = uuid.uuid4().hex[:12]
    companies = [Company(id=uuid.uuid4(), name=f"Synthetic {i}", slug=f"product-{suffix}-{i}", profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    ca, cb = [row.id for row in companies]
    users = [User(id=uuid.uuid4(), company_id=cid, name="Synthetic User", email=f"{suffix}-{i}@example.invalid",
                  password_hash="not-a-password", is_superadmin=False, mail_only=False)
             for i, cid in enumerate((ca, cb, ca))]
    db.add_all(users)
    await db.flush()
    ua, ub, other = users
    members = [UserCompany(user_id=u.id, company_id=u.company_id, role="user", modules=None) for u in users]
    db.add_all(members)
    orgs = [Organization(id=uuid.uuid4(), company_id=ca, name=f"Synthetic Organization {i}", inn=f"99999999{i:02d}") for i in range(2)]
    orgb = Organization(id=uuid.uuid4(), company_id=cb, name="Foreign Organization", inn="8888888888")
    db.add_all([*orgs, orgb])
    at = datetime(2026, 1, 2, 3, tzinfo=timezone.utc)
    locations = [ServiceLocation(id=f"{suffix}-loc-{i}", company_id=ca, code=f"CODE-{i}", name=f"Node {i}",
        type="ezs", status="active", created_at=at, latitude=None, longitude=None,
        extra_metadata={"secret": "NEVER-EXPOSE"}) for i in range(5)]
    foreign = ServiceLocation(id=f"{suffix}-foreign", company_id=cb, code="FOREIGN", name="Foreign", type="ezs", created_at=at)
    db.add_all([*locations, foreign])
    parties = [Counterparty(id=uuid.uuid4(), company_id=ca, name=f"Party {i}", inn=None,
        raw={"password": "NEVER-EXPOSE"}, bank_account="NEVER-EXPOSE", email="private@example.invalid") for i in range(4)]
    cpb = Counterparty(id=uuid.uuid4(), company_id=cb, name="Foreign Party")
    db.add_all([*parties, cpb])
    await db.flush()
    contracts = [Contract(id=uuid.uuid4(), company_id=ca, number=f"C-{i}", date="unknown" if i == 3 else "2026-01-02",
        type="service", counterparty_id=parties[min(i, 2)].id, organization_id=orgs[i % 2 if i < 2 else 0].id,
        scope_type=("locations" if i < 2 else "company" if i == 2 else "unassigned"), raw={"secret": "NEVER-EXPOSE"}) for i in range(4)]
    contractb = Contract(id=uuid.uuid4(), company_id=cb, number="FOREIGN", date="2026-01-02", type="service",
                          counterparty_id=cpb.id, organization_id=orgb.id, scope_type="company")
    db.add_all([*contracts, contractb])
    await db.flush()
    db.add_all([ContractLocation(company_id=ca, contract_id=contracts[index].id, location_id=locations[loc].id)
                for index, loc in ((0, 0), (0, 2), (1, 1))])
    equipment = [EzsEquipmentUnit(id=uuid.uuid4(), company_id=ca, kind="station", vendor="Vendor", model="Model",
        current_location_id=locations[i].id, state="in_operation", power_kwt=None, extra={"secret": "NEVER-EXPOSE"}) for i in range(2)]
    module = EzsEquipmentUnit(id=uuid.uuid4(), company_id=ca, kind="module", state="in_stock_new")
    eqb = EzsEquipmentUnit(id=uuid.uuid4(), company_id=cb, kind="station", current_location_id=foreign.id, state="in_operation")
    db.add_all([*equipment, module, eqb])
    kinds = [DocKind(id=uuid.uuid4(), company_id=cid, code=f"test-{suffix}", name="Synthetic kind", fields=[], route=[]) for cid in (ca, cb)]
    db.add_all(kinds)
    await db.flush()
    docs = [DocCard(id=uuid.uuid4(), company_id=ca, kind_id=kinds[0].id, title=f"Document {i}",
        confidentiality=("company" if i == 0 else "private" if i == 1 else "strict"), author_id=other.id,
        object_id=locations[0].id, organization_id=orgs[0].id, counterparty_id=parties[0].id,
        attrs={"secret": "NEVER-EXPOSE"}, source_ref="NEVER-EXPOSE", current_revision=1) for i in range(3)]
    docb = DocCard(id=uuid.uuid4(), company_id=cb, kind_id=kinds[1].id, title="Foreign Document", confidentiality="company", author_id=ub.id)
    db.add_all([*docs, docb])
    await db.flush()
    root = tmp_path / "uploads"
    root.mkdir()
    data = b"Actual synthetic bytes \x00\xff"
    sources, versions = [], []
    for doc in [*docs, docb]:
        fid = uuid.uuid4()
        path = root / f"{fid}.txt"
        path.write_bytes(data)
        source = SourceFile(id=fid, company_id=doc.company_id, file_name="test.txt", mime_type="text/plain",
                            size=len(data), storage_path=str(path), fingerprint=hashlib.sha256(data).hexdigest())
        version = DocVersion(id=uuid.uuid4(), company_id=doc.company_id, doc_id=doc.id, revision=1, role="body",
            file_id=fid, file_name="test.txt", mime="text/plain", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        sources.append(source)
        versions.append(version)
    db.add_all([*sources, *versions])
    await db.commit()
    def token(user, cid, client):
        return VerifiedFixture(client, uuid.uuid4(), uuid.uuid4(), cid, uuid.uuid4(), user.id, SCOPES,
            str(user.id), uuid.uuid4(), datetime.now(timezone.utc) + timedelta(hours=1), False, grants())
    tokens = {"client-a": token(ua, ca, "client-a"), "client-b": token(ub, cb, "client-b")}
    state = {"verifications": 0, "enabled": True}
    async def verify(raw, session):
        state["verifications"] += 1
        if raw not in tokens:
            raise HTTPException(401, "Secret token debug must never be echoed")
        return tokens[raw]
    app = create_product_api(session_factory=async_sessionmaker(db.bind, expire_on_commit=False), verifier=verify,
        enabled=lambda: state["enabled"], upload_dir=root, cursor_key=b"synthetic-cursor-key-32-bytes-only!",
        issuer="https://space.example.invalid", source_revision="synthetic-candidate")
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
                           headers={"Authorization": "Bearer client-a"}) as client:
        yield SimpleNamespace(**locals())


@pytest.mark.parametrize("resource,count", [("objects", 5), ("equipment", 2), ("counterparties", 4), ("contracts", 4), ("documents", 1)])
async def test_allowlisted_lists_are_tenant_scoped_and_have_true_levels(api, resource, count):
    response = await api.client.get("/" + resource)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["total"] == count and len(value["items"]) == count
    assert "NEVER-EXPOSE" not in response.text and "raw" not in response.text
    if resource in ("objects", "equipment"):
        assert {item["level"] for item in value["items"]} == {"servicePoint" if resource == "objects" else "station"}
    if resource == "equipment":
        assert value["items"][0]["powerKw"] is None


@pytest.mark.parametrize("resource,foreign_attr", [("objects", "foreign"), ("equipment", "eqb"), ("counterparties", "cpb"), ("contracts", "contractb"), ("documents", "docb")])
async def test_foreign_detail_is_404_and_other_client_sees_only_its_company(api, resource, foreign_attr):
    identifier = str(getattr(api, foreign_attr).id)
    denied = await api.client.get(f"/{resource}/{identifier}", headers={"X-Company-Id": str(api.cb)})
    assert denied.status_code == 404, denied.text
    allowed = await api.client.get(f"/{resource}/{identifier}", headers={"Authorization": "Bearer client-b"})
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("resource", RESOURCES)
async def test_set_and_empty_resource_grants_before_count_limit_and_detail(api, resource):
    values = {"objects": api.locations, "equipment": api.equipment, "counterparties": api.parties,
              "contracts": api.contracts, "documents": api.docs}[resource]
    first = str(values[0].id)
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=grants(**{resource: {"mode": "SET", "ids": frozenset([first])}}))
    response = await api.client.get("/" + resource)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and [item["id"] for item in response.json()["items"]] == [first]
    assert (await api.client.get(f"/{resource}/{values[1].id}")).status_code == 404
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=grants(**{resource: {"mode": "EMPTY", "ids": frozenset()}}))
    assert (await api.client.get("/" + resource)).status_code == 403


async def test_object_grant_does_not_grant_contract_or_counterparty_access(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=MappingProxyType({
        "objects": MappingProxyType({"mode": "ALL", "ids": frozenset()})}))
    assert (await api.client.get("/objects")).status_code == 200
    assert (await api.client.get("/contracts")).status_code == 403
    assert (await api.client.get("/counterparties")).status_code == 403


async def test_current_user_object_scope_filters_contracts_parties_equipment_without_duplicates(api):
    api.members[0].object_scope = [api.locations[0].id, api.locations[2].id]
    await api.db.commit()
    for resource, expected in (("contracts", [api.contracts[0].id]), ("counterparties", [api.parties[0].id]),
                               ("equipment", [api.equipment[0].id])):
        response = await api.client.get("/" + resource)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == len(expected)
        assert {item["id"] for item in response.json()["items"]} == {str(value) for value in expected}
    api.members[0].object_scope = []
    await api.db.commit()
    assert (await api.client.get("/contracts")).json()["total"] == 0


async def test_own_organization_intersects_current_user_and_all_domain_resources(api):
    api.members[0].own_organization_id = api.orgs[0].id
    await api.db.commit()
    assert (await api.client.get("/objects")).json()["total"] == 2
    assert (await api.client.get("/equipment")).json()["total"] == 1
    assert (await api.client.get("/contracts")).json()["total"] == 3
    assert (await api.client.get("/counterparties")).json()["total"] == 2
    api.tokens["client-a"] = replace(api.tokens["client-a"], own_organization_id=api.orgs[1].id)
    assert (await api.client.get("/objects")).status_code == 403


async def test_admin_still_cannot_widen_partner_resource_grant(api):
    api.members[0].role = "admin"
    api.users[0].is_superadmin = True
    await api.db.commit()
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=grants(objects={"mode": "SET", "ids": frozenset([api.locations[0].id])}))
    response = await api.client.get("/objects")
    assert response.json()["total"] == 1
    assert (await api.client.get(f"/objects/{api.locations[1].id}")).status_code == 404


async def test_links_to_inaccessible_resources_are_redacted(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=grants(
        objects={"mode": "EMPTY", "ids": frozenset()}, counterparties={"mode": "EMPTY", "ids": frozenset()}))
    assert (await api.client.get("/equipment")).json()["items"][0]["objectId"] is None
    assert (await api.client.get("/contracts")).json()["items"][0]["counterpartyId"] is None
    doc = (await api.client.get(f"/documents/{api.docs[0].id}")).json()
    assert doc["objectId"] is None and doc["counterpartyId"] is None


async def test_document_acl_is_current_and_independent_of_resource_grant(api):
    assert (await api.client.get(f"/documents/{api.docs[1].id}")).status_code == 404
    api.db.add(DocAccessGrant(company_id=api.ca, scope_type="doc", scope_id=api.docs[1].id,
        subject_type="user", subject_id=api.ua.id, permissions=["read"], denied_permissions=[]))
    await api.db.commit()
    response = await api.client.get(f"/documents/{api.docs[1].id}")
    assert response.status_code == 200 and response.json()["versions"][0]["id"] == str(api.versions[1].id)
    api.tokens["client-a"] = replace(api.tokens["client-a"], resource_scopes=grants(documents={"mode": "SET", "ids": frozenset([str(api.docs[0].id)])}))
    assert (await api.client.get(f"/documents/{api.docs[1].id}")).status_code == 404


async def test_strict_document_read_does_not_imply_native_download(api):
    doc = api.docs[2]
    grant = DocAccessGrant(company_id=api.ca, scope_type="doc", scope_id=doc.id,
        subject_type="user", subject_id=api.ua.id, permissions=["read"], denied_permissions=[])
    api.db.add(grant)
    await api.db.commit()
    assert (await api.client.get(f"/documents/{doc.id}")).status_code == 200
    url = f"/documents/{doc.id}/versions/{api.versions[2].id}/content"
    assert (await api.client.get(url)).status_code == 404
    grant.permissions = ["read", "download"]
    await api.db.commit()
    response = await api.client.get(url)
    assert response.status_code == 200 and response.content == api.data
    grant.denied_permissions = ["read"]
    await api.db.commit()
    assert (await api.client.get(url)).status_code == 404


async def test_download_uses_real_bytes_separate_scope_and_exact_version_chain(api):
    url = f"/documents/{api.docs[0].id}/versions/{api.versions[0].id}/content"
    response = await api.client.get(url)
    assert response.status_code == 200, response.text
    assert response.content == api.data and response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert (await api.client.get(url.replace(str(api.versions[0].id), str(api.versions[1].id)))).status_code == 404
    api.tokens["client-a"] = replace(api.tokens["client-a"], scopes=SCOPES - {"documents.files:download"})
    assert (await api.client.get(url)).status_code == 403
    assert (await api.client.get(f"/documents/{api.docs[0].id}")).status_code == 200


async def test_document_link_cannot_bypass_other_domain_file_policy(api):
    from app.models import StoreDocFile
    api.db.add(StoreDocFile(company_id=api.ca, doc_ref="synthetic-private-warehouse",
                           file_id=api.sources[0].id, tombstoned_at=datetime.now(timezone.utc)))
    await api.db.commit()
    assert (await api.client.get(f"/documents/{api.docs[0].id}")).status_code == 200
    response = await api.client.get(f"/documents/{api.docs[0].id}/versions/{api.versions[0].id}/content")
    assert response.status_code == 404


@pytest.mark.parametrize("mode", ["foreign-source", "tombstone", "purged", "retention", "outside", "symlink", "fifo"])
async def test_document_content_denies_closed_or_unsafe_file_paths(api, mode):
    version, source = api.versions[0], api.sources[0]
    if mode == "foreign-source":
        version.file_id = api.sources[3].id
    elif mode == "tombstone":
        version.tombstoned_at = datetime.now(timezone.utc)
    elif mode == "purged":
        # Column immutability is exercised by archive tests; create a distinct purged fixture.
        version.archive_purged_at = datetime.now(timezone.utc)
    elif mode == "retention":
        api.docs[0].retention_state = "destruction_authorized"
    elif mode == "fifo":
        target = api.root / "not-a-regular-file"
        os.mkfifo(target)
        source.storage_path = str(target)
    elif mode in {"outside", "symlink"}:
        target = api.tmp_path / "outside.txt"
        target.write_text("NEVER-EXPOSE")
        if mode == "outside":
            source.storage_path = str(target)
        else:
            link = api.root / "symlink.txt"
            link.symlink_to(target)
            source.storage_path = str(link)
    await api.db.commit()
    response = await api.client.get(f"/documents/{api.docs[0].id}/versions/{version.id}/content")
    assert response.status_code == 404, response.text
    assert "NEVER-EXPOSE" not in response.text


async def test_machine_is_registered_service_without_fake_user_and_documents_are_denied(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], is_machine=True, user_id=None, subject="machine:registered")
    assert (await api.client.get("/objects")).status_code == 200
    assert (await api.client.get("/documents")).status_code == 403
    assert (await api.client.get(f"/documents/{api.docs[0].id}/versions/{api.versions[0].id}/content")).status_code == 403


async def test_pagination_has_no_loss_on_equal_timestamps_and_binds_scope_filter_grant(api):
    seen, cursor = [], None
    while True:
        response = await api.client.get("/objects", params={"pageSize": 2, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["total"] == 5
        seen.extend(item["id"] for item in value["items"])
        if not value["nextCursor"]:
            break
        cursor = value["nextCursor"]
    assert len(seen) == 5 and len(set(seen)) == 5
    assert seen == sorted(row.id for row in api.locations)
    assert (await api.client.get("/objects", params={"pageSize": 2, "cursor": cursor, "q": "Node"})).status_code == 400
    api.tokens["client-a"] = replace(api.tokens["client-a"], grant_id=uuid.uuid4())
    assert (await api.client.get("/objects", params={"pageSize": 2, "cursor": cursor})).status_code == 400


async def test_cursor_is_invalid_for_other_resource_or_current_membership_scope(api):
    value = (await api.client.get("/objects", params={"pageSize": 1})).json()
    cursor = value["nextCursor"]
    assert (await api.client.get("/equipment", params={"pageSize": 1, "cursor": cursor})).status_code == 400
    api.members[0].object_scope = [api.locations[0].id]
    await api.db.commit()
    assert (await api.client.get("/objects", params={"pageSize": 1, "cursor": cursor})).status_code == 400
    assert (await api.client.get("/objects", params={"cursor": cursor[:-4] + "AAAA"})).status_code == 400


async def test_compatibility_location_limit_is_a_ceiling_not_a_resource_grant(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], location_ids=frozenset([api.locations[1].id]))
    assert (await api.client.get("/objects")).json()["total"] == 1
    assert (await api.client.get("/equipment")).json()["total"] == 1
    assert (await api.client.get("/contracts")).json()["items"][0]["id"] == str(api.contracts[1].id)
    api.tokens["client-a"] = replace(api.tokens["client-a"], location_ids=frozenset())
    assert (await api.client.get("/objects")).json()["total"] == 0


async def test_links_require_independent_read_scope_and_module_revocation_is_current(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], scopes=SCOPES - {"objects:read", "counterparties:read"})
    assert (await api.client.get("/equipment")).json()["items"][0]["objectId"] is None
    assert (await api.client.get("/contracts")).json()["items"][0]["counterpartyId"] is None
    api.members[0].modules = ["tasks"]
    await api.db.commit()
    assert (await api.client.get("/documents")).status_code == 403


@pytest.mark.parametrize("change,status", [
    ({"user_id": None}, 401), ({"is_machine": True}, 401),
    ({"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}, 401),
    ({"own_organization_id": "not-a-uuid"}, 401),
])
async def test_incomplete_or_expired_verified_facts_fail_closed(api, change, status):
    api.tokens["client-a"] = replace(api.tokens["client-a"], **change)
    assert (await api.client.get("/objects")).status_code == status


async def test_valid_date_window_and_unknown_source_date_preserve_nulls(api):
    assert (await api.client.get("/objects", params={"dateFrom": "2026-01-02", "dateTo": "2026-01-02"})).json()["total"] == 5
    assert (await api.client.get("/objects", params={"dateTo": "2026-01-01"})).json()["total"] == 0
    assert (await api.client.get("/objects", params={"dateTo": "9999-12-31"})).status_code == 200
    assert (await api.client.get(f"/contracts/{api.contracts[3].id}")).json()["date"] is None
    assert (await api.client.get(f"/objects/{api.locations[0].id}?unknown=secret")).status_code == 422


@pytest.mark.parametrize("params", [{"pageSize": 0}, {"pageSize": 201}, {"pageSize": "null"}, {"pageSize": "2.5"},
    {"dateFrom": "not-a-date"}, {"dateFrom": "0"}, {"dateFrom": "2026-01-02T00:00:00"},
    {"dateFrom": "2026-02-01", "dateTo": "2026-01-01"},
    {"companyId": "foreign"}, {"unknown": "NEVER-EXPOSE"}])
async def test_invalid_unknown_and_dates_return_safe_problem_details(api, params):
    response = await api.client.get("/objects", params=params)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_request"
    assert response.json()["requestId"] == response.headers["x-request-id"]
    assert "NEVER-EXPOSE" not in response.text and "input" not in response.text and "traceback" not in response.text


async def test_disabled_wrong_scope_and_credentials_deny_before_data_sql(api):
    captured = []
    def capture(conn, cursor, statement, params, context, executemany):
        captured.append(statement)
    event.listen(api.db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        api.state["enabled"] = False
        assert (await api.client.get("/objects")).status_code == 503
        assert api.state["verifications"] == 0 and not captured
        api.state["enabled"] = True
        api.tokens["client-a"] = replace(api.tokens["client-a"], scopes=frozenset())
        assert (await api.client.get("/objects")).status_code == 403
        assert not captured
        for bad in ("ordinary-user", "handoff", "refresh", "id-token"):
            assert (await api.client.get("/objects", headers={"Authorization": "Bearer " + bad})).status_code == 401
        assert (await api.client.get("/objects?access_token=client-a")).status_code == 401
        assert not captured
    finally:
        event.remove(api.db.bind.sync_engine, "before_cursor_execute", capture)


async def test_schema_and_registry_match_actual_child_routes_without_public_docs(api):
    schema = curated_openapi(api.app)
    registry = export_runtime_registry(api.app)
    assert registry["kind"] == "policy-runtime-registry" and registry["sourceRevision"] == "synthetic-candidate"
    assert len(registry["operations"]) == 14
    monitored = schema["paths"]["/objects/{objectId}/monitoring"]["get"]
    assert monitored["operationId"] == "getObjectMonitoring"
    assert monitored["security"] == [{"ProductOAuth": ["monitoring:read", "objects:read"]},
                                     {"ProductServiceOAuth": ["monitoring:read", "objects:read"]}]
    assert registry["mountPath"] == "/api/v1"
    assert {entry["path"] for entry in registry["operations"]} == set(schema["paths"])
    assert {entry["accessClass"] for entry in registry["operations"]} == {"partner"}
    assert {entry["operationId"] for entry in registry["operations"]} == {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()}
    assert {"Id", "Problem", "Object", "Contract", "DocumentDetail"} <= schema["components"]["schemas"].keys()
    assert schema["components"]["securitySchemes"]["ProductOAuth"]["type"] == "oauth2"
    def references(value):
        if isinstance(value, dict):
            if "$ref" in value:
                current = schema
                for part in value["$ref"].removeprefix("#/").split("/"):
                    current = current[part]
            for child in value.values():
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)
    references(schema)
    for path in schema["paths"].values():
        operation = path["get"]
        assert operation["security"] and operation["x-elsy-readiness"] == "candidate"
        assert operation["x-elsy-access-class"] == "partner" and "runtime-verified" not in operation
        assert set(operation["responses"]["422"]["content"]) == {"application/problem+json"}
    assert "evse" in schema["x-elsy-capabilities"]["gaps"]
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert (await api.client.get(path)).status_code == 404


async def test_formal_openapi_31_validation(api):
    validator = pytest.importorskip("openapi_spec_validator")
    validator.OpenAPIV31SpecValidator(curated_openapi(api.app)).validate()


async def test_default_factory_is_disabled_before_opening_sessions(api, monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace())
    def forbidden():
        raise AssertionError("A disabled API must not open a session")
    app = create_product_api(session_factory=forbidden)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/objects", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_deferred_m10_problem_is_translated_without_oauth_or_secret_body(api, monkeypatch):
    module = ModuleType("app.services.partner_identity")
    class PartnerProblem(Exception):
        status = 503
    async def verifier(raw, db):
        raise PartnerProblem("NEVER-EXPOSE OAuth configuration")
    module.PartnerProblem = PartnerProblem
    module.verify_partner_access_token = verifier
    monkeypatch.setitem(sys.modules, module.__name__, module)
    app = create_product_api(enabled=True, session_factory=async_sessionmaker(api.db.bind, expire_on_commit=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/objects", headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 503 and response.json()["code"] == "api_unavailable"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "NEVER-EXPOSE" not in response.text and "error_description" not in response.text


async def test_scope_catalog_is_exact_not_a_dot_alias(api):
    api.tokens["client-a"] = replace(api.tokens["client-a"], scopes=frozenset({"objects.read"}))
    assert (await api.client.get("/objects")).status_code == 403
