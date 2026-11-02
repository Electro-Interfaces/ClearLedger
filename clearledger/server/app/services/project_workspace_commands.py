"""Команды проекта с прежними membership, site lock и commit boundaries.

Связь с работой/файлом не предоставляет новых полномочий на её содержимое.
Native adapters передают только конкретные текущие compatibility hooks.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.auth import assert_company_member
from app.models import ChatMessage, DocRelation, EzsSite, EzsSiteDoc, EzsSiteEvent, TaskEvent
from app.schemas_project_workspace import DecisionBody, FileBody, LinkBody
from app.services import chat_access, ezs_site_work, project_work, track_files


async def owned(db, cid, sid, *, lock=False):
    query = select(EzsSite).where(EzsSite.id == sid, EzsSite.company_id == cid)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "Проект не найден")
    return row


async def source_message(db, cid, user, mid, *, participant_check=None, history_lookup=None):
    participant_check = participant_check if participant_check is not None else chat_access.assert_participant
    history_lookup = history_lookup if history_lookup is not None else chat_access.history_from
    msg = await db.get(ChatMessage, mid)
    if msg is None or msg.deleted_at:
        raise HTTPException(404, "Сообщение не найдено")
    room = await participant_check(msg.room_id, user, db)
    since = await history_lookup(msg.room_id, user, db)
    if since and msg.created_at < since:
        raise HTTPException(404, "Сообщение не найдено")
    if room.company_id != cid:
        raise HTTPException(404, "Сообщение не найдено")
    return msg


async def link_work(db, company_ref: str, user, sid: uuid.UUID, body: LinkBody, *,
                        member_check=None, site_lookup=None, message_lookup=None):
    member_check = member_check if member_check is not None else assert_company_member
    site_lookup = site_lookup if site_lookup is not None else owned
    message_lookup = message_lookup if message_lookup is not None else source_message
    cid = await member_check(company_ref, user, db)
    site = await site_lookup(db, cid, sid, lock=True)
    ref = f"site:{sid}"
    if body.kind == "message":
        msg = await message_lookup(db, cid, user, body.id)
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


async def record_decision(db, company_ref: str, user, sid: uuid.UUID, body: DecisionBody, *,
                        member_check=None, site_lookup=None, message_lookup=None):
    member_check = member_check if member_check is not None else assert_company_member
    site_lookup = site_lookup if site_lookup is not None else owned
    message_lookup = message_lookup if message_lookup is not None else source_message
    cid = await member_check(company_ref, user, db)
    site = await site_lookup(db, cid, sid, lock=True)
    details = {}
    if body.source_message_id:
        msg = await message_lookup(db, cid, user, body.source_message_id)
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


async def attach_message_file(db, company_ref: str, user, sid: uuid.UUID, body: FileBody, *,
                        member_check=None, site_lookup=None, message_lookup=None):
    member_check = member_check if member_check is not None else assert_company_member
    site_lookup = site_lookup if site_lookup is not None else owned
    message_lookup = message_lookup if message_lookup is not None else source_message
    cid = await member_check(company_ref, user, db)
    site = await site_lookup(db, cid, sid, lock=True)
    msg = await message_lookup(db, cid, user, body.message_id)
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
