"""Real native routers/SQL, synthetic membership; not an OAuth end-to-end test.

Opt in explicitly and pass the shared pure safety guard before requesting
conftest's destructive schema fixture; the runner owns the assigned target.
"""
import asyncio
from datetime import date
import os
from types import SimpleNamespace
from urllib.parse import quote
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_STATION_MAPPING_ADMISSION_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Company, Contract, ContractLocation, Counterparty, ObjectLink, Organization,
    ServiceLocation, User, UserCompany,
)
from app.routers import ops_router
from app.scope import set_request_organization, set_request_scope
from app.services import location_commands, station_mapping


@pytest_asyncio.fixture
async def world(db):
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    async with factory() as session:
        companies = [Company(name=f"Synthetic {suffix} {i}", slug=f"{suffix}-{i}", profile_id="energy")
                     for i in range(2)]
        actor = User(name="Synthetic ordinary member", email=f"{suffix}@example.invalid", password_hash="unused")
        session.add_all([*companies, actor])
        await session.flush()
        session.add_all([UserCompany(user_id=actor.id, company_id=c.id, role="member") for c in companies])
        points = [ServiceLocation(id=f"Точка {suffix} ?#%", company_id=companies[0].id,
                                  code=f"{suffix}-A", name="Synthetic A", source_bindings=[]),
                  ServiceLocation(id=f"hidden-{suffix}", company_id=companies[0].id,
                                  code=f"{suffix}-B", name="Synthetic B", source_bindings=[]),
                  ServiceLocation(id=f"foreign-{suffix}", company_id=companies[1].id,
                                  code=f"{suffix}-C", name="Synthetic C", source_bindings=[])]
        session.add_all(points)
        orgs = [Organization(company_id=companies[0].id, name=f"Synthetic org {i}", inn=f"{i:012}")
                for i in range(2)]
        party = Counterparty(company_id=companies[0].id, name="Synthetic party")
        session.add_all([*orgs, party])
        await session.flush()
        for index in range(2):
            contract = Contract(company_id=companies[0].id, organization_id=orgs[index].id,
                                counterparty_id=party.id, type="energy", scope_type="locations",
                                number=f"synthetic-{suffix}-{index}", date="2026-10-30")
            session.add(contract)
            await session.flush()
            session.add(ContractLocation(company_id=companies[0].id, contract_id=contract.id,
                                         location_id=points[index].id))
        await session.commit()

    w = SimpleNamespace(factory=factory, cid=companies[0].id, foreign=companies[1].id,
                        actor=actor, points=points, orgs=orgs, lock_timeout=False)
    app = FastAPI()
    app.include_router(ops_router.router, prefix="/api")

    async def get_actor():
        set_request_scope(None)
        set_request_organization(None)
        return actor

    async def get_session():
        async with factory() as session:
            try:
                if w.lock_timeout:
                    await session.execute(text("SET LOCAL lock_timeout = '300ms'"))
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_current_user] = get_actor
    app.dependency_overrides[get_db] = get_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                base_url="http://test") as client:
        w.client = client
        yield w
    set_request_scope(None)
    set_request_organization(None)


def mapping_path(identifier):
    return "/api/ops/station-mapping/" + quote(identifier, safe="")


async def restrict(w, *, objects=None, organization=None):
    async with w.factory() as session:
        await session.execute(update(UserCompany).where(
            UserCompany.user_id == w.actor.id, UserCompany.company_id == w.cid,
        ).values(object_scope=objects, own_organization_id=organization))
        await session.commit()


async def sentinel(w, *, parent=None, parent_type="station", relation="external_id", company=None):
    async with w.factory() as session:
        link = ObjectLink(company_id=company or w.cid,
                          parent_type=parent_type, parent_id=parent or w.points[0].id,
                          child_type="ocpi:evse", child_id="sentinel-" + uuid.uuid4().hex,
                          relation=relation, valid_from=date(2020, 1, 1), basis_note="synthetic basis")
        session.add(link)
        await session.commit()
        return link


async def links(w):
    async with w.factory() as session:
        return [tuple(row) for row in (await session.execute(select(
            ObjectLink.id, ObjectLink.company_id, ObjectLink.parent_type, ObjectLink.parent_id,
            ObjectLink.relation, ObjectLink.child_type, ObjectLink.child_id,
            ObjectLink.valid_from, ObjectLink.valid_to, ObjectLink.closed_reason,
            ObjectLink.basis_note, ObjectLink.recorded_by_id, ObjectLink.recorded_at,
        ).where(ObjectLink.company_id.in_([w.cid, w.foreign])).order_by(ObjectLink.id))).all()]


async def post(w, identifier, *, value="synthetic-new", company=None, headers=None):
    return await w.client.post(mapping_path(identifier), params={"company_id": str(company or w.cid)},
                               headers=headers,
                               json={"system": "ocpi", "role": "evse", "value": value,
                                     "valid_from": "2020-01-01", "note": "synthetic"})


async def close(w, identifier, link_id, *, company=None):
    return await w.client.delete(mapping_path(identifier) + "/" + str(link_id),
                                 params={"company_id": str(company or w.cid), "reason": "synthetic close"})


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("case", ["missing", "foreign", "object_scope", "organization"])
async def test_target_admission_denials_preserve_all_links(world, method, case):
    w = world
    link = await sentinel(w)
    identifier = w.points[0].id
    if case == "missing":
        identifier = "missing-" + uuid.uuid4().hex[:12]
    elif case == "foreign":
        identifier = w.points[2].id
    elif case == "object_scope":
        await restrict(w, objects=[w.points[1].id])
    else:
        await restrict(w, organization=w.orgs[1].id)
    before = await links(w)
    response = await (post(w, identifier, headers={"X-Company-Id": str(w.foreign)}) if method == "POST"
                      else close(w, identifier, link.id))
    after = await links(w)
    assert (response.status_code, after) == (404, before), response.text


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_explicit_empty_current_scope_denies_even_when_member(world, monkeypatch, method):
    w = world
    link = await sentinel(w)
    original = ops_router.assert_company_member

    async def empty_context(*args):
        cid = await original(*args)
        # Native stored [] historically means ALL via _as_ids. This tests the
        # distinct explicit EMPTY command context, without redefining membership.
        set_request_scope([])
        return cid

    monkeypatch.setattr(ops_router, "assert_company_member", empty_context)
    before = await links(w)
    response = await (post(w, w.points[0].id) if method == "POST" else close(w, w.points[0].id, link.id))
    assert (response.status_code, await links(w)) == (404, before), response.text


@pytest.mark.parametrize("case", ["wrong_path", "point_parent", "evse_parent", "number", "placed_at",
                                   "foreign_link", "missing_link", "invalid_uuid"])
async def test_delete_binds_the_entire_legacy_link_identity(world, case):
    w = world
    options = {
        "wrong_path": {"parent": w.points[1].id},
        "point_parent": {"parent_type": "point_of_service"},
        "evse_parent": {"parent_type": "evse"},
        "number": {"relation": "number"},
        "placed_at": {"relation": "placed_at"},
        "foreign_link": {"company": w.foreign},
    }.get(case, {})
    link = await sentinel(w, **options)
    link_id = uuid.uuid4() if case == "missing_link" else "not-a-uuid" if case == "invalid_uuid" else link.id
    before = await links(w)
    response = await close(w, w.points[0].id, link_id)
    assert (response.status_code, await links(w)) == (404, before), response.text


async def test_conflict_does_not_disclose_invisible_parent_id(world):
    w = world
    existing = await sentinel(w, parent=w.points[1].id)
    await restrict(w, objects=[w.points[0].id])
    before = await links(w)
    response = await post(w, w.points[0].id, value=existing.child_id)
    assert response.status_code == 409, response.text
    assert w.points[1].id not in response.text
    assert await links(w) == before


@pytest.mark.parametrize("scope", ["all", "object", "organization", "both"])
async def test_ordinary_member_unicode_post_get_delete_contract(world, scope):
    w = world
    await restrict(w, objects=[w.points[0].id] if scope in {"object", "both"} else None,
                   organization=w.orgs[0].id if scope in {"organization", "both"} else None)
    response = await post(w, w.points[0].id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "system", "role", "value"}
    assert body | {"id": "ignored"} == {"id": "ignored", "system": "ocpi", "role": "evse", "value": "synthetic-new"}
    response = await w.client.get(mapping_path(w.points[0].id), params={"company_id": str(w.cid)})
    assert response.status_code == 200, response.text
    mapping = response.json()
    assert mapping["found"] is True and mapping["locationId"] == w.points[0].id
    saved = next(item for item in mapping["registry"] if item["id"] == body["id"])
    assert saved["value"] == "synthetic-new" and saved["validFrom"] == "2020-01-01"
    assert saved["system"] == "ocpi" and saved["role"] == "evse"
    response = await close(w, w.points[0].id, body["id"])
    assert response.status_code == 200, response.text
    assert response.json() == {"id": body["id"], "validTo": date.today().isoformat()}
    async with w.factory() as session:
        saved = await session.get(ObjectLink, uuid.UUID(body["id"]))
        assert saved.parent_type == "station" and saved.parent_id == w.points[0].id
        assert saved.relation == "external_id" and saved.closed_reason == "synthetic close"
        assert saved.recorded_by_id == str(w.actor.id)


@pytest.mark.parametrize("case", ["missing", "foreign"])
async def test_existing_get_found_false_contract(world, case):
    w = world
    identifier = "missing" if case == "missing" else w.points[2].id
    response = await w.client.get(mapping_path(identifier), params={"company_id": str(w.cid)})
    assert response.status_code == 200
    assert response.json() == {"locationId": identifier, "found": False}


async def test_member_cannot_gain_target_through_another_company_selector(world):
    w = world
    before = await links(w)
    response = await post(w, w.points[0].id, company=w.foreign)
    assert (response.status_code, await links(w)) == (404, before), response.text


async def test_mapping_reloads_an_admission_preloaded_row(world):
    w = world
    set_request_scope(None)
    set_request_organization(None)
    async with w.factory() as session:
        preloaded = await session.get(ServiceLocation, w.points[0].id)
        original_name = preloaded.name
        async with w.factory() as concurrent:
            await concurrent.execute(update(ServiceLocation).where(ServiceLocation.id == preloaded.id)
                                     .values(name="Synthetic concurrent name"))
            await concurrent.commit()
        assert preloaded.name == original_name
        await station_mapping.add_external_id(session, w.cid, preloaded.id,
                                              system="ocpi", role="evse", value=uuid.uuid4().hex)
        assert preloaded.name == "Synthetic concurrent name"


async def test_mapping_checks_current_scope_after_an_earlier_allowed_read(world):
    w = world
    set_request_scope([w.points[0].id])
    set_request_organization(None)
    before = await links(w)
    try:
        async with w.factory() as session:
            assert await session.get(ServiceLocation, w.points[0].id) is not None
            set_request_scope([])
            with pytest.raises(location_commands.LocationConflict) as error:
                await station_mapping.add_external_id(session, w.cid, w.points[0].id,
                                                      system="ocpi", role="evse", value="denied")
            assert error.value.status == 404
            await session.rollback()
    finally:
        set_request_scope(None)
    assert await links(w) == before


async def test_foreign_target_rejection_does_not_wait_for_foreign_row_lock(world):
    w = world
    w.lock_timeout = True
    before = await links(w)
    async with w.factory() as holder:
        await holder.execute(select(ServiceLocation).where(ServiceLocation.id == w.points[2].id).with_for_update())
        try:
            response = await asyncio.wait_for(post(w, w.points[2].id), timeout=3)
            assert (response.status_code, await links(w)) == (404, before), response.text
        finally:
            await holder.rollback()
