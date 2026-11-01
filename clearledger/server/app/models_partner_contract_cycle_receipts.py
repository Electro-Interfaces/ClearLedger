"""Revision0005 owns these two immutable tables; registration never provisions them.

Original actor/resource identifiers are historical snapshots, not authority or
existence evidence. Only company ownership and the receipt/ref link are FKs.
The explicit SQL owns immutable row/statement triggers and DB-owned timestamps.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import CanonicalUUID as UUID


class PartnerContractCycleReceipt(Base):
    __tablename__ = "partner_contract_cycle_receipts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", name="fk_pcc_receipt_company", ondelete="RESTRICT"), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    command_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hash_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    target_kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    created_txid: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("pg_current_xact_id()::text"))
    __table_args__ = (
        UniqueConstraint("company_id", "app_id", "installation_id", "operation", "command_key", name="uq_pcc_receipt_namespace"),
        CheckConstraint("length(client_id) > 0", name="ck_pcc_receipt_client"),
        CheckConstraint("operation_version = 2", name="ck_pcc_receipt_operation_version"),
        CheckConstraint("hash_version = 1", name="ck_pcc_receipt_hash_version"),
        CheckConstraint("length(request_hash) = 64 AND request_hash ~ '^[0-9a-f]{64}$'", name="ck_pcc_receipt_hash"),
        CheckConstraint("(operation = 'v2.contract.create' AND target_kind = 'contract') OR "
                        "(operation = 'v2.contract.patch' AND target_kind = 'contract') OR "
                        "(operation = 'v2.contract.location.link' AND target_kind = 'contract') OR "
                        "(operation = 'v2.term.create' AND target_kind = 'term') OR "
                        "(operation = 'v2.term.version' AND target_kind = 'term') OR "
                        "(operation = 'v2.term.coverage' AND target_kind = 'term') OR "
                        "(operation = 'v2.site.contract.link' AND target_kind = 'site') OR "
                        "(operation = 'v2.site.location.link' AND target_kind = 'site') OR "
                        "(operation = 'v2.document.draft.create' AND target_kind = 'document') OR "
                        "(operation = 'v2.document.contract.link' AND target_kind = 'document') OR "
                        "(operation = 'v2.document.register' AND target_kind = 'document') OR "
                        "(operation = 'v2.document.version.upload' AND target_kind = 'version')", name="ck_pcc_receipt_target"),
        CheckConstraint("jsonb_typeof(result) = 'object'", name="ck_pcc_receipt_result_object"),
        CheckConstraint("octet_length(convert_to(result::text, 'UTF8')) <= 131072", name="ck_pcc_receipt_result_bytes"),
    )


class PartnerContractCycleReceiptRef(Base):
    __tablename__ = "partner_contract_cycle_receipt_refs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_contract_cycle_receipts.id", name="fk_pcc_ref_receipt", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    uuid_value: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    location_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("(kind = 'location' AND uuid_value IS NULL AND location_value IS NOT NULL) OR "
                        "(kind = 'organization' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'counterparty' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'site' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'contract' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'term' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'document' AND uuid_value IS NOT NULL AND location_value IS NULL) OR "
                        "(kind = 'version' AND uuid_value IS NOT NULL AND location_value IS NULL)", name="ck_pcc_ref_typed"),
        CheckConstraint("location_value IS NULL OR (length(location_value) > 0 AND length(location_value) <= 40)", name="ck_pcc_ref_location"),
        Index("uq_pcc_ref_uuid", "receipt_id", "kind", "uuid_value", unique=True, postgresql_where=text("uuid_value IS NOT NULL")),
        Index("uq_pcc_ref_location", "receipt_id", "kind", "location_value", unique=True, postgresql_where=text("location_value IS NOT NULL")),
    )


VERSIONED_TABLE_NAMES = frozenset({
    "partner_contract_cycle_receipts", "partner_contract_cycle_receipt_refs",
})
