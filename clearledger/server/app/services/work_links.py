import uuid

from fastapi import HTTPException
from sqlalchemy import String, and_, func, literal, or_, select, union_all

from app.models import ChatMessage, ChatParticipant, DocCard, DocRelation, Task, TaskEvent
from app.services import work_state


def subject_clause(model, cid, ref):
    if model is Task:
        return Task.subject_ref == ref
    return or_(DocCard.subject_ref == ref, select(DocRelation.id).where(
        DocRelation.company_id == cid, DocRelation.doc_id == DocCard.id,
        DocRelation.target_ref == ref).correlate(DocCard).exists())


async def visible_work(db, cid, user, *, ref=None, object_id=None, unlinked_prefix=None):
    from app.routers.docs_router import _readable_doc_clause
    from app.routers.tasks_router import _is_admin, _not_personal, _visible_to

    doc_acl = await _readable_doc_clause(db, cid, user)
    task_acl = _visible_to(user, await _is_admin(db, cid, user))
    parts = []
    for model, kind, acl, state, owner, key in (
        (DocCard, "doc", doc_acl, work_state.doc_state_sql(DocCard),
         DocCard.responsible_id, func.coalesce(DocCard.reg_number, "черновик")),
        (Task, "task", and_(task_acl, _not_personal()), work_state.task_state_sql(Task),
         Task.assignee_id, literal("№") + Task.number.cast(String)),
    ):
        where = [model.company_id == cid, acl]
        if ref:
            where.append(subject_clause(model, cid, ref))
        if object_id:
            where.append(or_(model.object_id == object_id,
                             subject_clause(model, cid, f"object:{object_id}")))
        if unlinked_prefix:
            where.append(or_(model.subject_ref.is_(None), ~model.subject_ref.like(f"{unlinked_prefix}:%")))
            if model is DocCard:
                where.append(~select(DocRelation.id).where(
                    DocRelation.company_id == cid, DocRelation.doc_id == DocCard.id,
                    DocRelation.target_ref.like(f"{unlinked_prefix}:%")).correlate(DocCard).exists())
        parts.append(select(model.id.label("id"), literal(kind).label("kind"),
            key.label("key"), model.title, state.label("state"), model.status,
            owner.label("responsible_id"), model.due_at, model.created_at.label("at"),
            model.subject_ref).where(*where))
    return union_all(*parts).subquery()


async def readable_entity(db, cid, user, kind, entity_id, *, edit=False):
    from app.routers.docs_router import _assert_doc_permission
    from app.routers.tasks_router import _assert_actor, _can_view_task

    model = DocCard if kind == "doc" else Task
    row = await db.get(model, entity_id)
    if row is None or row.company_id != cid:
        raise HTTPException(404, "Работа не найдена")
    if kind == "doc":
        await _assert_doc_permission(db, cid, row, user, "edit" if edit else "read")
    else:
        if row.visibility == "personal" or not await _can_view_task(db, cid, user, row):
            raise HTTPException(404, "Работа не найдена")
        if edit:
            await _assert_actor(db, cid, user, row)
    return row


async def origin(db, cid, user, kind, entity_id):
    row = await readable_entity(db, cid, user, kind, entity_id)
    refs = [row.source_ref] if kind == "doc" else [value for pair in (
        await db.execute(select(TaskEvent.note, TaskEvent.from_value).where(
            TaskEvent.task_id == entity_id, TaskEvent.kind == "created"))).all() for value in pair]
    for ref in refs:
        if not ref or not ref.startswith("chat:"):
            continue
        try:
            mid = uuid.UUID(ref.split(":")[1])
        except (ValueError, IndexError):
            continue
        msg = await db.get(ChatMessage, mid)
        if msg and not msg.deleted_at and await db.scalar(select(ChatParticipant.id).where(
                ChatParticipant.room_id == msg.room_id, ChatParticipant.user_id == user.id)):
            from app.routers.chat_router import _history_from
            since = await _history_from(msg.room_id, user, db)
            if since is None or msg.created_at >= since:
                return {"room_id": str(msg.room_id), "message_id": str(mid)}
    return None
