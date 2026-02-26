"""GIN index на entries.metadata + FK constraints в staging

Revision ID: 002
Revises: 001
Create Date: 2026-02-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # GIN-индекс на entries.metadata для быстрого поиска по JSONB
    op.execute(
        "CREATE INDEX idx_entries_metadata ON entries USING GIN (metadata jsonb_path_ops)"
    )

    # FK: staging.ai_results.raw_entry_id → staging.raw_entries.id
    op.create_foreign_key(
        "fk_ai_results_raw_entry",
        "ai_results",
        "raw_entries",
        ["raw_entry_id"],
        ["id"],
        source_schema="staging",
        referent_schema="staging",
        ondelete="CASCADE",
    )

    # FK: staging.sync_queue.raw_entry_id → staging.raw_entries.id
    op.create_foreign_key(
        "fk_sync_queue_raw_entry",
        "sync_queue",
        "raw_entries",
        ["raw_entry_id"],
        ["id"],
        source_schema="staging",
        referent_schema="staging",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sync_queue_raw_entry", "sync_queue", schema="staging", type_="foreignkey")
    op.drop_constraint("fk_ai_results_raw_entry", "ai_results", schema="staging", type_="foreignkey")
    op.execute("DROP INDEX IF EXISTS idx_entries_metadata")
