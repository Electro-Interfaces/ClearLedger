"""
Pydantic v2 схемы — Request / Response для всех сущностей.
snake_case на стороне Python; apiClient на фронте конвертирует camelCase <-> snake_case.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# ===== Auth =====

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=255)
    company_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Company =====

class CompanyResponse(BaseModel):
    id: str
    name: str
    slug: str
    profile_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== DataEntry =====

EntryStatusType = Literal[
    "new", "recognized", "verified", "transferred", "error", "archived"
]

EntrySourceType = Literal[
    "upload", "photo", "manual", "api", "email",
    "oneC", "whatsapp", "telegram", "paste",
]


class DataEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    category_id: str
    subcategory_id: str
    doc_type_id: str | None = None
    company_id: str
    status: EntryStatusType = "new"
    source: EntrySourceType = "manual"
    source_label: str = ""
    file_url: str | None = None
    file_type: str | None = None
    file_size: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    ocr_data: dict | None = None
    source_id: str | None = None


class DataEntryUpdate(BaseModel):
    title: str | None = None
    category_id: str | None = None
    subcategory_id: str | None = None
    doc_type_id: str | None = None
    status: EntryStatusType | None = None
    source_label: str | None = None
    metadata: dict[str, str] | None = None
    ocr_data: dict | None = None


class DataEntryResponse(BaseModel):
    id: str
    title: str
    category_id: str
    subcategory_id: str
    doc_type_id: str | None = None
    company_id: str
    status: str
    source: str
    source_label: str
    file_url: str | None = None
    file_type: str | None = None
    file_size: int | None = None
    metadata: dict[str, str]
    ocr_data: dict | None = None
    source_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedEntries(BaseModel):
    items: list[DataEntryResponse]
    total: int


class RejectBody(BaseModel):
    reason: str | None = None


class TransferBody(BaseModel):
    ids: list[str]


# ===== AuditEvent =====

AuditActionType = Literal[
    "created", "verified", "rejected", "transferred",
    "archived", "restored", "excluded", "included",
    "updated", "version_created", "exported",
    "bulk_archived", "bulk_excluded", "connector_synced",
]


class AuditEventResponse(BaseModel):
    id: str
    entry_id: str | None = None
    company_id: str
    user_id: str
    user_name: str
    action: str
    details: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class PaginatedAudit(BaseModel):
    items: list[AuditEventResponse]
    total: int


# ===== Connector =====

ConnectorStatusType = Literal["active", "error", "disabled"]
SyncStatusType = Literal["idle", "syncing", "synced", "error"]


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str
    url: str = ""
    company_id: str
    status: ConnectorStatusType = "active"
    category_id: str
    interval: int = 3600
    config: dict = Field(default_factory=dict)


class ConnectorUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    status: ConnectorStatusType | None = None
    category_id: str | None = None
    interval: int | None = None
    config: dict | None = None


class ConnectorResponse(BaseModel):
    id: str
    name: str
    type: str
    url: str
    company_id: str
    status: str
    last_sync: str | None = None
    last_sync_at: datetime | None = None
    sync_status: str
    records_count: int
    errors_count: int
    category_id: str
    interval: int
    config: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Reports =====

class PeriodReport(BaseModel):
    date_from: str
    date_to: str
    uploaded: int
    verified: int
    rejected: int
    transferred: int
    archived: int
    avg_verification_time_ms: float | None = None


class CounterpartyStat(BaseModel):
    counterparty: str
    count: int
    verified: int
    rejected: int


class SourceStat(BaseModel):
    source: str
    label: str
    count: int


class ErrorStat(BaseModel):
    reason: str
    count: int


# ===== OCR =====

class OcrField(BaseModel):
    key: str
    label: str
    value: str
    confidence: float


class OcrResponse(BaseModel):
    text: str
    fields: list[OcrField]
    confidence: float
    metadata: dict[str, str] = Field(default_factory=dict)
