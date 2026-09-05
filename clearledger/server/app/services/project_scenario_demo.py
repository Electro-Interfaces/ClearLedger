from datetime import datetime, timedelta, timezone
import os
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.auth import hash_password
from app.models import (App, ChatMessage, Company, CompanyApp, DocCard, DocKind, DocRelation, EzsSite,
    EzsSiteParticipant, Task, TaskEvent, User, UserCompany)
from app.services import context_chats, ezs_site_work, file_store, track_files
from app.services.project_scenario_settings import builtin, can_manage

DEMO_KEY = "procurement-v1"


async def available(db, cid, user):
    email = (os.environ.get("DEMO_SPACE_USER") or "").strip().lower()
    return bool(email and user.email.lower() == email and user.company_id == cid and await can_manage(db, cid, user))


async def prepare(db, cid, user):
    if not await available(db, cid, user):
        raise HTTPException(404, "Учебный пример доступен только на демонстрационном стенде")
    await db.scalar(select(Company.id).where(Company.id == cid).with_for_update())
    old = await db.scalar(select(EzsSite).where(EzsSite.company_id == cid, EzsSite.workspace_data["demo"]["key"].astext == DEMO_KEY))
    if old:
        return {"site_id": str(old.id), "created": False}
    app = await db.scalar(select(App).where(App.code == "projects"))
    if app is None:
        raise HTTPException(409, "Приложение «Проекты» отсутствует в каталоге")
    connection = await db.scalar(select(CompanyApp).where(CompanyApp.company_id == cid, CompanyApp.app_id == app.id))
    if connection is None:
        db.add(CompanyApp(company_id=cid, app_id=app.id, enabled=True))
    else:
        connection.enabled = True
    people = []
    for code, name, role in [("buyer", "Анна Соколова · демо", "Закупки"),
                              ("finance", "Павел Лебедев · демо", "ФБ"),
                              ("warehouse", "Мария Орлова · демо", "Склад")]:
        uid = uuid.uuid5(cid, f"project-demo:{code}")
        person = await db.get(User, uid)
        if person is None:
            person = User(id=uid, email=f"project-demo-{cid.hex[:12]}-{code}@example.invalid", name=name,
                          company_id=cid, password_hash=hash_password(secrets.token_urlsafe(24)))
            db.add(person)
            await db.flush()
            db.add(UserCompany(user_id=uid, company_id=cid, role="member"))
        people.append((person, role))
    site = await ezs_site_work.create_site(db, cid, {
        "kind": "procurement", "title": "Учебная закупка: оборудование для гостиницы",
        "city": "Учебный город", "address": "Учебная улица, 1", "place_kind": "Гостиница",
        "owner_user_id": str(user.id)}, user)
    site.owner_user_id = user.id
    for person, role in people:
        db.add(EzsSiteParticipant(company_id=cid, site_id=site.id, user_id=person.id, role_code=role))
    definition = builtin("procurement")
    for step, responsible in zip(definition["steps"], [people[0][0], people[1][0], people[0][0], people[2][0], people[2][0]]):
        step.update(responsible_id=str(responsible.id), due_days=3)
    site.workspace_data = {"scenario": {"version": 1, "definition": definition, "stage": "need",
        "fields": {"need": "Два учебных зарядных устройства по 240 000 ₽", "supplier": "Учебный поставщик", "budget": "480000"},
        "templates": {}, "evidence": {}}}
    await db.flush()
    room = await context_chats.ensure_room(db, cid, user, f"site:{site.id}", participant_ids=[p.id for p, _ in people])
    message = ChatMessage(room_id=room.id, user_id=people[0][0].id, user_name=people[0][0].name,
        content="Учебный пример. Для гостиницы нужны два устройства. Проверьте потребность и бюджет 480 000 ₽, согласуйте закупку и подтвердите приёмку. Все участники и документы вымышлены.")
    db.add(message)
    await db.flush()
    kind = await db.scalar(select(DocKind).where(DocKind.company_id == cid, DocKind.code == "demo_procurement"))
    if kind is None:
        kind = DocKind(company_id=cid, code="demo_procurement", name="Учебный документ закупки", number_prefix="УЧ")
        db.add(kind)
        await db.flush()
    guide = []
    for index, step in enumerate(definition["steps"]):
        title = f"Учебная закупка: {step['result'].lower()}"
        person_id = uuid.UUID(step["responsible_id"])
        if step["requirement"] == "done":
            row = Task(company_id=cid, title=title, description="Учебная работа. После проверки завершите поручение и примите результат этапа в проекте.",
                author_id=user.id, assignee_id=person_id, subject_ref=f"site:{site.id}", status="open", visibility="company",
                due_at=datetime.now(timezone.utc) + timedelta(days=index + 2))
            db.add(row)
            await db.flush()
            db.add(TaskEvent(task_id=row.id, kind="created", user_id=user.id, note=f"chat:{message.id}"))
            work_kind = "task"
        else:
            row = DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code, title=title,
                summary="Учебный документ. Не является договором, заказом или актом реальной организации.",
                author_id=user.id, responsible_id=person_id, source_ref=f"chat:{message.id}",
                status="draft", confidentiality="company")
            db.add(row)
            await db.flush()
            db.add(DocRelation(company_id=cid, doc_id=row.id, target_ref=f"site:{site.id}", kind="basis", created_by=user.id))
            source = file_store.put(db, cid, f"УЧЕБНЫЙ ПРИМЕР\n{step['name']}\nДва устройства. Бюджет 480 000 рублей.\n{step['result']}\nДокумент подготовлен для демонстрации и не подписан.\n".encode("utf-8"),
                file_name=f"demo-procurement-{step['code']}.txt", mime="text/plain")
            await db.flush()
            await track_files.initial_version(db, cid, row, source, user)
            work_kind = "doc"
        guide.append({"stage": step["code"], "title": step["name"], "kind": work_kind, "id": str(row.id), "requirement": step["requirement"]})
    site.workspace_data = {**site.workspace_data, "demo": {"key": DEMO_KEY, "guide": guide, "room_id": str(room.id)},
        "next_ref": f"task:{guide[0]['id']}"}
    await db.commit()
    return {"site_id": str(site.id), "created": True}
