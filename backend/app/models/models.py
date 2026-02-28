"""SQLAlchemy models — public + staging schemas."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, ForeignKey, Index, Integer, BigInteger,
    String, Text, DateTime, Float,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import relationship

from app.database import Base


# ============================================================
# PUBLIC SCHEMA (Layer 2)
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="operator")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_login = Column(DateTime(timezone=True))


class Company(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    short_name = Column(String, nullable=False)
    inn = Column(String)
    profile_id = Column(String, nullable=False)
    color = Column(String, nullable=False, default="#3b82f6")
    settings = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    entries = relationship("Entry", back_populates="company")
    sources = relationship("Source", back_populates="company")
    connectors = relationship("Connector", back_populates="company")


class UserCompany(Base):
    __tablename__ = "user_companies"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)


class Source(Base):
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String, nullable=False)
    fingerprint = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    company = relationship("Company", back_populates="sources")
    entries = relationship("Entry", back_populates="source")

    __table_args__ = (
        Index("idx_sources_company", "company_id"),
        Index("idx_sources_fingerprint", "fingerprint"),
    )


class Entry(Base):
    __tablename__ = "entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"))
    title = Column(String, nullable=False)
    category_id = Column(String, nullable=False)
    subcategory_id = Column(String, nullable=False)
    doc_type_id = Column(String)
    status = Column(String, nullable=False, default="new")
    source_type = Column(String, nullable=False)  # upload, photo, email, etc.
    source_label = Column(String, nullable=False, default="")
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    verified_at = Column(DateTime(timezone=True))
    verified_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    transferred_at = Column(DateTime(timezone=True))

    company = relationship("Company", back_populates="entries")
    source = relationship("Source", back_populates="entries")

    __table_args__ = (
        Index("idx_entries_company", "company_id"),
        Index("idx_entries_status", "company_id", "status"),
        Index("idx_entries_category", "company_id", "category_id"),
        Index("idx_entries_created", "company_id", "created_at"),
    )


class DocumentLink(Base):
    __tablename__ = "document_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_entry_id = Column(UUID(as_uuid=True), ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    target_entry_id = Column(UUID(as_uuid=True), ForeignKey("entries.id", ondelete="CASCADE"), nullable=False)
    link_type = Column(String, nullable=False)
    label = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_links_source", "source_entry_id"),
        Index("idx_links_target", "target_entry_id"),
    )


class Connector(Base):
    __tablename__ = "connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    url = Column(String, nullable=False, default="")
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String, nullable=False, default="disabled")
    category_id = Column(String, nullable=False)
    interval_sec = Column(Integer, nullable=False, default=3600)
    last_sync = Column(DateTime(timezone=True))
    records_count = Column(Integer, nullable=False, default=0)
    errors_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    company = relationship("Company", back_populates="connectors")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String)
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ip_address = Column(INET)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_created", "created_at"),
    )


class Settings(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


# ============================================================
# Справочники НСИ (Reference Data)
# ============================================================

class Counterparty(Base):
    __tablename__ = "counterparties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    inn = Column(String, nullable=False)
    kpp = Column(String)
    name = Column(String, nullable=False)
    short_name = Column(String)
    type = Column(String, nullable=False, default="ЮЛ")  # ЮЛ / ФЛ / ИП
    aliases = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    external_ref = Column(String)  # 1С Ref_Key (GUID)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    contracts = relationship("Contract", back_populates="counterparty")

    __table_args__ = (
        Index("idx_cp_company", "company_id"),
        Index("idx_cp_inn_kpp", "company_id", "inn", "kpp", unique=True),
        Index("idx_cp_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "gin_trgm_ops"}),
    )


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    inn = Column(String, nullable=False)
    kpp = Column(String)
    ogrn = Column(String)
    name = Column(String, nullable=False)
    bank_account = Column(String)
    bank_bik = Column(String)
    external_ref = Column(String)  # 1С Ref_Key (GUID)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    contracts = relationship("Contract", back_populates="organization")

    __table_args__ = (
        Index("idx_org_company", "company_id"),
        Index("idx_org_inn_kpp", "company_id", "inn", "kpp", unique=True),
    )


class Nomenclature(Base):
    __tablename__ = "nomenclature"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False, default="796")
    unit_label = Column(String, nullable=False, default="шт")
    vat_rate = Column(Float, nullable=False, default=20)
    external_ref = Column(String)  # 1С Ref_Key (GUID)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_nom_company_code", "company_id", "code", unique=True),
    )


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    number = Column(String, nullable=False)
    date = Column(String)
    counterparty_id = Column(UUID(as_uuid=True), ForeignKey("counterparties.id"))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    type = Column(String, nullable=False, default="Прочее")
    amount_limit = Column(Float)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    counterparty = relationship("Counterparty", back_populates="contracts")
    organization = relationship("Organization", back_populates="contracts")

    __table_args__ = (
        Index("idx_contracts_company", "company_id"),
        Index("idx_contracts_cp", "counterparty_id"),
    )


# ============================================================
# НСИ: Склады + Банковские счета
# ============================================================

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    address = Column(String)
    type = Column(String, nullable=False, default="warehouse")  # warehouse / station / office / other
    external_ref = Column(String)  # 1С Ref_Key
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_wh_company_code", "company_id", "code", unique=True),
    )


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    number = Column(String, nullable=False)
    bank_name = Column(String, nullable=False, default="")
    bik = Column(String, nullable=False, default="")
    corr_account = Column(String)
    currency = Column(String, nullable=False, default="RUB")
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    external_ref = Column(String)  # 1С Ref_Key
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    organization = relationship("Organization")

    __table_args__ = (
        Index("idx_ba_company", "company_id"),
        Index("idx_ba_number", "company_id", "number", unique=True),
    )


# ============================================================
# Интеграция 1С (OneCConnection + OneCSyncLog)
# ============================================================

class OneCConnection(Base):
    __tablename__ = "onec_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False, default="1С:Бухгалтерия")
    odata_url = Column(String, nullable=False)  # http://host/base/odata/standard.odata
    username = Column(String, nullable=False)
    password_encrypted = Column(String, nullable=False)  # Fernet-шифрование
    exchange_path = Column(String)  # путь к папке обмена
    status = Column(String, nullable=False, default="inactive")  # inactive / active / error
    last_sync_at = Column(DateTime(timezone=True))
    sync_interval_sec = Column(Integer, nullable=False, default=300)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    sync_logs = relationship("OneCSyncLog", back_populates="connection", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_onec_conn_company", "company_id"),
    )


class OneCSyncLog(Base):
    __tablename__ = "onec_sync_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("onec_connections.id", ondelete="CASCADE"), nullable=False)
    direction = Column(String, nullable=False)  # inbound / outbound
    sync_type = Column(String, nullable=False)  # catalogs / documents / full / export
    status = Column(String, nullable=False, default="running")  # running / success / error
    items_processed = Column(Integer, nullable=False, default=0)
    items_created = Column(Integer, nullable=False, default=0)
    items_updated = Column(Integer, nullable=False, default=0)
    items_errors = Column(Integer, nullable=False, default=0)
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True))

    connection = relationship("OneCConnection", back_populates="sync_logs")

    __table_args__ = (
        Index("idx_sync_log_conn", "connection_id"),
        Index("idx_sync_log_started", "started_at"),
    )


# ============================================================
# STAGING SCHEMA (Layer 1a)
# ============================================================

class RawEntry(Base):
    __tablename__ = "raw_entries"
    __table_args__ = {"schema": "staging"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String, nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    extracted_text = Column(Text, nullable=False, default="")
    extracted_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    page_count = Column(Integer)
    processing_status = Column(String, nullable=False, default="parsed")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class AiResult(Base):
    __tablename__ = "ai_results"
    __table_args__ = {"schema": "staging"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_entry_id = Column(UUID(as_uuid=True), ForeignKey("staging.raw_entries.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(String)
    subcategory_id = Column(String)
    doc_type_id = Column(String)
    confidence = Column(Float, nullable=False, default=0)
    normalized_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    decision = Column(String, nullable=False, default="pending")
    rejection_reason = Column(String)
    duplicate_of = Column(UUID(as_uuid=True))
    processed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    model_version = Column(String)


class SyncQueue(Base):
    __tablename__ = "sync_queue"
    __table_args__ = {"schema": "staging"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_entry_id = Column(UUID(as_uuid=True), ForeignKey("staging.raw_entries.id", ondelete="CASCADE"), nullable=False)
    direction = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    last_attempt = Column(DateTime(timezone=True))
    error = Column(String)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
