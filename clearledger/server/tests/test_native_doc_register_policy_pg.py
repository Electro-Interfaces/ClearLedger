"""AUTHORED / NOTRUN (including collection).

The runtime owner must isolate ancestor conftest BEFORE import and provide the
full native schema, codecs, constraints and disposable cleanup. No schema,
codec, copied policy, replacement Session or transaction runner is defined here.
"""
import os
import sys
from urllib.parse import urlsplit

_URL = os.environ.get("NATIVE_DOC_REGISTER_PG_URL", "")
_TARGET = urlsplit(_URL)
if not (_URL and _URL == os.environ.get("NATIVE_DOC_REGISTER_APPROVED_URL")
        and _URL == os.environ.get("DATABASE_URL") == os.environ.get("TEST_DATABASE_URL")
        and os.environ.get("NATIVE_DOC_REGISTER_PREIMPORT") == "reviewed-isolated"
        and os.environ.get("NATIVE_DOC_REGISTER_SCHEMA") == "full-native"
        and os.environ.get("NATIVE_DOC_REGISTER_CLEANUP") == "owner-disposable"
        and _TARGET.scheme == "postgresql+asyncpg" and _TARGET.hostname == "127.0.0.1"
        and _TARGET.port and _TARGET.password and not _TARGET.query and not _TARGET.fragment
        and _TARGET.path.startswith("/native_doc_register_test_")
        and len(_TARGET.path) > len("/native_doc_register_test_")
        and not any(n == "conftest" or n.endswith(".conftest") for n in sys.modules)):
    raise RuntimeError("Reviewed pre-import isolation/full native disposable schema required")


import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import inspect, select

from app.auth import native_claims_context
from app.models import (CompanyRole, DocAccessGrant, DocAcquaint, DocApproval,
    DocCard, DocCounter, DocKind, Organization, User, UserCompany, UserSubstitution)
from app.routers import docs_router as docs, users_router as users, roles_router as roles, auth_router as auth
from app.schemas import CompanyRoleUpdate, MemberAccessUpdate, UserAdminUpdate
from app.services import native_doc_register_locks as native, doc_approvals
from tests.test_native_doc_register_ownership_pg import (
    world, tag, blocked, running, register, no_register_dml, seed_substitution)

pytestmark = pytest.mark.asyncio


async def native_revoke(w, db, branch):
    admin = await db.get(User, w.admin)
    if branch == "role":
        return await roles.update_role(str(w.role), CompanyRoleUpdate(
            company_id=str(w.cid), name="Synthetic revoked", modules=["info"]), db, admin)
    if branch == "product":
        return await users.set_member_access(str(w.uid), MemberAccessUpdate(
            company_id=str(w.cid), mode="custom", modules=["info"]), db, admin)
    actor = await db.get(User, w.uid)
    return await auth.logout_all(Response(), actor, db)


@pytest.mark.parametrize("branch", ["role", "product", "session"])
@pytest.mark.parametrize("first", ["register", "writer"])
async def test_actual_identity_product_role_revoke_both_orders(world, branch, first):
    w = world
    model = CompanyRole if branch == "role" else User if branch == "session" else UserCompany
    async with w.factory() as blocker, w.factory() as writer, w.factory() as caller, w.factory() as observer:
        bp, wp, cp = await tag(blocker, "blocker"), await tag(writer, "revoke"), await tag(caller, "register")
        claims = {"sub": str(w.uid), "tv": 0}
        if first == "register":
            await blocker.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())
            async with running(register(w, caller, claims=claims)) as rt:
                await blocked(observer, cp, bp)
                async with running(native_revoke(w, writer, branch)) as wt:
                    await blocked(observer, wp, cp)
                    await blocker.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    assert await asyncio.wait_for(wt, 10)
        else:
            query = (select(model).where(model.id == (w.role if branch == "role" else w.uid))
                if model is not UserCompany else select(UserCompany).where(
                    UserCompany.user_id == w.uid, UserCompany.company_id == w.cid))
            await blocker.execute(query.with_for_update())
            async with running(native_revoke(w, writer, branch)) as wt:
                await blocked(observer, wp, bp)
                async with running(register(w, caller, claims=claims)) as rt:
                    await blocked(observer, cp, wp)
                    no_register_dml(w)
                    await blocker.rollback()
                    assert await asyncio.wait_for(wt, 10)
                    with pytest.raises(HTTPException) as error:
                        await asyncio.wait_for(rt, 10)
                    assert error.value.status_code in ({401} if branch == "session" else {403, 409})
                    await caller.rollback()


async def deputy_only_read(w):
    async with w.factory() as db:
        await seed_substitution(w, db)
        doc = await db.get(DocCard, w.doc)
        doc.author_id = doc.responsible_id = doc.signatory_id = w.foreign
        doc.confidentiality, doc.approval_status, doc.approval_round = "strict", "none", 1
        member = await db.get(UserCompany, (w.uid, w.cid))
        member.role = "admin"  # Native edit fallback; READ still requires deputy assignment.
        ids = [uuid4(), uuid4()]
        db.add_all([DocApproval(id=aid, company_id=w.cid, doc_id=w.doc, round=1,
            step_no=1, step_code="parallel", step_name="Synthetic parallel",
            mode="parallel", quorum="all", assignee_id=uid,
            # Keep original FK inventory stable while status changes, so the
            # oracle reaches native READ rather than the new-parent 409 guard.
            decided_by=uid, status="pending") for aid, uid in zip(ids, (w.principal, w.recipient))])
        await db.commit()
        return ids


@pytest.mark.parametrize("first", ["register", "decider"])
async def test_actual_decide_event_fk_fences_pending_deputy_read_without_approval_x(world, first):
    w = world
    approval, _ = await deputy_only_read(w)
    ready, release = asyncio.Event(), asyncio.Event()
    async with w.factory() as owner, w.factory() as caller, w.factory() as counter, w.factory() as observer:
        op, cp, bp = await tag(owner, "decider"), await tag(caller, "register"), await tag(counter, "counter")
        async def decide():
            doc = await owner.get(DocCard, w.doc)
            actor = await owner.get(User, w.principal)
            rows = await doc_approvals.lock_round(owner, w.cid, w.doc, 1)
            row = next(r for r in rows if r.id == approval)
            result = await doc_approvals.decide(owner, w.cid, doc, row, actor, True, None, rows)
            assert result["left"] == 1 and doc.approval_status == "none"
            ready.set()
            await release.wait()  # The real caller retains the real root/FK lease.
            await owner.commit()
            return result
        if first == "register":
            # Existing UPSERT wait parks register AFTER its Card X, before token.
            counter.add(DocCounter(company_id=w.cid, scope_key=f"synthetic|-|{w.year}", next_value=0))
            await counter.commit()
            await counter.execute(select(DocCounter).where(DocCounter.company_id == w.cid).with_for_update())
            async with running(register(w, caller)) as rt:
                await blocked(observer, cp, bp)
                async with running(decide()) as dt:
                    rows = await blocked(observer, op, cp, relation="doc_cards")
                    assert any(r.locktype == "transactionid" and not r.granted for r in rows)
                    assert not any(label == "register" and "doc_approvals" in sql and "for update" in sql
                                   for label, sql, _ in w.sql)
                    await counter.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    release.set()
                    assert await asyncio.wait_for(dt, 10)
        else:
            async with running(decide()) as dt:
                await asyncio.wait_for(ready.wait(), 10)
                async with running(register(w, caller)) as rt:
                    await blocked(observer, cp, op, relation="doc_cards")
                    no_register_dml(w)
                    release.set()
                    assert await asyncio.wait_for(dt, 10)
                    with pytest.raises(HTTPException) as error:
                        await asyncio.wait_for(rt, 10)
                    assert error.value.status_code == 403
                    await caller.rollback()


@pytest.mark.parametrize("entry", ["create", "stop"])
async def test_actual_admin_revoke_between_early_check_and_discovery_is_rechecked(world, monkeypatch, entry):
    w = world
    async with w.factory() as setup:
        member = await setup.get(UserCompany, (w.uid, w.cid))
        member.role = "admin"
        sub_id = await seed_substitution(w, setup)
    original = native.prepare_substitution
    revoked = False
    async def revoke_then_prepare(db, actor, company_ref, **kw):
        nonlocal revoked
        if not revoked:
            async with w.factory() as writer:
                admin = await writer.get(User, w.admin)
                await users.update_user(str(w.uid), UserAdminUpdate(company_id=str(w.cid), role="user"), writer, admin)
            revoked = True
        return await original(db, actor, company_ref, **kw)
    monkeypatch.setattr(native, "prepare_substitution", revoke_then_prepare)
    async with w.factory() as db:
        actor = await db.get(User, w.uid)
        with pytest.raises(HTTPException) as error:
            if entry == "create":
                day = datetime.now(timezone.utc).date()
                await docs.create_substitution(docs.SubstitutionIn(company_id=str(w.cid), user_id=str(w.principal),
                    deputy_id=str(w.recipient), starts_on=day, ends_on=day), db, actor)
            else:
                await docs.stop_substitution(str(sub_id), str(w.cid), db, actor)
        assert error.value.status_code == 403
        assert not db.new and not db.dirty and not db.deleted
        await db.rollback()


@pytest.mark.parametrize("dirty", ["own_pending", "policy_parent"])
async def test_pending_safe_check_preserves_exact_history_and_original_selector(world, dirty):
    w = world
    async with w.factory() as setup:
        setup.add(DocAcquaint(company_id=w.cid, doc_id=w.doc, user_id=w.recipient,
            status="pending", snapshot_sha256="1" * 64, created_by=w.admin))
        await setup.commit()
    async with w.factory() as db:
        actor = await db.get(User, w.uid)
        prepared = await native.prepare_register(db, actor, str(w.cid), str(w.doc))
        doc = (await db.execute(select(DocCard).where(DocCard.id == w.doc).with_for_update())).scalar_one()
        retained = native.retain_register(prepared, doc)
        await native.check_register(db, prepared, doc, retained, phase="card")
        doc.reg_number, doc.reg_date, doc.status = "SYN-OWN", datetime.now(timezone.utc).date(), "registered"
        retained = native.retain_register(prepared, doc)
        await native.supersede_register_acquaints(db, prepared)
        acquaint = next(x for x in db.dirty if isinstance(x, DocAcquaint))
        if dirty == "policy_parent":
            actor.name = "Unexpected policy mutation"
        before = native._pending_fingerprint(db)
        if dirty == "policy_parent":
            with pytest.raises(HTTPException) as error:
                await native.check_register(db, prepared, doc, retained, phase="pending")
            assert error.value.status_code == 409
        else:
            await native.check_register(db, prepared, doc, retained, phase="pending")
        assert native._pending_fingerprint(db) == before  # BEFORE caller rollback.
        assert inspect(doc).attrs.reg_number.history.added == ["SYN-OWN"]
        assert inspect(acquaint).attrs.status.history.added == ["superseded"]
        assert doc.status == "registered" and acquaint.status == "superseded"
        await db.rollback()


@pytest.mark.parametrize("extra", ["organization", "default_case", "principal", "acquaint", "approval", "subscription"])
async def test_original_footprint_never_extends_for_new_parent_after_wait(world, extra):
    w = world
    # Raw MVCC drift probes test detection, not supported-writer closure. Park
    # before Kind/Card rows so the real child FK can complete in the other root.
    async with w.factory() as setup:
        doc, kind = await setup.get(DocCard, w.doc), await setup.get(DocKind, w.kind)
        doc.organization_id, kind.number_scope = None, "kind_org_year"
        await setup.commit()
    async with w.factory() as blocker, w.factory() as caller, w.factory() as writer, w.factory() as observer:
        bp, cp = await tag(blocker, "blocker"), await tag(caller, "register")
        await blocker.execute(select(CompanyRole).where(CompanyRole.id == w.role).with_for_update())
        async with running(register(w, caller)) as task:
            await blocked(observer, cp, bp)
            if extra == "organization":
                writer.add(Organization(company_id=w.cid, name="Synthetic new inference", inn=""))
            elif extra == "default_case":
                from app.models import DocCase
                case = DocCase(company_id=w.cid, year=w.year, index="NEW", title="Synthetic new default")
                writer.add(case)
                await writer.flush()
                kind = await writer.get(DocKind, w.kind)
                kind.default_case_id = case.id
            elif extra == "principal":
                await seed_substitution(w, writer)
            elif extra == "acquaint":
                writer.add(DocAcquaint(company_id=w.cid, doc_id=w.doc, user_id=w.recipient))
            elif extra == "approval":
                writer.add(DocApproval(company_id=w.cid, doc_id=w.doc, assignee_id=w.recipient))
            else:
                from app.models import EventSubscription
                writer.add(EventSubscription(company_id=w.cid, label="Synthetic new recipient", target_kind="url",
                    url="https://example.invalid/new", secret_enc=w.cipher, event_types=["doc.registered"]))
            await writer.commit()
            await blocker.rollback()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, 10)
            assert error.value.status_code == 409
            no_register_dml(w)
            await caller.rollback()


@pytest.mark.parametrize("first", ["register", "physical_writer"])
async def test_native_visit_disable_physical_probe_both_orders_and_fresh_recheck(world, monkeypatch, first):
    """PartnerSpace row fence probe; no claim about an undiscovered app writer."""
    w = world
    from app.models import PartnerSpace
    calls = []
    original = native.native_visit_from_claims
    async def native_visit(claims, user, db):
        result = await original(claims, user, db)
        calls.append((claims.copy(), user.id, result))
        return result
    monkeypatch.setattr(native, "native_visit_from_claims", native_visit)
    claims = {"sub": str(w.uid), "tv": 0, "scp": "visit", "cid": str(w.cid), "pvs": str(w.partner)}
    async with w.factory() as blocker, w.factory() as caller, w.factory() as writer, w.factory() as observer:
        bp, cp, wp = await tag(blocker, "blocker"), await tag(caller, "register"), await tag(writer, "physical-disable")
        if first == "physical_writer":
            partner = await writer.get(PartnerSpace, w.partner)
            partner.is_active = False
            await writer.flush()
            async with running(register(w, caller, claims=claims)) as rt:
                await blocked(observer, cp, wp)
                no_register_dml(w)
                await writer.commit()
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(rt, 10)
                assert error.value.status_code == 401
                await caller.rollback()
        else:
            blocker.add(DocCounter(company_id=w.cid, scope_key=f"synthetic|-|{w.year}", next_value=0))
            await blocker.commit()
            bp = await tag(blocker, "blocker")
            await blocker.execute(select(DocCounter).where(DocCounter.company_id == w.cid).with_for_update())
            async with running(register(w, caller, claims=claims)) as rt:
                await blocked(observer, cp, bp)
                partner = await writer.get(PartnerSpace, w.partner)
                partner.is_active = False
                async with running(writer.flush()) as wt:
                    await blocked(observer, wp, cp)
                    await blocker.rollback()
                    assert await asyncio.wait_for(rt, 10)
                    assert len(calls) >= 5 and all(c[0] == claims and c[1:] == (w.uid, w.cid) for c in calls)
                    await asyncio.wait_for(wt, 10)
                    await writer.commit()


async def test_temporal_principal_expiry_recomputed_after_counter_wait(world, monkeypatch):
    w = world
    await deputy_only_read(w)
    async with w.factory() as holder, w.factory() as caller, w.factory() as observer:
        hp, cp = await tag(holder, "counter"), await tag(caller, "register")
        holder.add(DocCounter(company_id=w.cid, scope_key=f"synthetic|-|{w.year}", next_value=0))
        await holder.commit()
        hp = await tag(holder, "counter")
        await holder.execute(select(DocCounter).where(DocCounter.company_id == w.cid).with_for_update())
        async with running(register(w, caller)) as rt:
            await blocked(observer, cp, hp)
            later = datetime.now(timezone.utc) + timedelta(days=3)
            class LaterDateTime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return later.astimezone(tz) if tz else later.replace(tzinfo=None)
            monkeypatch.setattr(doc_approvals, "datetime", LaterDateTime)
            await holder.rollback()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(rt, 10)
            assert error.value.status_code == 403
            assert await caller.scalar(select(DocCounter.next_value).where(DocCounter.company_id == w.cid)) == 1
            doc = await caller.get(DocCard, w.doc)
            assert doc.reg_number is None and doc.status == "draft"
            await caller.rollback()


async def test_cached_grant_identity_is_refreshed_before_same_native_edit_evaluator(world):
    w = world
    from tests.test_native_doc_register_ownership_pg import grant
    async with w.factory() as setup:
        saved = await grant(w, setup)
    from uuid import UUID
    async with w.factory() as caller:
        retained = await caller.get(DocAccessGrant, UUID(saved["id"]))
        actor, doc = await caller.get(User, w.uid), await caller.get(DocCard, w.doc)
        assert await docs._can_doc(caller, w.cid, doc, actor, "edit", record_break_glass_use=False)
        async with w.factory() as writer:
            await grant(w, writer, deny=True)
        assert retained.permissions == ["edit"] and retained.denied_permissions == []
        with pytest.raises(HTTPException) as error:
            await register(w, caller)
        assert error.value.status_code == 403
        assert retained.permissions == [] and retained.denied_permissions == ["edit"]
        await caller.rollback()
