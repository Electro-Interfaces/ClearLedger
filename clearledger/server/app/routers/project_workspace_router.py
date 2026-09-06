from datetime import date, datetime, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (ApprovalRequest, ChatMessage, ChatParticipant, ChatRoom, DocCard,
    DocKind, DocRelation, DocVersion, EzsSite, EzsSiteDoc, EzsSiteEvent, EzsSiteParticipant,
    TaskEvent, User, UserCompany, WorkContextResult)
from app.services import ezs_site_work, track_files, project_scenarios, project_work

router = APIRouter(prefix="/project-workspace", tags=["Работа проекта"])


async def owned(db, cid, sid, *, lock=False):
    query = select(EzsSite).where(EzsSite.id == sid, EzsSite.company_id == cid)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "Проект не найден")
    return row


async def source_message(db, cid, user, mid):
    from app.routers.chat_router import _assert_participant, _history_from
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.deleted_at:
        raise HTTPException(404, "Сообщение не найдено")
    room = await _assert_participant(msg.room_id, user, db)
    since = await _history_from(msg.room_id, user, db)
    if since and msg.created_at < since:
        raise HTTPException(404, "Сообщение не найдено")
    if room.company_id != cid:
        raise HTTPException(404, "Сообщение не найдено")
    return msg


@router.get("/unlinked")
async def unlinked(company_id: str, q: str = Query("", max_length=200),
                   only_unlinked: bool = Query(True),
                   offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100),
                   user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    return await project_work.listing(db, cid, user, unlinked=only_unlinked, q=q, offset=offset, limit=limit)


@router.get("/work/{kind}/{entity_id}/origin")
async def origin(kind: Literal["doc", "task"], entity_id: uuid.UUID, company_id: str,
                 user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    return {"origin": await project_work.origin(db, cid, user, kind, entity_id)}


@router.get("/{sid}")
async def overview(sid: uuid.UUID, company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid)
    data = dict(site.workspace_data or {})
    track = await project_work.listing(db, cid, user, site=site, scope="open", limit=8)
    pending = await project_work.listing(db, cid, user, site=site, scope="pending", limit=8)
    next_work = None
    if data.get("next_ref"):
        kind, eid = data["next_ref"].split(":", 1)
        try:
            row = await project_work.readable_entity(db, cid, user, kind, uuid.UUID(eid))
            next_work = {"id": str(row.id), "kind": kind, "title": row.title, "due_at": row.due_at,
                         "status": row.status}
        except HTTPException:
            next_work = {"unavailable": True}
    team = (await db.execute(select(User.id, User.name, EzsSiteParticipant.role_code)
        .join(EzsSiteParticipant, EzsSiteParticipant.user_id == User.id)
        .where(EzsSiteParticipant.site_id == sid, EzsSiteParticipant.company_id == cid))).all()
    events = (await db.execute(select(EzsSiteEvent, User.name).outerjoin(User,
        EzsSiteEvent.author_user_id == User.id).where(EzsSiteEvent.company_id == cid,
        EzsSiteEvent.site_id == sid, EzsSiteEvent.kind.in_(("decision", "discussion", "result", "scenario")))
        .order_by(EzsSiteEvent.created_at.desc()).limit(30))).all()
    unread = await db.scalar(select(func.count(ChatMessage.id)).join(ChatRoom,
        ChatRoom.id == ChatMessage.room_id).join(ChatParticipant, and_(
        ChatParticipant.room_id == ChatRoom.id, ChatParticipant.user_id == user.id)).where(
        ChatRoom.company_id == cid, ChatRoom.scope_ref == f"site:{sid}", ChatRoom.is_active.is_(True),
        ChatMessage.deleted_at.is_(None), ChatMessage.user_id != user.id,
        or_(ChatParticipant.history_from.is_(None), ChatMessage.created_at >= ChatParticipant.history_from),
        or_(ChatParticipant.last_read_at.is_(None), ChatMessage.created_at > ChatParticipant.last_read_at)))
    return {"work": track, "pending_results": pending, "next_work": next_work, "external_wait": data.get("external_wait"),
        "scenario": project_scenarios.scenario(site), "demo": data.get("demo"), "unread": unread,
        "target_date": data.get("target_date"), "budget": data.get("budget"),
        "team": [{"id": str(uid), "name": name, "role": role} for uid, name, role in team],
        "events": [{"id": str(e.id), "kind": e.kind, "text": e.text, "author": name,
                    "at": e.created_at, "changes": e.changes} for e, name in events]}


class LinkBody(BaseModel):
    kind: Literal["doc", "task", "message"]
    id: uuid.UUID


@router.post("/{sid}/link")
async def link(sid: uuid.UUID, body: LinkBody, company_id: str,
               user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    ref = f"site:{sid}"
    if body.kind == "message":
        msg = await source_message(db, cid, user, body.id)
        previous = await db.scalar(select(EzsSiteEvent.id).where(
            EzsSiteEvent.site_id == sid, EzsSiteEvent.kind == "discussion",
            EzsSiteEvent.changes.contains([{"message_id": str(msg.id)}])))
        if previous is None:
            await ezs_site_work.log_event(db, site, "discussion", text="Привязано обсуждение", user=user,
                changes=[{"room_id": str(msg.room_id), "message_id": str(msg.id)}])
    else:
        row = await project_work.readable_entity(db, cid, user, body.kind, body.id, edit=True)
        if body.kind == "task":
            if row.subject_ref and row.subject_ref != ref:
                raise HTTPException(409, "У поручения уже есть предмет. Измените его в карточке поручения")
            if row.subject_ref != ref:
                row.subject_ref = ref
                db.add(TaskEvent(task_id=row.id, kind="edit", user_id=user.id,
                                  to_value=ref, note="Привязано к проекту"))
        elif not await db.scalar(select(DocRelation.id).where(DocRelation.company_id == cid,
                DocRelation.doc_id == row.id, DocRelation.target_ref == ref, DocRelation.kind == "basis")):
            db.add(DocRelation(company_id=cid, doc_id=row.id, target_ref=ref, kind="basis", created_by=user.id))
        await ezs_site_work.log_event(db, site, "note", text="Связана работа Трека", user=user,
                                      changes=[{"work_ref": f"{body.kind}:{body.id}"}])
    await db.commit()
    return {"ok": True}


class NextBody(BaseModel):
    work: LinkBody | None = None
    waiting_for: str | None = Field(None, max_length=300)
    owner_id: uuid.UUID | None = None
    follow_up: date | None = None


@router.put("/{sid}/next")
async def next_action(sid: uuid.UUID, body: NextBody, company_id: str,
                      user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    data = dict(site.workspace_data or {})
    if body.work:
        if body.work.kind == "message":
            raise HTTPException(400, "Следующий результат — поручение или документ")
        row = await project_work.readable_entity(db, cid, user, body.work.kind, body.work.id)
        if not await db.scalar(select(row.__class__.id).where(row.__class__.id == row.id,
                project_work.project_clause(row.__class__, cid, f"site:{sid}"))):
            raise HTTPException(400, "Сначала свяжите работу с проектом")
        data["next_ref"] = f"{body.work.kind}:{body.work.id}"
        data.pop("external_wait", None)
    elif body.waiting_for:
        if not body.owner_id or not body.follow_up or not await db.get(UserCompany, (body.owner_id, cid)):
            raise HTTPException(400, "Укажите ответственного из пространства и дату следующего контакта")
        person = await db.get(User, body.owner_id)
        data["external_wait"] = {"waiting_for": body.waiting_for, "owner_id": str(body.owner_id),
                                 "owner_name": person.name, "follow_up": body.follow_up.isoformat()}
        data.pop("next_ref", None)
    else:
        data.pop("next_ref", None)
        data.pop("external_wait", None)
    site.workspace_data = data
    if body.work or body.waiting_for:
        site.next_action = None
        site.next_action_due = None
    await ezs_site_work.log_event(db, site, "note", text="Обновлён следующий результат проекта", user=user)
    await db.commit()
    return {"ok": True}


class DecisionBody(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    source_message_id: uuid.UUID | None = None
    work: LinkBody | None = None
    deadline: date | None = None
    budget: float | None = Field(None, ge=0, allow_inf_nan=False)


@router.post("/{sid}/decision", status_code=201)
async def decision(sid: uuid.UUID, body: DecisionBody, company_id: str,
                   user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    details = {}
    if body.source_message_id:
        msg = await source_message(db, cid, user, body.source_message_id)
        details.update(room_id=str(msg.room_id), message_id=str(msg.id))
    if body.work:
        if body.work.kind == "message":
            raise HTTPException(400, "Укажите поручение или документ")
        row = await project_work.readable_entity(db, cid, user, body.work.kind, body.work.id)
        if not await db.scalar(select(row.__class__.id).where(row.__class__.id == row.id,
                project_work.project_clause(row.__class__, cid, f"site:{sid}"))):
            raise HTTPException(400, "Сначала свяжите работу с проектом")
        details["work_ref"] = f"{body.work.kind}:{body.work.id}"
    if body.deadline or body.budget is not None:
        data = dict(site.workspace_data or {})
        if body.deadline:
            details["deadline"] = {"from": data.get("target_date"), "to": body.deadline.isoformat()}
            data["target_date"] = body.deadline.isoformat()
        if body.budget is not None:
            details["budget"] = {"from": data.get("budget"), "to": body.budget}
            data["budget"] = body.budget
        site.workspace_data = data
    event = await ezs_site_work.log_event(db, site, "decision", text=body.text.strip(), user=user, changes=[details])
    await db.commit()
    return {"id": str(event.id)}


@router.post("/{sid}/chat")
async def main_chat(sid: uuid.UUID, company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    from app.services.context_chats import ensure_room
    cid = await assert_company_member(company_id, user, db)
    await owned(db, cid, sid)
    room = await ensure_room(db, cid, user, f"site:{sid}", purpose="main", audience="internal")
    await db.commit()
    return {"room_id": str(room.id)}


class FileBody(BaseModel):
    message_id: uuid.UUID
    kind: str = Field("other", max_length=24)


@router.post("/{sid}/file", status_code=201)
async def attach_file(sid: uuid.UUID, body: FileBody, company_id: str,
                      user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    msg = await source_message(db, cid, user, body.message_id)
    source = await track_files.message_file(db, cid, msg)
    if source is None:
        raise HTTPException(400, "В сообщении нет файла")
    row = await db.scalar(select(EzsSiteDoc).where(EzsSiteDoc.site_id == sid, EzsSiteDoc.file_id == source.id))
    if row is None:
        row = EzsSiteDoc(company_id=cid, site_id=sid, file_id=source.id, kind=body.kind,
                        title=source.file_name[:300], stage=site.stage, uploaded_by=user.id,
                        note=f"chat:{msg.id}")
        db.add(row)
        await ezs_site_work.log_event(db, site, "note", text="Добавлен файл из обсуждения", user=user,
            changes=[{"room_id": str(msg.room_id), "message_id": str(msg.id)}])
    await db.commit()
    return {"id": str(row.id)}


class PromoteBody(BaseModel):
    file_id: uuid.UUID
    kind_id: uuid.UUID
    title: str = Field(min_length=3, max_length=300)


@router.post("/{sid}/promote", status_code=201)
async def promote(sid: uuid.UUID, body: PromoteBody, company_id: str,
                  user=Depends(get_current_user), db=Depends(get_db)):
    from app.models import SourceFile, DocEvent
    from app.services.process_templates import can_launch_kind
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    link = await db.scalar(select(EzsSiteDoc).where(EzsSiteDoc.company_id == cid,
        EzsSiteDoc.site_id == sid, EzsSiteDoc.id == body.file_id))
    source = await db.get(SourceFile, link.file_id) if link and link.file_id else None
    kind = await db.get(DocKind, body.kind_id)
    if source is None or source.company_id != cid or kind is None or kind.company_id != cid or not kind.is_active:
        raise HTTPException(404, "Файл или вид документа не найден")
    if not await can_launch_kind(db, cid, kind.id, user):
        raise HTTPException(403, "Недостаточно прав на этот вид документа")
    source_ref = f"site-file:{link.id}"
    old = await db.scalar(select(DocCard).where(DocCard.company_id == cid, DocCard.source_ref == source_ref))
    if old:
        await project_work.readable_entity(db, cid, user, "doc", old.id)
        return {"doc_id": str(old.id)}
    doc = DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code, family=kind.family,
        direction=kind.direction, title=body.title, author_id=user.id, responsible_id=user.id,
        source="api", source_ref=source_ref)
    db.add(doc)
    await db.flush()
    await track_files.initial_version(db, cid, doc, source, user)
    db.add(DocRelation(company_id=cid, doc_id=doc.id, kind="basis", target_ref=f"site:{sid}", created_by=user.id))
    db.add(DocEvent(doc_id=doc.id, kind="created", user_id=user.id, actor_name=user.name,
                    note="Оформлен из файла проекта"))
    await db.commit()
    return {"doc_id": str(doc.id)}


@router.post("/{sid}/retry/{request_id}")
async def retry(sid: uuid.UUID, request_id: uuid.UUID, company_id: str,
                user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    await owned(db, cid, sid)
    request = await db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.id == request_id, ApprovalRequest.company_id == cid).with_for_update())
    if request is None:
        request = await db.scalar(select(WorkContextResult).where(WorkContextResult.id == request_id,
            WorkContextResult.company_id == cid, WorkContextResult.context_ref == f"site:{sid}").with_for_update())
        if request is None:
            raise HTTPException(404, "Возврат результата не найден")
        await project_work.readable_entity(db, cid, user, request.work_kind, request.entity_id, edit=True)
        if request.delivered_at:
            raise HTTPException(409, "Результат уже доставлен")
        request.attempts = 0
        request.last_error = None
        await db.commit()
        return {"ok": True}
    kind, eid = ("doc", request.doc_id) if request.doc_id else ("task", request.task_id)
    row = await project_work.readable_entity(db, cid, user, kind, eid, edit=True)
    if not await db.scalar(select(row.__class__.id).where(row.__class__.id == row.id,
            project_work.project_clause(row.__class__, cid, f"site:{sid}"))):
        raise HTTPException(404, "Возврат результата не найден в проекте")
    if not request.outcome or request.delivered_at:
        raise HTTPException(409, "Результат ещё не принят или уже доставлен")
    request.attempts = 0
    request.last_error = None
    await ezs_site_work.log_event(db, await owned(db, cid, sid), "result",
                                 text="Запрошен повтор возврата результата", user=user)
    await db.commit()
    return {"ok": True}


class ScenarioBody(BaseModel):
    templates: dict[str, uuid.UUID | None] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    advance: bool = False
    expected_stage: str | None = None
    evidence: LinkBody | None = None


@router.put("/{sid}/scenario")
async def update_scenario(sid: uuid.UUID, body: ScenarioBody, company_id: str,
                          user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    site = await owned(db, cid, sid, lock=True)
    spec = project_scenarios.scenario(site)
    if spec is None:
        raise HTTPException(400, "Проект использует основной маршрут")
    project_scenarios.validate_fields(spec, body.fields)
    templates = dict(spec["templates"])
    if set(body.templates) - {s["code"] for s in spec["steps"]}:
        raise HTTPException(400, "Неизвестный этап сценария")
    from app.models import TaskTemplate
    for code, tid in body.templates.items():
        if tid is None:
            templates[code] = None
        else:
            template = await db.get(TaskTemplate, tid)
            if template is None or template.company_id != cid:
                raise HTTPException(404, "Шаблон Трека не найден")
            step_spec = next(s for s in spec["steps"] if s["code"] == code)
            if step_spec["requirement"] != "done" and template.doc_kind_id is None:
                raise HTTPException(400, "Для этого этапа нужен шаблон документа")
            templates[code] = str(tid)
    values = {**spec["values"], **body.fields}
    stage, evidence = spec["stage"], dict(spec["evidence"])
    if body.advance:
        member = await db.get(UserCompany, (user.id, cid))
        if not user.is_superadmin and site.owner_user_id != user.id and (member is None or member.role != "admin"):
            raise HTTPException(403, "Результат этапа принимает ответственный проекта или администратор")
        if body.expected_stage != stage:
            raise HTTPException(409, "Этап уже изменился. Обновите проект")
        step = next((s for s in spec["steps"] if s["code"] == stage), None)
        if step is None or body.evidence is None or body.evidence.kind == "message":
            raise HTTPException(400, "Выберите работу, подтверждающую результат этапа")
        if any(not values.get(key, "").strip() for key in step.get("fields", [])):
            raise HTTPException(400, "Заполните обязательные поля этапа")
        row = await project_work.readable_entity(db, cid, user, body.evidence.kind, body.evidence.id)
        if not await db.scalar(select(row.__class__.id).where(row.__class__.id == row.id,
                project_work.project_clause(row.__class__, cid, f"site:{sid}"))):
            raise HTTPException(400, "Подтверждающая работа должна быть связана с проектом")
        signed = False
        if body.evidence.kind == "doc":
            signed = await track_files.signed_current(db, row)
        if not project_scenarios.evidence_satisfies(body.evidence.kind, row, step["requirement"], signed=signed):
            raise HTTPException(409, "Работа ещё не подтверждает требуемый результат этапа")
        ref = f"{body.evidence.kind}:{body.evidence.id}"
        evidence[stage] = {"ref": ref, "by": str(user.id), "at": datetime.now(timezone.utc).isoformat(),
                           "revision": getattr(row, "current_revision", None)}
        index = spec["steps"].index(step)
        stage = spec["steps"][index + 1]["code"] if index + 1 < len(spec["steps"]) else "done"
        await ezs_site_work.log_event(db, site, "scenario", text=step["result"], user=user,
            changes=[{"work_ref": ref, "from": spec["stage"], "to": stage}])
    definition = {key: spec[key] for key in ("name", "fields", "steps", "message_actions") if key in spec}
    site.workspace_data = {**(site.workspace_data or {}), "scenario": {
        "definition": definition, "version": spec["version"],
        "stage": stage, "fields": values, "templates": templates, "evidence": evidence}}
    await db.commit()
    return {"ok": True, "scenario": project_scenarios.scenario(site)}
