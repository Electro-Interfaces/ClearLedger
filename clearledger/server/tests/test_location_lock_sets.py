"""Opt-in isolated PG foundation tests; no import/unit writer activation.

The v1 characterization is a future naive multi-command harness, not evidence
of a current importer defect. Capability cases run only on the candidate.
"""
import asyncio
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text, update

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_LOCATION_LOCK_SET_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Opt in with {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)

from tests.test_location_commands import world as native_world, native_payload, seed_freeze
from tests.test_station_mapping_admission import world as mapping_world, post as mapping_post
from app.models import Contract, ContractLocation, Counterparty, Organization, ServiceLocation
from app.scope import (current_object_scope, install_orm_scope, set_request_organization,
                       set_request_scope)
from app.services import location_commands as commands


@pytest.fixture(scope="module", autouse=True)
def production_scope_listener():
    install_orm_scope()


@pytest_asyncio.fixture
async def world(native_world):
    set_request_scope(None)
    set_request_organization(None)
    yield native_world
    set_request_scope(None)
    set_request_organization(None)


def legacy_key(namespace, value):
    # Independent contract, deliberately not the candidate helper.
    return int.from_bytes(hashlib.blake2b(
        f"location-command:v1:{namespace}:{value}".encode(), digest_size=8).digest(),
        "big", signed=True)


class Trace:
    def __init__(self, factory):
        self.engine = factory.kw["bind"].sync_engine
        self.sql = []
        self.locks = []

    def before(self, conn, cursor, statement, parameters, context, executemany):
        pid = conn.connection.driver_connection.get_server_pid()
        self.sql.append((pid, statement))
        if "pg_advisory_xact_lock" in statement:
            key = parameters[0] if not isinstance(parameters, dict) else parameters["key"]
            self.locks.append((pid, key))

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.before)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self.before)

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *args):
        self.__exit__(*args)

    def keys(self, pid):
        return [key for owner, key in self.locks if owner == pid]


async def pid(db):
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def observed_block(observer, waiter, blocker):
    """Require a real pg_blocking_pids edge, never infer waiting from a sleep."""
    async with asyncio.timeout(4):
        while True:
            await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            row = (await observer.execute(text(
                "SELECT pg_blocking_pids(:pid) AS blockers, wait_event_type, wait_event "
                "FROM pg_stat_activity WHERE pid=:pid"), {"pid": waiter})).one()
            if blocker in row.blockers:
                assert row.wait_event_type == "Lock"
                return {"waiter": waiter, "blocker": blocker, "event": row.wait_event}


async def observed_lock_caller(observer, trace, key, excluded):
    async with asyncio.timeout(4):
        while True:
            for owner, value in trace.locks:
                if value == key and owner not in excluded:
                    return owner
            await observer.execute(text("SELECT 1"))


async def stop_tasks(*tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def expect_conflict(awaitable, status=409):
    with pytest.raises(commands.LocationConflict) as error:
        await awaitable
    assert error.value.status == status
    return error.value


async def test_v1_naive_multi_id_characterization(world, record_property):
    """Both revisions: intentionally naive I(P),C / I(Q)->C / P-owner->I(Q)."""
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as first, w.factory() as second, w.factory() as observer:
        a, b = await pid(first), await pid(second)
        await commands.update(first, w.cid, p, {"name": "Synthetic naive first"})

        async def naive(db, identifier):
            try:
                await commands.update(db, w.cid, identifier, {"name": "Synthetic naive second"})
            finally:
                await db.rollback()

        waiting_b = asyncio.create_task(naive(second, q))
        waiting_a = None
        try:
            edge_b = await observed_block(observer, b, a)
            waiting_a = asyncio.create_task(naive(first, q))
            edge_a = await observed_block(observer, a, b)
            # Record both real edges before PG's deadlock detector selects a victim.
            record_property("naive_v1_wait_graph", json.dumps([edge_b, edge_a]))
            results = await asyncio.wait_for(asyncio.gather(waiting_a, waiting_b,
                                                          return_exceptions=True), 8)
            deadlocks = [exc for exc in results
                         if getattr(getattr(exc, "orig", None), "sqlstate", None) == "40P01"]
            assert len(deadlocks) == 1, [repr(exc) for exc in results]
            assert sum(exc is None for exc in results) == 1
        finally:
            await stop_tasks(*[t for t in (waiting_a, waiting_b) if t is not None])
            await first.rollback()
            await second.rollback()


@pytest.mark.parametrize("identifiers", [[], ["p"], [" Я ?#% ", "p"], ["z", "a", "z"],
                                        ["é", "e\u0301", " ", "A", "a"], ["x" * 40]])
async def test_set_sorts_opaque_ids_and_preserves_legacy_hash_bytes(world, identifiers):
    w = world
    async with w.factory() as db, Trace(w.factory) as trace:
        owner = await pid(db)
        cap = await commands.acquire_location_set(db, w.cid, identifiers)
        assert isinstance(cap, commands.LockedLocationSet)
        assert cap.identifiers == frozenset(identifiers)
        assert trace.keys(owner) == [legacy_key("id", value) for value in sorted(set(identifiers))] + [legacy_key("company", w.cid)]
        assert not db.identity_map and not db.new and not db.dirty
        assert db.in_transaction()
        with pytest.raises(FrozenInstanceError):
            cap.identifiers = frozenset()
        await db.rollback()


@pytest.mark.parametrize("bad", [[""], ["a", "\x00"], ["x" * 41], [None], [1], "abc", None])
async def test_invalid_full_set_fails_422_before_any_advisory_sql(world, bad):
    async with world.factory() as db, Trace(world.factory) as trace:
        await expect_conflict(commands.acquire_location_set(db, world.cid, bad), 422)
        assert not trace.locks
        assert not db.new and not db.dirty


async def test_repeated_set_and_subset_take_no_new_locks_even_in_savepoint(world):
    w = world
    ids = [loc.id for loc in w.locations]
    async with w.factory() as db, Trace(w.factory) as trace:
        owner = await pid(db)
        cap = await commands.acquire_location_set(db, w.cid, ids[::-1])
        before = trace.keys(owner)
        for subset in (ids, ids[::-1], [ids[0]], []):
            assert await commands.acquire_location_set(db, w.cid, subset) is cap
        async with db.begin_nested():
            assert await commands.acquire_location_set(db, w.cid, [ids[1]]) is cap
            assert (await commands.locked_visible_in_set(db, w.cid, ids[1], cap)).id == ids[1]
        assert trace.keys(owner) == before
        await db.rollback()


@pytest.mark.parametrize("operation", ["acquire", "visible", "_barrier", "_locked", "locked_visible", "update", "upsert", "create"])
async def test_late_id_is_rejected_before_sql_in_old_and_new_entrances(world, operation):
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        before = len(trace.sql)
        if operation == "acquire":
            attempt = commands.acquire_location_set(db, w.cid, [p, q])
        elif operation == "visible":
            attempt = commands.locked_visible_in_set(db, w.cid, q, cap)
        elif operation in ("update", "upsert", "create"):
            attempt = getattr(commands, operation)(db, w.cid, q, {"name": "forbidden"})
        else:
            attempt = getattr(commands, operation)(db, w.cid, q)
        error = await expect_conflict(attempt)
        assert q not in error.detail
        assert len(trace.sql) == before
        assert not db.new and not db.dirty
        await db.rollback()


@pytest.mark.parametrize("entrance", ["_barrier", "_locked", "locked_visible", "update"])
async def test_preparation_after_single_entrance_is_rejected_without_sql(world, entrance):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, Trace(w.factory) as trace:
        if entrance == "update":
            await commands.update(db, w.cid, p, {})
        else:
            await getattr(commands, entrance)(db, w.cid, p)
        before = len(trace.sql)
        await expect_conflict(commands.acquire_location_set(db, w.cid, [p]))
        assert len(trace.sql) == before
        # Ordinary single paths stay usable; this is a prohibition on late prep.
        assert (await commands.locked_visible(db, w.cid, p)).id == p
        await db.rollback()
        cap = await commands.acquire_location_set(db, w.cid, [p])
        assert (await commands.locked_visible_in_set(db, w.cid, p, cap)).id == p
        await db.rollback()


async def test_fresh_acquisition_inside_savepoint_rejected_before_sql(world):
    async with world.factory() as db, Trace(world.factory) as trace:
        async with db.begin_nested():
            before = len(trace.sql)
            await expect_conflict(commands.acquire_location_set(db, world.cid, []))
            assert len(trace.sql) == before
        cap = await commands.acquire_location_set(db, world.cid, [])
        assert cap.identifiers == frozenset()
        await db.rollback()


@pytest.mark.parametrize("boundary", ["commit", "rollback", "close"])
async def test_root_boundary_invalidates_old_capability_even_after_autobegin(world, boundary):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        await getattr(db, boundary)()
        await db.scalar(text("SELECT 1"))  # New root must not revive the old token.
        before = len(trace.sql)
        await expect_conflict(commands.locked_visible_in_set(db, w.cid, p, cap))
        assert len(trace.sql) == before
        fresh = await commands.acquire_location_set(db, w.cid, [p])
        assert fresh is not cap
        await db.rollback()


@pytest.mark.parametrize("wrong", ["session", "company", "forged", "none"])
async def test_capability_cannot_be_reused_with_another_authority(world, wrong):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, w.factory() as other, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        target_db, company, supplied = db, w.cid, cap
        if wrong == "session":
            target_db = other
        elif wrong == "company":
            company = w.foreign
        elif wrong == "forged":
            supplied = replace(cap)
        else:
            supplied = None
        before = len(trace.sql)
        await expect_conflict(commands.locked_visible_in_set(target_db, company, p, supplied))
        assert len(trace.sql) == before
        await db.rollback()


@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_savepoint_boundary_preserves_preheld_root_locks_and_token(world, outcome):
    w = world
    p = w.locations[0].id
    async with w.factory() as first, w.factory() as other, w.factory() as observer:
        a, b = await pid(first), await pid(other)
        cap = await commands.acquire_location_set(first, w.cid, [p])
        nested = await first.begin_nested()
        assert (await commands.locked_visible_in_set(first, w.cid, p, cap)).id == p
        await getattr(nested, outcome)()
        assert await commands.acquire_location_set(first, w.cid, []) is cap
        waiting = asyncio.create_task(commands.locked_visible(other, w.cid, p))
        try:
            await observed_block(observer, b, a)
            assert (await commands.locked_visible_in_set(first, w.cid, p, cap)).id == p
            await first.rollback()
            assert (await asyncio.wait_for(waiting, 7)).id == p
        finally:
            await stop_tasks(waiting)
            await other.rollback()


async def test_locked_reload_keeps_fresh_metadata_and_does_not_flush_or_commit(world):
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as db, w.factory() as editor, w.factory() as observer, Trace(w.factory) as trace:
        stale = await db.get(ServiceLocation, p)
        other = await db.get(ServiceLocation, q)
        await editor.execute(update(ServiceLocation).where(ServiceLocation.id == p).values(
            name="Synthetic fresh", extra_metadata={"number": "number-0", "server": ["fresh"]}))
        await editor.commit()
        cap = await commands.acquire_location_set(db, w.cid, [p])
        other.name = "Synthetic pending caller edit"
        before = len(trace.sql)
        row = await commands.locked_visible_in_set(db, w.cid, p, cap)
        assert row is stale and row.name == "Synthetic fresh" and row.extra_metadata["server"] == ["fresh"]
        assert other in db.dirty and other.name == "Synthetic pending caller edit"
        assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE", "COMMIT"))
                       for _, sql in trace.sql[before:])
        assert (await observer.get(ServiceLocation, q)).name == "Synthetic point"
        await db.rollback()
        assert (await observer.get(ServiceLocation, q)).name == "Synthetic point"


@pytest.mark.parametrize("ids", [(0, 1), (1, 0)])
@pytest.mark.parametrize("same_company", [True, False])
async def test_two_reverse_or_overlapping_sets_wait_before_company(world, ids, same_company, record_property):
    w = world
    p, q = [loc.id for loc in w.locations]
    extra = "future-" + uuid.uuid4().hex[:15]
    requested = [p, q] if ids == (0, 1) else [q, extra]
    company = w.cid if same_company else w.foreign
    async with w.factory() as first, w.factory() as second, w.factory() as observer, Trace(w.factory) as trace:
        a, b = await pid(first), await pid(second)
        await commands.acquire_location_set(first, w.cid, [q, p])
        waiting = asyncio.create_task(commands.acquire_location_set(second, company, requested[::-1]))
        try:
            edge = await observed_block(observer, b, a)
            assert legacy_key("company", company) not in trace.keys(b)
            record_property("set_wait_before_company", json.dumps(edge))
            await first.rollback()
            cap = await asyncio.wait_for(waiting, 7)
            assert cap.identifiers == frozenset(requested)
            assert trace.keys(b) == [legacy_key("id", v) for v in sorted(requested)] + [legacy_key("company", company)]
        finally:
            await stop_tasks(waiting)
            await second.rollback()


@pytest.mark.parametrize("kind", ["native", "upsert", "registry"])
async def test_prepared_set_serializes_with_actual_single_native_registry_routes(world, kind):
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as first, w.factory() as observer, Trace(w.factory) as trace:
        a = await pid(first)
        await commands.acquire_location_set(first, w.cid, [q, p])
        if kind == "native":
            request = w.client.patch("/api/locations/" + q, json={"name": "Synthetic later"})
        elif kind == "upsert":
            request = w.client.post("/api/locations", json=native_payload(w, w.locations[1], name="Synthetic later"))
        else:
            request = w.client.patch("/api/registry/objects/" + q, params={"company_id": str(w.cid)},
                                     json={"name": "Synthetic later"})
        waiting = asyncio.create_task(request)
        try:
            b = await observed_lock_caller(observer, trace, legacy_key("id", q), {a})
            await observed_block(observer, b, a)
            await first.rollback()
            response = await asyncio.wait_for(waiting, 7)
            assert response.status_code == 200, response.text
        finally:
            await stop_tasks(waiting)


async def test_prepared_set_serializes_with_actual_mapping_route(mapping_world):
    w = mapping_world
    p, q = [row.id for row in w.points[:2]]
    async with w.factory() as first, w.factory() as observer, Trace(w.factory) as trace:
        a = await pid(first)
        await commands.acquire_location_set(first, w.cid, [q, p])
        waiting = asyncio.create_task(mapping_post(w, q))
        try:
            b = await observed_lock_caller(observer, trace, legacy_key("id", q), {a})
            await observed_block(observer, b, a)
            await first.rollback()
            response = await asyncio.wait_for(waiting, 7)
            assert response.status_code == 201, response.text
        finally:
            await stop_tasks(waiting)


async def test_old_single_owner_can_complete_while_set_waits_for_its_id(world):
    w = world
    p, q = [row.id for row in w.locations]
    async with w.factory() as single, w.factory() as prepared, w.factory() as observer, Trace(w.factory) as trace:
        a, b = await pid(single), await pid(prepared)
        await commands.locked_visible(single, w.cid, q)
        waiting = asyncio.create_task(commands.acquire_location_set(prepared, w.cid, [q, p]))
        try:
            await observed_block(observer, b, a)
            assert legacy_key("company", w.cid) not in trace.keys(b)
            assert (await commands.update(single, w.cid, q, {"name": "Synthetic single wins"})).location.id == q
            await single.commit()
            cap = await asyncio.wait_for(waiting, 7)
            assert (await commands.locked_visible_in_set(prepared, w.cid, q, cap)).name == "Synthetic single wins"
        finally:
            await stop_tasks(waiting)
            await prepared.rollback()


async def test_foreign_held_row_is_never_loaded_or_waited_on(mapping_world):
    w = mapping_world
    foreign = w.points[2].id
    set_request_scope(None)
    set_request_organization(None)
    async with w.factory() as holder, w.factory() as own:
        await holder.execute(select(ServiceLocation).where(ServiceLocation.id == foreign,
                              ServiceLocation.company_id == w.foreign).with_for_update())
        cap = await commands.acquire_location_set(own, w.cid, [foreign])
        error = await expect_conflict(asyncio.wait_for(
            commands.locked_visible_in_set(own, w.cid, foreign, cap), 1), 404)
        assert foreign not in error.detail
        assert not any(isinstance(row, ServiceLocation) for row in own.identity_map.values())
        await own.rollback()
        await holder.rollback()


@pytest.mark.parametrize("scope", [[], ["missing-synthetic"]])
async def test_explicit_scope_is_rechecked_not_granted_by_capability(world, scope):
    w = world
    p = w.locations[0].id
    async with w.factory() as db:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        set_request_scope(scope)
        await expect_conflict(commands.locked_visible_in_set(db, w.cid, p, cap), 404)
        assert current_object_scope() == scope
        await db.rollback()


async def test_current_object_scope_after_observed_lock_wait_is_rechecked(world):
    w = world
    p = w.locations[0].id
    allowed = [p]
    async with w.factory() as holder, w.factory() as reader, w.factory() as observer:
        a, b = await pid(holder), await pid(reader)
        await commands.locked_visible(holder, w.cid, p)

        async def waiting_reader():
            set_request_scope(allowed)
            cap = await commands.acquire_location_set(reader, w.cid, [p])
            return await commands.locked_visible_in_set(reader, w.cid, p, cap)

        waiting = asyncio.create_task(waiting_reader())
        try:
            await observed_block(observer, b, a)
            allowed.clear()  # Current ContextVar value narrows during the wait.
            await holder.rollback()
            error = await expect_conflict(asyncio.wait_for(waiting, 7), 404)
            assert p not in error.detail
        finally:
            await stop_tasks(waiting)
            await reader.rollback()


async def test_organization_evidence_is_reloaded_after_row_wait(world):
    w = world
    p = w.locations[0].id
    async with w.factory() as seed:
        orgs = [Organization(company_id=w.cid, name="Synthetic lock organization", inn=f"{i:012}") for i in (7, 8)]
        party = Counterparty(company_id=w.cid, name="Synthetic lock party")
        seed.add_all([*orgs, party])
        await seed.flush()
        contract = Contract(company_id=w.cid, counterparty_id=party.id, organization_id=orgs[0].id,
                            type="energy", scope_type="locations", number="synthetic-lock", date="2026-10-30")
        seed.add(contract)
        await seed.flush()
        seed.add(ContractLocation(company_id=w.cid, contract_id=contract.id, location_id=p))
        await seed.commit()
    async with w.factory() as holder, w.factory() as reader, w.factory() as editor, w.factory() as observer:
        a, b = await pid(holder), await pid(reader)
        await holder.execute(select(ServiceLocation).where(ServiceLocation.id == p).with_for_update())
        cap = await commands.acquire_location_set(reader, w.cid, [p])

        async def org_reader():
            set_request_organization(orgs[0].id)
            return await commands.locked_visible_in_set(reader, w.cid, p, cap)

        waiting = asyncio.create_task(org_reader())
        try:
            await observed_block(observer, b, a)
            await editor.execute(update(Contract).where(Contract.id == contract.id).values(organization_id=orgs[1].id))
            await editor.commit()
            await holder.rollback()
            await expect_conflict(asyncio.wait_for(waiting, 7), 404)
        finally:
            await stop_tasks(waiting)
            await reader.rollback()


async def test_late_id_rejection_avoids_real_wait_cycle_with_old_single_writer(world):
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as first, w.factory() as second, w.factory() as observer, Trace(w.factory) as trace:
        a, b = await pid(first), await pid(second)
        await commands.acquire_location_set(first, w.cid, [p])
        waiting = asyncio.create_task(commands.locked_visible(second, w.cid, q))
        try:
            await observed_block(observer, b, a)  # B holds I(Q), waits C owned by A.
            before = len(trace.sql)
            await expect_conflict(commands.update(first, w.cid, q, {"name": "forbidden"}))
            assert len(trace.sql) == before  # No attempt to wait for B's I(Q).
            await first.rollback()
            assert (await asyncio.wait_for(waiting, 7)).id == q
        finally:
            await stop_tasks(waiting)
            await second.rollback()


async def test_cancelled_partial_acquisition_poisoned_until_root_rollback(world):
    w = world
    p, q = [loc.id for loc in w.locations]
    async with w.factory() as holder, w.factory() as prepared, w.factory() as observer, Trace(w.factory) as trace:
        a, b = await pid(holder), await pid(prepared)
        await commands.locked_visible(holder, w.cid, q)
        waiting = asyncio.create_task(commands.acquire_location_set(prepared, w.cid, [q, p]))
        try:
            await observed_block(observer, b, a)
            assert trace.keys(b) == [legacy_key("id", p), legacy_key("id", q)]
            await stop_tasks(waiting)
            before = len(trace.sql)
            await expect_conflict(commands.acquire_location_set(prepared, w.cid, [p]))
            await expect_conflict(commands._barrier(prepared, w.cid, p))
            assert len(trace.sql) == before
            await holder.rollback()
            await prepared.rollback()
            cap = await commands.acquire_location_set(prepared, w.cid, [q, p])
            assert cap.identifiers == frozenset([p, q])
        finally:
            await stop_tasks(waiting)
            await holder.rollback()
            await prepared.rollback()


@pytest.mark.parametrize("entrance", ["update", "upsert"])
@pytest.mark.parametrize("frozen", [True, False])
async def test_known_id_old_mutation_keeps_freeze_typed_history_and_caller_rollback(world, entrance, frozen):
    w = world
    p = w.locations[0].id
    if frozen:
        await seed_freeze(w, "session")
    async with w.factory() as db, w.factory() as observer, Trace(w.factory) as trace:
        cap = await commands.acquire_location_set(db, w.cid, [p])
        keys = list(trace.locks)
        operation = getattr(commands, entrance)(db, w.cid, p, {"code": "synthetic-next-code"},
                                               actor_id=w.user.id, source="synthetic-prepared")
        if frozen:
            await expect_conflict(operation)
            assert not db.dirty and not db.new
        else:
            result = await operation
            row = result.location if entrance == "update" else result
            assert row.code == "synthetic-next-code"
            history = row.extra_metadata["identifierHistory"]
            assert [(h["domain"], h["old"], h["new"]) for h in history] == [
                ("code", "code-0", "synthetic-next-code")]
            assert row.extra_metadata["numberHistory"] == [{"было": "old-0"}]
            assert (await observer.get(ServiceLocation, p)).code == "code-0"
        assert trace.locks == keys  # Existing commands reuse the preheld set.
        assert await commands.acquire_location_set(db, w.cid, []) is cap
        await db.rollback()
        assert (await observer.get(ServiceLocation, p)).code == "code-0"


async def test_other_company_set_and_single_entrance_rejected_without_sql(world):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, Trace(w.factory) as trace:
        await commands.acquire_location_set(db, w.cid, [p])
        before = len(trace.sql)
        await expect_conflict(commands.acquire_location_set(db, w.foreign, []))
        await expect_conflict(commands._locked(db, w.foreign, p))
        assert len(trace.sql) == before
        await db.rollback()
        # A normal single command in the next root is unaffected by the old set.
        q = w.locations[1].id
        assert (await commands.locked_visible(db, w.cid, q)).id == q
        await db.rollback()


async def test_dirty_target_is_preserved_without_flush_reload_or_commit(world, record_property):
    w = world
    p = w.locations[0].id
    async with w.factory() as db, w.factory() as observer, Trace(w.factory) as trace:
        row = await db.get(ServiceLocation, p)
        cap = await commands.acquire_location_set(db, w.cid, [p])
        row.name = "Synthetic unflushed target"
        before = len(trace.sql)
        status = None
        try:
            await commands.locked_visible_in_set(db, w.cid, p, cap)
        except commands.LocationConflict as error:
            status = error.status
            assert p not in error.detail
        lookup_sql = trace.sql[before:]
        observed = await observer.get(ServiceLocation, p)
        actual = (status, row.name, db.is_modified(row), observed.name)
        record_property("dirty_target_state", json.dumps(actual))
        assert actual == (409, "Synthetic unflushed target", True, "Synthetic point")
        assert not lookup_sql
        assert row in db.dirty
        assert await commands.acquire_location_set(db, w.cid, []) is cap
        await db.rollback()
        assert observed.name == "Synthetic point"
