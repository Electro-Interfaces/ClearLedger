"""AUTHORED / NOTRUN. Uses the guarded native composition, never old conftest.

The runtime owner must isolate ancestors before import, bootstrap the complete
native schema/codecs/constraints, and dispose the database after these cases.
Only synthetic rows are authored; seed_data/startup transaction ownership stays
unchanged. This module invokes the actual _seed_doc_kinds in a normal Session.
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from tests.test_doc_case_writer_protocol_pg import (
    Company, CompanyRole, DocCase, DocKind, User, UserCompany,
    acquire_case_catalog, blocked, docs, running, tag, world, writer,
)
from app.seed import _DOC_KINDS_SEED, _seed_doc_kinds

pytestmark = pytest.mark.asyncio


async def empty_company(w):
    cid = uuid4()
    async with w.factory() as db:
        db.add(Company(id=cid, slug="synthetic-seed-" + cid.hex, name="Synthetic empty catalog",
                       profile_id="energy"))
        await db.flush()
        db.add_all([UserCompany(user_id=w.uid, company_id=cid, role="admin"),
                    UserCompany(user_id=w.ordinary, company_id=cid, role="user", modules=["docs"])])
        await db.commit()
    return SimpleNamespace(**(vars(w) | {"cid": cid}))


@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_seed_pending_role_user_autoflush_precedes_all_sorted_catalog_keys(world, completion):
    w = world
    async with w.factory() as db, w.factory() as observer:
        pid = await tag(db, "seed")
        expected = sorted({cid.int % 2**31 for cid in (await observer.scalars(select(Company.id))).all()})
        role_id, user_id = uuid4(), uuid4()
        db.add(CompanyRole(id=role_id, company_id=w.cid, name="Synthetic pending role", modules=["docs"]))
        db.add(User(id=user_id, company_id=w.cid, email=f"{user_id.hex}@example.invalid",
                    name="Synthetic pending user", password_hash="synthetic-noncredential"))
        await _seed_doc_kinds(db)
        rows = [(s, p) for label, s, p in w.sql if label == "seed"]
        keys = [(i, tuple(p)[-1]) for i, (s, p) in enumerate(rows) if "pg_advisory_xact_lock(" in s]
        assert [key for _, key in keys] == expected
        first, last = keys[0][0], keys[-1][0]
        role_writes = [i for i, (s, _) in enumerate(rows) if s.lstrip().startswith(("insert into company_roles", "insert into users"))]
        assert len(role_writes) == 2 and max(role_writes) < first
        first_company = next(i for i, (s, _) in enumerate(rows) if s.startswith("select ") and "companies" in s)
        assert max(role_writes) < first_company < first
        assert not any(("company_roles" in s or "users" in s) and s.lstrip().startswith(("insert ", "update ", "delete "))
                       for s, _ in rows[first:])
        case_reads = [i for i, (s, _) in enumerate(rows) if "doc_cases" in s]
        assert case_reads and last < min(case_reads)
        held = (await observer.execute(text(
            "SELECT objid FROM pg_locks WHERE pid=:pid AND locktype='advisory' "
            "AND classid=435223 AND objsubid=2 AND granted ORDER BY objid"), {"pid": pid})).scalars().all()
        assert held == expected
        await getattr(db, completion)()
        assert not (await observer.execute(text(
            "SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory' "
            "AND classid=435223"), {"pid": pid})).all()
        assert (await observer.get(CompanyRole, role_id) is not None) == (completion == "commit")
        assert (await observer.get(User, user_id) is not None) == (completion == "commit")


@pytest.mark.parametrize("closed", [False, True])
async def test_seed_new_kind_uses_open_match_and_preserves_nil_on_closed_match(world, closed):
    w = await empty_company(world)
    case_id = uuid4()
    async with w.factory() as db:
        db.add(DocCase(id=case_id, company_id=w.cid, year=w.year, index="01-02",
                       title="Synthetic matched case", status="closed" if closed else "open"))
        await db.commit()
        await _seed_doc_kinds(db)
        await db.commit()
    async with w.factory() as db:
        kinds = (await db.scalars(select(DocKind).where(DocKind.company_id == w.cid))).all()
        assert {k.code for k in kinds} == {r["code"] for r in _DOC_KINDS_SEED}
        assert all(k.default_case_id == (None if closed else case_id)
                   for k in kinds if k.code in ("doc_in", "doc_out"))
        assert all(k.default_case_id is None for k in kinds if k.code in ("memo", "order"))


async def test_seed_backfill_closed_skips_none_and_existing_nonnull_stays(world):
    w = await empty_company(world)
    closed, retained, missing = uuid4(), uuid4(), uuid4()
    async with w.factory() as db:
        db.add(DocCase(id=closed, company_id=w.cid, year=w.year, index="01-02",
                       title="Synthetic historical closed case", status="closed"))
        await db.flush()
        db.add_all([DocKind(id=retained, company_id=w.cid, code="doc_in", name="Synthetic retained",
                            default_case_id=closed),
                    DocKind(id=missing, company_id=w.cid, code="doc_out", name="Synthetic unset")])
        await db.commit()
        await _seed_doc_kinds(db)
        await db.commit()
    async with w.factory() as db:
        assert (await db.get(DocKind, retained)).default_case_id == closed
        assert (await db.get(DocKind, missing)).default_case_id is None
        assert (await db.get(DocCase, closed)).status == "closed"
        assert set((await db.scalars(select(DocKind.code).where(DocKind.company_id == w.cid))).all()) == {"doc_in", "doc_out"}


async def test_seed_open_backfill_and_root_rollback_restore_catalog(world):
    w = await empty_company(world)
    kid = uuid4()
    async with w.factory() as db:
        db.add(DocKind(id=kid, company_id=w.cid, code="doc_in", name="Synthetic backfill"))
        await db.commit()
        await _seed_doc_kinds(db)
        await db.flush()
        assert (await db.get(DocKind, kid)).default_case_id is not None
        await db.rollback()
    async with w.factory() as db:
        assert (await db.get(DocKind, kid)).default_case_id is None
        assert not (await db.scalars(select(DocCase.id).where(DocCase.company_id == w.cid))).all()
        await _seed_doc_kinds(db)
        await db.commit()
        assert (await db.get(DocKind, kid)).default_case_id is not None


@pytest.mark.parametrize("root", ["create_kind", "update_kind", "clear_default", "starter", "contract"])
async def test_native_nil_default_kind_writer_first_then_seed_no_kinds_predicate(world, root):
    w = world if root in ("update_kind", "clear_default") else await empty_company(world)
    async with w.factory() as blocker, w.factory() as owner, w.factory() as seed, w.factory() as observer:
        bp, op, sp = await tag(blocker, "row-owner"), await tag(owner, "nil-writer"), await tag(seed, "seed")
        if root in ("update_kind", "clear_default"):
            await blocker.execute(select(DocKind).where(DocKind.id == w.kind).with_for_update())
        else:
            await blocker.execute(select(Company).where(Company.id == w.cid).with_for_update())
        async with running(writer(w, owner, root)) as wt:
            await blocked(observer, op, bp)
            async with running(_seed_doc_kinds(seed)) as st:
                await blocked(observer, sp, op, advisory=True)
                assert not any(label == "seed" and "doc_cases" in s for label, s, _ in w.sql)
                await blocker.rollback()
                assert await asyncio.wait_for(wt, 10)
                await asyncio.wait_for(st, 10)
                await seed.commit()
    async with w.factory() as check:
        codes = set((await check.scalars(select(DocKind.code).where(DocKind.company_id == w.cid))).all())
        if root == "create_kind":
            assert codes == {"new_synthetic"}  # noKinds was false; seed did not restore starter kinds.
        elif root in ("update_kind", "clear_default"):
            assert codes == {"synthetic"}
            assert (await check.get(DocKind, w.kind)).default_case_id == (w.case if root == "update_kind" else None)
        elif root == "contract":
            assert codes == {r["code"] for r in docs.STARTER_KINDS_CONTRACT}
        else:
            assert codes and "doc_in" in codes


@pytest.mark.parametrize("root", ["create_kind", "update_kind", "clear_default", "starter", "contract"])
@pytest.mark.parametrize("completion", ["commit", "rollback"])
async def test_seed_first_blocks_native_nil_writers_until_real_root_completion(world, root, completion):
    w = world if root in ("update_kind", "clear_default") else await empty_company(world)
    async with w.factory() as seed, w.factory() as caller, w.factory() as observer:
        sp, cp = await tag(seed, "seed"), await tag(caller, "nil-writer")
        await _seed_doc_kinds(seed)  # Real seed root is still uncommitted and retains every X.
        async with running(writer(w, caller, root)) as task:
            await blocked(observer, cp, sp, advisory=True)
            await getattr(seed, completion)()
            assert await asyncio.wait_for(task, 10)
    async with w.factory() as check:
        codes = set((await check.scalars(select(DocKind.code).where(DocKind.company_id == w.cid))).all())
        if root in ("update_kind", "clear_default"):
            assert codes == {"synthetic"}
            assert (await check.get(DocKind, w.kind)).default_case_id == (w.case if root == "update_kind" else None)
        elif completion == "commit":
            assert {r["code"] for r in _DOC_KINDS_SEED} <= codes
        elif root == "create_kind":
            assert codes == {"new_synthetic"}


@pytest.mark.parametrize("mode", ["S", "X"])
async def test_seed_waits_on_company_catalog_before_any_case_predicate(world, mode):
    w = world
    async with w.factory() as holder, w.factory() as seed, w.factory() as observer:
        hp, sp = await tag(holder, "holder"), await tag(seed, "seed")
        await acquire_case_catalog(holder, [w.cid], mode)
        async with running(_seed_doc_kinds(seed)) as task:
            await blocked(observer, sp, hp, advisory=True)
            assert not any(label == "seed" and ("doc_cases" in s or "doc_kinds" in s)
                           for label, s, _ in w.sql)
            await holder.rollback()
            await asyncio.wait_for(task, 10)
            await seed.rollback()
