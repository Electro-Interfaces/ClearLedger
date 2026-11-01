"""AUTHORED / NOTRUN. ROOT must review an isolated preimport composition first.

Repository conftest may import app and DROP schemas before this file's guard.
This file grants no execution, provisioning, runner or installation permission.
"""
import os
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_PARTY_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("NATIVE_PARTY_ROOT_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("NATIVE_PARTY_APPROVAL") == "ROOT-reviewed-synthetic-native-party-v1"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password and _TARGET.path == "/api_native_party_test_20261101"
    and not _TARGET.query and not _TARGET.fragment
):
    raise RuntimeError("Separate ROOT-reviewed native party preimport composition required")

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.routers import references_router as router
from app.schemas import (
    CounterpartyContactIn, CounterpartyCreate, CounterpartyUpdate,
    OrganizationCreate, OrganizationUpdate,
)
from app.services import contract_write_locks as locks
from app.services import native_party_locks as native

S, X = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE


@pytest.mark.parametrize("contacts, mode", [(False, X), (True, S)])
@pytest.mark.parametrize("home_kind", ["absent", "same", "other"])
def test_actual_party_plan_covers_only_native_authority_and_actual_homes(contacts, mode, home_kind):
    actor, company = uuid4(), uuid4()
    home = None if home_kind == "absent" else company if home_kind == "same" else uuid4()
    plan = native.native_party_plan(actor, company, home, contacts=contacts)
    expected = {(locks.UserKey(actor), S), (locks.CompanyKey(company), S),
                (locks.MemberKey(company, actor), S), (locks.RefCompositeKey(company), mode)}
    if home is not None:
        expected.add((locks.CompanyKey(home), S))
    assert {(request.key, request.mode) for request in plan.requests} == expected
    assert len(plan.requests) == len(expected)
    assert all(type(request.key) not in (locks.RoleKey, locks.TypeCatalogKey) for request in plan.requests)


@pytest.mark.parametrize("bad", [None, "not-a-uuid", "00000000-0000-0000-0000-000000000001"])
def test_plan_does_not_normalize_actor_identifiers_or_invent_keys(bad):
    with pytest.raises(TypeError):
        native.native_party_plan(bad, uuid4(), None)


@pytest.mark.parametrize("bad", [None, "contact", 1])
def test_plan_requires_explicit_contact_purpose(bad):
    with pytest.raises(TypeError):
        native.native_party_plan(uuid4(), uuid4(), None, contacts=bad)


def test_actual_contact_company_adds_only_its_fk_parent_without_foreign_member_policy():
    actor, company, legacy_owner = uuid4(), uuid4(), uuid4()
    plan = native.native_party_plan(actor, company, None, contacts=True,
        reference_companies=(legacy_owner, legacy_owner))
    assert {(r.key, r.mode) for r in plan.requests} == {
        (locks.CompanyKey(company), S), (locks.CompanyKey(legacy_owner), S),
        (locks.UserKey(actor), S), (locks.MemberKey(company, actor), S),
        (locks.RefCompositeKey(company), S),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("root", ["cp_create", "cp_patch", "cp_delete", "org_create", "org_patch",
                                  "contact_create", "contact_put", "contact_delete"])
async def test_all_actual_roots_reject_pending_state_before_discovery_or_flush(monkeypatch, root):
    actor = User(id=uuid4(), email="synthetic@unit.invalid", name="Synthetic", password_hash="synthetic")
    uid, cid = str(uuid4()), str(uuid4())
    async with AsyncSession() as db:
        db.add(actor)
        async def forbidden(*args, **kwargs):
            raise AssertionError("Pending entrance must not do I/O or discard state")
        for name in ("execute", "get", "flush", "rollback", "commit"):
            monkeypatch.setattr(db, name, forbidden)
        calls = {
            "cp_create": lambda: router.create_counterparty(CounterpartyCreate(company_id=cid, name="Synthetic"), db, actor),
            "cp_patch": lambda: router.update_counterparty(uid, CounterpartyUpdate(name="Synthetic"), db, actor),
            "cp_delete": lambda: router.delete_counterparty(uid, db, actor),
            "org_create": lambda: router.create_organization(OrganizationCreate(company_id=cid, name="Synthetic", inn=""), db, actor),
            "org_patch": lambda: router.update_organization(uid, OrganizationUpdate(name="Synthetic"), db, actor),
            "contact_create": lambda: router.create_counterparty_contact(uid, CounterpartyContactIn(name="Synthetic"), db, actor),
            "contact_put": lambda: router.update_counterparty_contact(uid, uid, CounterpartyContactIn(name="Synthetic"), db, actor),
            "contact_delete": lambda: router.delete_counterparty_contact(uid, uid, db, actor),
        }
        with pytest.raises(locks.ScopedLockError, match="clean entry"):
            await calls[root]()
        assert actor in db.new and actor.email == "synthetic@unit.invalid"
        # Restore the real rollback for AsyncSession's context manager cleanup.
        monkeypatch.undo()


@pytest.mark.asyncio
@pytest.mark.parametrize("entity, party, child", [("delete_organization", None, None),
                                                 ("contact", None, None),
                                                 ("counterparty", None, uuid4())])
async def test_helper_rejects_unknown_or_inconsistent_purpose_without_discovery(monkeypatch, entity, party, child):
    async with AsyncSession() as db:
        async def forbidden(*args, **kwargs):
            raise AssertionError("Invalid purpose must fail before I/O")
        monkeypatch.setattr(db, "execute", forbidden)
        with pytest.raises(locks.ScopedLockError):
            await native.prepare_native_party_write(db, User(id=uuid4()), uuid4(),
                entity=entity, party_id=party, contact_id=child)


@pytest.mark.asyncio
async def test_fabricated_or_retargeted_preparation_cannot_authorize_a_write():
    actor, company = User(id=uuid4()), uuid4()
    plan = native.native_party_plan(actor.id, company, None)
    prepared = native.NativePartyWrite(company, actor.id, None, plan,
        locks.ScopedLockCapability(plan), actor, "counterparty", None, None, None)
    async with AsyncSession() as db:
        for candidate in (prepared, replace(prepared, company_id=uuid4()),
                          replace(prepared, entity="contact", party_id=uuid4())):
            with pytest.raises(locks.ScopedLockError):
                native.require_native_party_write(db, candidate)
