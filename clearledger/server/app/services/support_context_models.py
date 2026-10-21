"""Состояние делегирования Core; предметное досье остаётся в Support.

Импортируется роутером до штатного create_all. Все таблицы additive, legacy
таблицы и их правила не меняются. JSON claims нужен для точного digest binding.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContextBinding(Base):
    __tablename__ = "support_context_bindings"
    context_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    core_cid: Mapped[str] = mapped_column(String(36), nullable=False)
    support_cid: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(200), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("core_cid", "support_cid", "node_id", "connector_id", "contact_id"),)


class ContextGrant(Base):
    __tablename__ = "support_context_grants"
    grant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    claims: Mapped[dict] = mapped_column(JSONB, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False)
    permissions_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    authority: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContextReplay(Base):
    __tablename__ = "support_context_replays"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
