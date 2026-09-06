from copy import deepcopy
import uuid

import pytest
from sqlalchemy import select

from app.auth import create_access_token
from app.models import App, Company, CompanyApp, EzsSite, User, UserCompany
from app.services.project_scenarios import scenario
from app.services.project_scenario_settings import builtin
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def setup(auth_client, db):
    from app.services.app_registry import seed_apps
    await seed_apps(db)
    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    app = await db.scalar(select(App).where(App.code == "projects"))
    row = await db.scalar(select(CompanyApp).where(CompanyApp.company_id == cid, CompanyApp.app_id == app.id))
    if row is None:
        row = CompanyApp(company_id=cid, app_id=app.id, enabled=True)
        db.add(row)
    row.enabled = True
    row.config = {"name": "Проекты", "project_scenarios": {}}
    await db.commit()
    return cid, uuid.UUID(me["id"])


async def test_публикация_фиксирует_старые_проекты_и_новую_версию(auth_client, db):
    cid, uid = await setup(auth_client, db)
    old = EzsSite(company_id=cid, title="Старый проект", kind="procurement",
        workspace_data={"budget": 100, "scenario": {"stage": "order", "fields": {"supplier": "Поставщик"}}})
    db.add(old)
    await db.commit()
    definition = builtin("procurement")
    definition["steps"][0].update(name="Заявка на закупку", due_days=3, responsible_id=str(uid))
    definition["message_actions"] = ["decision"]
    params = {"company_id": str(cid)}
    url = "/api/project-scenarios/procurement"
    draft = await auth_client.put(url + "/draft", params=params, json={"expected_revision": 0, "definition": definition})
    assert draft.status_code == 200, draft.text
    assert draft.json()["version"] == 1
    response = await auth_client.post(url + "/publish", params=params, json={"expected_revision": 1})
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    await db.refresh(old)
    assert scenario(old)["steps"][0]["name"] == "Потребность"
    assert scenario(old)["stage"] == "order" and old.workspace_data["budget"] == 100
    fresh = await auth_client.post("/api/sites", params=params, json={"kind": "procurement", "title": "Новая закупка", "city": "Учебный город"})
    assert fresh.status_code == 201, fresh.text
    sid = fresh.json()["id"]
    overview = await auth_client.get(f"/api/project-workspace/{sid}", params=params)
    assert overview.json()["scenario"]["version"] == 2
    context = await auth_client.get("/api/work-contexts/resolve", params={**params, "ref": f"site:{sid}"})
    assert context.status_code == 200, context.text
    assert context.json()["defaults"]["due_days"] == 3
    assert [action["code"] for action in context.json()["actions"]] == ["decision"]
    changed = deepcopy(definition)
    changed["steps"][0]["name"] = "Изменённый этап"
    await auth_client.put(url + "/draft", params=params, json={"expected_revision": 2, "definition": changed})
    published = await auth_client.post(url + "/publish", params=params, json={"expected_revision": 3})
    assert published.status_code == 200, published.text
    project = await db.get(EzsSite, uuid.UUID(sid))
    await db.refresh(project)
    assert scenario(project)["version"] == 2 and scenario(project)["steps"][0]["name"] == "Заявка на закупку"


async def test_конфликт_черновиков_и_недоступные_ссылки(auth_client, db):
    cid, _ = await setup(auth_client, db)
    params = {"company_id": str(cid)}
    url = "/api/project-scenarios/warehouse"
    definition = builtin("warehouse")
    definition["steps"][0]["responsible_id"] = str(uuid.uuid4())
    first = await auth_client.put(url + "/draft", params=params, json={"expected_revision": 0, "definition": definition})
    assert first.status_code == 200 and not first.json()["readiness"]["ready"]
    conflict = await auth_client.put(url + "/draft", params=params, json={"expected_revision": 0, "definition": builtin("warehouse")})
    assert conflict.status_code == 409
    blocked = await auth_client.post(url + "/publish", params=params, json={"expected_revision": 1})
    assert blocked.status_code == 409
    duplicate = builtin("warehouse")
    duplicate["steps"][1]["code"] = duplicate["steps"][0]["code"]
    invalid = await auth_client.put(url + "/draft", params=params, json={"expected_revision": 1, "definition": duplicate})
    assert invalid.status_code == 422


async def test_обычный_сотрудник_читает_но_не_публикует(auth_client, db):
    cid, _ = await setup(auth_client, db)
    person = User(email=f"scenario-{uuid.uuid4().hex}@example.test", name="Исполнитель", password_hash="unused", company_id=cid)
    db.add(person)
    await db.flush()
    db.add(UserCompany(user_id=person.id, company_id=cid, role="member"))
    await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(str(person.id), person.email)}"}
    params = {"company_id": str(cid)}
    view = await auth_client.get("/api/project-scenarios", params=params, headers=headers)
    assert view.status_code == 200 and not view.json()["can_manage"]
    denied = await auth_client.put("/api/project-scenarios/procurement/draft", params=params, headers=headers,
        json={"expected_revision": 0, "definition": builtin("procurement")})
    assert denied.status_code == 403
    other = await db.scalar(select(Company.id).where(Company.id != cid).limit(1))
    cross = await auth_client.get("/api/project-scenarios", params={"company_id": str(other)}, headers=headers)
    assert cross.status_code == 403


async def test_чтение_сценариев_не_создаёт_настройки(auth_client, db):
    cid, _ = await setup(auth_client, db)
    app_id = await db.scalar(select(App.id).where(App.code == "projects"))
    row = await db.scalar(select(CompanyApp).where(CompanyApp.company_id == cid, CompanyApp.app_id == app_id))
    before = deepcopy(row.config)
    response = await auth_client.get("/api/project-scenarios", params={"company_id": str(cid)})
    assert response.status_code == 200
    await db.refresh(row)
    assert row.config == before


async def test_учебный_пример_закрыт_на_обычном_стеке_и_не_дублируется(auth_client, db, monkeypatch):
    from app.models import DocCard, DocRelation, DocVersion, Task
    cid, uid = await setup(auth_client, db)
    user = await db.get(User, uid)
    params = {"company_id": str(cid)}
    monkeypatch.delenv("DEMO_SPACE_USER", raising=False)
    denied = await auth_client.post("/api/project-scenarios/demo", params=params)
    assert denied.status_code == 404
    monkeypatch.setenv("DEMO_SPACE_USER", user.email)
    user.company_id = cid
    await db.commit()
    first = await auth_client.post("/api/project-scenarios/demo", params=params)
    assert first.status_code == 200, first.text
    second = await auth_client.post("/api/project-scenarios/demo", params=params)
    assert second.status_code == 200, second.text
    assert first.json()["site_id"] == second.json()["site_id"] and not second.json()["created"]
    project = await db.get(EzsSite, uuid.UUID(first.json()["site_id"]))
    assert scenario(project)["stage"] == "need"
    guide = project.workspace_data["demo"]["guide"]
    assert len(guide) == 5
    for work in guide:
        row = await db.get(Task if work["kind"] == "task" else DocCard, uuid.UUID(work["id"]))
        assert row.company_id == cid
        if work["kind"] == "task":
            assert row.subject_ref == f"site:{project.id}"
        else:
            assert await db.scalar(select(DocRelation.id).where(DocRelation.doc_id == row.id, DocRelation.target_ref == f"site:{project.id}"))
        assert row.status in ("open", "draft")
        if work["kind"] == "doc":
            assert await db.scalar(select(DocVersion.id).where(DocVersion.doc_id == row.id))
        origin = await auth_client.get(f"/api/work-contexts/work/{work['kind']}/{work['id']}/origin", params=params)
        assert origin.status_code == 200 and origin.json()["origin"]["message_id"]
        accept = {"fields": {}, "advance": True, "expected_stage": work["stage"],
                  "evidence": {"kind": work["kind"], "id": work["id"]}}
        stage_url = f"/api/project-workspace/{project.id}/scenario"
        unfinished = await auth_client.put(stage_url, params=params, json=accept)
        assert unfinished.status_code == 409, unfinished.text
        if work["kind"] == "task":
            finished = await auth_client.post(f"/api/tasks/{row.id}/action", json={"company_id": str(cid), "status": "done", "note": "Учебный результат проверен"})
            assert finished.status_code == 200, finished.text
        else:
            if work["requirement"] == "signed":
                row.signatory_id = uid
                await db.commit()
            registered = await auth_client.post(f"/api/docs/{row.id}/register", json={"company_id": str(cid)})
            assert registered.status_code == 200, registered.text
            start = await auth_client.post(f"/api/docs/{row.id}/approval/start", json={"company_id": str(cid), "route": [{
                "code": "check", "name": "Учебное подписание" if work["requirement"] == "signed" else "Учебное согласование",
                "step_kind": "sign" if work["requirement"] == "signed" else "approve", "mode": "serial", "quorum": "all",
                "actors": [{"by": "user", "ref": str(uid)}]}]})
            assert start.status_code == 201, start.text
            mine = (await auth_client.get("/api/docs/approvals/mine", params=params)).json()["approvals"]
            approval = next(item for item in mine if item["doc_id"] == str(row.id))
            vote = await auth_client.post(f"/api/docs/approvals/{approval['id']}", json={"company_id": str(cid), "approved": True})
            assert vote.status_code == 200, vote.text
        accepted = await auth_client.put(stage_url, params=params, json=accept)
        assert accepted.status_code == 200, accepted.text
    finished_project = await auth_client.get(f"/api/project-workspace/{project.id}", params=params)
    assert finished_project.json()["scenario"]["stage"] == "done"
    assert len(finished_project.json()["scenario"]["evidence"]) == 5
