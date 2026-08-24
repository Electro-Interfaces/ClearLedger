"""Посев заготовок работы: чем живёт разработка в новом пространстве.

Ловим то, из-за чего посев оказался бы бесполезным или вредным: заготовка без
своего типа (маршрут поедет не тот), повторное нажатие с задвоением, потеря
правок пространства, и молчаливое удаление расписания вместе с заготовкой.
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskRecurrence, TaskTemplate, TaskType
from app.routers.tasks_router import (
    STARTER_TEMPLATES_COMMON, STARTER_TEMPLATES_ENERGY, STARTER_TEMPLATES_OFFICE,
    starter_templates,
)
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_посев_заводит_заготовки_вместе_с_их_типами(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    first = await auth_client.post("/api/tasks/templates/starter",
                                   params={"company_id": cid})
    assert first.status_code == 201, first.text

    company = (await auth_client.get("/api/companies",
                                     params={"limit": 200})).json()
    profile = next((c.get("profile_id") for c in (
        company.get("companies") if isinstance(company, dict) else company)
        if str(c.get("id")) == cid), None)
    listing = (await auth_client.get("/api/tasks/templates",
                                     params={"company_id": cid})).json()["templates"]
    by_name = {item["name"]: item for item in listing}
    for spec in starter_templates(profile):
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
    assert {spec["type_code"] for spec in starter_templates(profile)} <= codes


async def test_повтор_ничего_не_задваивает_и_не_трогает_правки(
        auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    await auth_client.post("/api/tasks/templates/starter", params={"company_id": cid})

    # Пространство переписало заготовку под себя — посев не должен это вернуть.
    mine = (await db.execute(select(TaskTemplate).where(
        TaskTemplate.company_id == uuid.UUID(cid),
        TaskTemplate.name == "Разбор обращения"))).scalars().first()
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
        TaskTemplate.name == "Разбор обращения"))).scalars().all()
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
    которого нет. Проверяется без базы: это про сами наборы, а не про пространство.

    Профили проверяются вместе: разъехаться они могут по-разному, а требование к
    заготовке одно. Заодно ловим совпадение имён между общим и профильным
    набором — посев идёт по имени, и двойник молча потерялся бы.
    """
    from app.routers.tasks_router import STARTER_TYPES

    known = {spec["code"] for spec in STARTER_TYPES}
    for profile in ("energy", "office", "fuel", None):
        names = [spec["name"] for spec in starter_templates(profile)]
        assert len(names) == len(set(names)), profile
    assert starter_templates("energy") != starter_templates("office")
    assert starter_templates(None) == STARTER_TEMPLATES_COMMON
    for spec in (STARTER_TEMPLATES_COMMON + STARTER_TEMPLATES_ENERGY
                 + STARTER_TEMPLATES_OFFICE):
        assert spec["checklist"], spec["name"]
        assert spec["type_code"] in known, spec["name"]
        # Заголовок подставляется в задачу как есть: пустой дал бы строку-призрак
        # в реестре, а короче трёх знаков не пройдёт и собственную форму.
        assert len(spec["title"].strip()) >= 3, spec["name"]


async def test_заготовку_названную_маршрутом_не_удалить(
        auth_client: AsyncClient, db: AsyncSession):
    """Просьба зовёт заготовку ПО ИМЕНИ: удаление названной останавливает маршрут
    молча — просьба становится `skipped` в журнале, а работа не появляется."""
    from sqlalchemy import text

    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    name = f"Выезд по обращению {uuid.uuid4().hex[:6]}"
    made = (await auth_client.post("/api/tasks/templates", json={
        "company_id": cid, "name": name, "title": "Выезд на площадку",
        "checklist": ["Согласовать доступ"]})).json()

    # Витрина «Поддержки» живёт в схеме `public` той же базы. В прогоне её нет —
    # заводим ровно то, что читает проверка, и убираем за собой.
    await db.execute(text(
        "create table if not exists public.ticket_stage_links "
        "(id uuid primary key, action jsonb)"))
    link_id = uuid.uuid4()
    await db.execute(text(
        "insert into public.ticket_stage_links (id, action) "
        "values (:id, cast(:act as jsonb))"),
        {"id": str(link_id), "act": json.dumps(
            {"kind": "connector_call", "provider": "core",
             "payload": {"type": "errand.requested", "template": name}},
            ensure_ascii=False)})
    await db.commit()
    try:
        refused = await auth_client.delete(f"/api/tasks/templates/{made['id']}",
                                           params={"company_id": cid})
        assert refused.status_code == 409, refused.text
        assert "маршрут" in refused.json()["detail"].lower()

        # Маршрут поправили — заготовка снова удаляется.
        await db.execute(text("delete from public.ticket_stage_links where id = :id"),
                         {"id": str(link_id)})
        await db.commit()
        freed = await auth_client.delete(f"/api/tasks/templates/{made['id']}",
                                         params={"company_id": cid})
        assert freed.status_code == 200, freed.text
    finally:
        await db.execute(text("delete from public.ticket_stage_links where id = :id"),
                         {"id": str(link_id)})
        await db.commit()
