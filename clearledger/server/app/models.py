"""
SQLAlchemy 2.0 ORM модели ClearLedger.
Все первичные ключи — UUID (хранятся как PostgreSQL UUID).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_id: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cloud_api_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Кастомизация профиля (JSONB)
    customization: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Связи
    users: Mapped[list["User"]] = relationship(back_populates="company")
    entries: Mapped[list["DataEntry"]] = relationship(back_populates="company")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="company")
    connectors: Mapped[list["Connector"]] = relationship(back_populates="company")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    company: Mapped["Company"] = relationship(back_populates="users")


# ---------------------------------------------------------------------------
# DataEntry
# ---------------------------------------------------------------------------
class DataEntry(Base):
    __tablename__ = "data_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    subcategory_id: Mapped[str] = mapped_column(String(100), nullable=False)
    doc_type_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Статус: new, recognized, verified, transferred, error, archived
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")

    # Источник: upload, photo, manual, api, email, oneC, whatsapp, telegram, paste
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSONB для произвольных метаданных (атрибут "meta" → колонка "metadata")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # OCR данные (JSONB)
    ocr_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Связи
    company: Mapped["Company"] = relationship(back_populates="entries")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="entry")


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Действие: created, verified, rejected, transferred, archived, restored,
    #   excluded, included, updated, version_created, exported,
    #   bulk_archived, bulk_excluded, connector_synced
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    entry: Mapped["DataEntry | None"] = relationship(back_populates="audit_events")
    company: Mapped["Company"] = relationship(back_populates="audit_events")


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Статус: active, error, disabled
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    last_sync: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="idle"
    )

    records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[str] = mapped_column(String(100), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)

    # Произвольная конфигурация (JSONB)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    company: Mapped["Company"] = relationship(back_populates="connectors")


# ---------------------------------------------------------------------------
# SourceFile (uploaded files)
# ---------------------------------------------------------------------------
class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# DocumentLink
# ---------------------------------------------------------------------------
class DocumentLink(Base):
    __tablename__ = "document_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="CASCADE"), nullable=False
    )
    target_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Counterparty (Контрагенты)
# ---------------------------------------------------------------------------
class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    inn: Mapped[str] = mapped_column(String(20), nullable=False)
    kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False, default="ЮЛ")
    aliases: Mapped[list] = mapped_column(ARRAY(String), nullable=False, default=list)
    # Ref_Key из БП ГИГ (OData) — связка записей справочника с источником
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Organization (Организации / Юрлица)
# ---------------------------------------------------------------------------
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    inn: Mapped[str] = mapped_column(String(20), nullable=False)
    kpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    bank_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_bik: Mapped[str | None] = mapped_column(String(12), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Nomenclature (Номенклатура)
# ---------------------------------------------------------------------------
class NomenclatureItem(Base):
    __tablename__ = "nomenclature"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    vat_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Contract (Договоры)
# ---------------------------------------------------------------------------
class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(String(100), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# AccountingDoc (Учётные документы 1С)
# ---------------------------------------------------------------------------
class AccountingDoc(Base):
    __tablename__ = "accounting_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)  # GUID 1С
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    counterparty_inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    organization_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    vat_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_1c: Mapped[str] = mapped_column(String(50), nullable=False, default="Проведён")
    lines: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    matched_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    match_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: Warehouse (Склады / АЗС)
# ---------------------------------------------------------------------------
class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="warehouse")
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# НСИ: BankAccount (Банковские счета)
# ---------------------------------------------------------------------------
class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    bik: Mapped[str] = mapped_column(String(12), nullable=False)
    corr_account: Mapped[str | None] = mapped_column(String(30), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    organization_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ===========================================================================
# FUEL: Топливный учёт (GIG Fuel Ledger)
# ===========================================================================


# ---------------------------------------------------------------------------
# FuelStation (АЗС)
# ---------------------------------------------------------------------------
class FuelStation(Base):
    __tablename__ = "fuel_stations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    code: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sts_system_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# FuelShift (Сменный отчёт — нормализованный)
# ---------------------------------------------------------------------------
class FuelShift(Base):
    __tablename__ = "fuel_shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=False
    )
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    operator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="new"
    )  # new|verified|exported|posted

    total_liters: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    cash: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    card: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    voucher: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Ссылка на сырой документ
    raw_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    # Учётный период (Шаг 1) — определяется по closed_at смены
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )
    # Период закрыт в БП — запись read-only
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Уникальный UUID для pull-расширения БП (идемпотентность)
    source_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    station: Mapped["FuelStation"] = relationship()
    tanks: Mapped[list["FuelTank"]] = relationship(back_populates="shift")
    pumps: Mapped[list["FuelPump"]] = relationship(back_populates="shift")


# ---------------------------------------------------------------------------
# FuelTank (Резервуар — по смене)
# ---------------------------------------------------------------------------
class FuelTank(Base):
    __tablename__ = "fuel_tanks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False
    )
    tank_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    volume_start: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    volume_end: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    sales: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Связи
    shift: Mapped["FuelShift"] = relationship(back_populates="tanks")


# ---------------------------------------------------------------------------
# FuelPump (ТРК/колонка — по смене)
# ---------------------------------------------------------------------------
class FuelPump(Base):
    __tablename__ = "fuel_pumps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="CASCADE"),
        nullable=False
    )
    pump_number: Mapped[int] = mapped_column(Integer, nullable=False)
    nozzle: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sales_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Связи
    shift: Mapped["FuelShift"] = relationship(back_populates="pumps")


# ---------------------------------------------------------------------------
# FuelReceipt (ТТН / Поступление)
# ---------------------------------------------------------------------------
class FuelReceipt(Base):
    __tablename__ = "fuel_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=False
    )
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="SET NULL"),
        nullable=True
    )
    ttn: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fuel_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(500), nullable=True)

    doc_volume_liters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    doc_mass_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    doc_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    fact_volume_liters: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fact_mass_kg: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fact_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    density: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    diff_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    diff_mass: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="new"
    )

    raw_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    # Учётный период (Шаг 1) — определяется по received_at
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # ИсточникUUID для pull-расширения БП
    source_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# FuelExportDoc (Документ для выгрузки в 1С)
# ---------------------------------------------------------------------------
class FuelExportDoc(Base):
    __tablename__ = "fuel_export_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # receipt|transfer|assembly|retail_sales
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_shifts.id", ondelete="SET NULL"),
        nullable=True
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_stations.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft"
    )  # draft|confirmed|exported|posted
    export_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    export_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Учётный период (Шаг 1)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )

    # Подтверждение от расширения БП (ack от GIG_Ledger.cfe)
    bp_doc_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bp_acked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# FuelValidationResult (Результат проверки по эталону)
# ---------------------------------------------------------------------------
class FuelValidationResult(Base):
    __tablename__ = "fuel_validation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # shift|receipt
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_code: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # counterparty_inn, nomenclature, vat_rate
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning"
    )  # info|warning|error|block
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ===========================================================================
# ACCOUNTING PERIODS — цикл «симбиоз с бухгалтерией» (Шаг 1)
# ===========================================================================
# Период — первичная сущность нормализованной БД. Каждый рабочий объект
# (FuelShift, FuelReceipt, DataEntry, AccountingDoc) привязан к Period
# и наследует флаг is_locked, если период закрыт.
#
# Закрытие происходит ВНЕ ClearLedger (в БП ГИГ через УстановкуДатЗапрета
# или аналогичный механизм). ClearLedger детектирует закрытие при
# репликации и проставляет Period.status='closed' + is_locked=true
# на привязанные сущности.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Period (Учётный период)
# ---------------------------------------------------------------------------
class Period(Base):
    __tablename__ = "periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..12

    # open|closed — закрыт ли период в бухгалтерии-эталоне
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Источник установки статуса: manual (вручную в UI ClearLedger)
    # или from_bp (репликация из БП через OData / явный признак закрытия)
    closure_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="from_bp"
    )

    # Связь с записью в БП: «дата запрета изменений до X числа» либо
    # явная регистровая запись. JSONB для гибкости.
    bp_closure_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ReferenceSnapshot (Снимок эталона из БП по периоду)
# ---------------------------------------------------------------------------
# Хранит «срез знаний» из БП на момент закрытия периода — для
# воспроизводимости проверок незакрытого периода. Не дублирует
# справочники (они в Counterparty/Nomenclature/...), а фиксирует
# *версию* справочников и список документов с проводками.
# ---------------------------------------------------------------------------
class ReferenceSnapshot(Base):
    __tablename__ = "reference_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="CASCADE"),
        nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Сводка снимка: сколько документов, контрагентов, проводок и т.д.
    # Структура: {"counterparties_count": N, "documents_count": M,
    #             "postings_count": K, "checksum": "sha256:..."}
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Полный список Ref_Key документов БП в этом периоде —
    # для быстрого «список финализированных документов периода».
    document_refs: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )


# ---------------------------------------------------------------------------
# SourceSync (Лог репликации из БП через OData)
# ---------------------------------------------------------------------------
class SourceSync(Base):
    __tablename__ = "source_syncs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Тип репликации: catalogs (справочники) | closed_periods (документы и
    # проводки за закрытые периоды) | period_closure (детект закрытия) |
    # full (полная синхронизация)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # success|partial|error
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Время начала и завершения
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Счётчики
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Детали ошибок и метаданные
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ---------------------------------------------------------------------------
# PullCheckpoint (Точка чтения для расширения БП — pull-расширение)
# ---------------------------------------------------------------------------
# Хранит «что уже забрало расширение БП» для идемпотентности.
# При повторном опросе расширение присылает свой extension_id и last_seen,
# ClearLedger отдаёт только дельту с этого момента.
# ---------------------------------------------------------------------------
class PullCheckpoint(Base):
    __tablename__ = "pull_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Идентификатор расширения-потребителя (например, "gig_ledger_cfe@bp_gig")
    extension_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Тип забираемых документов: fuel_shift | fuel_receipt | ...
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Что забирали — за какой период
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"),
        nullable=True
    )

    # Последняя отметка времени, на которую расширение получило документы
    last_pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Список ИсточникUUID документов, которые расширение подтвердило загруженными
    acknowledged_uuids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # Сколько документов в последнем pull-вызове
    last_pulled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
