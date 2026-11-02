"""Native HTTP/PostgreSQL invariants; opt-in isolated synthetic test database."""
import asyncio
from datetime import date
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid
from urllib.parse import quote

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_OBJECT_COMMAND_TESTS") != "1":
    pytest.skip("Opt in with RUN_OBJECT_COMMAND_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_OBJECT_COMMAND_TESTS"):
    raise RuntimeError(error)

from app.auth import get_current_user
from app.database import get_db
from app.models import (AuditEvent, ChargeSession, Company, Contract, ContractLocation, EzsEquipmentUnit,
                        Counterparty, ObjectExportLog, ObjectLink, Organization,
                        ServiceLocation, User, UserCompany)
from app.routers import locations_router, space_registry_router
from app.scope import set_request_organization, set_request_scope
from app.services import location_commands, space_projection, space_registry


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:12]
    async with factory() as session:
        companies = [Company(name="Synthetic " + suffix + str(i), slug=suffix + str(i), profile_id="energy") for i in range(2)]
        session.add_all(companies)
        user = User(name="Synthetic member", email=suffix + "@example.invalid", password_hash="unused")
        session.add(user)
        await session.flush()
        session.add_all([UserCompany(user_id=user.id, company_id=c.id, role="admin") for c in companies])
        locations = [ServiceLocation(id=suffix + str(i), company_id=companies[0].id,
                                     code="code-" + str(i), name="Synthetic point", station_number="number-" + str(i),
                                     extra_metadata={"number": "number-" + str(i), "asuimStationId": "raw",
                                                     "numberHistory": [{"было": "old-" + str(i)}]},
                                     source_bindings=[{"sourceId": "raw-source"}]) for i in range(2)]
        session.add_all(locations)
        await session.commit()
    projections = []

    async def project(session, cid, identifier, *args, **kwargs):
        row = await session.get(ServiceLocation, identifier)
        projections.append((cid, identifier, row.code))
        return {"sent": 1}

    monkeypatch.setattr(space_projection, "project_object", project)
    app = FastAPI()
    app.include_router(locations_router.router, prefix="/api")
    app.include_router(space_registry_router.router, prefix="/api")

    async def get_actor():
        set_request_scope(None)
        set_request_organization(None)
        return user

    async def get_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_current_user] = get_actor
    app.dependency_overrides[get_db] = get_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url="http://test") as client:
        yield SimpleNamespace(factory=factory, cid=companies[0].id, foreign=companies[1].id,
                              user=user, locations=locations, client=client, app=app, projections=projections)
    set_request_scope(None)
    set_request_organization(None)


def native_payload(w, loc=None, **changes):
    loc = loc or w.locations[0]
    return {"id": loc.id, "company_id": str(w.cid), "code": loc.code,
            "name": loc.name, "metadata": loc.extra_metadata, **changes}


async def seed_freeze(w, reason):
    loc = w.locations[0]
    async with w.factory() as session:
        if reason == "session":
            session.add(ChargeSession(company_id=w.cid, location_id=loc.id, session_ext_id=uuid.uuid4().hex))
        elif reason in {"external", "internal"}:
            session.add(ObjectExportLog(company_id=w.cid, actor_kind="integration", destination="synthetic",
                                        is_external=reason == "external", objects_count=1))
        elif reason == "contract":
            party = Counterparty(company_id=w.cid, name="Synthetic party")
            org = Organization(company_id=w.cid, name="Synthetic contract organization", inn="000000000001")
            session.add_all([party, org])
            await session.flush()
            contract = Contract(company_id=w.cid, counterparty_id=party.id, organization_id=org.id,
                                type="energy", scope_type="locations", number="test", date="2026-10-29")
            session.add(contract)
            await session.flush()
            session.add(ContractLocation(company_id=w.cid, contract_id=contract.id, location_id=loc.id))
        elif reason == "accounted":
            unit = EzsEquipmentUnit(company_id=w.cid, inventory_number="synthetic-inventory")
            session.add(unit)
            await session.flush()
            session.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=loc.id,
                                   child_type="station", child_id=str(unit.id), relation="placed_at",
                                   valid_from=date(2020, 1, 1)))
        await session.commit()


async def test_characterization_registry_cannot_rename_frozen_point(world):
    w = world
    await seed_freeze(w, "session")
    response = await w.client.patch(f"/api/registry/objects/{w.locations[0].id}",
                                    params={"company_id": str(w.cid)}, json={"code": "rewritten"})
    assert response.status_code == 409, response.text


async def test_characterization_upsert_cannot_move_tenant_even_with_two_memberships(world):
    w = world
    response = await w.client.post("/api/locations", json=native_payload(w, company_id=str(w.foreign)))
    assert response.status_code == 404, response.text
    async with w.factory() as session:
        assert (await session.get(ServiceLocation, w.locations[0].id)).company_id == w.cid
    assert w.projections == []


async def test_characterization_upsert_checks_duplicate_before_assignment(world):
    w = world
    response = await w.client.post("/api/locations", json=native_payload(w, code=w.locations[1].code))
    assert response.status_code == 409, response.text


async def mutate(w, path, changes):
    if path == "upsert":
        return await w.client.post("/api/locations", json=native_payload(w, **changes))
    if path == "native":
        return await w.client.patch(f"/api/locations/{w.locations[0].id}", json=changes)
    return await w.client.patch(f"/api/registry/objects/{w.locations[0].id}",
                                params={"company_id": str(w.cid)}, json=changes)


@pytest.mark.parametrize("path", ["upsert", "native", "registry"])
@pytest.mark.parametrize("reason", ["contract", "session", "external", "accounted"])
async def test_all_mutation_paths_enforce_freeze_before_effects(world, path, reason):
    w = world
    await seed_freeze(w, reason)
    response = await mutate(w, path, {"code": "rewritten"})
    assert response.status_code == 409, response.text
    async with w.factory() as session:
        row = await session.get(ServiceLocation, w.locations[0].id)
        assert row.code == w.locations[0].code and row.company_id == w.cid
        assert row.extra_metadata == w.locations[0].extra_metadata
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid)) == 0
    assert w.projections == []


@pytest.mark.parametrize("path", ["upsert", "native"])
@pytest.mark.parametrize("metadata", [{"number": None}, {"number": ""}, None])
async def test_frozen_number_cannot_be_cleared_by_null_or_empty(world, path, metadata):
    await seed_freeze(world, "session")
    response = await mutate(world, path, {"metadata": metadata})
    assert response.status_code == 409, response.text
    assert not world.projections


@pytest.mark.parametrize("path", ["upsert", "native", "registry"])
async def test_interapp_projection_is_not_external_freeze(world, path):
    w = world
    await seed_freeze(w, "internal")
    response = await mutate(w, path, {"code": "legitimate", "address": "new address"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "legitimate" and body["id"] == w.locations[0].id
    if path == "registry":
        assert body["companyId"] == str(w.cid) and "metadata" not in body and "sourceBindings" not in body
        assert not w.projections  # The registry never acquired native projection side effects.
        async with w.factory() as session:
            audit = (await session.scalars(select(AuditEvent).where(AuditEvent.company_id == w.cid))).one()
            assert audit.action == "space.object.update"
            assert json.loads(audit.details)["code"] == {"from": "code-0", "to": "legitimate"}
    else:
        assert body["metadata"]["asuimStationId"] == "raw"
        assert "passport" in body and "sourceBindings" in body
        assert w.projections == [(w.cid, w.locations[0].id, "legitimate")]


async def test_metadata_partial_update_preserves_identity_and_explicit_nullable_clears(world):
    w = world
    await seed_freeze(w, "session")
    response = await mutate(w, "native", {"metadata": {"comment": "checked"}, "address": None})
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["number"] == "number-0"
    assert response.json()["passport"]["stationNumber"] == "number-0"
    assert response.json()["metadata"]["numberHistory"] == [{"было": "old-0"}]
    assert response.json()["sourceBindings"] == [{"sourceId": "raw-source"}]
    assert response.json()["address"] is None


async def test_upsert_omitted_metadata_does_not_clear_a_frozen_number(world):
    w = world
    await seed_freeze(w, "session")
    payload = native_payload(w, name="renamed display name")
    payload.pop("metadata")
    response = await w.client.post("/api/locations", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["number"] == "number-0"
    assert response.json()["passport"]["stationNumber"] == "number-0"


@pytest.mark.parametrize("changes", [{"code": None}, {"code": "  "}, {"name": None}, {"sourceBindings": None}])
async def test_null_required_fields_fail_without_mutation(world, changes):
    response = await mutate(world, "native", changes)
    assert response.status_code == 422, response.text
    assert world.projections == []


@pytest.mark.parametrize("path", ["upsert", "native", "registry"])
@pytest.mark.parametrize("historical", [False, True])
async def test_current_and_history_numbers_are_reserved(world, path, historical):
    code = "old-1" if historical else "number-1"
    response = await mutate(world, path, {"code": code})
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("path", ["native", "registry"])
async def test_own_retired_alias_cannot_be_silently_reassigned(world, path):
    response = await mutate(world, path, {"code": "old-0"})
    assert response.status_code == 409, response.text


async def test_dated_number_link_is_reserved_after_retirement(world):
    w = world
    async with w.factory() as session:
        session.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id="retired-id",
                               child_type="number", child_id="retired-number", relation="number",
                               valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1)))
        await session.commit()
    response = await mutate(w, "registry", {"code": "retired-number"})
    assert response.status_code == 409, response.text


async def test_create_is_distinct_from_upsert_and_command_does_not_commit(world):
    w = world
    set_request_scope(None)
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.create(session, w.cid, w.locations[0].id, {"code": "new", "name": "new"})
        assert error.value.status == 409
        await session.rollback()
        identifier = uuid.uuid4().hex
        await location_commands.create(session, w.cid, identifier, {"code": "uncommitted", "name": "new"})
        await session.flush()
        async with w.factory() as observer:
            assert await observer.get(ServiceLocation, identifier) is None
        await session.rollback()
    async with w.factory() as observer:
        assert await observer.get(ServiceLocation, identifier) is None


async def test_command_tenant_fields_are_not_payload_authority(world):
    w = world
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.upsert(session, w.cid, w.locations[0].id, {"company_id": w.foreign})
        assert error.value.status == 422
        await session.rollback()


@pytest.mark.parametrize("path", ["upsert", "native"])
async def test_native_member_scope_cannot_expand_through_mutation(world, path):
    w = world
    async with w.factory() as session:
        member = await session.get(UserCompany, (w.user.id, w.cid))
        member.role, member.object_scope = "user", [w.locations[1].id]
        await session.commit()
    response = await mutate(w, path, {"address": "outside"})
    assert response.status_code == 404, response.text
    response = await w.client.post("/api/locations", json=native_payload(w, id=uuid.uuid4().hex, code="new"))
    assert response.status_code == 403, response.text
    registry = await mutate(w, "registry", {"address": "outside"})
    assert registry.status_code == 403  # Distinct registry admin admission retained.


async def test_own_org_is_intersected_without_unassigned_fallback(world):
    w = world
    async with w.factory() as session:
        org = Organization(company_id=w.cid, name="Own synthetic organization", inn="000000000002")
        session.add(org)
        await session.flush()
        member = await session.get(UserCompany, (w.user.id, w.cid))
        member.role, member.own_organization_id = "user", org.id
        await session.commit()
    response = await mutate(w, "native", {"address": "not granted"})
    assert response.status_code == 404, response.text
    await seed_freeze(w, "contract")
    async with w.factory() as session:
        contract = await session.scalar(select(Contract).where(Contract.company_id == w.cid))
        contract.organization_id = org.id
        await session.commit()
    response = await mutate(w, "native", {"address": "permitted"})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("kind", ["create", "patch", "upsert"])
async def test_concurrent_native_and_registry_duplicates_without_unique_index(world, kind):
    w = world
    async with w.factory() as session:
        # Model legacy startup where creating the existing partial index failed
        # on old duplicates: the command barrier must carry the guarantee itself.
        await session.execute(text("DROP INDEX IF EXISTS uq_service_locations_code"))
        await session.commit()
    try:
        if kind == "create":
            requests = [w.client.post("/api/locations", json=native_payload(w, id=uuid.uuid4().hex, code="race")),
                        w.client.post("/api/registry/objects", params={"company_id": str(w.cid)},
                                      json={"code": "race", "name": "new"})]
        else:
            requests = [mutate(w, "upsert" if kind == "upsert" else "native", {"code": "race"}),
                        w.client.patch(f"/api/registry/objects/{w.locations[1].id}",
                                       params={"company_id": str(w.cid)}, json={"code": "race"})]
        results = await asyncio.wait_for(asyncio.gather(*requests), 10)
        assert sum(r.status_code in {200, 201} for r in results) == 1, [(r.status_code, r.text) for r in results]
        assert sum(r.status_code == 409 for r in results) == 1
        async with w.factory() as session:
            assert await session.scalar(select(func.count()).select_from(ServiceLocation).where(
                ServiceLocation.company_id == w.cid, ServiceLocation.code == "race")) == 1
    finally:
        async with w.factory() as session:
            await session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_service_locations_code ON service_locations(company_id, code) WHERE is_test = false"))
            await session.commit()


@pytest.mark.parametrize("path", ["native", "registry"])
@pytest.mark.parametrize("reason", ["session", "contract"])
async def test_freeze_insert_committing_first_is_rechecked_after_row_lock(world, path, reason):
    w = world
    async with w.factory() as producer:
        if reason == "session":
            producer.add(ChargeSession(company_id=w.cid, location_id=w.locations[0].id, session_ext_id=uuid.uuid4().hex))
        else:
            party = Counterparty(company_id=w.cid, name="Synthetic concurrent party")
            org = Organization(company_id=w.cid, name="Synthetic concurrent org", inn="000000000003")
            producer.add_all([party, org])
            await producer.flush()
            contract = Contract(company_id=w.cid, counterparty_id=party.id, organization_id=org.id,
                                type="energy", number="race", date="2026-10-29")
            producer.add(contract)
            await producer.flush()
            producer.add(ContractLocation(company_id=w.cid, location_id=w.locations[0].id, contract_id=contract.id))
        await producer.flush()  # Holds the FK key-share lock until commit.
        mutation = asyncio.create_task(mutate(w, path, {"code": "racy-rename"}))
        try:
            done, _ = await asyncio.wait({mutation}, timeout=0.05)
            assert not done, "mutation must wait for the FK producer"
            await producer.commit()
            response = await asyncio.wait_for(mutation, 5)
            assert response.status_code == 409, response.text
        finally:
            if not mutation.done():
                mutation.cancel()
                await asyncio.gather(mutation, return_exceptions=True)


async def test_mutation_lock_first_blocks_fk_insert_until_caller_rollback(world):
    w = world
    set_request_scope(None)
    async with w.factory() as mutation, w.factory() as producer:
        await location_commands.update(mutation, w.cid, w.locations[0].id, {"code": "provisional"})
        await mutation.flush()
        producer.add(ChargeSession(company_id=w.cid, location_id=w.locations[0].id, session_ext_id=uuid.uuid4().hex))
        pending = asyncio.create_task(producer.flush())
        try:
            done, _ = await asyncio.wait({pending}, timeout=0.05)
            assert not done
            await mutation.rollback()
            await asyncio.wait_for(pending, 5)
            await producer.commit()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    async with w.factory() as observer:
        assert (await observer.get(ServiceLocation, w.locations[0].id)).code == "code-0"


@pytest.mark.parametrize("path", ["native", "registry"])
async def test_failure_rolls_back_local_changes_and_registry_audit(world, path, monkeypatch):
    w = world

    async def failure(*args, **kwargs):
        raise RuntimeError("synthetic use-case failure")

    monkeypatch.setattr(space_projection if path == "native" else space_registry,
                        "project_object" if path == "native" else "_audit", failure)
    response = await mutate(w, path, {"code": "rolled-back"})
    assert response.status_code == 500
    async with w.factory() as session:
        assert (await session.get(ServiceLocation, w.locations[0].id)).code == "code-0"
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == w.cid)) == 0


async def test_initial_create_keeps_raw_metadata_and_zero_is_a_number(world):
    w = world
    identifier = uuid.uuid4().hex
    payload = native_payload(w, id=identifier, code="  new  ", metadata={"number": 0, "asuimStationId": "raw-new", "nested": {"x": 1}},
                             sourceBindings=[{"sourceId": "test", "config": {"station": "0"}}])
    response = await w.client.post("/api/locations", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["code"] == "new"
    assert response.json()["metadata"] == payload["metadata"]
    assert response.json()["sourceBindings"] == payload["sourceBindings"]
    assert response.json()["passport"]["stationNumber"] == "0"


@pytest.mark.parametrize("evidence", ["link", "audit"])
async def test_known_retired_id_cannot_be_reused_by_upsert(world, evidence):
    w = world
    identifier = uuid.uuid4().hex
    async with w.factory() as session:
        if evidence == "link":
            session.add(ObjectLink(company_id=w.cid, parent_type="point_of_service", parent_id=identifier,
                                   child_type="number", child_id="old-retired-number", relation="number",
                                   valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1)))
        else:
            session.add(AuditEvent(company_id=w.cid, user_id=str(w.user.id), user_name=w.user.name, action="space.object.create",
                                   details=json.dumps({"objectId": identifier})))
        await session.commit()
    response = await w.client.post("/api/locations", json=native_payload(w, id=identifier, code="new"))
    assert response.status_code == 409, response.text


def test_domain_commands_have_no_router_or_http_dependency():
    source = Path(location_commands.__file__).read_text()
    assert "from fastapi" not in source and "app.routers" not in source


async def test_physical_delete_is_closed_without_fabricating_retirement(world):
    w = world
    response = await w.client.delete(f"/api/locations/{w.locations[0].id}")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Физическое удаление объекта недоступно: требуется вывод из эксплуатации с сохранением истории"
    async with w.factory() as session:
        row = await session.get(ServiceLocation, w.locations[0].id)
        assert row is not None and row.status == "active" and row.code == "code-0"
    assert w.projections == []
    unknown = await w.client.delete("/api/locations/not-a-real-id")
    assert unknown.status_code == 404
    async with w.factory() as session:
        member = await session.get(UserCompany, (w.user.id, w.cid))
        member.role, member.object_scope = "user", [w.locations[1].id]
        await session.commit()
    forbidden = await w.client.delete(f"/api/locations/{w.locations[0].id}")
    assert forbidden.status_code == 404


@pytest.mark.parametrize("operation", ["update", "create", "upsert"])
async def test_foreign_row_lock_never_delays_own_company_command(world, operation):
    w = world
    identifier = uuid.uuid4().hex
    async with w.factory() as seed:
        seed.add(ServiceLocation(id=identifier, company_id=w.foreign, code="foreign-lock", name="Foreign payload"))
        await seed.commit()
    set_request_scope(None)
    async with w.factory() as owner, w.factory() as requester:
        await owner.execute(select(ServiceLocation.id).where(ServiceLocation.id == identifier).with_for_update())
        # PostgreSQL server timeout makes a cross-tenant wait a deterministic
        # failure. The foreign owner transaction remains open throughout.
        await requester.execute(text("SET LOCAL lock_timeout = '250ms'"))
        command = getattr(location_commands, operation)
        if operation == "update":
            assert await command(requester, w.cid, identifier, {"name": "forbidden"}) is None
        else:
            with pytest.raises(location_commands.LocationConflict) as error:
                await command(requester, w.cid, identifier, {"code": "new", "name": "forbidden"})
            assert error.value.status == 404
        assert not any(isinstance(row, ServiceLocation) and row.id == identifier
                       for row in requester.identity_map.values())
        await requester.rollback()
        # Legitimate same-company UPDATE still waits for the very same row lock.
        await requester.execute(text("SET LOCAL lock_timeout = '250ms'"))
        from sqlalchemy.exc import DBAPIError
        with pytest.raises(DBAPIError):
            await location_commands.update(requester, w.foreign, identifier, {"name": "legitimate"})
        await requester.rollback()
        await owner.rollback()
        result = await location_commands.update(requester, w.foreign, identifier, {"name": "legitimate"})
        assert result.location.name == "legitimate"
        await requester.rollback()


@pytest.mark.parametrize("identifier", ["x" * 41, "bad\x00id"])
@pytest.mark.parametrize("operation", ["post", "patch", "delete", "operational-status"])
async def test_invalid_native_mutation_id_is_422_before_any_sql(world, identifier, operation):
    w = world
    statements = []
    engine = w.factory.kw["bind"].sync_engine
    def observed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observed)
    try:
        path = "/api/locations/" + quote(identifier, safe="")
        if operation == "post":
            response = await w.client.post("/api/locations", json=native_payload(w, id=identifier, code="invalid", metadata=None))
        elif operation == "operational-status":
            response = await w.client.patch(path + "/operational-status", json={"status": "working"})
        else:
            response = await w.client.request(operation.upper(), path,
                **({"json": {"name": "invalid"}} if operation == "patch" else {}))
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert response.status_code == 422, response.text
    assert statements == []
    assert not w.projections


@pytest.mark.parametrize("operation", ["create", "upsert", "update"])
@pytest.mark.parametrize("identifier", ["x" * 41, "bad\x00id", ""])
async def test_direct_command_id_validation_precedes_advisory_or_data_sql(world, operation, identifier):
    w = world
    statements = []
    engine = w.factory.kw["bind"].sync_engine
    def observed(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observed)
    try:
        async with w.factory() as session:
            with pytest.raises(location_commands.LocationConflict) as error:
                await getattr(location_commands, operation)(session, w.cid, identifier, {"code": "new", "name": "new"})
            assert error.value.status == 422
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert statements == []


@pytest.mark.parametrize("identifier", ["a" * 40, "Я" * 40, " Точка-Я "])
async def test_legitimate_opaque_id_roundtrips_without_trimming(world, identifier):
    w = world
    response = await w.client.post("/api/locations", json=native_payload(w, id=identifier, code="valid", metadata=None))
    assert response.status_code == 200, response.text
    assert response.json()["id"] == identifier
    path = "/api/locations/" + quote(identifier, safe="")
    response = await w.client.patch(path, json={"name": "updated opaque"})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == identifier and response.json()["name"] == "updated opaque"


@pytest.mark.parametrize("path", ["registry", "upsert"])
async def test_http_own_company_request_rejects_foreign_id_while_owner_holds_row_lock(world, path):
    w = world
    identifier = uuid.uuid4().hex
    async with w.factory() as seed:
        seed.add(ServiceLocation(id=identifier, company_id=w.foreign, code="foreign-http", name="Foreign payload"))
        await seed.commit()

    async def request_session():
        async with w.factory() as session:
            await session.execute(text("SET LOCAL lock_timeout = '250ms'"))
            try:
                yield session
            finally:
                await session.rollback()

    w.app.dependency_overrides[get_db] = request_session
    async with w.factory() as owner:
        await owner.execute(select(ServiceLocation.id).where(ServiceLocation.id == identifier).with_for_update())
        if path == "registry":
            response = await w.client.patch(f"/api/registry/objects/{identifier}",
                params={"company_id": str(w.cid)}, json={"name": "forbidden"})
        else:
            response = await w.client.post("/api/locations", json=native_payload(w, id=identifier))
        assert response.status_code == 404, response.text
        assert owner.in_transaction()  # The foreign row was never released to make this pass.
