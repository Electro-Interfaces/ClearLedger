"""Многомерный жизненный цикл: doc_purpose + sync_status в entries

Revision ID: 006
Revises: 005
Create Date: 2026-02-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entries",
        sa.Column("doc_purpose", sa.String(), nullable=False, server_default="accounting"),
    )
    op.add_column(
        "entries",
        sa.Column("sync_status", sa.String(), nullable=False, server_default="not_applicable"),
    )
    op.create_index("idx_entries_doc_purpose", "entries", ["company_id", "doc_purpose"])
    op.create_index("idx_entries_sync_status", "entries", ["company_id", "sync_status"])


def downgrade() -> None:
    op.drop_index("idx_entries_sync_status")
    op.drop_index("idx_entries_doc_purpose")
    op.drop_column("entries", "sync_status")
    op.drop_column("entries", "doc_purpose")
