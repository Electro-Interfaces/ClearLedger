from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.models import App, Company, CompanyApp, EzsSite, TaskTemplate, User, UserCompany
from app.services import app_registry
from app.services.project_scenarios import SCENARIOS


class StepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    result: str = Field(min_length=3, max_length=300)
    requirement: Literal["done", "approved", "signed"]
    fields: list[str] = Field(default_factory=list, max_length=30)
    responsible_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    due_days: int | None = Field(None, ge=1, le=365)


class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    fields: dict[str, str] = Field(min_length=1, max_length=30)
    steps: list[StepDefinition] = Field(min_length=1, max_length=30)
    message_actions: list[Literal["discussion", "decision", "file"]] = Field(
        default_factory=lambda: ["discussion", "decision", "file"], max_length=3)

    @model_validator(mode="after")
    def validate_structure(self):
        import re
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key) or not label.strip() or len(label) > 120
               for key, label in self.fields.items()):
            raise ValueError("Укажите коды и названия полей сценария")
        codes = [step.code for step in self.steps]
        if len(codes) != len(set(codes)) or "done" in codes:
            raise ValueError("Коды этапов должны быть уникальны; код done зарезервирован")
        if any(set(step.fields) - self.fields.keys() for step in self.steps):
            raise ValueError("Обязательные поля этапов должны существовать в сценарии")
        if len(self.message_actions) != len(set(self.message_actions)):
            raise ValueError("Действия Чата не должны повторяться")
        return self


def builtin(kind):
    if kind not in SCENARIOS:
        raise HTTPException(404, "Сценарий не найден")
    return ScenarioDefinition.model_validate(SCENARIOS[kind]).model_dump(mode="json")


async def can_manage(db, cid, user):
    member = await db.get(UserCompany, (user.id, cid))
    return bool(user.is_superadmin or member and member.role == "admin")


async def app_config(db, cid, *, lock=False):
    if lock:
        await db.scalar(select(Company.id).where(Company.id == cid).with_for_update())
    app = await db.scalar(select(App).where(App.code == "projects"))
    if app is None:
        raise HTTPException(409, "Приложение «Проекты» отсутствует в каталоге пространства")
    query = select(CompanyApp).where(CompanyApp.company_id == cid, CompanyApp.app_id == app.id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    return app, row


def entry(row, kind):
    definition = builtin(kind)
    saved = ((row.config or {}).get("project_scenarios", {}).get(kind, {}) if row else {})
    return {"revision": 0, "version": 1, "published": definition, "draft": None, "history": [], **deepcopy(saved)}


async def readiness(db, cid, definition):
    checks = []
    apps = await app_registry.company_apps(db, cid)
    enabled = {app["code"] for app in apps if app["enabled"]}
    for code, label in [("projects", "Проекты"), ("docs", "Трек")]:
        checks.append({"key": code, "ok": code in enabled, "message": f"{label}: приложение подключено" if code in enabled else f"Подключите приложение «{label}»"})
    if definition.get("message_actions"):
        ready = "chat" in enabled
        checks.append({"key": "chat", "ok": ready, "message": "Чат доступен" if ready else "Включите Чат или уберите действия с сообщениями"})
    for step in definition["steps"]:
        if step.get("responsible_id"):
            uid = uuid.UUID(step["responsible_id"])
            person = await db.scalar(select(User).join(UserCompany, UserCompany.user_id == User.id)
                .where(User.id == uid, UserCompany.company_id == cid))
            ok = person is not None and not person.mail_only
            checks.append({"key": f"{step['code']}:person", "ok": ok,
                "message": f"{step['name']}: исполнитель доступен" if ok else f"{step['name']}: выберите сотрудника пространства"})
        if step.get("template_id"):
            template = await db.scalar(select(TaskTemplate).where(TaskTemplate.id == uuid.UUID(step["template_id"]), TaskTemplate.company_id == cid))
            ok = template is not None and (step["requirement"] == "done" or template.doc_kind_id is not None)
            checks.append({"key": f"{step['code']}:template", "ok": ok,
                "message": f"{step['name']}: шаблон доступен" if ok else f"{step['name']}: выберите доступный шаблон {'документа' if step['requirement'] != 'done' else 'Трека'}"})
    return {"ready": all(check["ok"] for check in checks), "checks": checks}


async def catalog(db, cid, user):
    _, row = await app_config(db, cid)
    items = []
    for kind in SCENARIOS:
        state = entry(row, kind)
        items.append({"kind": kind, **state, "readiness": await readiness(db, cid, state["draft"] or state["published"])})
    return {"can_manage": await can_manage(db, cid, user), "items": items}


async def save(db, cid, user, kind, expected_revision, definition=None, *, publish=False):
    if not await can_manage(db, cid, user):
        raise HTTPException(403, "Сценарии пространства настраивает администратор компании")
    app, row = await app_config(db, cid, lock=True)
    state = entry(row, kind)
    if state["revision"] != expected_revision:
        raise HTTPException(409, "Настройки уже изменены. Обновите сценарий перед сохранением")
    if publish:
        if state["draft"] is None:
            raise HTTPException(409, "Сначала сохраните черновик сценария")
        report = await readiness(db, cid, state["draft"])
        if not report["ready"]:
            raise HTTPException(409, "; ".join(c["message"] for c in report["checks"] if not c["ok"]))
        if len(state["history"]) >= 100:
            raise HTTPException(409, "Достигнут предел в 100 версий. Обратитесь к администратору поставки")
        projects = (await db.scalars(select(EzsSite).where(EzsSite.company_id == cid, EzsSite.kind == kind,
            EzsSite.workspace_data["scenario"]["definition"].astext.is_(None)).with_for_update())).all()
        for project in projects:
            data = deepcopy(project.workspace_data or {})
            data["scenario"] = {**data.get("scenario", {}), "version": 1, "definition": builtin(kind)}
            project.workspace_data = data
        state["history"].append({"version": state["version"], "definition": state["published"],
            "published_at": state.get("published_at"), "published_by": state.get("published_by")})
        state.update(version=state["version"] + 1, published=state["draft"], draft=None,
            published_at=datetime.now(timezone.utc).isoformat(), published_by=str(user.id))
    else:
        state["draft"] = definition.model_dump(mode="json")
    state["revision"] += 1
    state["updated_by"] = str(user.id)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if row is None:
        effective = next((a for a in await app_registry.company_apps(db, cid) if a["code"] == "projects"), None)
        row = CompanyApp(company_id=cid, app_id=app.id, enabled=bool(effective and effective["enabled"]))
        db.add(row)
    config = deepcopy(row.config or {})
    config.setdefault("project_scenarios", {})[kind] = state
    row.config = config
    await db.commit()
    return {"kind": kind, **state, "readiness": await readiness(db, cid, state["draft"] or state["published"])}


async def initialize(db, site):
    if site.kind not in SCENARIOS:
        return
    _, row = await app_config(db, site.company_id, lock=True)
    state = entry(row, site.kind)
    site.workspace_data = {**(site.workspace_data or {}), "scenario": {
        "version": state["version"], "definition": state["published"],
        "stage": state["published"]["steps"][0]["code"], "fields": {}, "templates": {}, "evidence": {}}}
