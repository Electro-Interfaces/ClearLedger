from datetime import datetime, timezone
from sqlalchemy import and_, false, func, or_, select

from app.models import ApprovalRequest, DocApproval, DocCard, User, WorkContextResult
from app.services import work_state
from app.services.work_links import subject_clause as project_clause, visible_work, readable_entity, origin


async def listing(db, cid, user, *, site=None, scope="all", offset=0, limit=40,
                  common=False, unlinked=False, q="", kind=None):
    ref = f"site:{site.id}" if site and not common else None
    work = await visible_work(db, cid, user, ref=ref,
        object_id=site.location_id if site and common else None, unlinked_prefix="site" if unlinked else None)
    now = datetime.now(timezone.utc)
    where = []
    if common and (not site or not site.location_id):
        where.append(false())
    if common and site:
        direct = await visible_work(db, cid, user, ref=f"site:{site.id}")
        where.append(~select(direct.c.id).where(
            direct.c.id == work.c.id, direct.c.kind == work.c.kind).exists())
    if scope in ("open", "overdue"):
        where.append(work.c.state != "done")
    if scope == "mine":
        where.append(work.c.responsible_id == user.id)
    if scope == "overdue":
        where.append(work.c.due_at < now)
    if scope == "pending":
        returned_pending = select(WorkContextResult.id).where(
            WorkContextResult.company_id == cid, WorkContextResult.entity_id == work.c.id,
            WorkContextResult.work_kind == work.c.kind, WorkContextResult.delivered_at.is_(None))
        if site:
            returned_pending = returned_pending.where(WorkContextResult.context_ref == f"site:{site.id}")
        route_pending = select(ApprovalRequest.id).where(ApprovalRequest.company_id == cid,
            ApprovalRequest.outcome.is_not(None), ApprovalRequest.delivered_at.is_(None),
            or_(and_(work.c.kind == "doc", ApprovalRequest.doc_id == work.c.id),
                and_(work.c.kind == "task", ApprovalRequest.task_id == work.c.id)))
        where.append(or_(returned_pending.correlate(work).exists(), route_pending.correlate(work).exists()))
    if q:
        where.append(or_(work.c.title.ilike(f"%{q}%"), work.c.key.ilike(f"%{q}%")))
    if kind:
        where.append(work.c.kind == kind)
    total = await db.scalar(select(func.count()).select_from(work).where(*where))
    rows = (await db.execute(select(work).where(*where).order_by(
        work.c.at.desc(), work.c.kind, work.c.id).offset(offset).limit(limit))).mappings().all()
    ids = [r["id"] for r in rows]
    people = dict((await db.execute(select(User.id, User.name).where(
        User.id.in_([r["responsible_id"] for r in rows if r["responsible_id"]])))).all()) if rows else {}
    requests = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.company_id == cid,
        or_(ApprovalRequest.doc_id.in_(ids), ApprovalRequest.task_id.in_(ids)))
        .order_by(ApprovalRequest.created_at.desc()))).scalars().all() if ids else []
    returned = (await db.execute(select(WorkContextResult).where(WorkContextResult.company_id == cid,
        WorkContextResult.context_ref == f"site:{site.id}", WorkContextResult.entity_id.in_(ids))
        .order_by(WorkContextResult.created_at.desc()))).scalars().all() if site and ids else []
    outcomes = {}
    for request in requests:
        key = ("doc", request.doc_id) if request.doc_id else ("task", request.task_id)
        outcomes.setdefault(key, []).append(request)
    doc_ids = [r["id"] for r in rows if r["kind"] == "doc"]
    documents = {d.id: d for d in (await db.execute(select(DocCard).where(
        DocCard.company_id == cid, DocCard.id.in_(doc_ids)))).scalars().all()} if doc_ids else {}
    pending_people = (await db.execute(select(DocApproval.doc_id, User.name).join(User, User.id == DocApproval.assignee_id)
        .where(DocApproval.company_id == cid, DocApproval.doc_id.in_(doc_ids), DocApproval.status == "pending"))).all() if doc_ids else []
    items = []
    for row in rows:
        item = dict(row)
        item["id"] = str(row["id"])
        item["responsible_id"] = str(row["responsible_id"]) if row["responsible_id"] else None
        item["responsible_name"] = people.get(row["responsible_id"])
        item["state_name"] = work_state.COLUMN_NAMES.get(row["state"], row["state"])
        item["overdue"] = bool(row["due_at"] and row["due_at"] < now and row["state"] != "done")
        if row["kind"] == "doc":
            doc = documents[row["id"]]
            item["waiting_for_names"] = list(dict.fromkeys(name for did, name in pending_people if did == doc.id))
            item["revision"] = doc.current_revision
            item["approval_status"] = doc.approval_status
            from app.services.track_files import signed_current
            signed = await signed_current(db, doc) if doc.approval_status == "approved" or doc.status in ("signed", "in_force", "executed") else False
            item["document_state"] = "Подписан" if signed else "Согласован" if doc.approval_status == "approved" else "На согласовании" if doc.approval_status == "pending" else "Подготовка"
        related = outcomes.get((row["kind"], row["id"]), [])
        item["required"] = any(r.on_approved and r.outcome is None for r in related)
        item["deliveries"] = [{"id": str(r.id), "outcome": r.outcome,
            "pending": bool(r.outcome and not r.delivered_at), "error": bool(r.last_error),
            "attempts": r.attempts, "decided_at": r.decided_at, "delivered_at": r.delivered_at}
            for r in related]
        item["deliveries"].extend({"id": str(r.id), "outcome": r.outcome, "pending": not bool(r.delivered_at),
            "error": bool(r.last_error), "attempts": r.attempts, "decided_at": r.created_at, "delivered_at": r.delivered_at}
            for r in returned if r.work_kind == row["kind"] and r.entity_id == row["id"])
        items.append(item)
    blocking = select(ApprovalRequest.id).where(ApprovalRequest.company_id == cid,
        ApprovalRequest.outcome.is_(None), ApprovalRequest.on_approved.is_not(None),
        ApprovalRequest.on_approved != "", or_(
            and_(work.c.kind == "doc", ApprovalRequest.doc_id == work.c.id),
            and_(work.c.kind == "task", ApprovalRequest.task_id == work.c.id))).correlate(work).exists()
    waiting = await db.scalar(select(func.count()).select_from(work).where(blocking))
    return {"site_id": str(site.id) if site else None, "object_id": site.location_id if site else None,
            "subject_ref": ref, "items": items, "total": total, "offset": offset, "limit": limit,
            "waiting": waiting}
