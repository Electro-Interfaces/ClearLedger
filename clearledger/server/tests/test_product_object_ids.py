"""Opaque service-point IDs; pure checks and opt-in synthetic PostgreSQL HTTP."""
from datetime import datetime, timedelta, timezone
import os
from types import MappingProxyType, SimpleNamespace
from urllib.parse import quote
import uuid

from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_PRODUCT_OBJECT_ID_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(FLAG + "=1 is required", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError(error)

from app.models import (ChargeSession, Company, DocCard, DocKind, EzsEquipmentUnit,
                        ServiceLocation, User, UserCompany)
from app.product_api import create_product_api, curated_openapi
from app.product_api import dto


@pytest.mark.parametrize("identifier", ["x" * 40, "Я" * 40, " Точка Я ", "точка?x#50%", "legacy/point", "legacy\npoint"])
def test_pure_service_point_output_keeps_native_identity(identifier):
    adapter = TypeAdapter(dto.Object.model_fields["id"].annotation)
    assert adapter.validate_python(identifier) == identifier


@pytest.mark.parametrize("identifier", ["", "x" * 41, "bad\x00id"])
def test_pure_service_point_invalid_id_is_rejected(identifier):
    adapter = TypeAdapter(dto.Object.model_fields["id"].annotation)
    with pytest.raises(ValidationError):
        adapter.validate_python(identifier)


def test_pure_other_id_contract_is_unchanged():
    adapter = TypeAdapter(dto.Id)
    identifier = str(uuid.uuid4())
    assert adapter.validate_python(identifier) == identifier
    for value in ("Я", " point ", "point/other", "bad\x00id"):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
    assert TypeAdapter(dto.Equipment.model_fields["id"].annotation).validate_python(identifier) == identifier


def test_pure_schema_distinguishes_object_identity_from_other_ids():
    schema = curated_openapi(create_product_api(enabled=False, issuer="https://synthetic.example"))
    models = schema["components"]["schemas"]
    assert models["ObjectId"]["minLength"] == 1 and models["ObjectId"]["maxLength"] == 40
    assert models["Id"]["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$"
    for path in ("/objects/{objectId}", "/objects/{objectId}/monitoring"):
        parameter = next(p for p in schema["paths"][path]["get"]["parameters"] if p["name"] == "objectId")
        assert parameter["schema"]["$ref"] == "#/components/schemas/ObjectId"
    for model, field in (("Equipment", "objectId"), ("Document", "objectId")):
        assert {"$ref": "#/components/schemas/ObjectId"} in models[model]["properties"][field]["anyOf"]
    assert models["Monitoring"]["properties"]["pointId"]["$ref"] == "#/components/schemas/ObjectId"


@pytest_asyncio.fixture
async def api(db):
    suffix = uuid.uuid4().hex[:8]
    companies = [Company(name="Synthetic IDs", slug=suffix + str(i), profile_id="energy") for i in range(2)]
    db.add_all(companies)
    await db.flush()
    cid, foreign_cid = (row.id for row in companies)
    user = User(company_id=cid, email=suffix + "@example.invalid", name="Synthetic IDs", password_hash="unused")
    db.add(user)
    await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid, role="user"))
    ids = [suffix + "a" * 32, suffix + "Я" * 32, " " + suffix + " Точка Я ",
           suffix + "?x#50%", suffix + "/legacy", suffix + "\ncontrol"]
    at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    points = [ServiceLocation(id=value, company_id=cid, code="id-" + str(i), name="Synthetic point " + str(i),
                              type="ev_charging", created_at=at) for i, value in enumerate(ids)]
    foreign = ServiceLocation(id=suffix + "-чужая", company_id=foreign_cid, code="foreign", name="Foreign")
    db.add_all([*points, foreign])
    await db.flush()
    equipment = EzsEquipmentUnit(company_id=cid, current_location_id=ids[1], kind="station", state="in_operation")
    kind = DocKind(company_id=cid, code=suffix, name="Synthetic", fields=[], route=[])
    db.add_all([equipment, kind])
    await db.flush()
    document = DocCard(company_id=cid, kind_id=kind.id, author_id=user.id, confidentiality="company",
                       object_id=ids[2], title="Synthetic ID reference", current_revision=1)
    db.add(document)
    db.add_all([ChargeSession(company_id=cid, location_id=value, session_ext_id=suffix + str(i),
                             started_at=at.replace(tzinfo=None), energy_kwh=1) for i, value in enumerate(ids)])
    await db.commit()
    resources = ("objects", "equipment", "counterparties", "contracts", "documents")
    scopes = frozenset({resource + ":read" for resource in resources} | {"monitoring:read"})
    grants = MappingProxyType({resource: MappingProxyType({"mode": "ALL", "ids": frozenset()}) for resource in resources})
    state = {"enabled": True, "grants": grants, "scopes": scopes, "calls": 0}

    async def verify(token, session):
        state["calls"] += 1
        return SimpleNamespace(client_id="synthetic-client", subject="synthetic-user", app_id=uuid.uuid4(),
            installation_id=uuid.uuid4(), grant_id=grant_id, company_id=cid, token_id=uuid.uuid4(),
            user_id=user.id, is_machine=False, scopes=state["scopes"], resource_scopes=state["grants"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1), own_organization_id=None, location_ids=None)

    grant_id = uuid.uuid4()
    # Stable identity dimensions are essential to exercise cursor binding.
    installation_id, app_id = uuid.uuid4(), uuid.uuid4()
    original_verify = verify
    async def stable_verify(token, session):
        value = await original_verify(token, session)
        value.installation_id, value.app_id = installation_id, app_id
        return value
    app = create_product_api(session_factory=async_sessionmaker(db.bind, expire_on_commit=False),
        verifier=stable_verify, enabled=lambda: state["enabled"], issuer="https://synthetic.example",
        cursor_key=b"synthetic-object-id-cursor-key-32!")
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
                           headers={"Authorization": "Bearer synthetic"}) as client:
        yield SimpleNamespace(**locals())


async def test_object_pages_keep_all_opaque_ids_and_cursor_identity(api):
    seen, cursor = [], None
    while True:
        response = await api.client.get("/objects", params={"pageSize": 2, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == len(api.ids)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == len(api.ids) and set(seen) == set(api.ids)


@pytest.mark.parametrize("index", [0, 1, 2, 3, 5])
async def test_encoded_object_detail_and_monitoring_roundtrip(api, index):
    identifier = api.ids[index]
    path = "/objects/" + quote(identifier, safe="")
    response = await api.client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == identifier
    response = await api.client.get(path + "/monitoring")
    assert response.status_code == 200, response.text
    assert response.json()["pointId"] == identifier


@pytest.mark.parametrize("resource", ["equipment", "documents"])
async def test_related_object_reference_is_lossless(api, resource):
    response = await api.client.get("/" + resource)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    expected = api.ids[1 if resource == "equipment" else 2]
    assert item["objectId"] == expected
    detail = await api.client.get("/" + resource + "/" + item["id"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["objectId"] == expected


@pytest.mark.parametrize("identifier", ["x" * 41, "bad\x00id"])
@pytest.mark.parametrize("suffix", ["", "/monitoring"])
async def test_invalid_path_is_422_before_domain_sql(api, identifier, suffix):
    statements = []
    def observed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(api.db.bind.sync_engine, "before_cursor_execute", observed)
    try:
        response = await api.client.get("/objects/" + quote(identifier, safe="") + suffix)
    finally:
        event.remove(api.db.bind.sync_engine, "before_cursor_execute", observed)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert not any("service_locations" in statement or "charge_sessions" in statement for statement in statements)


async def test_wrong_tenant_and_narrow_grant_do_not_expand(api):
    for suffix in ("", "/monitoring"):
        foreign = await api.client.get("/objects/" + quote(api.foreign.id, safe="") + suffix,
                                       headers={"X-Company-Id": str(api.foreign_cid)})
        assert foreign.status_code == 404, foreign.text
    api.state["grants"] = MappingProxyType({**api.grants, "objects": MappingProxyType({"mode": "SET", "ids": frozenset({api.ids[2]})})})
    visible = await api.client.get("/objects")
    assert visible.status_code == 200, visible.text
    assert [item["id"] for item in visible.json()["items"]] == [api.ids[2]]
    assert (await api.client.get("/objects/" + quote(api.ids[1], safe=""))).status_code == 404
    equipment = await api.client.get("/equipment")
    assert equipment.status_code == 200, equipment.text
    assert equipment.json()["items"][0]["objectId"] is None


async def test_slash_id_is_listed_but_single_segment_detail_does_not_remap(api):
    response = await api.client.get("/objects/" + quote(api.ids[4], safe=""))
    assert response.status_code == 404, response.text


async def test_other_resource_id_validation_and_disabled_gate_are_unchanged(api):
    for resource in ("equipment", "counterparties", "contracts", "documents"):
        response = await api.client.get("/" + resource + "/" + quote("чужая", safe=""))
        assert response.status_code == 422, response.text
    api.state["enabled"] = False
    assert (await api.client.get("/objects/" + "x" * 41)).status_code == 503


async def test_invalid_object_id_does_not_bypass_authentication(api):
    async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://test") as client:
        assert (await client.get("/objects/" + "x" * 41)).status_code == 401
