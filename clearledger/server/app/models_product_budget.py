"""Shared product-request counters, subordinate to the approved installation."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductAPIBudget(Base):
    __tablename__ = "product_api_budgets"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["installation_id", "client_id", "company_id"],
            ["partner_installations.id", "partner_installations.client_id", "partner_installations.company_id"],
            ondelete="CASCADE"),
        CheckConstraint("request_limit BETWEEN 1 AND 1000000", name="ck_product_budget_limit"),
        CheckConstraint("window_seconds BETWEEN 1 AND 3600", name="ck_product_budget_window"),
        CheckConstraint("used BETWEEN 1 AND request_limit + 1", name="ck_product_budget_used"),
        Index("ix_product_api_budgets_reset", "reset_at"),
    )
