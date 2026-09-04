"""События проекта в журнале организации — на них живёт подписка «Проекты сети».

Ловим то, из-за чего подписка молчала бы при живой работе: история площадки
лежит в своей таблице, и в журнал (а значит и в оповещения) не попадала вовсе.
Второе — шум: если в журнал уедут заметки и правки паспорта, подписку выключат
на второй день, и вместе с шумом пропадёт важное.
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, EzsSite, User
from app.notify_catalog import category_for
from app.services import ezs_site_work
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _events(db: AsyncSession, cid: uuid.UUID, action: str) -> list[AuditEvent]:
    return list((await db.execute(select(AuditEvent).where(
        AuditEvent.company_id == cid, AuditEvent.action == action))).scalars().all())


async def test_смена_стадии_попадает_в_журнал(auth_client, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    user = await db.get(User, uuid.UUID(me["id"]))

    site = EzsSite(company_id=cid, title=f"Пауза {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="negotiation")
    db.add(site)
    await db.commit()

    before = len(await _events(db, cid, "project.stage"))
    await ezs_site_work.set_stage(db, site, "on_hold", user=user,
                                  reason="Собственник думает до весны")
    await db.commit()

    made = await _events(db, cid, "project.stage")
    assert len(made) == before + 1, "смена стадии не дошла до журнала"
    last = made[-1]
    # Подписка находит событие по префиксу — иначе оно уедет в «Прочие», которые
    # выключены по умолчанию, и человек не получит ничего.
    assert category_for(last.action) == "projects"
    # В строке видно, о каком проекте речь и куда он поехал: без этого читатель
    # оповещения идёт искать проект руками.
    assert site.title in (last.details or "")
    assert "Пауза" in (last.details or ""), last.details


async def test_заметка_журнал_не_шумит(auth_client, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    user = await db.get(User, uuid.UUID(me["id"]))

    site = EzsSite(company_id=cid, title=f"Заметка {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="lead")
    db.add(site)
    await db.commit()

    before = len(await _events(db, cid, "project.note"))
    await ezs_site_work.log_event(db, site, "note", text="Созвонились с собственником",
                                  user=user)
    await db.commit()
    assert len(await _events(db, cid, "project.note")) == before
