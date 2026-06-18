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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
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
    # Члены компании (M2M через user_companies) — источник истины прав доступа.
    members: Mapped[list["User"]] = relationship(
        secondary="user_companies", back_populates="companies", viewonly=False
    )
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
    # Компания по умолчанию (какую показать первой). Источник истины ПРАВ —
    # user_companies. Nullable: суперадмин может не иметь дефолтной компании.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    # Суперадмин видит и переключает ВСЕ компании без записей в user_companies.
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Связи
    company: Mapped["Company | None"] = relationship(back_populates="users")
    # Доступные компании (M2M через user_companies).
    companies: Mapped[list["Company"]] = relationship(
        secondary="user_companies", back_populates="members", viewonly=False
    )


# ---------------------------------------------------------------------------
# UserCompany — членство пользователя в компании (M2M, источник истины прав)
# ---------------------------------------------------------------------------
class UserCompany(Base):
    __tablename__ = "user_companies"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Роль пользователя В ЭТОЙ компании: user | admin (роль-на-компанию).
    # server_default обязателен: backfill-INSERT миграции v2.0 не указывает role.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", server_default=text("'user'")
    )
    # Должность сотрудника в этой компании (per-company).
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Invitation — приглашение сотрудника в компанию по email
# ---------------------------------------------------------------------------
class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", server_default=text("'user'")
    )
    position: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # SHA256 от сырого токена (сырой токен только в письме, в БД не хранится).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # pending | accepted | revoked
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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

    # Слой данных (см. docs/sverka-spec.md §0):
    # 'raw' (L1) — сырьё из внешнего источника как пришло (status='new'|'recognized')
    # 'clean' (L2) — нормализовано бухгалтером/AI, готово к выгрузке (status='verified')
    # Поле упрощает фильтрацию вместо производной по status.
    layer: Mapped[str] = mapped_column(String(10), nullable=False, default="raw")

    # Lineage: какой raw-Entry породил этот clean-Entry (для diff L1↔L2).
    # NULL для raw-entries и для clean-entries без явной raw-предтечи.
    derived_from_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_entries.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

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
    # v2.5: универсальный снимок ВСЕХ реквизитов источника (L1 RAW) + промо-колонки.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    okpo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Ref_Key головного контрагента (иерархия), если задан
    head_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Ось контрагента: external (внешний) | retail (служебный розничный) |
    # internal (наша организация для внутренних движений). См. TRADELEDGER_COUNTERPARTY_AXIS §6.
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="external", server_default=text("'external'")
    )
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
    # v2.5: универсальный снимок ВСЕХ реквизитов 1С (L1 RAW) + промо-колонки.
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ВидДоговора 1С: СПокупателем | СПоставщиком | СКомитентом | ... (см. SCHEMA_REFS_GIG §2)
    kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # СрокДействия (ISO-дата строкой) и ДоговорЗакрыт
    valid_until: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Охват договора по торговым точкам (НАШ слой, не из 1С):
    # company (вся компания) | locations (набор contract_locations) | unassigned (дефолт).
    # См. TRADELEDGER_COUNTERPARTY_AXIS §5, SCHEMA_REFS_GIG §2a.
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unassigned", server_default=text("'unassigned'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ContractLocation (связь договор ↔ торговая точка — НАШ слой охвата)
# ---------------------------------------------------------------------------
# Заполняется только при Contract.scope_type='locations' (ad-hoc набор точек).
# Для 'company' (вся компания) и 'unassigned' — пусто. Точки контрагента =
# производное (объединение охватов его договоров). См.
# TRADELEDGER_COUNTERPARTY_AXIS §5, SCHEMA_REFS_GIG §2a.
# ---------------------------------------------------------------------------
class ContractLocation(Base):
    __tablename__ = "contract_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("service_locations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_contract_locations", "contract_id", "location_id", unique=True),
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
    # Реквизиты входящего документа поставщика (ТТН №+дата).
    # Композитный ключ сверки ТТН-файл ↔ ПТУ —
    # (counterparty_inn + external_number + external_date + amount).
    external_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # ВидОперации из 1С — критичен для интерпретации проводок ОРП:
    # ОтчетККМОПродажах vs НТТО дают разные формулы НДС/выручки.
    operation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Статус периода — кэш от Period.status на момент загрузки документа.
    # open | closed. В closed-периоде любое расхождение подсвечивается строже
    # (требование МАГ — см. docs/sverka-spec.md §7a).
    period_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="open"
    )
    # Состояние сверки этого документа с парной ClearLedger.DataEntry.
    # pending | none | rounding | minor | material | critical | unmatched
    discrepancy_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    # Короткая свёртка расхождений для строки таблицы UI.
    discrepancy_summary: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    # Полный список расхождений с формулами (см. §7a.3 спецификации).
    discrepancy_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# ReconcileMapping (маппинг внешний ключ → запись в БП ГИГ)
# ---------------------------------------------------------------------------
# Соответствия между ключами источников ClearLedger (station_id из STS,
# артикул топлива, код вида оплаты, артикул номенклатуры из ТТН-файла)
# и записями в Catalog.Склады / Catalog.Номенклатура / Catalog.ВидыОплат БП.
# Используется reconciliation_service для построчного матчинга
# (см. docs/sverka-spec.md §2.5 — каскад артикул → код → имя → AI).

# ---------------------------------------------------------------------------
# ExportPacket (L3 — что мы выгружаем в 1С)
# ---------------------------------------------------------------------------
# Пакет данных, подготовленный для загрузки в БП ГИГ через её расширение
# (TradeLedger.cfe тянет через HTTP API ClearLedger). Один пакет = один или
# несколько target-документов в 1С (агрегация смен в один ОРП, разделение
# ТТН на ПТУ+ПКО и т.п.). См. docs/sverka-spec.md §0.

class ExportPacket(Base):
    __tablename__ = "export_packets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Тип пакета — определяет какой документ ожидается в 1С на выходе.
    # 'shift_orp'   — смена АЗС → ОРП
    # 'purchase_ttn' — ТТН поставщика → ПТУ
    # 'cash_pko'    — кассовая операция → ПКО
    # 'production'  — общепит → ОПЗС
    # 'correction'  — корректировка поступления
    kind: Mapped[str] = mapped_column(String(30), nullable=False)

    # Натуральный ключ идемпотентности = КлючЗагрузки нативного пути .cfe
    # (например TL|СМЕНА|{system}|{station}|{shift}). Частичный UNIQUE-индекс
    # (company_id, idem_key) WHERE status<>'rejected' не даёт задвоить смену
    # при пере-источивании на живой бухгалтерии (блокер №1, см. database.py).
    idem_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Какие clean-DataEntry (L2) пошли в пакет. Один пакет = одна смена
    # (натуральный ключ); JSONB-массив UUID.
    source_entry_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Жизненный цикл пакета:
    # 'draft'    — подготовлен в ClearLedger, не отправлен
    # 'queued'   — поставлен в очередь HTTP-обмена (TradeLedger ещё не забрал)
    # 'sent'     — отдан расширению 1С (получен запросом extension'а)
    # 'acked'    — 1С квитировала: пакет загружен, ссылка на документ известна
    # 'rejected' — 1С отвергла (с указанием причины в reject_reason)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Полезная нагрузка, что мы реально отправили (JSON, сериализация L3).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Когда 1С квитировала — сюда ставится id AccountingDoc, который
    # представляет L4-snapshot этого пакета. Связь L3↔L4.
    target_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_docs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# OneCPolicy — учётная политика организации (срез из РегС.УчетнаяПолитика БП 3.0)
# ---------------------------------------------------------------------------
# Хранит последнюю запись УчетнаяПолитики на организацию. Используется для:
# - Понимания метода оценки МПЗ (FIFO/Средняя) при сверке ОРП/Списания.
# - Режима налогообложения (ОСН/УСН), ставки НДС.
# - Раздельного учёта НДС.

class OneCPolicy(Base):
    __tablename__ = "onec_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_external_ref: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
    organization_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    # Произвольные поля среза учётной политики из БП (PBU/НДС/ставки/раздельный учёт).
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Отдельные часто используемые поля для быстрого SQL-фильтра в UI.
    mpz_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pbu_18_02: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    separate_vat_accounting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# PostingTemplate — справочник ожидаемых проводок по ВидОперации
# ---------------------------------------------------------------------------
# При проведении документа определённого ВидОперации 1С формирует
# характерный набор проводок (например ОРП ВидОп=ОтчетККМОПродажах →
# 90.02.1/41.02 + 62.Р/90.01.1 + 50.01/62.Р + 90.03/68.02).
# Этот шаблон храним локально для подсветки соответствия факт vs ожидание
# в UI Sheet документа.

class PostingTemplate(Base):
    __tablename__ = "posting_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Массив объектов {dt, kt, formula, comment} — что ожидаем.
    expected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NomenclaturePrice(Base):
    """Срез РегС.ЦеныНоменклатуры из БП ГИГ — оптовые/розничные/закупочные
    цены номенклатуры на дату. Используем для:
      - проверки входной цены ТТН против актуальной закупочной цены
      - сверки розничной выручки против актуальной розничной цены
      - подсветки отклонений в DocumentsPage.
    Уникальность по (company_id, nomenclature_ref, price_type, period)."""
    __tablename__ = "nomenclature_prices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # GUID Catalog.Номенклатура — джойнится с NomenclatureItem.external_ref.
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nomenclature_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # GUID Catalog.ВидыЦен (Оптовая, Розничная, Закупочная и т.п.)
    price_type_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    price_type_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True, default="RUB")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryBatch(Base):
    """Партия товара (FIFO) — остаток по регистратору-документу.

    В БП 3.0 ред.3 источник:
      1) РегистрНакопления.ПартииТоваровНаСкладах (виртуальная Остатки) —
         основной канал. Если регистр пуст (часто на розничных АЗС с
         учётом по средней) — пробуем второй вариант.
      2) Аналитика по счёту 41.01 через СубконтоДт2 (партии-документы)
         регистра РегистрБухгалтерии.Хозрасчетный.

    Регистратор-партия — обычно ПТУ или ВводОстатков.
    """
    __tablename__ = "inventory_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Документ-регистратор партии (ПТУ/ВводОстатков/Корректировка)
    batch_doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_doc_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_doc_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_doc_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Аналитика
    nomenclature_ref: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nomenclature_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warehouse_ref: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    organization_ref: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Остатки на момент среза
    quantity_remaining: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    amount_remaining: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Источник данных: 'register' (РегистрНакопления) | 'postings' (бухсчёт)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="register")
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReconcileMapping(Base):
    __tablename__ = "reconcile_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Маппинг уровня КАНАЛА (override) — значения в STS/TradeCorp/MSTO/ЦБ
    # называются по-разному. NULL = дефолт компании (общий для всех каналов).
    # Резолв: channel_id-specific → company-default(NULL) → канон-сид.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # Тип маппинга: 'station' | 'fuel' | 'paytype' | 'nomenclature' | 'counterparty'
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Ключ во внешнем источнике (station_id STS, артикул поставщика, pay_type STS).
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # external_ref записи в Catalog (GUID в БП) — JOIN на Counterparty/Warehouse/...
    target_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    # Имя цели для UI (кеш — обновляется при sync_catalogs)
    target_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 0..100, насколько уверены в маппинге
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Как создан: 'manual' | 'auto' | 'ai' | 'imported_from_bp'
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # Комментарий пользователя
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
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


# ===========================================================================
# CHANNEL SUBSYSTEM — подсистема входных каналов (Шаг 1.5)
# ===========================================================================
# Source         — настроенное подключение (STS, ОФД, OData 1С, ...).
# SourceCredentials — зашифрованные креды (Fernet, отдельная таблица).
# Channel        — pipeline обработки: 1+ Source → stages → результат.
# ChannelStream  — что забираем из каждого источника канала.
# ChannelStage   — этап pipeline (fetch / normalize / reconcile / ...).
# ReconcileRule  — правила сверки между потоками.
# ChannelTemplate — шаблон pipeline для типовой задачи.
# SyncLog        — журнал прогонов канала.
# RawBatchRecord — сырой ответ источника (для дебага и переигрывания).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Source (Настроенное подключение)
# ---------------------------------------------------------------------------
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    # Тип источника — соответствует SourceAdapter.source_type
    # ("sts", "onec_odata", "ofd_platforma", "acquiring_sber", ...)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Имя, заданное пользователем («STS ГИГ (65)», «1С Бухгалтерия ГИГ»)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # connected | disconnected | error | draft
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")

    # Не-секретные настройки (URL, login, system_ids — без пароля)
    connection_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# SourceCredentials (Секреты — отдельная таблица, Fernet)
# ---------------------------------------------------------------------------
# Хранение паролей / токенов отдельно от Source — чтобы дамп-эндпоинты
# CRUD случайно не вернули секреты, и чтобы можно было ротировать
# Fernet-ключ без переписывания Source.
# ---------------------------------------------------------------------------
class SourceCredentials(Base):
    __tablename__ = "source_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )

    # Ключ → зашифрованное значение Fernet (base64)
    # Например: {"password": "gAAAAA..."}
    encrypted_values: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Версия шифрования (для будущих миграций ключа)
    cipher_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Channel (Pipeline обработки)
# ---------------------------------------------------------------------------
class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # active | paused | error | draft
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")

    # ID шаблона, из которого канал создан (опционально)
    template_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Расписание: { mode: 'manual'|'interval'|'cron', interval_minutes, cron, ... }
    schedule: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {"mode": "manual", "pause_on_error": True, "max_retries": 3}
    )

    # skip | warn | overwrite
    duplicate_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="skip"
    )

    # Период загрузки (дней назад) — для каналов с дельтой по дате
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Произвольная конфигурация (специфика канала)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Каталог хранения сырых файлов (если канал работает с файлами)
    root_catalog: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    docs_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ChannelStream (Поток данных канала — что из какого Source забираем)
# ---------------------------------------------------------------------------
class ChannelStream(Base):
    __tablename__ = "channel_streams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False
    )

    # ID типа документа в Source.adapter.available_doc_types
    # (например, "shift_report" / "receipt" / "transactions")
    doc_type_id: Mapped[str] = mapped_column(String(100), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    catalog_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# ChannelStage (Этап pipeline канала)
# ---------------------------------------------------------------------------
class ChannelStage(Base):
    __tablename__ = "channel_stages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    # fetch | normalize | reconcile | validate | transform | save
    stage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Для fetch — из какого Source через какой поток
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True
    )
    # Для reconcile — массив stream id
    reconcile_stream_ids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# ReconcileRule (Правило сверки между потоками канала)
# ---------------------------------------------------------------------------
class ReconcileRule(Base):
    __tablename__ = "reconcile_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Минимум 2 stream-id для сверки
    stream_ids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )

    # По какому полю сопоставлять записи между потоками
    match_field: Mapped[str] = mapped_column(String(100), nullable=False)
    # Какие поля сравнивать
    compare_fields: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    # Допустимое расхождение (%)
    tolerance: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# ChannelTemplate (Пользовательский шаблон канала)
# ---------------------------------------------------------------------------
# Шаблоны хранятся также в коде (clearledger/src/templates/), но если
# пользователь модифицировал шаблон — сохраняется в БД компании.
# ---------------------------------------------------------------------------
class ChannelTemplate(Base):
    __tablename__ = "channel_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )

    # Если NULL company_id — это «системный» шаблон из кода
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # Полный JSON шаблона: streams, stages, schedule, default_connection
    template_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# ChannelSyncLog (Журнал прогона канала)
# ---------------------------------------------------------------------------
class ChannelSyncLog(Base):
    __tablename__ = "channel_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # success | partial | error | running
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")

    loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Подробный лог: список событий [{ts, level, event, message}]
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


# ---------------------------------------------------------------------------
# RawBatchRecord (Сырой ответ источника — для дебага и переигрывания)
# ---------------------------------------------------------------------------
# Каждый fetch_delta пишет сюда RawBatch. Полезно когда нормализация
# упадёт на странных данных — можно посмотреть исходник и переиграть.
# ---------------------------------------------------------------------------
class RawBatchRecord(Base):
    __tablename__ = "raw_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True
    )
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_sync_logs.id", ondelete="SET NULL"),
        nullable=True
    )

    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Сырая полезная нагрузка
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Интеграция 1С: подключения и журнал синхронизации
# ---------------------------------------------------------------------------
class OneCConnection(Base):
    __tablename__ = "onec_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # mode='odata' — HTTP-публикация, odata_url хранит URL.
    # mode='com'  — V83.COMConnector, odata_url хранит строку соединения
    # (File=... или Srvr=...;Ref=...). См. services/onec/com_client.py.
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="odata")
    odata_url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    exchange_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="inactive"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_interval_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    sync_logs: Mapped[list["OneCSyncLog"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class OneCSyncLog(Base):
    __tablename__ = "onec_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("onec_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    connection: Mapped["OneCConnection"] = relationship(back_populates="sync_logs")


# ---------------------------------------------------------------------------
# ServiceLocation (Точки обслуживания — АЗС/магазины/офисы)
# ---------------------------------------------------------------------------
# Перенесено из localStorage в бэкенд: точки должны быть общими для всех
# браузеров/пользователей и совпадать с конфигом каналов. id — клиентский
# nanoid (String), чтобы фронт и бэк совпадали без доп. резолва.
# ---------------------------------------------------------------------------
class ServiceLocation(Base):
    __tablename__ = "service_locations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # fuel_station | retail | office | warehouse | other
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    # active | closed | planned
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Привязки к источникам: [{sourceId, config:{system_id,station}, label}]
    source_bindings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Произвольные метаданные (в API — поле metadata)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# LocationTypeDef (Каталог типов точек обслуживания — редактируемый)
# ---------------------------------------------------------------------------
# Тип точки = код + единица + набор полей (схема). Встроенные типы:
# company_id IS NULL (доступны всем, is_builtin=true, не удаляются); кастомные
# типы компании: company_id задан. Значения полей конкретной точки хранятся в
# ServiceLocation.extra_metadata. Нижестоящий код опирается на стабильный `code`
# (например 'fuel_station'), а не на лейбл.
# ---------------------------------------------------------------------------
class LocationTypeDef(Base):
    __tablename__ = "location_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = встроенный (системный) тип; задан = кастомный тип компании
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="MapPin")
    # Единица измерения по умолчанию: л / кВт·ч / шт / "" (нет)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("''"))
    # fuel | energy | goods | food | none — задел под единицы/сверку
    nomenclature_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", server_default=text("'none'")
    )
    # Схема полей типа: [{key,label,type,options?,unit?,required?}] (форма MetadataField)
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Код уникален среди встроенных типов (company_id IS NULL)
        Index(
            "uq_location_types_builtin_code", "code",
            unique=True, postgresql_where=text("company_id IS NULL"),
        ),
        # Код уникален в пределах компании (кастомные типы)
        Index(
            "uq_location_types_company_code", "company_id", "code",
            unique=True, postgresql_where=text("company_id IS NOT NULL"),
        ),
    )
