"""Explicit revision0006 native Site authority; registration never provisions it."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKeyConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import CanonicalUUID as UUID


SITE_ACTIONS = (
    "site.read", "site.link_edit", "contract.create", "document.create",
    "document.read", "document.edit", "document.download", "document.print",
    "document.export", "document.send", "document.approve", "document.sign",
    "document.archive", "document.manage_acl",
)
ACTION_CHECK = " OR ".join("action='" + action + "'" for action in SITE_ACTIONS)
VERSIONED_TABLE_NAMES = frozenset({"site_authority_contexts", "site_user_permissions"})


class SiteAuthorityContext(Base):
    __tablename__ = "site_authority_contexts"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    policy_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "site_id"], ["ezs_sites.company_id", "ezs_sites.id"], name="fk_site_context_site", ondelete="CASCADE"),
        ForeignKeyConstraint(["company_id", "organization_id"], ["organizations.company_id", "organizations.id"], name="fk_site_context_organization", ondelete="CASCADE"),
        CheckConstraint("policy_generation > 0", name="ck_site_context_generation"),
    )


class SiteUserPermission(Base):
    __tablename__ = "site_user_permissions"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), primary_key=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "site_id"], ["site_authority_contexts.company_id", "site_authority_contexts.site_id"], name="fk_site_permission_context", ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "company_id"], ["user_companies.user_id", "user_companies.company_id"], name="fk_site_permission_membership", ondelete="CASCADE"),
        CheckConstraint(ACTION_CHECK, name="ck_site_permission_action"),
    )
