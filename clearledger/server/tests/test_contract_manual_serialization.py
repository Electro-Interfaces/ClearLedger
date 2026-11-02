"""Actual native PATCH / actual import, ordered by events and PostgreSQL waits.

Only HTTP dependencies and upstream transport are fixtures. No lock, SELECT,
marker, matcher or transaction implementation is replaced. All data is synthetic.
"""
import asyncio
import os
from types import SimpleNamespace
import uuid

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_CONTRACT_MANUAL_SERIALIZATION_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Требуется {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise pytest.UsageError(error)

from sqlalchemy import delete, text

from app.auth import get_current_user
from app.database import get_db
from app.models import (Company, Contract, ContractLink, ContractLocation, Counterparty,
                        Organization, UserCompany)
from app.services.reference_identity import lock_manual_creation
from app.services.reference_overrides import mark_reference_changes, snapshot_reference_fields
from tests.test_contract_manual_freshness import (
    Source, UPDATED, assert_identity_and_local_layer, contract_world, persisted, sync_log,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")
TIMEOUT = 12
FIELDS = {"valid_until", "amount_limit", "amount_incl_vat", "payment_term_days"}
MANUAL_NULL = {"validUntil": None, "amountLimit": None, "amountInclVat": None,
               "paymentTermDays": None}


async def wait(event):
    await asyncio.wait_for(event.wait(), TIMEOUT)


async def configure(db):
    await db.execute(text("SET LOCAL lock_timeout = '10000ms'"))
    await db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


class PausedSource(Source):
    """describe runs only AFTER the actual company-scoped Contract SELECT."""
    def __init__(self, row):
        super().__init__(row)
        self.selected = asyncio.Event()
        self.release = asyncio.Event()

    async def describe_entity(self, entity):
        self.selected.set()
        await wait(self.release)
        return await super().describe_entity(entity)


class PatchTransaction:
    """Hold the real dependency transaction after native flush/refresh."""
    def __init__(self, w):
        self.w = w
        self.started = asyncio.Event()
        self.flushed = asyncio.Event()
        self.release = asyncio.Event()
        self.pid = None
        # ASGITransport owns the local fixture app; no production app is used.
        self.app = w.client._transport.app
        self.previous = self.app.dependency_overrides[get_db]

    async def session(self):
        async with self.w.factory() as db:
            try:
                self.pid = await configure(db)
                self.started.set()
                yield db
                self.flushed.set()
                await wait(self.release)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    def install(self):
        self.app.dependency_overrides[get_db] = self.session

    def restore(self):
        self.app.dependency_overrides[get_db] = self.previous


async def checkpoint(w, *, waiter, blocker, reached, task):
    """Return an actual wait or a real application event, never elapsed time."""
    async with w.factory() as monitor:
        async with asyncio.timeout(TIMEOUT):
            while True:
                if task.done():
                    await task  # Surface errors instead of manufacturing a race result.
                    assert reached.is_set(), "task completed without expected checkpoint"
                if reached.is_set():
                    return "event"
                pids = await monitor.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
                if blocker in pids:
                    locks = (await monitor.execute(text(
                        "SELECT locktype FROM pg_locks WHERE pid=:pid AND NOT granted"
                    ), {"pid": waiter})).scalars().all()
                    assert locks, "blocking backend without an ungranted lock"
                    return tuple(locks)
                # Poll cadence only; proof is pg_blocking_pids/event above.
                await asyncio.sleep(0.01)


async def run_import(w, source, *, ready=None, before_commit=None):
    try:
        pid = await configure(w.db)
        if ready is not None:
            ready.pid = pid
            ready.event.set()
        log = sync_log()
        stats = await w.service._sync_contracts(source, w.connection, log)
        assert stats == UPDATED
        assert (log.items_processed, log.items_created, log.items_updated, log.items_errors) == (1, 0, 1, 0)
        if before_commit is not None:
            await wait(before_commit)
        await w.db.commit()  # caller owns the commit
    except BaseException:
        await w.db.rollback()
        raise


async def native_patch(w, payload=MANUAL_NULL):
    response = await w.client.patch(f"/api/references/contracts/{w.identifier}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def stop_tasks(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("changed", [True, False], ids=["changed-upstream", "same-upstream"])
@pytest.mark.parametrize("first", ["import", "patch"])
async def test_concurrent_manual_null_survives_actual_import(contract_world, first, changed):
    w = await contract_world()
    before = await persisted(w)
    if changed:
        w.source.update({"СрокДействия": "2027-12-31", "Сумма": 200,
                         "СуммаВключаетНДС": False, "СрокОплаты": 20,
                         "ДоговорПодписан": False, "ExtraSourceField": "changed"})
    source = PausedSource(w.source)
    patch = PatchTransaction(w)
    patch.install()
    ready = SimpleNamespace(event=asyncio.Event(), pid=None)
    import_commit = asyncio.Event()
    tasks = []
    try:
        if first == "import":
            importer = asyncio.create_task(run_import(w, source, ready=ready))
            tasks.append(importer)
            await wait(source.selected)
            writer = asyncio.create_task(native_patch(w))
            tasks.append(writer)
            await wait(patch.started)
            proof = await checkpoint(w, waiter=patch.pid, blocker=ready.pid,
                                     reached=patch.flushed, task=writer)
            if proof == "event":
                # Baseline: PATCH can commit after import SELECT but before UPDATE.
                patch.release.set()
                await asyncio.wait_for(writer, TIMEOUT)
                saved = await persisted(w)
                assert all(saved[f] is None for f in FIELDS)
                assert FIELDS <= set(saved["manual_overrides"])
                source.release.set()
                await asyncio.wait_for(importer, TIMEOUT)
            else:
                # A joined company barrier must block PATCH before row/FK locks.
                assert proof == ("advisory",), proof
                source.release.set()
                await asyncio.wait_for(importer, TIMEOUT)
                await wait(patch.flushed)
                patch.release.set()
                await asyncio.wait_for(writer, TIMEOUT)
        else:
            writer = asyncio.create_task(native_patch(w))
            tasks.append(writer)
            await wait(patch.flushed)
            importer = asyncio.create_task(run_import(w, source, ready=ready,
                                                      before_commit=import_commit))
            tasks.append(importer)
            await wait(ready.event)
            proof = await checkpoint(w, waiter=ready.pid, blocker=patch.pid,
                                     reached=source.selected, task=importer)
            if proof == "event" and changed:
                # Baseline read uncommitted PATCH as old data; force real UPDATE wait.
                source.release.set()
                never = asyncio.Event()
                row_wait = await checkpoint(w, waiter=ready.pid, blocker=patch.pid,
                                            reached=never, task=importer)
                assert "transactionid" in row_wait, row_wait
            elif proof != "event":
                assert proof == ("advisory",), proof
            patch.release.set()
            await asyncio.wait_for(writer, TIMEOUT)
            saved = await persisted(w)
            assert all(saved[f] is None for f in FIELDS)
            assert FIELDS <= set(saved["manual_overrides"])
            source.release.set()
            import_commit.set()
            await asyncio.wait_for(importer, TIMEOUT)
        after = await persisted(w)  # independent session, both commits completed
        assert all(after[f] is None for f in FIELDS), {
            "ordering": first, "changed": changed, "ordering_proof": proof,
            "persisted_manual_intent": {f: None for f in FIELDS},
            "persisted_after_both_commits": {f: after[f] for f in FIELDS},
            "persisted_markers": after["manual_overrides"],
        }
        assert FIELDS <= set(after["manual_overrides"])
        assert after["raw"]["СрокДействия"] == w.source["СрокДействия"]
        assert after["raw"]["ExtraSourceField"] == w.source["ExtraSourceField"]
        assert after["signed"] is (not changed)
        assert_identity_and_local_layer(before, after)
    finally:
        source.release.set()
        import_commit.set()
        patch.release.set()
        await stop_tasks(tasks)
        patch.restore()


class PendingPatchTransaction(PatchTransaction):
    """Actual unflushed ORM change, held strongly before native admission."""
    async def session(self):
        async with self.w.factory() as db:
            try:
                self.pid = await configure(db)
                self.row = await db.get(Contract, self.w.identifier)
                before = snapshot_reference_fields(self.row)
                self.row.valid_until = None
                mark_reference_changes(self.row, before)
                assert self.row in db.dirty
                self.started.set()
                yield db
                self.flushed.set()
                await wait(self.release)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise


async def import_first_with_request_state(w, transaction, payload):
    """Additional loader controls; original four-case baseline remains intact."""
    before = await persisted(w)
    w.source["СрокДействия"] = "2027-12-31"
    source = PausedSource(w.source)
    ready = SimpleNamespace(event=asyncio.Event(), pid=None)
    transaction.install()
    tasks = []
    try:
        importer = asyncio.create_task(run_import(w, source, ready=ready))
        tasks.append(importer)
        await wait(source.selected)
        writer = asyncio.create_task(native_patch(w, payload))
        tasks.append(writer)
        await wait(transaction.started)
        proof = await checkpoint(w, waiter=transaction.pid, blocker=ready.pid,
                                 reached=transaction.flushed, task=writer)
        if proof == "event":
            transaction.release.set()
            await asyncio.wait_for(writer, TIMEOUT)
            source.release.set()
            await asyncio.wait_for(importer, TIMEOUT)
        else:
            assert proof == ("advisory",), proof
            source.release.set()
            await asyncio.wait_for(importer, TIMEOUT)
            await wait(transaction.flushed)
            transaction.release.set()
            await asyncio.wait_for(writer, TIMEOUT)
        after = await persisted(w)
        assert_identity_and_local_layer(before, after)
        assert after["raw"]["СрокДействия"] == "2027-12-31"
        return after, proof
    finally:
        source.release.set()
        transaction.release.set()
        await stop_tasks(tasks)
        transaction.restore()


async def test_payload_equal_to_old_value_is_compared_after_barrier_reload(contract_world):
    w = await contract_world()
    after, proof = await import_first_with_request_state(
        w, PatchTransaction(w), {"validUntil": "2026-12-31"})
    assert after["valid_until"] == "2026-12-31", (proof, after["valid_until"])
    assert "valid_until" in after["manual_overrides"]
    assert proof == ("advisory",), proof


async def test_pending_dirty_request_joins_company_barrier_before_autoflush(contract_world):
    w = await contract_world()
    after, proof = await import_first_with_request_state(w, PendingPatchTransaction(w), {})
    assert after["valid_until"] is None, (proof, after["valid_until"])
    assert "valid_until" in after["manual_overrides"]
    assert proof == ("advisory",), proof


class CachedAdmissionTransaction(PatchTransaction):
    """Pin the pre-wait membership so the identity-map pitfall is real."""
    def __init__(self, w, user):
        super().__init__(w)
        self.user = user

    async def session(self):
        async with self.w.factory() as db:
            try:
                self.pid = await configure(db)
                self.row = await db.get(Contract, self.w.identifier)
                self.membership = await db.get(UserCompany, (self.user.id, self.w.cid))
                assert self.membership is not None
                self.started.set()
                yield db
                self.flushed.set()
                await wait(self.release)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise


@pytest.mark.parametrize("change", ["revoke", "scope", "demote", "member", "admin", "move", "delete"])
async def test_current_admission_after_wait_with_retained_membership(contract_world, change):
    w = await contract_world()
    user = await w.client._transport.app.dependency_overrides[get_current_user]()
    member = await w.db.get(UserCompany, (user.id, w.cid))
    member.role = "member" if change in {"scope", "member"} else "admin"
    member.object_scope = ["synthetic-outside"] if change in {"demote", "admin"} else None
    await w.db.commit()
    before = await persisted(w)
    gate = CachedAdmissionTransaction(w, user)
    gate.install()
    tasks = []
    moved_company = None
    try:
        async with w.factory() as holder:
            holder_pid = await configure(holder)
            await lock_manual_creation(holder, w.cid, "contract")
            writer = asyncio.create_task(w.client.patch(
                f"/api/references/contracts/{w.identifier}", json={"validUntil": None}))
            tasks.append(writer)
            await wait(gate.started)
            proof = await checkpoint(w, waiter=gate.pid, blocker=holder_pid,
                                     reached=gate.flushed, task=writer)
            assert proof == ("advisory",), proof
            current = await holder.get(UserCompany, (user.id, w.cid))
            if change == "revoke":
                await holder.delete(current)
            elif change == "scope":
                current.object_scope = ["synthetic-outside"]
            elif change == "demote":
                current.role = "member"
            elif change == "move":
                company = Company(name="Синтетическая компания назначения",
                                  slug=f"moved-{uuid.uuid4().hex[:12]}", profile_id="energy")
                holder.add(company)
                await holder.flush()
                moved_company = company.id
                row = await holder.get(Contract, w.identifier)
                row.company_id = company.id
            elif change == "delete":
                await holder.execute(delete(ContractLink).where(ContractLink.contract_id == w.identifier))
                await holder.execute(delete(ContractLocation).where(ContractLocation.contract_id == w.identifier))
                await holder.delete(await holder.get(Contract, w.identifier))
            await holder.commit()
            gate.release.set()
            response = await asyncio.wait_for(writer, TIMEOUT)
        allowed = change in {"member", "admin"}
        assert response.status_code == (200 if allowed else 404), response.text
        if change == "delete":
            async with w.factory() as fresh:
                assert await fresh.get(Contract, w.identifier) is None
        else:
            after = await persisted(w)
            if allowed:
                assert after["valid_until"] is None
                assert "valid_until" in after["manual_overrides"]
                assert_identity_and_local_layer(before, after)
            elif change == "move":
                assert after["company_id"] == moved_company
                assert after["valid_until"] == before["valid_until"]
                assert after["manual_overrides"] == before["manual_overrides"]
            else:
                assert after == before
    finally:
        gate.release.set()
        await stop_tasks(tasks)
        gate.restore()


@pytest.mark.parametrize("axis", ["counterpartyId", "organizationId", "foreign_contract"])
async def test_foreign_company_admission_and_parties_remain_unchanged(contract_world, axis):
    w = await contract_world()
    before = await persisted(w)
    async with w.factory() as writer:
        company = Company(name="Другая синтетическая компания",
                          slug=f"foreign-{uuid.uuid4().hex[:12]}", profile_id="energy")
        writer.add(company)
        await writer.flush()
        party = Counterparty(company_id=company.id, name="Синтетическая чужая сторона", inn="")
        org = Organization(company_id=company.id, name="Синтетическое чужое юрлицо", inn="")
        writer.add_all([party, org])
        await writer.flush()
        foreign = Contract(company_id=company.id, counterparty_id=party.id,
                           organization_id=org.id, number="Чужой тестовый",
                           date="2026-01-01", type="Прочее", valid_until="2040-01-01",
                           raw={"synthetic": "foreign"})
        writer.add(foreign)
        await writer.commit()
        identifier = foreign.id if axis == "foreign_contract" else w.identifier
        payload = ({"validUntil": None} if axis == "foreign_contract" else
                   {axis: str(party.id if axis == "counterpartyId" else org.id)})
        response = await w.client.patch(f"/api/references/contracts/{identifier}", json=payload)
        assert response.status_code == (404 if axis == "foreign_contract" else 400), response.text
        async with w.factory() as fresh:
            saved = await fresh.get(Contract, foreign.id)
            assert saved.valid_until == "2040-01-01"
            assert saved.raw == {"synthetic": "foreign"} and saved.manual_overrides == []
    assert await persisted(w) == before
