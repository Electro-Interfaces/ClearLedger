"""Short-lived browser capability for documentation, never product API auth."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DocsPortalSession(Base):
    __tablename__ = "partner_docs_sessions"
    cookie_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("partner_tokens.id", ondelete="CASCADE"), nullable=False, unique=True)
    verification_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
