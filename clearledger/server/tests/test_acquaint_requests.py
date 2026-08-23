"""Ознакомление как активность процесса: разбор просьбы и возврат исхода.

Ловим то, из-за чего приказ остался бы недоведённым, а маршрут — стоящим
навсегда: некого знакомить, документ не назван и его неоткуда взять, лист
закрылся, а процесс об этом не узнал.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, Department, DocAcquaint, User, UserCompany
from app.services import acquaint_requests
from app.services.acquaint_requests import AcquaintRequestError
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _context(client: AsyncClient) -> tuple[dict, str, dict]:
    me = (await client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    await client.post(f"/api/docs/kinds/starter?company_id={cid}")
    kinds = (await client.get("/api/docs/kinds",
                              params={"company_id": cid})).json()["kinds"]
    return me, cid, next(item for item in kinds if item["code"] == "doc_in")


async def test_срок_считается_днями_и_датой():
    """Маршрут пишется один раз, а срабатывает много: «три дня» осмысленно
    всегда, конкретная дата — ровно один раз."""
    assert acquaint_requests._due({}) is None
    by_days = acquaint_requests._due({"due_days": 3})
    assert by_days is not None and by_days > datetime.now(timezone.utc)
    by_date = acquaint_requests._due({"due_at": "2026-12-31T09:00:00Z"})
    assert by_date == datetime(2026, 12, 31, 9, tzinfo=timezone.utc)
    with pytest.raises(AcquaintRequestError):
        acquaint_requests._due({"due_at": "не дата"})


async def test_просьба_без_процесса_отклоняется(db: AsyncSession):
    # Без процесса некому вернуть исход: лист завёлся бы в никуда.
    with pytest.raises(AcquaintRequestError):
        await acquaint_requests.request(db, uuid.uuid4(), "req-1", {})


async def test_документ_берётся_у_процесса_а_лист_закрывает_просьбу(
        auth_client: AsyncClient, db: AsyncSession):
    """Сквозной ход: маршрут просит ознакомить, человек читает, процесс идёт дальше.

    Документ намеренно не называется: в типовой цепочке «заведи документ →
    собери визы → ознакомь смену» он рождается внутри процесса, и маршруту
    неоткуда взять его идентификатор.
    """
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    process_id = f"ticket-{uuid.uuid4().hex[:8]}"

    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-приказ-{uuid.uuid4().hex}",
    })).json()

    # След того, что документ завёл этот же процесс, — именно по нему просьба
    # об ознакомлении найдёт бумагу, не называя её.
    db.add(ApprovalRequest(
        company_id=cid, request_id=f"doc-{uuid.uuid4().hex}", kind="document",
        process_id=process_id, doc_id=uuid.UUID(doc["id"]),
        outcome="approved", decided_at=datetime.now(timezone.utc)))
    await db.commit()

    row = await acquaint_requests.request(db, cid, f"req-{uuid.uuid4().hex}", {
        "process_id": process_id, "user_ids": [me["id"]], "due_days": 3,
        "on_done": "Доведено"})
    await db.commit()
    assert row.doc_id == uuid.UUID(doc["id"])
    assert row.round == 1 and row.outcome is None  # ждём исход: глагол задан

    sheet = (await db.execute(select(DocAcquaint).where(
        DocAcquaint.doc_id == uuid.UUID(doc["id"])))).scalars().all()
    assert [item.status for item in sheet] == ["pending"]
    assert sheet[0].due_at is not None

    read = await auth_client.post(f"/api/docs/{doc['id']}/acquaint/read",
                                  json={"company_id": cid_raw})
    assert read.status_code == 200, read.text

    await db.refresh(row)
    assert row.outcome == "done" and row.decided_at is not None


async def test_без_глагола_просьба_не_держит_документ(
        auth_client: AsyncClient, db: AsyncSession):
    """Разослали и не ждём — запись закрывается сразу.

    Открытая просьба заняла бы документ (одна живая просьба на бумагу) и не
    пустила бы по нему следующий круг виз.
    """
    me, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-уведомление-{uuid.uuid4().hex}",
    })).json()

    row = await acquaint_requests.request(db, cid, f"req-{uuid.uuid4().hex}", {
        "process_id": f"ticket-{uuid.uuid4().hex[:8]}", "doc_id": doc["id"],
        "user_ids": [me["id"]]})
    await db.commit()
    assert row.outcome == "done"


async def test_некого_знакомить_отбивается_причиной(
        auth_client: AsyncClient, db: AsyncSession):
    """Человек без доступа к «Треку» в лист не попадает: иначе лист врал бы о том,
    что документ доведён."""
    _, cid_raw, kind = await _context(auth_client)
    cid = uuid.UUID(cid_raw)
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"],
        "title": f"ПРОВЕРКА-пустой-лист-{uuid.uuid4().hex}",
    })).json()

    department = Department(company_id=cid, name=f"Смена {uuid.uuid4().hex[:8]}")
    outsider = User(company_id=cid, email=f"no-docs-{uuid.uuid4().hex}@example.org",
                    name="Без доступа к Треку", password_hash="!")
    db.add_all([department, outsider])
    await db.flush()
    db.add(UserCompany(user_id=outsider.id, company_id=cid, role="user",
                       modules=["tasks"], department_id=department.id))
    await db.commit()

    with pytest.raises(AcquaintRequestError):
        await acquaint_requests.request(db, cid, f"req-{uuid.uuid4().hex}", {
            "process_id": "ticket-1", "doc_id": doc["id"],
            "department": department.name})

    # Подразделения с таким именем нет вовсе — причина должна называть его.
    with pytest.raises(AcquaintRequestError):
        await acquaint_requests.request(db, cid, f"req-{uuid.uuid4().hex}", {
            "process_id": "ticket-1", "doc_id": doc["id"],
            "department": "Нет такого подразделения"})
