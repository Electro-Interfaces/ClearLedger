"""AUTHORED / NOTRUN, including collection.

Requires separately reviewed pre-import isolation of ancestor conftest, full
native schema/bootstrap/codecs/constraints and disposable database cleanup by
the runtime owner. A module guard cannot undo an ancestor conftest import.
No provisioning, schema weakening, substitute transaction or runner lives here.
Direct native handlers preserve product/permission checks and real completion.
"""
import os
import sys
from urllib.parse import urlsplit

_URL = os.environ.get("DOC_CASE_PROTOCOL_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (
    _URL and _URL == os.environ.get("DOC_CASE_PROTOCOL_APPROVED_URL")
    and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
    and os.environ.get("DOC_CASE_PROTOCOL_PREIMPORT_ISOLATED") == "reviewed"
    and os.environ.get("DOC_CASE_PROTOCOL_NATIVE_BOOTSTRAP") == "full-native"
    and os.environ.get("DOC_CASE_PROTOCOL_DISPOSABLE_CLEANUP") == "owner"
    and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
    and _TARGET.port and _TARGET.password
    and _TARGET.path.startswith("/doc_case_protocol_test_")
    and len(_TARGET.path) > len("/doc_case_protocol_test_")
    and not _TARGET.query and not _TARGET.fragment
    and not any(name == "conftest" or name.endswith(".conftest") for name in sys.modules)
):
    raise RuntimeError("Reviewed pre-import isolation and disposable native bootstrap required")

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import native_claims_context
from app.models import Company, CompanyRole, DocCard, DocCase, DocCounter, DocKind, User, UserCompany
from app.routers import docs_router as docs
from app.scope import set_request_organization, set_request_scope
from app.services.doc_case_locks import acquire_case_catalog

pytestmark = pytest.mark.asyncio
WRITERS = ("create_kind", "update_kind", "clear_default", "starter", "contract",
           "create_case", "close", "rollover")
READERS = ("register", "assign", "bulk")


@pytest_asyncio.fixture
async def world(monkeypatch):
    engine = create_async_engine(_URL, pool_size=10, max_overflow=0,
                                 isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    w = SimpleNamespace(engine=engine, factory=factory, year=datetime.now(timezone.utc).year,
                        cid=uuid4(), other=uuid4(), uid=uuid4(), ordinary=uuid4(),
                        case=uuid4(), kind=uuid4(), doc=uuid4(), sql=[], notifications=[])
    def trace(conn, cursor, statement, parameters, context, executemany):
        w.sql.append((conn.info.get("case_protocol_label"), statement.lower(), parameters))
    event.listen(engine.sync_engine, "before_cursor_execute", trace)
    from app.services import notify
    monkeypatch.setattr(notify, "dispatch_async", lambda *a, **kw: w.notifications.append((a, kw)))
    try:
        async with factory() as db:
            db.add_all([Company(id=cid, slug="synthetic-case-" + cid.hex,
                                name="Synthetic catalog", profile_id="energy")
                        for cid in (w.cid, w.other)])
            await db.flush()
            db.add_all([User(id=uid, company_id=w.cid, email=f"{uid.hex}@example.invalid",
                             name="Synthetic participant", password_hash="synthetic-noncredential",
                             is_superadmin=False) for uid in (w.uid, w.ordinary)])
            db.add(DocCase(id=w.case, company_id=w.cid, year=w.year, index="01-02",
                           title="Synthetic open case", storage_years=5, status="open"))
            db.add(DocKind(id=w.kind, company_id=w.cid, code="synthetic", name="Synthetic kind",
                           number_scope="kind_year", number_prefix="SYN",
                           number_template="{prefix}-{yyyy}-{n:04d}"))
            await db.flush()
            db.add_all([UserCompany(user_id=w.uid, company_id=w.cid, role="admin"),
                        UserCompany(user_id=w.ordinary, company_id=w.cid, role="user", modules=["docs"])])
            db.add(DocCard(id=w.doc, company_id=w.cid, kind_id=w.kind, kind_code="synthetic",
                           author_id=w.uid, title="Synthetic draft", attrs={}))
            await db.commit()
        w.sql.clear()
        set_request_scope(None)
        set_request_organization(None)
        with native_claims_context(None, None):
            yield w
    finally:
        set_request_scope(None)
        set_request_organization(None)
        event.remove(engine.sync_engine, "before_cursor_execute", trace)
        await engine.dispose()


async def tag(db, label):
    conn = await db.connection()
    await conn.run_sync(lambda c: c.info.update(case_protocol_label=label))
    await db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def blocked(observer, waiter, holder, *, advisory=False):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
        if holder in blockers:
            locks = (await observer.execute(text(
                "SELECT locktype, mode, granted, classid, objid, objsubid "
                "FROM pg_locks WHERE pid=:pid"), {"pid": waiter})).all()
            if advisory:
                assert any(r.locktype == "advisory" and not r.granted
                           and r.classid == 435223 and r.objsubid == 2 for r in locks)
            return locks
        await asyncio.sleep(0.01)
    raise AssertionError("Expected native PostgreSQL wait was not observed")


@asynccontextmanager
async def running(coro):
    task = asyncio.create_task(coro)
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def kind_body(w, **changes):
    return docs.KindIn(**(dict(company_id=str(w.cid), code="synthetic", name="Synthetic changed",
                              number_scope="kind_year", number_template="{prefix}-{yyyy}-{n:04d}") | changes))


async def reader(w, db, root, **changes):
    actor = await db.get(User, w.uid)
    if root == "register":
        return await docs.register_doc(str(w.doc), docs.RegisterIn(company_id=str(w.cid), **changes), db, actor)
    if root == "assign":
        return await docs.assign_doc_case(str(w.doc), docs.CaseAssignIn(
            company_id=str(w.cid), case_id=str(w.case)), db, actor)
    return await docs.bulk_docs(docs.DocBulkIn(company_id=str(w.cid), action="assign_case",
                                              doc_ids=[str(w.doc)], case_id=str(w.case)), db, actor)


async def writer(w, db, root):
    actor = await db.get(User, w.uid)
    if root == "create_kind":
        return await docs.create_kind(kind_body(w, code="new_synthetic"), db, actor)
    if root in ("update_kind", "clear_default"):
        return await docs.update_kind(str(w.kind), kind_body(w, default_case_id=(
            str(w.case) if root == "update_kind" else None)), db, actor)
    if root == "starter":
        return await docs.create_starter_kinds(str(w.cid), db, actor)
    if root == "contract":
        # Ordinary membership remains sufficient for this idempotent GET writer.
        actor = await db.get(User, w.ordinary)
        return await docs.contract_kinds(str(w.cid), db, actor)
    if root == "create_case":
        return await docs.create_case(docs.CaseIn(company_id=str(w.cid), year=w.year,
                                                 index="NEW", title="Synthetic new case"), db, actor)
    if root == "close":
        return await docs.close_case(str(w.case), docs.CaseCloseIn(company_id=str(w.cid)), db, actor)
    return await docs.rollover_cases(str(w.cid), w.year + 1, db, actor)


@pytest.mark.parametrize("root", READERS)
@pytest.mark.parametrize("catalog_mode", ["S", "X"])
async def test_native_reader_shared_admission_and_doc_before_case(world, root, catalog_mode):
    w = world
    async with w.factory() as setup:
        await writer(w, setup, "update_kind")
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "holder"), await tag(caller, "reader")
        await acquire_case_catalog(holder, [w.cid], catalog_mode)
        async with running(reader(w, caller, root)) as task:
            if catalog_mode == "X":
                await blocked(observer, cp, hp, advisory=True)
                assert not any(label == "reader" and "for update" in sql for label, sql, _ in w.sql)
                await holder.rollback()
            result = await asyncio.wait_for(task, 10)
            assert result
        rows = [sql for label, sql, _ in w.sql if label == "reader"]
        barrier = next(i for i, s in enumerate(rows) if "pg_advisory_xact_lock_shared" in s)
        doc_lock = next(i for i, s in enumerate(rows) if "doc_cards" in s and "for update" in s)
        case_locks = [i for i, s in enumerate(rows) if "doc_cases" in s and "for update" in s]
        assert barrier < doc_lock
        assert case_locks and all(doc_lock < i for i in case_locks)


@pytest.mark.parametrize("root", WRITERS)
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_native_writers_wait_for_shared_catalog_before_predicates(world, root, completion):
    w = world
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "holder"), await tag(caller, "writer")
        await acquire_case_catalog(holder, [w.cid], "S")
        async with running(writer(w, caller, root)) as task:
            await blocked(observer, cp, hp, advisory=True)
            rows = [s for label, s, _ in w.sql if label == "writer"]
            assert not any(("doc_kinds" in s or "doc_cases" in s) for s in rows)
            await getattr(holder, completion)()
            assert await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("root", WRITERS)
async def test_native_writer_first_blocks_shared_admission_until_real_completion(world, root):
    w = world
    async with w.factory() as blocker, w.factory() as owner, w.factory() as admission, w.factory() as observer:
        bp, op, ap = await tag(blocker, "blocker"), await tag(owner, "writer"), await tag(admission, "reader")
        # Hold a real row that the native writer must reach AFTER its catalog X.
        if root in ("update_kind", "clear_default"):
            await blocker.execute(select(DocKind).where(DocKind.id == w.kind).with_for_update())
        elif root == "close":
            await blocker.execute(select(DocCase).where(DocCase.id == w.case).with_for_update())
        else:
            # A pending unique key stops the INSERT after catalog X while
            # allowing register's earlier Company SHARE. MVCC duplicate reads
            # cannot see this pending row; the real unique index must wait.
            if root in ("create_kind", "starter", "contract"):
                code = ("new_synthetic" if root == "create_kind" else
                        docs.starter_kinds("energy")[0]["code"] if root == "starter" else
                        docs.STARTER_KINDS_CONTRACT[0]["code"])
                blocker.add(DocKind(company_id=w.cid, code=code,
                                    name="Synthetic pending unique key"))
            else:
                blocker.add(DocCase(company_id=w.cid, organization_id=None,
                    year=w.year if root == "create_case" else w.year + 1,
                    index="NEW" if root == "create_case" else "01-02",
                    title="Synthetic pending unique key"))
            await blocker.flush()
        async with running(writer(w, owner, root)) as wt:
            waits = await blocked(observer, op, bp)
            if root not in ("update_kind", "clear_default", "close"):
                assert any(r.locktype == "transactionid" and not r.granted for r in waits)
            held = (await observer.execute(text(
                "SELECT mode FROM pg_locks WHERE pid=:pid AND locktype='advisory' "
                "AND classid=435223 AND objsubid=2 AND granted"), {"pid": op})).all()
            assert any(r.mode == "ExclusiveLock" for r in held)
            async with running(reader(w, admission, "register")) as rt:
                await blocked(observer, ap, op, advisory=True)
                assert not any(label == "reader" and "for update" in s for label, s, _ in w.sql)
                await blocker.rollback()
                assert await asyncio.wait_for(wt, 10)
                assert await asyncio.wait_for(rt, 10)


@pytest.mark.parametrize("root", READERS)
async def test_actual_reader_first_retains_shared_catalog_across_doc_wait(world, root):
    w = world
    async with w.factory() as row_owner, w.factory() as admission, w.factory() as mutator, w.factory() as observer:
        bp, ap, mp = await tag(row_owner, "row-owner"), await tag(admission, "reader"), await tag(mutator, "writer")
        await row_owner.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
        async with running(reader(w, admission, root)) as rt:
            await blocked(observer, ap, bp)
            async with running(writer(w, mutator, "create_case")) as wt:
                await blocked(observer, mp, ap, advisory=True)
                await row_owner.rollback()
                assert await asyncio.wait_for(rt, 10)
                assert await asyncio.wait_for(wt, 10)


@pytest.mark.parametrize("mode", ["S", "X"])
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_physical_collision_dedup_sorted_keys_and_transaction_lifetime(world, mode, completion):
    w = world
    # Logical order differs from physical key order; two UUIDs collide physically.
    a, collision, b = UUID(int=7), UUID(int=7 + 2**31), UUID(int=3)
    async with w.factory() as owner, w.factory() as waiter, w.factory() as observer:
        op, wp = await tag(owner, "keys"), await tag(waiter, "waiter")
        await acquire_case_catalog(owner, [a, b, collision, a], mode)
        locks = (await observer.execute(text(
            "SELECT objid, mode FROM pg_locks WHERE pid=:pid AND locktype='advisory' "
            "AND classid=435223 AND objsubid=2 AND granted ORDER BY objid"), {"pid": op})).all()
        assert [r.objid for r in locks] == [3, 7]
        assert all(r.mode == ("ShareLock" if mode == "S" else "ExclusiveLock") for r in locks)
        calls = [params for label, sql, params in w.sql if label == "keys" and "pg_advisory_xact_lock" in sql]
        assert [tuple(p)[-1] for p in calls] == [3, 7]
        async with running(acquire_case_catalog(waiter, [collision], "X")) as task:
            await blocked(observer, wp, op, advisory=True)
            await getattr(owner, completion)()
            await asyncio.wait_for(task, 10)
        await waiter.rollback()


async def test_cross_company_does_not_block_and_noop_return_keeps_caller_lease(world):
    w = world
    async with w.factory() as owner, w.factory() as other, w.factory() as waiter, w.factory() as observer:
        op, wp = await tag(owner, "owner"), await tag(waiter, "waiter")
        assert w.cid.int % 2**31 != w.other.int % 2**31
        await acquire_case_catalog(owner, [w.cid], "X")
        await asyncio.wait_for(acquire_case_catalog(other, [w.other], "X"), 5)
        await other.rollback()
        # A shared no-op assignment does not commit; the caller still owns S.
        await owner.rollback()
        op = await tag(owner, "owner-noop")
        actor = await owner.get(User, w.uid)
        result = await docs.assign_doc_case(str(w.doc), docs.CaseAssignIn(
            company_id=str(w.cid), case_id=None), owner, actor)
        assert result["case_id"] is None
        async with running(acquire_case_catalog(waiter, [w.cid], "X")) as task:
            await blocked(observer, wp, op, advisory=True)
            await owner.rollback()
            await asyncio.wait_for(task, 10)


@pytest.mark.parametrize("first", ["set", "close"])
async def test_default_set_versus_close_has_no_phantom(world, first):
    w = world
    async with w.factory() as db:
        if first == "set":
            await writer(w, db, "update_kind")
            with pytest.raises(HTTPException) as error:
                await writer(w, db, "close")
            assert error.value.status_code == 409
            assert "по умолчанию" in error.value.detail
        else:
            await writer(w, db, "close")
            with pytest.raises(HTTPException) as error:
                await writer(w, db, "update_kind")
            assert error.value.status_code == 409
            assert error.value.detail == "Закрытое дело нельзя назначить делом по умолчанию"
        await db.rollback()
    async with w.factory() as check:
        kind, case = await check.get(DocKind, w.kind), await check.get(DocCase, w.case)
        assert not (kind.default_case_id == case.id and case.status == "closed")


async def test_default_clear_then_close_and_rollover_open_admission(world):
    w = world
    async with w.factory() as db:
        await writer(w, db, "update_kind")
        await writer(w, db, "clear_default")
        await writer(w, db, "close")
        new = await writer(w, db, "create_case")
        await docs.update_kind(str(w.kind), kind_body(w, default_case_id=new["id"]), db,
                               await db.get(User, w.uid))
        rolled = await writer(w, db, "rollover")
        assert rolled["added"] == 1 and rolled["defaults_updated"] == 1
        await docs.update_kind(str(w.kind), kind_body(w, default_case_id=None), db,
                               await db.get(User, w.uid))
        # Registration still works with no Case/default; numbering stays native.
        result = await reader(w, db, "register")
        assert result["case_id"] is None and result["reg_number"]


async def test_bulk_sorted_doc_locks_precede_case_and_preserve_deduplicated_result(world):
    w = world
    other_doc = UUID(int=(w.doc.int + 1) % 2**128)
    async with w.factory() as setup:
        setup.add(DocCard(id=other_doc, company_id=w.cid, kind_id=w.kind, kind_code="synthetic",
                          author_id=w.uid, title="Synthetic second draft", attrs={}))
        await setup.commit()
    async with w.factory() as blocker, w.factory() as caller, w.factory() as observer:
        bp, cp = await tag(blocker, "case-owner"), await tag(caller, "bulk-sorted")
        await blocker.execute(select(DocCase).where(DocCase.id == w.case).with_for_update())
        actor = await caller.get(User, w.uid)
        payload = docs.DocBulkIn(company_id=str(w.cid), action="assign_case", case_id=str(w.case),
                                 doc_ids=[str(max(w.doc, other_doc)), str(min(w.doc, other_doc)), str(w.doc)])
        async with running(docs.bulk_docs(payload, caller, actor)) as task:
            await blocked(observer, cp, bp)
            rows = [s for label, s, _ in w.sql if label == "bulk-sorted"]
            dl = next(i for i, s in enumerate(rows) if "doc_cards" in s and "for update" in s)
            cl = next(i for i, s in enumerate(rows) if "doc_cases" in s and "for update" in s)
            assert "order by doc_cards.id" in rows[dl] and dl < cl
            # An independent reader cannot lock either card while bulk waits on Case.
            for did in (w.doc, other_doc):
                found = await observer.scalar(select(DocCard.id).where(
                    DocCard.id == did).with_for_update(skip_locked=True))
                assert found is None
            await blocker.rollback()
            assert await asyncio.wait_for(task, 10) == {"selected": 2, "updated": 2, "unchanged": 0}


async def test_rollover_new_case_is_open_for_native_registration_admission(world):
    w = world
    async with w.factory() as db:
        case = await db.get(DocCase, w.case)
        case.year = w.year - 1
        await db.commit()
        await writer(w, db, "update_kind")
        result = await docs.rollover_cases(str(w.cid), w.year, db, await db.get(User, w.uid))
        assert result == {"added": 1, "defaults_updated": 1, "year": w.year}
        registered = await reader(w, db, "register")
        assert registered["case_id"] != str(w.case)
        target = await db.get(DocCase, UUID(registered["case_id"]))
        assert target.status == "open" and target.year == w.year
