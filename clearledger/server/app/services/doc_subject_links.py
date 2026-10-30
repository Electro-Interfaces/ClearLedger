"""Explicit document subject/graph links shared by native and product reads."""
from sqlalchemy import or_, select

from app.models import DocCard, DocRelation


def subject_documents_clause(company_id, ref, *, correlate_doc=False):
    """Shared subject/graph predicate, not an access permission.

    Default auto-correlation is the existing R2/native-docs construction profile.
    Work-links opts into explicit DocCard correlation to retain its old behavior
    with outer DocRelation joins/nesting. This flag never adds authority.
    """
    related = select(DocRelation.doc_id).where(
        DocRelation.company_id == company_id,
        DocRelation.doc_id == DocCard.id,
        DocRelation.target_ref == ref)
    if correlate_doc:
        related = related.correlate(DocCard)
    return or_(DocCard.subject_ref == ref, related.exists())
