"""Focused actual native HTTP/PG characterization; execute only through ROOT gate."""
import os
from urllib.parse import urlsplit

import pytest

from tests.partner_test_safety import partner_test_safety_error

FLAG = "RUN_NATIVE_CONTRACT_CREATE_TESTS"
if os.environ.get(FLAG) != "1":
    pytest.skip(f"Requires {FLAG}=1", allow_module_level=True)
if error := partner_test_safety_error(os.environ, flag=FLAG):
    raise RuntimeError(error)
if (urlsplit(os.environ["TEST_DATABASE_URL"]).path != "/api_native_contract_create_test_20261030"
        or os.environ.get("DATABASE_URL") != os.environ["TEST_DATABASE_URL"]
        or os.environ.get("ROOT_APPROVED_NATIVE_CONTRACT_CREATE_TESTS") != "1"):
    raise RuntimeError("Requires ROOT approval and the exact disposable native-create database")

import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import _visit_company, get_current_user
from app.database import get_db
from app.models import Company, Contract, ContractLocation, Counterparty, Organization, User, UserCompany
from app.routers import references_router
from app.schemas import ContractCreate
from app.scope import set_request_organization, set_request_scope
from app.services.native_contract_commands import create_native_contract

pytestmark = pytest.mark.asyncio(loop_scope="session")
URL = "/api/references/contracts"
KEY_CONFLICT = "Ключ создания договора уже использован с другими реквизитами"
CP_ERROR = "Контрагент не найден в справочнике пространства"
ORG_ERROR = "Организация не найдена в справочнике пространства"


def full_input(w):
    """Literal native input contract, including every documented default field."""
    return {
        "company_id": w.slug, "creationKey": str(uuid.uuid4()),
        "number": "Native-74", "date": "2026-01-01", "type": "Аренда",
        "counterpartyId": str(w.cp_id), "organizationId": str(w.org_id),
        "typeCode": None, "amountLimit": None, "kind": None, "currency": None,
        "validUntil": None, "vatRate": None, "amountInclVat": None,
        "settlementKind": None, "comment": None, "basis": None,
        "isClosed": False, "scopeType": "unassigned", "signed": None, "signedAt": None,
        "paymentTermDays": None, "isStateContract": None, "igk": None, "responsibleId": None,
        "signerOur": None, "signerOurPosition": None, "signerCp": None,
        "signerCpPosition": None, "signerCpBasis": None,
    }


def golden_hash(explicit_complete_input):
    # No model_dump/schema/helper call: the oracle is the complete literal input.
    values = {key: value for key, value in explicit_complete_input.items()
              if key not in {"company_id", "creationKey"}}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def persisted(w, cid=None):
    async with w.factory() as fresh:
        rows = (await fresh.execute(select(Contract).where(
            Contract.company_id == (w.cid if cid is None else cid)).order_by(Contract.id))).scalars()
        return [{prop.key: deepcopy(getattr(row, prop.key)) for prop in row.__mapper__.column_attrs}
                for row in rows]


async def post(w, payload, actor=None, **headers):
    return await w.client.post(URL, json=payload, headers={
        "X-Synthetic-Actor": str(w.member_id if actor is None else actor), **headers})


@pytest_asyncio.fixture(loop_scope="session")
async def world(db):
    set_request_scope(None)
    set_request_organization(None)
    _visit_company.set(None)
    token = uuid.uuid4().hex[:12]
    companies = [Company(name="Синтетическая компания", slug=f"native-create-{token}-{i}", profile_id="energy")
                 for i in range(2)]
    actors = [User(name="Синтетический пользователь", email=f"{token}-{i}@example.invalid",
                   password_hash="unused", is_superadmin=(i == 3)) for i in range(5)]
    db.add_all([*companies, *actors])
    await db.flush()
    cid, foreign_cid = (c.id for c in companies)
    cps = [Counterparty(id=uuid.UUID("a" + uuid.uuid4().hex[1:]), company_id=cid,
                        name=f"Синтетическая сторона {i}", inn=None) for i in range(2)]
    foreign_cp = Counterparty(company_id=foreign_cid, name="Чужая синтетическая сторона", inn=None)
    orgs = [Organization(company_id=cid, name=f"Синтетическая организация {i}", inn="", prefix=f"Т{i}") for i in range(2)]
    foreign_org = Organization(company_id=foreign_cid, name="Чужая синтетическая организация", inn="", prefix="Ч")
    db.add_all([*cps, foreign_cp, *orgs, foreign_org,
                *(UserCompany(user_id=actor.id, company_id=cid, role=role)
                  for actor, role in zip(actors[:3], ["member", "admin", "member"]))])
    await db.flush()
    active, inactive = f"native-active-{token}", f"native-inactive-{token}"
    await db.execute(text("INSERT INTO contract_types(code,label,is_active) VALUES "
                          "(:active,'Синтетический вид',true),(:inactive,'Неактивный синтетический вид',false)"),
                     {"active": active, "inactive": inactive})
    w = SimpleNamespace(db=db, factory=async_sessionmaker(db.bind, expire_on_commit=False),
                        cid=cid, slug=companies[0].slug, foreign_cid=foreign_cid,
                        cp_id=cps[0].id, cp2_id=cps[1].id, foreign_cp_id=foreign_cp.id,
                        org_id=orgs[0].id, org2_id=orgs[1].id, foreign_org_id=foreign_org.id,
                        member_id=actors[0].id, admin_id=actors[1].id, peer_id=actors[2].id,
                        super_id=actors[3].id, outsider_id=actors[4].id,
                        actors={str(a.id): a for a in actors}, active=active, inactive=inactive,
                        gates={}, pids={}, entered={}, bodies={})
    await db.commit()
    app = FastAPI()
    app.include_router(references_router.router, prefix="/api")

    async def principal(request: Request):
        # Only the native authentication dependency is a fixture. Every value is
        # a real User; no partner principal, membership or policy is fabricated.
        actor = w.actors[request.headers.get("X-Synthetic-Actor", str(w.member_id))]
        visit = request.headers.get("X-Synthetic-Visit")
        scope_token = _visit_company.set(uuid.UUID(visit) if visit else None)
        set_request_scope(None)
        set_request_organization(None)
        try:
            yield actor
        finally:
            _visit_company.reset(scope_token)
            set_request_scope(None)
            set_request_organization(None)

    async def session(request: Request):
        async with w.factory() as transaction:
            label = request.headers.get("X-Synthetic-Transaction")
            try:
                if label:
                    w.pids[label] = await transaction.scalar(text("SELECT pg_backend_pid()"))
                    w.entered[label].set()
                yield transaction
                if label == "hold":
                    w.gates["flushed"].set()
                    await w.gates["release"].wait()
                if label == "rollback":
                    raise RuntimeError("Synthetic caller rollback after native flush")
                await transaction.commit()
            except BaseException:
                await transaction.rollback()
                raise

    app.dependency_overrides[get_current_user] = principal
    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://synthetic-native.test") as client:
        w.client = client
        try:
            yield w
        finally:
            for event in w.gates.values():
                event.set()
            await db.rollback()
    set_request_scope(None)
    set_request_organization(None)
    _visit_company.set(None)


async def test_full_native_contract_golden_and_exact_hash(world):
    w = world
    body = full_input(w) | {
        "typeCode": w.active, "amountLimit": 125.5, "kind": "СПоставщиком", "currency": "RUB",
        "validUntil": "2027-12-31", "vatRate": "20", "amountInclVat": False,
        "settlementKind": "Синтетический расчёт", "comment": "Синтетический комментарий", "basis": "договор",
        "isClosed": True, "scopeType": "locations", "signed": True, "signedAt": "2026-01-02",
        "paymentTermDays": 0, "isStateContract": False, "igk": "synthetic-igk", "responsibleId": str(w.member_id),
        "signerOur": "Подписант 1", "signerOurPosition": "Должность 1", "signerCp": "Подписант 2",
        "signerCpPosition": "Должность 2", "signerCpBasis": "Синтетическое основание",
    }
    response = await post(w, body)
    assert response.status_code == 201, response.text
    wire = response.json()
    assert {key: wire[key] for key in body if key not in {"company_id", "creationKey"}} == {
        key: value for key, value in body.items() if key not in {"company_id", "creationKey"}}
    assert wire["companyId"] == str(w.cid) and "creationKey" not in wire
    row, = await persisted(w)
    expected = {
        "number": "Native-74", "date": "2026-01-01", "type": "Аренда", "company_id": w.cid,
        "counterparty_id": w.cp_id, "organization_id": w.org_id, "type_code": w.active,
        "amount_limit": 125.5, "kind": "СПоставщиком", "currency": "RUB", "valid_until": "2027-12-31",
        "vat_rate": "20", "amount_incl_vat": False, "settlement_kind": "Синтетический расчёт",
        "comment": "Синтетический комментарий", "basis": "договор", "is_closed": True,
        "scope_type": "locations", "signed": True, "signed_at": "2026-01-02", "payment_term_days": 0,
        "is_state_contract": False, "igk": "synthetic-igk", "responsible_id": w.member_id,
        "signer_our": "Подписант 1", "signer_our_position": "Должность 1", "signer_cp": "Подписант 2",
        "signer_cp_position": "Должность 2", "signer_cp_basis": "Синтетическое основание",
        "creation_key": uuid.UUID(body["creationKey"]), "creation_actor_id": w.member_id,
        "creation_request_hash": golden_hash(body), "raw": None, "external_ref": None,
        "manual_overrides": [], "liability": None, "title": None,
    }
    assert {key: row[key] for key in expected} == expected
    async with w.factory() as fresh:
        links = (await fresh.scalars(select(ContractLocation).where(ContractLocation.contract_id == row["id"]))).all()
        assert links == []


async def test_omitted_defaults_and_explicit_null_share_hash(world):
    w = world
    full = full_input(w)
    minimal = {key: full[key] for key in ("company_id", "creationKey", "number", "date", "type", "counterpartyId", "organizationId")}
    first, replay = await post(w, minimal), await post(w, full)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    row, = await persisted(w)
    assert row["creation_request_hash"] == golden_hash(full)
    assert row["scope_type"] == "unassigned" and row["manual_overrides"] == []


async def test_blank_req_values_normalize_columns_but_not_request_hash(world):
    w = world
    fields = ["signedAt", "igk", "responsibleId", "signerOur", "signerOurPosition", "signerCp", "signerCpPosition", "signerCpBasis"]
    body = full_input(w) | {key: "" for key in fields}
    response = await post(w, body)
    assert response.status_code == 201, response.text
    assert all(response.json()[key] is None for key in fields)
    row, = await persisted(w)
    assert row["creation_request_hash"] == golden_hash(body)
    assert row["creation_request_hash"] != golden_hash(full_input(w))


@pytest.mark.parametrize("case", ["member", "admin", "superadmin", "outsider", "foreign-company", "missing-company", "visit-foreign"])
async def test_native_company_admission(world, case):
    w = world
    body, headers = full_input(w), {}
    actor, expected = {"admin": w.admin_id, "superadmin": w.super_id, "outsider": w.outsider_id}.get(case, w.member_id), 201
    if case == "outsider":
        expected = 403
    elif case == "foreign-company":
        body["company_id"], expected = str(w.foreign_cid), 403
    elif case == "missing-company":
        body["company_id"], expected = "synthetic-company-does-not-exist", 400
    elif case == "visit-foreign":
        headers["X-Synthetic-Visit"], expected = str(w.foreign_cid), 403
    response = await post(w, body, actor, **headers)
    assert response.status_code == expected, response.text
    rows = await persisted(w)
    assert len(rows) == (1 if expected == 201 else 0)
    if rows:
        assert rows[0]["creation_actor_id"] == actor
    elif expected == 403:
        assert response.json() == {"detail": "Нет доступа к компании"}


@pytest.mark.parametrize("axis", ["counterpartyId", "organizationId"])
@pytest.mark.parametrize("bad", ["malformed", "missing", "foreign"])
async def test_party_rejections(world, axis, bad):
    w = world
    value = "not-a-uuid" if bad == "malformed" else str(uuid.uuid4()) if bad == "missing" else str(
        w.foreign_cp_id if axis == "counterpartyId" else w.foreign_org_id)
    response = await post(w, full_input(w) | {axis: value})
    expected = ("Невалидный контрагента" if axis == "counterpartyId" else "Невалидный организации") if bad == "malformed" else (
        CP_ERROR if axis == "counterpartyId" else ORG_ERROR)
    assert response.status_code == 400 and response.json() == {"detail": expected}
    assert await persisted(w) == []


@pytest.mark.parametrize("case", ["both-malformed", "missing-cp-malformed-org", "both-foreign", "type-before-responsible", "invalid-responsible", "party-before-type"])
async def test_native_failure_precedence(world, case):
    w = world
    values, status, detail = {}, 400, CP_ERROR
    if case == "both-malformed":
        values, detail = {"counterpartyId": "bad", "organizationId": "bad"}, "Невалидный контрагента"
    elif case == "missing-cp-malformed-org":
        values, detail = {"counterpartyId": str(uuid.uuid4()), "organizationId": "bad"}, "Невалидный организации"
    elif case == "both-foreign":
        values = {"counterpartyId": str(w.foreign_cp_id), "organizationId": str(w.foreign_org_id)}
    elif case == "type-before-responsible":
        values, status, detail = {"typeCode": "synthetic-unknown-type", "responsibleId": "bad"}, 422, "Неизвестный вид договора: synthetic-unknown-type"
    elif case == "invalid-responsible":
        values, detail = {"typeCode": w.active, "responsibleId": "bad"}, "Невалидный ID"
    else:
        values = {"counterpartyId": str(uuid.uuid4()), "typeCode": "synthetic-unknown-type"}
    response = await post(w, full_input(w) | values)
    assert response.status_code == status and response.json() == {"detail": detail}
    assert await persisted(w) == []


@pytest.mark.parametrize("case", ["active", "inactive", "unknown", "empty"])
async def test_contract_type_lookup(world, case):
    w = world
    code = {"active": w.active, "inactive": w.inactive, "unknown": "synthetic-unknown-type", "empty": ""}[case]
    response = await post(w, full_input(w) | {"typeCode": code})
    if case in {"inactive", "unknown"}:
        assert response.status_code == 422 and response.json() == {"detail": f"Неизвестный вид договора: {code}"}
        assert await persisted(w) == []
    else:
        assert response.status_code == 201
        row, = await persisted(w)
        assert row["type_code"] == (w.active if case == "active" else None)


@pytest.mark.parametrize("case", ["actor", "number", "amount", "normalized-empty", "same-uuid-different-spelling"])
async def test_creation_key_conflicts_preserve_original(world, case):
    w = world
    body = full_input(w)
    assert (await post(w, body)).status_code == 201
    before = await persisted(w)
    actor, changed = w.member_id, dict(body)
    if case == "actor":
        actor = w.peer_id
    elif case == "number":
        changed["number"] = "Другой номер"
    elif case == "amount":
        changed["amountLimit"] = 12.5
    elif case == "normalized-empty":
        changed["signedAt"] = ""
    else:
        changed["counterpartyId"] = body["counterpartyId"].upper()
    response = await post(w, changed, actor)
    assert response.status_code == 409 and response.json() == {"detail": KEY_CONFLICT}
    assert await persisted(w) == before


async def test_company_alias_excluded_and_replay_precedes_type_revalidation(world):
    w = world
    body = full_input(w) | {"typeCode": w.active}
    first = await post(w, body)
    assert first.status_code == 201
    before = await persisted(w)
    await w.db.execute(text("UPDATE contract_types SET is_active=false WHERE code=:code"), {"code": w.active})
    await w.db.commit()
    replay = await post(w, body | {"company_id": str(w.cid)})
    assert replay.status_code == 201 and replay.json() == first.json()
    assert await persisted(w) == before


@pytest.mark.parametrize("axis", ["counterpartyId", "organizationId"])
async def test_replay_validates_parties_before_key_conflict(world, axis):
    w = world
    body = full_input(w)
    assert (await post(w, body)).status_code == 201
    before = await persisted(w)
    response = await post(w, body | {axis: str(uuid.uuid4())})
    assert response.status_code == 400 and response.json() == {"detail": CP_ERROR if axis == "counterpartyId" else ORG_ERROR}
    assert await persisted(w) == before


@pytest.mark.parametrize("case", ["new-key", "unkeyed", "identity-whitespace", "duplicate-before-type", "different-date", "different-party", "different-organization"])
async def test_business_duplicate_and_distinct_contracts(world, case):
    w = world
    body = full_input(w)
    first = await post(w, body)
    assert first.status_code == 201
    changed = body | {"creationKey": str(uuid.uuid4())}
    expected = 409
    if case == "unkeyed":
        changed.pop("creationKey")
    elif case == "identity-whitespace":
        changed["number"], changed["type"], changed["date"] = " Native-74 ", " Аренда ", "2026-01-01 "
    elif case == "duplicate-before-type":
        changed["typeCode"] = "synthetic-unknown-type"
    elif case == "different-date":
        changed["date"], expected = "2026-02-01", 201
    elif case == "different-party":
        changed["counterpartyId"], expected = str(w.cp2_id), 201
    elif case == "different-organization":
        changed["organizationId"], expected = str(w.org2_id), 201
    response = await post(w, changed)
    assert response.status_code == expected, response.text
    if expected == 409:
        assert response.json() == {"detail": "Договор с такими сторонами и реквизитами уже существует: " + first.json()["id"]}
    assert len(await persisted(w)) == (1 if expected == 409 else 2)


@pytest.mark.parametrize("field,value", [("number", ""), ("date", ""), ("type", ""), ("date", "not-an-iso-date")])
@pytest.mark.parametrize("keyed", [True, False])
async def test_incomplete_identity_preserves_intention_semantics(world, field, value, keyed):
    w = world
    body = full_input(w) | {field: value}
    if not keyed:
        body.pop("creationKey")
    first, second = await post(w, body), await post(w, body)
    assert first.status_code == second.status_code == 201
    assert (first.json()["id"] == second.json()["id"]) is keyed
    rows = await persisted(w)
    assert len(rows) == (1 if keyed else 2)
    if not keyed:
        assert all(row["creation_key"] is row["creation_actor_id"] is row["creation_request_hash"] is None for row in rows)


async def test_zero_false_values_are_not_replaced_by_defaults(world):
    w = world
    response = await post(w, full_input(w) | {"amountLimit": 0, "amountInclVat": False, "signed": False,
                                             "paymentTermDays": 0, "isStateContract": False})
    assert response.status_code == 201
    row, = await persisted(w)
    assert (row["amount_limit"], row["amount_incl_vat"], row["signed"], row["payment_term_days"], row["is_state_contract"]) == (0, False, False, 0, False)


async def test_creation_key_is_scoped_to_company(world):
    w = world
    body = full_input(w)
    first = await post(w, body, w.super_id)
    foreign = await post(w, body | {"company_id": str(w.foreign_cid), "counterpartyId": str(w.foreign_cp_id),
                                    "organizationId": str(w.foreign_org_id)}, w.super_id)
    assert first.status_code == foreign.status_code == 201
    own, = await persisted(w)
    other, = await persisted(w, w.foreign_cid)
    assert own["creation_key"] == other["creation_key"] and own["id"] != other["id"]
    assert own["creation_actor_id"] == other["creation_actor_id"] == w.super_id


@pytest.mark.parametrize("mode", ["http", "direct-use-case"])
async def test_caller_rollback_after_native_flush(world, mode):
    w = world
    body = full_input(w)
    if mode == "http":
        w.entered["rollback"] = asyncio.Event()
        response = await post(w, body, **{"X-Synthetic-Transaction": "rollback"})
        assert response.status_code == 500
    else:
        async with w.factory() as transaction:
            row = await create_native_contract(transaction, ContractCreate(**body), w.actors[str(w.member_id)])
            assert isinstance(row, Contract) and row.id is not None
            assert row.creation_request_hash == golden_hash(body)
            await transaction.rollback()
    assert await persisted(w) == []


@pytest.mark.parametrize("same_key", [True, False])
async def test_actual_post_concurrency_uses_existing_company_barrier(world, same_key):
    w = world
    w.gates = {name: asyncio.Event() for name in ("flushed", "release")}
    w.entered = {name: asyncio.Event() for name in ("hold", "second")}
    body = full_input(w)
    if not same_key:
        body.pop("creationKey")
    first = asyncio.create_task(post(w, body, **{"X-Synthetic-Transaction": "hold"}))
    second = None
    try:
        async with asyncio.timeout(10):
            await w.gates["flushed"].wait()
            second = asyncio.create_task(post(w, body, **{"X-Synthetic-Transaction": "second"}))
            await w.entered["second"].wait()
            async with w.factory() as observer:
                while True:
                    wait = await observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=:pid "
                        "AND locktype='advisory' AND NOT granted) AND :blocker=ANY(pg_blocking_pids(:pid))"),
                        {"pid": w.pids["second"], "blocker": w.pids["hold"]})
                    if wait:
                        break
                    if second.done():
                        pytest.fail("Second POST completed before the expected actual advisory wait: " + (await second).text)
                    await asyncio.sleep(0.02)
            w.gates["release"].set()
            a, b = await asyncio.gather(first, second)
            assert a.status_code == 201 and b.status_code == (201 if same_key else 409)
            if same_key:
                assert a.json() == b.json()
    finally:
        w.gates["release"].set()
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(await persisted(w)) == 1
