"""Opt-in PostgreSQL checks with the production ORM scope listener installed."""
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_LOCATION_NUMBER_SCOPE_TESTS") != "1":
    pytest.skip("Opt in with RUN_LOCATION_NUMBER_SCOPE_TESTS=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag="RUN_LOCATION_NUMBER_SCOPE_TESTS"):
    raise RuntimeError(error)

# Reuse the existing synthetic HTTP world, including its separate opt-in guard.
from tests.test_location_commands import world, mutate, native_payload, seed_freeze
from app.models import (Contract, ContractLocation, Counterparty, Organization,
                        ServiceLocation, UserCompany)
from app.scope import (current_object_scope, current_organization, install_orm_scope,
                       set_request_organization, set_request_scope)
from app.services import location_commands

CONFLICT = "Номер уже занят текущим или историческим объектом компании"


@pytest.fixture(scope="module", autouse=True)
def real_orm_listener():
    # The small ASGI world does not run main.lifespan. Install the real listener
    # just as production does; no fake matcher, listener or admission predicate.
    install_orm_scope()


async def snapshot(w):
    table = ServiceLocation.__table__.c
    async with w.factory() as session:
        return (await session.execute(select(table.id, table.company_id, table.code,
            table.station_number, table.extra_metadata, table.source_bindings)
            .where(table.company_id == w.cid).order_by(table.id))).all()


@pytest_asyncio.fixture
async def scoped(world):
    w = world
    async with w.factory() as session:
        member = await session.get(UserCompany, (w.user.id, w.cid))
        member.role, member.object_scope = "user", [w.locations[0].id]
        await session.commit()
    return w


def assert_no_hidden_entities(session, w):
    assert not any(isinstance(row, ServiceLocation) and row.id != w.locations[0].id
                   for row in session.identity_map.values())


@pytest.mark.parametrize("path,field", [("native", "code"), ("upsert", "code"),
                                      ("native", "number"), ("upsert", "number")])
async def test_hidden_history_collision_http_is_generic_and_atomic(scoped, path, field):
    w = scoped
    # B's current code is code-1: the partial unique index cannot catch old-1.
    before = await snapshot(w)
    changes = {"code": "old-1"} if field == "code" else {"metadata": {"number": "old-1"}}
    response = await mutate(w, path, changes)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": CONFLICT}
    assert w.locations[1].id not in response.text and "old-1" not in response.text
    assert current_object_scope() == [w.locations[0].id]
    assert await snapshot(w) == before
    assert not w.projections


@pytest.mark.parametrize("operation", ["update", "upsert"])
@pytest.mark.parametrize("field", ["code", "number"])
@pytest.mark.parametrize("occupied", ["code-1", "number-1", "old-1"])
async def test_shared_command_checks_hidden_current_and_history(scoped, operation, field, occupied):
    w = scoped
    before = await snapshot(w)
    set_request_scope([w.locations[0].id])
    changes = {"code": occupied} if field == "code" else {"metadata": {"number": occupied}}
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await getattr(location_commands, operation)(session, w.cid, w.locations[0].id, changes)
        assert error.value.status == 409 and error.value.detail == CONFLICT
        assert_no_hidden_entities(session, w)
        assert current_object_scope() == [w.locations[0].id]
        await session.rollback()
    assert await snapshot(w) == before


async def test_listener_positive_control_hides_b_on_list_get_and_write(scoped):
    w = scoped
    response = await w.client.get("/api/locations", params={"company_id": str(w.cid)})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [w.locations[0].id]
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        assert await session.get(ServiceLocation, w.locations[1].id) is None
        assert [row.id for row in (await session.scalars(select(ServiceLocation)
            .where(ServiceLocation.company_id == w.cid))).all()] == [w.locations[0].id]
        assert_no_hidden_entities(session, w)
    response = await w.client.patch("/api/locations/" + w.locations[1].id, json={"name": "forbidden"})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("existing", [True, False])
async def test_scoped_upsert_keeps_hidden_existing_404_and_new_403(scoped, existing):
    w = scoped
    identifier = w.locations[1].id if existing else uuid.uuid4().hex
    expected = 404 if existing else 403
    before = await snapshot(w)
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.upsert(session, w.cid, identifier,
                {"code": "unassigned-code", "name": "forbidden"})
        assert error.value.status == expected
        assert_no_hidden_entities(session, w)
        assert not session.new
        assert current_object_scope() == [w.locations[0].id]
        await session.rollback()
    response = await w.client.post("/api/locations", json=native_payload(w,
        id=identifier, code="unassigned-code", name="forbidden"))
    assert response.status_code == expected, response.text
    if existing:
        assert response.json() == {"detail": "Объект не найден"}
    assert await snapshot(w) == before and not w.projections


async def test_code_preflight_is_company_wide_without_loading_hidden_entities(scoped):
    w = scoped
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        assert await location_commands.code_taken(session, w.cid, " code-1 ")
        assert not await location_commands.code_taken(session, w.cid, "code-1", except_id=w.locations[1].id)
        assert not await location_commands.code_taken(session, w.foreign, "code-1")
        assert_no_hidden_entities(session, w)
        assert current_object_scope() == [w.locations[0].id]


@pytest.mark.parametrize("path", ["native", "upsert", "registry"])
async def test_registry_and_native_admin_history_contract(world, path):
    before = await snapshot(world)
    response = await mutate(world, path, {"code": "old-1"})
    assert response.status_code == 409 and response.json() == {"detail": CONFLICT}
    assert await snapshot(world) == before and not world.projections


async def test_registry_scoped_member_admission_stays_forbidden(scoped):
    before = await snapshot(scoped)
    response = await mutate(scoped, "registry", {"code": "old-1"})
    assert response.status_code == 403
    assert await snapshot(scoped) == before and not scoped.projections


@pytest.mark.parametrize("scope", [[], ["unassigned-synthetic-id"]])
async def test_empty_and_disjoint_command_admission_stays_closed(world, scope):
    before = await snapshot(world)
    set_request_scope(scope)
    async with world.factory() as session:
        if scope == []:
            with pytest.raises(location_commands.LocationConflict) as error:
                await location_commands.update(session, world.cid, world.locations[0].id, {"name": "forbidden"})
            assert error.value.status == 404
        else:
            assert await location_commands.update(session, world.cid, world.locations[0].id,
                {"name": "forbidden"}) is None
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.create(session, world.cid, uuid.uuid4().hex, {"code": "new", "name": "forbidden"})
        assert error.value.status == 403
        assert current_object_scope() == scope
        await session.rollback()
    assert await snapshot(world) == before


async def test_organization_admission_is_not_expanded(world):
    w = world
    async with w.factory() as session:
        org = Organization(company_id=w.cid, name="Synthetic scoped organization", inn="000000000003")
        party = Counterparty(company_id=w.cid, name="Synthetic scoped party")
        session.add_all([org, party])
        await session.flush()
        contract = Contract(company_id=w.cid, counterparty_id=party.id, organization_id=org.id,
            type="energy", scope_type="locations", number="test", date="2026-10-30")
        session.add(contract)
        await session.flush()
        session.add(ContractLocation(company_id=w.cid, contract_id=contract.id, location_id=w.locations[0].id))
        await session.commit()
    set_request_scope([w.locations[0].id])
    set_request_organization(uuid.uuid4())
    async with w.factory() as session:
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.update(session, w.cid, w.locations[0].id, {"name": "forbidden"})
        assert error.value.status == 404
        await session.rollback()
        set_request_organization(org.id)
        result = await location_commands.update(session, w.cid, w.locations[0].id, {"name": "allowed"})
        assert result.location.name == "allowed"
        assert current_organization() == org.id
        await session.rollback()


async def test_foreign_numbers_do_not_reserve_own_company_and_caller_owns_rollback(scoped):
    w = scoped
    async with w.factory() as session:
        session.add(ServiceLocation(id=uuid.uuid4().hex, company_id=w.foreign, code="foreign-current",
            name="Synthetic foreign point", extra_metadata={"numberHistory": [{"было": "foreign-alias"}]}))
        await session.commit()
    before = await snapshot(w)
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        result = await location_commands.update(session, w.cid, w.locations[0].id,
            {"code": "foreign-current", "metadata": {"number": "foreign-alias"}})
        assert result.location.code == "foreign-current"
        assert_no_hidden_entities(session, w)
        await session.flush()
        assert await snapshot(w) == before  # separate fresh observer; no implicit commit
        await session.rollback()
    assert await snapshot(w) == before


@pytest.mark.parametrize("company", ["cid", "foreign"])
async def test_scoped_global_id_collision_is_denied_before_flush(scoped, company):
    w = scoped
    set_request_scope([w.locations[0].id])
    async with w.factory() as session:
        # Hidden same-tenant/foreign existing IDs can be masked by the ORM read,
        # but restricted create must still stop at the existing 403 admission.
        with pytest.raises(location_commands.LocationConflict) as error:
            await location_commands.create(session, getattr(w, company), w.locations[1].id,
                {"code": "new", "name": "forbidden"})
        assert error.value.status == 403
        assert not session.new
        assert_no_hidden_entities(session, w)
        await session.rollback()


@pytest.mark.parametrize("reason", ["session", "contract", "external", "accounted"])
async def test_freeze_remains_before_number_validation(scoped, reason):
    await seed_freeze(scoped, reason)
    response = await mutate(scoped, "native", {"code": "old-1"})
    assert response.status_code == 409
    assert response.json()["detail"].startswith("Номер объекта изменить нельзя:")
    assert not scoped.projections
