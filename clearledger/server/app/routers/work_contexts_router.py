import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import ApprovalRequest, ChatMessage, DocCard, Task, TaskEvent, WorkContextResult
from app.services import work_contexts, work_links, work_state

router = APIRouter(prefix="/work-contexts", tags=["Контекст общей работы"])


@router.get("")
async def providers(company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    await assert_company_member(company_id, user, db)
    return {"providers": [{"prefix": p.prefix, "label": p.label, "application": p.application}
                          for p in work_contexts.providers()]}


@router.get("/search")
async def search(company_id: str, prefix: str, q: str = Query("", max_length=200),
                 user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    provider, _ = work_contexts.provider_for(prefix + ":search")
    return {"items": await provider.search(db, cid, user, q)}


@router.get("/resolve")
async def resolve(company_id: str, ref: str = Query(..., max_length=120),
                  user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    return await work_contexts.resolve(db, cid, user, ref)


class ActionBody(BaseModel):
    ref: str = Field(max_length=120)
    action: str = Field(max_length=80)
    message_id: uuid.UUID
    text: str | None = Field(None, max_length=4000)


@router.post("/action")
async def action(body: ActionBody, company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    provider, key = work_contexts.provider_for(body.ref)
    context = await provider.resolve(db, cid, user, key)
    if body.action not in {a["code"] for a in context.get("actions", [])}:
        raise HTTPException(400, "Действие не поддерживается приложением")
    return await provider.execute(db, cid, user, key, body)


@router.get("/work/{kind}/{entity_id}/origin")
async def origin(kind: str, entity_id: uuid.UUID, company_id: str,
                 user=Depends(get_current_user), db=Depends(get_db)):
    if kind not in ("doc", "task"):
        raise HTTPException(400, "Неизвестный вид работы")
    cid = await assert_company_member(company_id, user, db)
    return {"origin": await work_links.origin(db, cid, user, kind, entity_id)}


@router.get("/rooms/{room_id}/work")
async def room_work(room_id: uuid.UUID, company_id: str, messages: str = Query("", max_length=7500),
                    user=Depends(get_current_user), db=Depends(get_db)):
    from app.routers.chat_router import _assert_participant, _history_from
    cid = await assert_company_member(company_id, user, db)
    room = await _assert_participant(room_id, user, db)
    if room.company_id != cid:
        raise HTTPException(404, "Чат не найден")
    try:
        ids = [uuid.UUID(x) for x in messages.split(",") if x][:200]
    except ValueError:
        raise HTTPException(400, "Неверный идентификатор сообщения") from None
    since = await _history_from(room_id, user, db)
    allowed = (await db.execute(select(ChatMessage.id).where(ChatMessage.room_id == room_id,
        ChatMessage.id.in_(ids), ChatMessage.deleted_at.is_(None),
        ChatMessage.created_at >= since if since else True))).scalars().all()
    if not allowed:
        return {"items": []}
    prefixes = [f"chat:{mid}:%" for mid in allowed]
    visible = await work_links.visible_work(db, cid, user)
    task_sources = (await db.execute(select(TaskEvent.task_id, TaskEvent.note, TaskEvent.from_value)
        .join(Task, Task.id == TaskEvent.task_id).where(Task.company_id == cid,
        TaskEvent.kind == "created", or_(*[or_(TaskEvent.note.like(p), TaskEvent.from_value.like(p)) for p in prefixes])))).all()
    doc_sources = (await db.execute(select(DocCard.id, DocCard.source_ref).where(
        DocCard.company_id == cid, or_(*[DocCard.source_ref.like(p) for p in prefixes])))).all()
    sources = {("doc", did): ref for did, ref in doc_sources}
    for tid, note, previous in task_sources:
        sources[("task", tid)] = note if note and note.startswith("chat:") else previous
    if not sources:
        return {"items": []}
    rows = (await db.execute(select(visible).where(or_(*[
        and_(visible.c.kind == kind, visible.c.id == eid) for kind, eid in sources])))).mappings().all()
    return {"items": [{"id": str(r["id"]), "kind": r["kind"], "title": r["title"],
        "state": r["state"], "state_name": work_state.COLUMN_NAMES.get(r["state"], r["state"]),
        "message_id": sources[(r["kind"], r["id"])].split(":")[1]} for r in rows]}


@router.get("/work/{kind}/{entity_id}/results")
async def work_results(kind: str, entity_id: uuid.UUID, company_id: str,
                       user=Depends(get_current_user), db=Depends(get_db)):
    if kind not in ("doc", "task"):
        raise HTTPException(400, "Неизвестный вид работы")
    cid = await assert_company_member(company_id, user, db)
    await work_links.readable_entity(db, cid, user, kind, entity_id)
    rows = (await db.scalars(select(WorkContextResult).where(WorkContextResult.company_id == cid,
        WorkContextResult.work_kind == kind, WorkContextResult.entity_id == entity_id)
        .order_by(WorkContextResult.created_at.desc()).limit(30))).all()
    items = []
    contexts = {}
    for row in rows:
        if row.context_ref not in contexts:
            try:
                contexts[row.context_ref] = await work_contexts.resolve(db, cid, user, row.context_ref)
            except HTTPException:
                contexts[row.context_ref] = None
        context = contexts[row.context_ref]
        items.append({"id": str(row.id), "title": context["title"] if context else "Связанное приложение",
            "url": context["url"] if context else None, "outcome": row.outcome,
            "pending": row.delivered_at is None, "error": bool(row.last_error),
            "attempts": row.attempts, "created_at": row.created_at, "delivered_at": row.delivered_at})
    return {"items": items}


class ContextRoomBody(BaseModel):
    ref: str = Field(max_length=120)
    purpose: str = Field("main", pattern="^[a-z][a-z0-9_]{0,39}$")
    audience: str = Field("internal", pattern="^(internal|mixed)$")
    participant_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


@router.post("/room")
async def context_room(body: ContextRoomBody, company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    from app.services.context_chats import ensure_room
    cid = await assert_company_member(company_id, user, db)
    room = await ensure_room(db, cid, user, body.ref, purpose=body.purpose,
                             audience=body.audience, participant_ids=body.participant_ids)
    await db.commit()
    return {"room_id": str(room.id)}


@router.post("/results/{result_id}/retry")
async def retry_result(result_id: uuid.UUID, company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    row = await db.scalar(select(WorkContextResult).where(WorkContextResult.id == result_id,
        WorkContextResult.company_id == await assert_company_member(company_id, user, db)).with_for_update())
    if row:
        kind, eid = row.work_kind, row.entity_id
    else:
        cid = await assert_company_member(company_id, user, db)
        row = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == result_id,
            ApprovalRequest.company_id == cid).with_for_update())
        if row is None:
            raise HTTPException(404, "Возврат результата не найден")
        kind, eid = ("doc", row.doc_id) if row.doc_id else ("task", row.task_id)
    await work_links.readable_entity(db, row.company_id, user, kind, eid, edit=True)
    if not row.outcome or row.delivered_at:
        raise HTTPException(409, "Результат ещё не принят или уже доставлен")
    row.attempts = 0
    row.last_error = None
    await db.commit()
    return {"ok": True}
