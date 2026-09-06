import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.models import EzsSite, EzsSiteEvent, EzsSiteParticipant, User, UserCompany
from app.services import ezs_sites, project_scenarios


class ProjectsContext:
    prefix = "site"
    application = "projects"
    label = "Проекты"

    async def search(self, db, cid, user, q):
        result = await ezs_sites.list_sites(db, cid, search=q, page_size=20)
        return [{"ref": f"site:{s['id']}", "title": f"{s.get('projectNo') or ''} · {s.get('title') or s.get('city') or 'Проект'}",
                 "hint": s.get("address") or s.get("fullAddress") or ""} for s in result["items"]]

    async def resolve(self, db, cid, user, key):
        try:
            sid = uuid.UUID(key)
        except ValueError:
            raise HTTPException(404, "Проект не найден") from None
        site = await db.scalar(select(EzsSite).where(EzsSite.id == sid, EzsSite.company_id == cid))
        if site is None:
            raise HTTPException(404, "Проект не найден")
        scenario = project_scenarios.scenario(site)
        step = next((s for s in scenario["steps"] if s["code"] == scenario["stage"]), None) if scenario else None
        team_ids = set((await db.scalars(select(EzsSiteParticipant.user_id).where(
            EzsSiteParticipant.company_id == cid, EzsSiteParticipant.site_id == sid,
            EzsSiteParticipant.user_id.is_not(None)))).all())
        if site.owner_user_id:
            team_ids.add(site.owner_user_id)
        people = (await db.scalars(select(User).join(UserCompany, UserCompany.user_id == User.id)
            .where(User.id.in_(team_ids), UserCompany.company_id == cid))).all() if team_ids else []
        from app.routers.chat_router import _is_insider
        suggestions = []
        for person in people:
            if not person.mail_only and await _is_insider(person, cid):
                suggestions.append({"id": str(person.id), "name": person.name})
        responsible_id = step.get("responsible_id") if step else None
        if responsible_id and not await db.get(UserCompany, (uuid.UUID(responsible_id), cid)):
            responsible_id = None
        actions = [{"code": "discussion", "label": "Добавить обсуждение в проект"},
                   {"code": "decision", "label": "Зафиксировать решение", "text_required": True},
                   {"code": "file", "label": "Добавить файл в документы проекта", "requires_file": True}]
        if scenario and "message_actions" in scenario:
            actions = [action for action in actions if action["code"] in scenario["message_actions"]]
        return {"ref": f"site:{sid}", "application": self.application,
            "title": f"{site.project_no or ''} · {site.title or site.city or 'Проект'}",
            "url": f"/projects?mode=projects&sub=pr_project&project={sid}&ptab=overview", "object_id": site.location_id,
            "suggested_people": suggestions,
            "defaults": {"responsible_id": responsible_id or (str(site.owner_user_id) if site.owner_user_id else None),
                         "due_days": step.get("due_days") if step else None,
                         "title": step["result"] if step else None,
                         "template_ids": [scenario["templates"][step["code"]]] if step and scenario["templates"].get(step["code"]) else []},
            "actions": actions}

    async def execute(self, db, cid, user, key, body):
        context = await self.resolve(db, cid, user, key)
        if body.action not in {action["code"] for action in context["actions"]}:
            raise HTTPException(403, "Действие отключено в сценарии приложения")
        from app.routers import project_workspace_router as projects
        sid = uuid.UUID(key)
        if body.action == "file":
            return await projects.attach_file(sid, projects.FileBody(message_id=body.message_id), str(cid), user, db)
        if body.action == "decision":
            if len((body.text or "").strip()) < 3:
                raise HTTPException(400, "Сформулируйте решение")
            return await projects.decision(sid, projects.DecisionBody(text=body.text, source_message_id=body.message_id), str(cid), user, db)
        return await projects.link(sid, projects.LinkBody(kind="message", id=body.message_id), str(cid), user, db)

    async def result(self, db, cid, key, work_ref, outcome, result_key):
        sid = uuid.UUID(key)
        site = await db.scalar(select(EzsSite).where(EzsSite.id == sid, EzsSite.company_id == cid).with_for_update())
        if site is None:
            return
        if await db.scalar(select(EzsSiteEvent.id).where(EzsSiteEvent.site_id == sid,
                EzsSiteEvent.kind == "result", EzsSiteEvent.changes.contains([{"result_key": result_key}]))):
            return
        from app.services.ezs_site_work import log_event
        await log_event(db, site, "result", text="Результат работы принят" if outcome in ("done", "approved") else "Работа отклонена или отменена",
                        source="track", changes=[{"work_ref": work_ref, "outcome": outcome, "result_key": result_key}])
