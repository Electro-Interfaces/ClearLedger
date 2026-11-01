"""AUTHORED / NOTRUN: native error and concurrency contracts, not AST mirrors.

Imports the guarded shared native test composition. Ancestor conftest isolation,
full schema/codecs/constraints/bootstrap and disposable cleanup are mandatory
before import and remain the runtime owner's responsibility.
"""
import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from tests.test_doc_case_writer_protocol_pg import (
    Company, DocCard, DocCase, DocCounter, DocKind, User,
    acquire_case_catalog, blocked, docs, kind_body, reader, running, tag, world, writer,
)

pytestmark = pytest.mark.asyncio


async def counters(db, cid):
    return [(r.scope_key, r.next_value) for r in (await db.scalars(select(DocCounter).where(
        DocCounter.company_id == cid).order_by(DocCounter.scope_key))).all()]


@pytest.mark.parametrize("first", ["set", "close"])
async def test_concurrent_default_set_close_observed_wait_and_no_closed_default(world, first):
    w = world
    async with w.factory() as blocker, w.factory() as owner, w.factory() as waiter, w.factory() as observer:
        bp, op, wp = await tag(blocker, "blocker"), await tag(owner, "first"), await tag(waiter, "second")
        model, key = (DocKind, w.kind) if first == "set" else (DocCase, w.case)
        await blocker.execute(select(model).where(model.id == key).with_for_update())
        roots = ("update_kind", "close") if first == "set" else ("close", "update_kind")
        async with running(writer(w, owner, roots[0])) as a:
            await blocked(observer, op, bp)
            async with running(writer(w, waiter, roots[1])) as b:
                await blocked(observer, wp, op, advisory=True)
                await blocker.rollback()
                assert await asyncio.wait_for(a, 10)
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(b, 10)
                assert error.value.status_code == 409
                await waiter.rollback()
    async with w.factory() as check:
        kind, case = await check.get(DocKind, w.kind), await check.get(DocCase, w.case)
        assert not (kind.default_case_id == case.id and case.status == "closed")
        assert (kind.default_case_id == w.case) == (first == "set")


async def test_concurrent_default_none_clear_waits_before_setters_then_close_succeeds(world):
    w = world
    async with w.factory() as setup:
        await writer(w, setup, "update_kind")
    async with w.factory() as blocker, w.factory() as clearer, w.factory() as closer, w.factory() as observer:
        bp, cp, xp = await tag(blocker, "blocker"), await tag(clearer, "clearer"), await tag(closer, "closer")
        await blocker.execute(select(DocKind).where(DocKind.id == w.kind).with_for_update())
        async with running(writer(w, clearer, "clear_default")) as a:
            await blocked(observer, cp, bp)
            async with running(writer(w, closer, "close")) as b:
                await blocked(observer, xp, cp, advisory=True)
                await blocker.rollback()
                assert (await asyncio.wait_for(a, 10))["default_case_id"] is None
                assert (await asyncio.wait_for(b, 10))["status"] == "closed"


async def test_register_none_case_waits_for_new_kind_default_and_snapshots_retention(world):
    w = world
    async with w.factory() as blocker, w.factory() as setter, w.factory() as registrar, w.factory() as observer:
        bp, sp, rp = await tag(blocker, "blocker"), await tag(setter, "setter"), await tag(registrar, "registrar")
        await blocker.execute(select(DocKind).where(DocKind.id == w.kind).with_for_update())
        async with running(writer(w, setter, "update_kind")) as a:
            await blocked(observer, sp, bp)
            async with running(reader(w, registrar, "register")) as b:
                await blocked(observer, rp, sp, advisory=True)
                await blocker.rollback()
                await asyncio.wait_for(a, 10)
                result = await asyncio.wait_for(b, 10)
                assert result["case_id"] == str(w.case)
                assert result["storage_until"] == f"{w.year + 5}-12-31"
    async with w.factory() as check:
        card = await check.get(DocCard, w.doc)
        assert card.retention_snapshot["case_id"] == str(w.case)


@pytest.mark.parametrize("manual", [False, True])
async def test_native_number_completion_counter_and_repeat_409(world, manual):
    w = world
    async with w.factory() as db:
        before = await counters(db, w.cid)
        kwargs = dict(reg_number="  SYN-MANUAL  ", manual_reason="Synthetic import") if manual else {}
        result = await reader(w, db, "register", **kwargs)
        after = await counters(db, w.cid)
        if manual:
            assert result["reg_number"] == "SYN-MANUAL" and result["number_manual"]
            assert after == before
        else:
            assert result["reg_number"].endswith("0001") and not result["number_manual"]
            assert len(after) == 1 and after[0][1] == 1
        with pytest.raises(HTTPException) as error:
            await reader(w, db, "register", **kwargs)
        assert error.value.status_code == 409
        assert error.value.detail == f"Документ уже зарегистрирован под номером {result['reg_number']}"
        await db.rollback()
        assert await counters(db, w.cid) == after


@pytest.mark.parametrize("scenario, expected, detail", [
    ("blank", 400, "Ручной регистрационный номер не может быть пустым"),
    ("reason", 409, "Укажите причину переноса номера из прежнего журнала"),
    ("future", 400, "Дата регистрации не может быть в будущем"),
    ("pending", 409, "Во время согласования реквизиты зафиксированы. Сначала отмените круг"),
    ("required", 409, "Заполните обязательный реквизит «Synthetic required»"),
    ("closed_case", 409, "Закрытое дело не принимает новые документы"),
])
async def test_native_register_error_precedence_and_whole_root_rollback(world, scenario, expected, detail):
    w = world
    async with w.factory() as setup:
        card, kind, case = await setup.get(DocCard, w.doc), await setup.get(DocKind, w.kind), await setup.get(DocCase, w.case)
        card.case_id = w.case
        case.status = "closed"
        if scenario == "pending":
            card.approval_status = "pending"
        if scenario == "required":
            kind.fields = [{"code": "required", "label": "Synthetic required", "type": "text", "required": True}]
        await setup.commit()
    kwargs = {}
    if scenario in ("blank", "reason"):
        kwargs = dict(reg_number="   " if scenario == "blank" else "SYN", manual_reason="")
    if scenario == "future":
        kwargs = dict(reg_date=docs.datetime.now(docs._BUSINESS_TIMEZONE).date() + timedelta(days=1))
    async with w.factory() as db, w.factory() as waiter, w.factory() as observer:
        dp, wp = await tag(db, "register"), await tag(waiter, "waiter")
        before = await counters(db, w.cid)
        with pytest.raises(HTTPException) as error:
            await reader(w, db, "register", **kwargs)
        assert error.value.status_code == expected and error.value.detail == detail
        # Even failure retains the transaction catalog lease until caller rollback.
        async with running(acquire_case_catalog(waiter, [w.cid], "X")) as task:
            await blocked(observer, wp, dp, advisory=True)
            await db.rollback()
            await asyncio.wait_for(task, 10)
            await waiter.rollback()
        assert await counters(db, w.cid) == before
        card = await db.get(DocCard, w.doc)
        assert card.reg_number is None and card.verify_token is None


async def test_manual_ordinary_user_denied_and_busy_number_preserves_counter(world):
    w = world
    async with w.factory() as setup:
        card = await setup.get(DocCard, w.doc)
        card.author_id = w.ordinary
        other_id = uuid4()
        setup.add(DocCard(id=other_id, company_id=w.cid, kind_id=w.kind, kind_code="synthetic",
                          author_id=w.uid, title="Synthetic prior registration", attrs={}, reg_number="BUSY"))
        await setup.commit()
    async with w.factory() as db:
        ordinary = await db.get(User, w.ordinary)
        before = await counters(db, w.cid)
        with pytest.raises(HTTPException) as error:
            await docs.register_doc(str(w.doc), docs.RegisterIn(company_id=str(w.cid), reg_number="MANUAL",
                                    manual_reason="Synthetic reason"), db, ordinary)
        assert error.value.status_code == 403
        await db.rollback()
        with pytest.raises(HTTPException) as error:
            await reader(w, db, "register", reg_number="BUSY", manual_reason="Synthetic reason")
        assert error.value.status_code == 409
        assert error.value.detail == "Номер BUSY уже занят другим документом"
        await db.rollback()
        assert await counters(db, w.cid) == before


async def test_ordinary_contract_kind_get_repeats_without_admin_or_duplicates(world):
    w = world
    async with w.factory() as db:
        first = await writer(w, db, "contract")
        again = await writer(w, db, "contract")
        assert first == again
        codes = [k["code"] for k in first["kinds"]]
        assert len(codes) == len(set(codes)) > 0
        assert all(k["default_case_id"] is None for k in first["kinds"])
        assert await db.scalar(select(func.count()).select_from(DocKind).where(
            DocKind.company_id == w.cid, DocKind.code.in_(codes))) == len(codes)


@pytest.mark.parametrize("default", [None, "closed", "foreign"])
async def test_default_delegate_native_errors_and_nil_clear(world, default):
    w = world
    async with w.factory() as db:
        value = None
        if default == "closed":
            case = await db.get(DocCase, w.case)
            case.status = "closed"
            value = str(case.id)
        elif default == "foreign":
            case = DocCase(id=uuid4(), company_id=w.other, year=w.year, index="FOREIGN",
                           title="Synthetic foreign case")
            db.add(case)
            await db.flush()
            value = str(case.id)
        await db.commit()
        if default is None:
            assert await docs._default_case_id(db, w.cid, value) is None
        else:
            with pytest.raises(HTTPException) as error:
                await docs._default_case_id(db, w.cid, value)
            assert error.value.status_code == (409 if default == "closed" else 404)
            assert error.value.detail == ("Закрытое дело нельзя назначить делом по умолчанию"
                                          if default == "closed" else "Дело не найдено")


async def test_bulk_other_action_has_no_catalog_lock_and_keeps_native_result(world):
    w = world
    async with w.factory() as db:
        await tag(db, "bulk-other")
        due = docs.datetime.now(docs.timezone.utc)
        result = await docs.bulk_docs(docs.DocBulkIn(company_id=str(w.cid), doc_ids=[str(w.doc)],
                                      action="set_due", due_at=due), db, await db.get(User, w.uid))
        assert result == {"selected": 1, "updated": 1, "unchanged": 0}
        assert not any(label == "bulk-other" and "pg_advisory_xact_lock" in s for label, s, _ in w.sql)
