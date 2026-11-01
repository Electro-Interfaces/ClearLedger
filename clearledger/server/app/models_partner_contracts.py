"""Хранение Contract CREATE принадлежит revision0004; HTTP/issuance не включены.

Регистрация выполняется существующим владельцем database. Все шесть таблиц
исключены из legacy create_all во всех namespace. FK к raw contract_types и
триггеры неизменности принадлежат versioned SQL. Tenant/ref eligibility проверит
будущий предметный владелец.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CHAR, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import CanonicalUUID as UUID


class PartnerContractCreateProfile(Base):
    __tablename__ = "partner_contract_create_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    service_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    policy_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    __table_args__ = (
        ForeignKeyConstraint(["installation_id", "client_id", "company_id"],
            ["partner_installations.id", "partner_installations.client_id", "partner_installations.company_id"],
            name="fk_pc_profile_installation", ondelete="CASCADE"),
        UniqueConstraint("installation_id", name="uq_pc_profile_installation"),
        CheckConstraint("policy_generation > 0", name="ck_pc_profile_generation"),
        Index("ix_pc_profile_company", "company_id", "installation_id"),
    )


class PartnerContractCreatePrincipal(Base):
    __tablename__ = "partner_contract_create_principals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_contract_create_profiles.id", name="fk_pc_principal_profile", ondelete="CASCADE"), nullable=False)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", name="fk_pc_principal_user", ondelete="CASCADE"), nullable=True)
    machine_grant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_grants.id", name="fk_pc_principal_grant", ondelete="CASCADE"), nullable=True)
    __table_args__ = (
        CheckConstraint("(actor_kind = 'user' AND user_id IS NOT NULL AND machine_grant_id IS NULL) OR (actor_kind = 'machine' AND user_id IS NULL AND machine_grant_id IS NOT NULL)", name="ck_pc_principal_actor"),
        Index("uq_pc_principal_user", "profile_id", "user_id", unique=True, postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_pc_principal_grant", "profile_id", "machine_grant_id", unique=True, postgresql_where=text("machine_grant_id IS NOT NULL")),
    )


class PartnerContractCreateRef(Base):
    __tablename__ = "partner_contract_create_refs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_contract_create_profiles.id", name="fk_pc_ref_profile", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", name="fk_pc_ref_org", ondelete="CASCADE"), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("counterparties.id", name="fk_pc_ref_cp", ondelete="CASCADE"), nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("service_locations.id", name="fk_pc_ref_location", ondelete="CASCADE"), nullable=True)
    __table_args__ = (
        CheckConstraint("(kind = 'organization' AND organization_id IS NOT NULL AND counterparty_id IS NULL AND location_id IS NULL) OR (kind = 'counterparty' AND organization_id IS NULL AND counterparty_id IS NOT NULL AND location_id IS NULL) OR (kind = 'location' AND organization_id IS NULL AND counterparty_id IS NULL AND location_id IS NOT NULL)", name="ck_pc_ref_typed"),
        CheckConstraint("location_id IS NULL OR location_id ~ '[^[:space:]]'", name="ck_pc_ref_location"),
        Index("uq_pc_ref_org", "profile_id", "organization_id", unique=True, postgresql_where=text("organization_id IS NOT NULL")),
        Index("uq_pc_ref_cp", "profile_id", "counterparty_id", unique=True, postgresql_where=text("counterparty_id IS NOT NULL")),
        Index("uq_pc_ref_location", "profile_id", "location_id", unique=True, postgresql_where=text("location_id IS NOT NULL")),
    )


class PartnerContractCreateType(Base):
    __tablename__ = "partner_contract_create_types"
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_contract_create_profiles.id", name="fk_pc_type_profile", ondelete="CASCADE"), primary_key=True)
    # contract_types — raw-таблица Core без ORM-модели. FK принадлежит SQL.
    type_code: Mapped[str] = mapped_column(Text, primary_key=True)
    __table_args__ = (CheckConstraint("type_code ~ '[^[:space:]]'", name="ck_pc_type_code"),)


class PartnerContractSuccessIntent(Base):
    __tablename__ = "partner_contract_success_intents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    create_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    creation_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    current_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", name="fk_pc_intent_user", ondelete="SET NULL"), nullable=True)
    newborn_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", name="fk_pc_intent_contract", ondelete="SET NULL"), nullable=True)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    hash_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_counterparty_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_type_code: Mapped[str] = mapped_column(Text, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    # Маркер верхней транзакции с эпохой устанавливает БД: children после commit не добавляются.
    created_txid: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("pg_current_xact_id()::text"))
    __table_args__ = (
        UniqueConstraint("company_id", "app_id", "installation_id", "operation", "creation_key", name="uq_pc_intent_namespace"),
        CheckConstraint("operation = 'createContract'", name="ck_pc_intent_operation"),
        CheckConstraint("succeeded", name="ck_pc_intent_success"),
        CheckConstraint("hash_version = 1", name="ck_pc_intent_hash_version"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_pc_intent_hash"),
        CheckConstraint("client_id ~ '[^[:space:]]' AND created_type_code ~ '[^[:space:]]'", name="ck_pc_intent_text"),
        CheckConstraint("(actor_kind = 'user' AND actor_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND (current_user_id IS NULL OR actor_key = current_user_id::text)) OR (actor_kind = 'machine' AND actor_key = client_id AND current_user_id IS NULL)", name="ck_pc_intent_actor"),
        CheckConstraint("current_contract_id IS NULL OR current_contract_id = newborn_id", name="ck_pc_intent_contract"),
        Index("ix_pc_success_principal_contract", "company_id", "installation_id", "app_id", "client_id", "original_grant_id", "actor_kind", "actor_key", "current_contract_id", postgresql_where=text("succeeded AND current_contract_id IS NOT NULL")),
        Index("ix_pc_success_profile", "create_profile_id", "company_id"),
    )


class PartnerContractIntentLocation(Base):
    __tablename__ = "partner_contract_intent_locations"
    intent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_contract_success_intents.id", name="fk_pc_intent_location", ondelete="CASCADE"), primary_key=True)
    location_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    __table_args__ = (CheckConstraint("location_id ~ '[^[:space:]]'", name="ck_pc_intent_location"),)


VERSIONED_TABLE_NAMES = frozenset({
    "partner_contract_create_profiles", "partner_contract_create_principals",
    "partner_contract_create_refs", "partner_contract_create_types",
    "partner_contract_success_intents", "partner_contract_intent_locations",
})
