"""Initial: public + staging schemas

Revision ID: 001
Revises:
Create Date: 2026-02-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === PUBLIC SCHEMA ===

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String, unique=True, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "companies",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("short_name", sa.String, nullable=False),
        sa.Column("inn", sa.String),
        sa.Column("profile_id", sa.String, nullable=False),
        sa.Column("color", sa.String, nullable=False, server_default="#3b82f6"),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "user_companies",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("file_name", sa.String, nullable=False),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("file_path", sa.String, nullable=False),
        sa.Column("fingerprint", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_sources_company", "sources", ["company_id"])
    op.create_index("idx_sources_fingerprint", "sources", ["fingerprint"])

    op.create_table(
        "entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("sources.id")),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("category_id", sa.String, nullable=False),
        sa.Column("subcategory_id", sa.String, nullable=False),
        sa.Column("doc_type_id", sa.String),
        sa.Column("status", sa.String, nullable=False, server_default="new"),
        sa.Column("source_type", sa.String, nullable=False),
        sa.Column("source_label", sa.String, nullable=False, server_default=""),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("transferred_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_entries_company", "entries", ["company_id"])
    op.create_index("idx_entries_status", "entries", ["company_id", "status"])
    op.create_index("idx_entries_category", "entries", ["company_id", "category_id"])
    op.create_index("idx_entries_created", "entries", ["company_id", sa.text("created_at DESC")])

    op.create_table(
        "document_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_entry_id", UUID(as_uuid=True), sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entry_id", UUID(as_uuid=True), sa.ForeignKey("entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", sa.String, nullable=False),
        sa.Column("label", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_links_source", "document_links", ["source_entry_id"])
    op.create_index("idx_links_target", "document_links", ["target_entry_id"])

    op.create_table(
        "connectors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("url", sa.String, nullable=False, server_default=""),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String, nullable=False, server_default="disabled"),
        sa.Column("category_id", sa.String, nullable=False),
        sa.Column("interval_sec", sa.Integer, nullable=False, server_default="3600"),
        sa.Column("last_sync", sa.DateTime(timezone=True)),
        sa.Column("records_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", sa.String),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", INET),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # === STAGING SCHEMA ===

    op.execute("CREATE SCHEMA IF NOT EXISTS staging")

    op.create_table(
        "raw_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String, nullable=False),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=False, server_default=""),
        sa.Column("extracted_fields", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("page_count", sa.Integer),
        sa.Column("processing_status", sa.String, nullable=False, server_default="parsed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="staging",
    )
    op.create_index("idx_raw_entries_status", "raw_entries", ["processing_status"], schema="staging")

    op.create_table(
        "ai_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("raw_entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", sa.String),
        sa.Column("subcategory_id", sa.String),
        sa.Column("doc_type_id", sa.String),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("normalized_metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decision", sa.String, nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.String),
        sa.Column("duplicate_of", UUID(as_uuid=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("model_version", sa.String),
        schema="staging",
    )
    op.create_index("idx_ai_results_entry", "ai_results", ["raw_entry_id"], schema="staging")
    op.create_index("idx_ai_results_decision", "ai_results", ["decision"], schema="staging")

    op.create_table(
        "sync_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("raw_entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="staging",
    )
    op.create_index("idx_sync_queue_status", "sync_queue", ["status"], schema="staging")


def downgrade() -> None:
    op.drop_table("sync_queue", schema="staging")
    op.drop_table("ai_results", schema="staging")
    op.drop_table("raw_entries", schema="staging")
    op.execute("DROP SCHEMA IF EXISTS staging")

    op.drop_table("settings")
    op.drop_table("audit_log")
    op.drop_table("connectors")
    op.drop_table("document_links")
    op.drop_table("entries")
    op.drop_table("sources")
    op.drop_table("user_companies")
    op.drop_table("companies")
    op.drop_table("users")
