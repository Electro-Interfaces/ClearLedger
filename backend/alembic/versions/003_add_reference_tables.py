"""Справочники НСИ: counterparties, organizations, nomenclature, contracts

Revision ID: 003
Revises: 002
Create Date: 2026-02-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm для fuzzy-поиска по имени контрагента
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Контрагенты
    op.create_table(
        "counterparties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("inn", sa.String, nullable=False),
        sa.Column("kpp", sa.String),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("short_name", sa.String),
        sa.Column("type", sa.String, nullable=False, server_default="ЮЛ"),
        sa.Column("aliases", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_cp_company", "counterparties", ["company_id"])
    op.create_index("idx_cp_inn_kpp", "counterparties", ["company_id", "inn", "kpp"], unique=True)
    op.execute(
        "CREATE INDEX idx_cp_name_trgm ON counterparties USING gin (name gin_trgm_ops)"
    )

    # Организации
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("inn", sa.String, nullable=False),
        sa.Column("kpp", sa.String),
        sa.Column("ogrn", sa.String),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("bank_account", sa.String),
        sa.Column("bank_bik", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_org_company", "organizations", ["company_id"])
    op.create_index("idx_org_inn_kpp", "organizations", ["company_id", "inn", "kpp"], unique=True)

    # Номенклатура
    op.create_table(
        "nomenclature",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("unit", sa.String, nullable=False, server_default="796"),
        sa.Column("unit_label", sa.String, nullable=False, server_default="шт"),
        sa.Column("vat_rate", sa.Float, nullable=False, server_default=sa.text("20")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_nom_company_code", "nomenclature", ["company_id", "code"], unique=True)

    # Договоры
    op.create_table(
        "contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("number", sa.String, nullable=False),
        sa.Column("date", sa.String),
        sa.Column("counterparty_id", UUID(as_uuid=True), sa.ForeignKey("counterparties.id")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id")),
        sa.Column("type", sa.String, nullable=False, server_default="Прочее"),
        sa.Column("amount_limit", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_contracts_company", "contracts", ["company_id"])
    op.create_index("idx_contracts_cp", "contracts", ["counterparty_id"])


def downgrade() -> None:
    op.drop_table("contracts")
    op.drop_table("nomenclature")
    op.drop_table("organizations")
    op.drop_table("counterparties")
