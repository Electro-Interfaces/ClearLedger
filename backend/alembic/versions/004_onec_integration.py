"""Интеграция 1С: OneCConnection, OneCSyncLog, Warehouse, BankAccount, external_ref

Revision ID: 004
Revises: 003
Create Date: 2026-02-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- external_ref в существующие справочники ---
    op.add_column("counterparties", sa.Column("external_ref", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("external_ref", sa.String(), nullable=True))
    op.add_column("nomenclature", sa.Column("external_ref", sa.String(), nullable=True))

    # --- Склады ---
    op.create_table(
        "warehouses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, server_default="warehouse"),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_wh_company_code", "warehouses", ["company_id", "code"], unique=True)

    # --- Банковские счета ---
    op.create_table(
        "bank_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("number", sa.String(), nullable=False),
        sa.Column("bank_name", sa.String(), nullable=False, server_default=""),
        sa.Column("bik", sa.String(), nullable=False, server_default=""),
        sa.Column("corr_account", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default="RUB"),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_ba_company", "bank_accounts", ["company_id"])
    op.create_index("idx_ba_number", "bank_accounts", ["company_id", "number"], unique=True)

    # --- Подключения 1С ---
    op.create_table(
        "onec_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default="1С:Бухгалтерия"),
        sa.Column("odata_url", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_encrypted", sa.String(), nullable=False),
        sa.Column("exchange_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="inactive"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_interval_sec", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_onec_conn_company", "onec_connections", ["company_id"])

    # --- Лог синхронизаций ---
    op.create_table(
        "onec_sync_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", UUID(as_uuid=True),
                  sa.ForeignKey("onec_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("sync_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("items_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_sync_log_conn", "onec_sync_logs", ["connection_id"])
    op.create_index("idx_sync_log_started", "onec_sync_logs", ["started_at"])


def downgrade() -> None:
    op.drop_table("onec_sync_logs")
    op.drop_table("onec_connections")
    op.drop_table("bank_accounts")
    op.drop_table("warehouses")
    op.drop_column("nomenclature", "external_ref")
    op.drop_column("organizations", "external_ref")
    op.drop_column("counterparties", "external_ref")
