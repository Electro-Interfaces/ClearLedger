"""Витрина всей работы «Трека» для пульта управляющего звена.

Витрина одной заявки отвечает «что по ней». Управляющему нужен другой вопрос:
где сейчас стоит контур целиком. Ловим то, из-за чего список был бы бесполезен:

* «Держат ход» показывает не всё незакрытое, а только то, чего ждёт процесс, —
  иначе повод вмешаться тонет среди работы, идущей своим чередом;
* просрочка считается по сроку предмета (поручение — свой, документ — срок
  незакрытой визы), а не по дате просьбы;
* закрытое из открытых разрезов уходит, но остаётся в «Всё».
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRequest, Company, Task

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _key(db: AsyncSession, cid: uuid.UUID, value: str) -> dict[str, str]:
    company = await db.get(Company, cid)
    company.cloud_api_key = value
    await db.commit()
    return {"X-Cloud-API-Key": value}


async def test_витрина_работы_компании(auth_client: AsyncClient, db: AsyncSession):
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    head = await _key(db, cid, f"desk-{uuid.uuid4().hex[:8]}")

    now = datetime.now(timezone.utc)
    late = Task(company_id=cid, title="Заменить модуль", status="open",
                due_at=now - timedelta(days=2))
    fresh = Task(company_id=cid, title="Согласовать смету", status="open",
                 due_at=now + timedelta(days=3))
    db.add_all([late, fresh])
    await db.flush()

    # Ход процесса стоит только там, где задано, чем его двигать: без глагола
    # исход просто фиксируется, и заявка идёт дальше сама.
    holds = ApprovalRequest(
        company_id=cid, request_id=f"t:{uuid.uuid4().hex[:8]}", process_id="ticket-1",
        kind="errand", task_id=late.id, on_approved="Выполнено")
    runs = ApprovalRequest(
        company_id=cid, request_id=f"t:{uuid.uuid4().hex[:8]}", process_id="ticket-2",
        kind="errand", task_id=fresh.id)
    closed = ApprovalRequest(
        company_id=cid, request_id=f"t:{uuid.uuid4().hex[:8]}", process_id="ticket-3",
        kind="errand", task_id=fresh.id, on_approved="Выполнено",
        outcome="approved", decided_at=now)
    db.add_all([holds, runs, closed])
    await db.commit()

    async def rows(**params):
        r = await auth_client.get("/api/eco/work", params=params, headers=head)
        assert r.status_code == 200, r.text
        return {i["id"]: i for i in r.json()["items"]}

    waiting = await rows(scope="waiting")
    assert str(holds.id) in waiting, "работа, на которой стоит ход, не показана"
    assert str(runs.id) not in waiting, "в «держат ход» попала работа, которой процесс не ждёт"
    assert str(closed.id) not in waiting, "закрытое держит ход"

    item = waiting[str(holds.id)]
    assert item["overdue"] is True and item["waits"] is True
    assert item["title"] == "Заменить модуль"
    assert item["process_id"] == "ticket-1", "заявку по строке не найти"
    assert item["url"], "нет перехода в «Трек» — решение принять негде"

    overdue = await rows(scope="overdue")
    assert set(overdue) == {str(holds.id)}, "просрочка считается не по сроку предмета"

    opened = await rows(scope="open")
    assert {str(holds.id), str(runs.id)} <= set(opened)
    assert str(closed.id) not in opened, "закрытое осталось в незакрытом"

    everything = await rows(scope="all")
    assert str(closed.id) in everything, "история потерялась"
    assert everything[str(closed.id)]["outcome"] == "approved"

    # Разрез по виду — иначе поручения тонут среди ознакомлений.
    assert set(await rows(scope="all", kind="approval")) == set()
    assert str(holds.id) in await rows(scope="all", kind="errand")

    await db.execute(  # прибираем за собой: витрина смотрит всю компанию
        ApprovalRequest.__table__.delete().where(
            ApprovalRequest.id.in_([holds.id, runs.id, closed.id])))
    await db.execute(Task.__table__.delete().where(Task.id.in_([late.id, fresh.id])))
    await db.commit()


async def test_чужая_компания_витрину_не_видит(auth_client: AsyncClient, db: AsyncSession):
    """Ключ пространства открывает работу своей компании и только её."""
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    head = await _key(db, cid, f"desk-{uuid.uuid4().hex[:8]}")

    other = (await db.execute(select(Company).where(Company.id != cid).limit(1))).scalars().first()
    if other is None:
        pytest.skip("в стенде одна компания — изоляцию проверять не на чем")

    task = Task(company_id=other.id, title="Чужая работа", status="open")
    db.add(task)
    await db.flush()
    row = ApprovalRequest(company_id=other.id, request_id=f"t:{uuid.uuid4().hex[:8]}",
                          process_id="ticket-x", kind="errand", task_id=task.id,
                          on_approved="Выполнено")
    db.add(row)
    await db.commit()

    r = await auth_client.get("/api/eco/work", params={"scope": "all"}, headers=head)
    assert r.status_code == 200
    assert str(row.id) not in [i["id"] for i in r.json()["items"]], "видна чужая работа"

    await db.execute(ApprovalRequest.__table__.delete().where(ApprovalRequest.id == row.id))
    await db.execute(Task.__table__.delete().where(Task.id == task.id))
    await db.commit()
