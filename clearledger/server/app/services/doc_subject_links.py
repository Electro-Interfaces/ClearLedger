"""Explicit document subject/graph links shared by native and product reads."""
from sqlalchemy import or_, select

from app.models import DocCard, DocRelation


def subject_documents_clause(company_id, ref):
    """Keep native ref semantics; EXISTS prevents duplicate graph edges."""
    related = select(DocRelation.doc_id).where(
        DocRelation.company_id == company_id,
        DocRelation.doc_id == DocCard.id,
        DocRelation.target_ref == ref).exists()
    return or_(DocCard.subject_ref == ref, related)
