from sqlalchemy import select

from app.models import DocCard, DocRelation
from app.services import work_contexts


async def task_result(db, task, outcome):
    await work_contexts.publish_result(db, task.company_id, task.subject_ref,
        work_ref=f"task:{task.id}", outcome=outcome,
        result_key=f"task:{task.id}:{task.closed_at}:{outcome}")


async def document_result(db, doc_id, outcome, *, event_key=None):
    doc = await db.get(DocCard, doc_id)
    if doc is None:
        return
    refs = set((await db.execute(select(DocRelation.target_ref).where(
        DocRelation.company_id == doc.company_id, DocRelation.doc_id == doc.id))).scalars().all())
    if doc.subject_ref:
        refs.add(doc.subject_ref)
    for ref in sorted(refs):
        await work_contexts.publish_result(db, doc.company_id, ref, work_ref=f"doc:{doc.id}",
            outcome=outcome, result_key=f"doc:{doc.id}:{event_key or doc.approval_round}:{outcome}")
