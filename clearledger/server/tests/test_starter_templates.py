"""Посев заготовок работы: чем живёт разработка в новом пространстве.

Ловим то, из-за чего посев оказался бы бесполезным или вредным: заготовка без
своего типа (маршрут поедет не тот), повторное нажатие с задвоением, потеря
правок пространства, и молчаливое удаление расписания вместе с заготовкой.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskRecurrence, TaskTemplate, TaskType
from app.routers.tasks_router import STARTER_TEMPLATES
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_посев_заводит_заготовки_вместе_с_их_типами(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    first = await auth_client.post("/api/tasks/templates/starter",
                                   params={"company_id": cid})
    assert first.status_code == 201, first.text

    listing = (await auth_client.get("/api/tasks/templates",
                                     params={"company_id": cid})).json()["templates"]
    by_name = {item["name"]: item for item in listing}
    for spec in STARTER_TEMPLATES:
        assert spec["name"] in by_name, spec["name"]
        made = by_name[spec["name"]]
        # Чек-лист и есть причина существования заготовки: без него она лишний
        # клик, разовое поручение ставится и без шаблона.
        assert made["checklist"] == spec["checklist"]
        # Тип обязателен: без него «Разбор ошибки» пошёл бы маршрутом по
        # умолчанию — «Постановка → В работе → Проверка» вместо диагностики.
        assert made["type_id"], spec["name"]

    types = (await auth_client.get("/api/tasks/types",
                                   params={"company_id": cid})).json()["types"]
    codes = {item["code"] for item in types}
    assert {spec["type_code"] for spec in STARTER_TEMPLATES} <= codes


async def test_повтор_ничего_не_задваивает_и_не_трогает_правки(
        auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    await auth_client.post("/api/tasks/templates/starter", params={"company_id": cid})

    # Пространство переписало заготовку под себя — посев не должен это вернуть.
    mine = (await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == uuid.UUID(cid),
        TaskTemplate.name == "Разбор ошибки"))).scalars().first()
    assert mine is not None
    mine.checklist = ["Свой единственный пункт"]
    await db.commit()

    again = await auth_client.post("/api/tasks/templates/starter",
                                   params={"company_id": cid})
    assert again.status_code == 201, again.text
    assert again.json()["added"] == 0

    await db.refresh(mine)
    assert mine.checklist == ["Свой единственный пункт"]

    same = (await db.execute(select(TaskTemplate.id).where(
        TaskTemplate.company_id == uuid.UUID(cid),
        TaskTemplate.name == "Разбор ошибки"))).scalars().all()
    assert len(same) == 1


async def test_заготовку_с_расписанием_не_удалить_молча(
        auth_client: AsyncClient, db: AsyncSession):
    """Расписание висит на заготовке каскадом: удаление унесло бы его без слов, и
    «акт сверки к 5 числу» просто перестал бы заводиться."""
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    made = (await auth_client.post("/api/tasks/templates", json={
        "company_id": cid, "name": f"Сверка {uuid.uuid4().hex[:6]}",
        "title": "Акт сверки", "checklist": ["Собрать обороты"]})).json()

    db.add(TaskRecurrence(company_id=uuid.UUID(cid), template_id=uuid.UUID(made["id"]),
                          rule={"mode": "monthly", "day": 5, "at": "09:00",
                                "tz": "Europe/Moscow"}))
    await db.commit()

    refused = await auth_client.delete(f"/api/tasks/templates/{made['id']}",
                                       params={"company_id": cid})
    assert refused.status_code == 409, refused.text
    assert "расписание" in refused.json()["detail"].lower()


async def test_у_каждой_заготовки_есть_чеклист_и_известный_тип():
    """Заготовка без чек-листа — лишний клик, а с неизвестным типом — маршрут,
    которого нет. Проверяется без базы: это про сам набор, а не про пространство."""
    from app.routers.tasks_router import STARTER_TYPES

    known = {spec["code"] for spec in STARTER_TYPES}
    names = [spec["name"] for spec in STARTER_TEMPLATES]
    assert len(names) == len(set(names))
    for spec in STARTER_TEMPLATES:
        assert spec["checklist"], spec["name"]
        assert spec["type_code"] in known, spec["name"]
        # Заголовок подставляется в задачу как есть: пустой дал бы строку-призрак
        # в реестре, а короче трёх знаков не пройдёт и собственную форму.
        assert len(spec["title"].strip()) >= 3, spec["name"]
