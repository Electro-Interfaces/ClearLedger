"""OAuth approvals and credentials; App/Company/CompanyApp remain Core masters.

All tables are new and registered in the existing metadata/create_all bootstrap.
Secrets, codes and refresh tokens are stored only as SHA-256 digests of random
256-bit values. User grants never substitute for membership or domain policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PartnerClient(Base):
    __tablename__ = "partner_clients"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eco_apps.id", ondelete="CASCADE"), nullable=False, unique=True)
    owner_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    redirect_uris: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    allowed_scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    auth_method: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("auth_method IN ('none','client_secret_basic')", name="ck_partner_client_auth"),)


class PartnerCredential(Base):
    __tablename__ = "partner_credentials"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("partner_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PartnerInstallation(Base):
    __tablename__ = "partner_installations"
    # This IS the existing company app installation, not a second master.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eco_company_apps.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("partner_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    all_locations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("id", "client_id", "company_id", name="uq_partner_install_client_company"),)


class PartnerInstallationLocation(Base):
    __tablename__ = "partner_installation_locations"
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_installations.id", ondelete="CASCADE"), primary_key=True)
    location_id: Mapped[str] = mapped_column(String(40), ForeignKey("service_locations.id", ondelete="CASCADE"), primary_key=True)


class PartnerResourceScope(Base):
    __tablename__ = "partner_resource_scopes"
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_installations.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    mode: Mapped[str] = mapped_column(String(5), nullable=False, default="EMPTY")
    __table_args__ = (
        CheckConstraint("kind IN ('objects','equipment','counterparties','contracts','documents')", name="ck_partner_resource_kind"),
        CheckConstraint("mode IN ('ALL','SET','EMPTY')", name="ck_partner_resource_mode"),
    )


class PartnerResourceItem(Base):
    __tablename__ = "partner_resource_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("service_locations.id", ondelete="CASCADE"), nullable=True)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ezs_equipment_units.id", ondelete="CASCADE"), nullable=True)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="CASCADE"), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("doc_cards.id", ondelete="CASCADE"), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["installation_id", "kind"], ["partner_resource_scopes.installation_id", "partner_resource_scopes.kind"], ondelete="CASCADE"),
        CheckConstraint("num_nonnulls(object_id,equipment_id,counterparty_id,contract_id,document_id)=1", name="ck_partner_resource_one_id"),
        CheckConstraint("(kind='objects' AND object_id IS NOT NULL) OR (kind='equipment' AND equipment_id IS NOT NULL) OR (kind='counterparties' AND counterparty_id IS NOT NULL) OR (kind='contracts' AND contract_id IS NOT NULL) OR (kind='documents' AND document_id IS NOT NULL)", name="ck_partner_resource_typed_id"),
    )


class PartnerGrant(Base):
    __tablename__ = "partner_grants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["installation_id", "client_id", "company_id"], ["partner_installations.id", "partner_installations.client_id", "partner_installations.company_id"], ondelete="CASCADE"),
        CheckConstraint("(kind='user' AND user_id IS NOT NULL) OR (kind='machine' AND user_id IS NULL)", name="ck_partner_grant_actor"),
    )


class PartnerAuthorizationRequest(Base):
    __tablename__ = "partner_authorization_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("partner_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # First Core bearer opening this unguessable request owns its consent.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)


class PartnerSubject(Base):
    __tablename__ = "partner_subjects"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("partner_clients.id", ondelete="CASCADE"), primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class PartnerCode(Base):
    __tablename__ = "partner_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_grants.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("partner_clients.id", ondelete="CASCADE"), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    scope: Mapped[str] = mapped_column(String(2000), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(4), nullable=False, default="S256")
    nonce: Mapped[str | None] = mapped_column(String(256), nullable=True)
    auth_time: Mapped[int] = mapped_column(Integer, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def get_redirect_uri(self):
        return self.redirect_uri

    def get_scope(self):
        return self.scope

    def get_nonce(self):
        return self.nonce

    def get_auth_time(self):
        return self.auth_time

    def get_acr(self):
        return None

    def get_amr(self):
        return None


class PartnerTokenFamily(Base):
    __tablename__ = "partner_token_families"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_credentials.id", ondelete="SET NULL"), nullable=True)
    token_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auth_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PartnerToken(Base):
    __tablename__ = "partner_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_token_families.id", ondelete="CASCADE"), nullable=False, index=True)
    access_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    scope: Mapped[str] = mapped_column(String(2000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def get_scope(self):
        return self.scope
