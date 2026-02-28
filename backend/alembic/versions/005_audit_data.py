"""Аудит-данные: таблица audit_findings для облачного аудитора

Revision ID: 005
Revises: 004
Create Date: 2026-02-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("finding_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("affected_entry_ids", ARRAY(sa.String()), server_default="{}"),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("cloud_finding_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_findings_status", "audit_findings", ["status"])
    op.create_index("idx_audit_findings_severity", "audit_findings", ["severity"])


def downgrade() -> None:
    op.drop_index("idx_audit_findings_severity")
    op.drop_index("idx_audit_findings_status")
    op.drop_table("audit_findings")
