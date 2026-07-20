"""Факты по карточкам номенклатуры 208 из боевой 1С — эра продаж относительно
Дня X (11.06.2026, НЛ→ГИГ) и текущий остаток. Отдельная таблица от dedup_cards:
наполняется своей пробой/эндпоинтом и НЕ стирается при reload среза дублей.

Ключ — (company_id, guid) номенклатуры. Модель регистрируется в Base импортом
из dedup_service.py (файл кладём отдельно, чтобы не трогать общий models.py)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DedupCardFacts(Base):
    __tablename__ = "dedup_card_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    guid: Mapped[str] = mapped_column(String(40), nullable=False)  # UUID номенклатуры (lower)
    # Эра продаж относительно Дня X (11.06.2026). Карточка может быть в обеих
    # (торговалась и до, и после) — тогда gig_traded=True (актуальнее).
    gig_traded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # оборот с 11.06.2026 (ГИГ)
    nl_traded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)   # оборот только до 11.06 (НЛ)
    ostatok_208: Mapped[float | None] = mapped_column(Numeric(15, 3), nullable=True)  # текущий остаток склада 208
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("uq_dedup_facts", "company_id", "guid", unique=True),
    )
