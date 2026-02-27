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


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_id: str
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse | None = None


# ===== Company =====

class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=50)
    short_name: str | None = None
    profile_id: str
    color: str | None = None
    inn: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    short_name: str | None = None
    profile_id: str | None = None
    color: str | None = None
    inn: str | None = None


class CompanyResponse(BaseModel):
    id: str
    name: str
    slug: str
    short_name: str | None = None
    profile_id: str
    color: str | None = None
    inn: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Stats =====

class KpiResponse(BaseModel):
    uploadedToday: int = Field(alias="uploaded_today", default=0)
    totalVerified: int = Field(alias="total_verified", default=0)
    inProcessing: int = Field(alias="in_processing", default=0)
    errors: int = 0
    transferredToday: int = Field(alias="transferred_today", default=0)

    model_config = {"populate_by_name": True}


class CategoryStatResponse(BaseModel):
    categoryId: str = Field(alias="category_id")
    label: str
    count: int

    model_config = {"populate_by_name": True}


# ===== Settings =====

class CompanyCustomization(BaseModel):
    """Кастомизация профиля — camelCase, совпадает с фронтендом напрямую."""
    disabledCategories: list[str] = Field(default_factory=list)
    disabledSubcategories: list[str] = Field(default_factory=list)
    disabledDocTypes: list[str] = Field(default_factory=list)
    disabledConnectors: list[str] = Field(default_factory=list)


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


# ===== DocumentLink =====

LinkTypeEnum = Literal[
    "email-attachment", "duplicate", "related",
    "correction", "manual", "subordinate",
]


class DocumentLinkCreate(BaseModel):
    source_entry_id: str
    target_entry_id: str
    link_type: LinkTypeEnum
    label: str | None = None


class DocumentLinkResponse(BaseModel):
    id: str
    source_entry_id: str
    target_entry_id: str
    link_type: str
    label: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


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


# ===== НСИ: Reference Data =====
# camelCase для прямой совместимости с фронтендом (referenceService.ts)

CounterpartyTypeEnum = Literal["ЮЛ", "ФЛ", "ИП"]


class CounterpartyCreate(BaseModel):
    company_id: str
    inn: str
    kpp: str | None = None
    name: str = Field(min_length=1, max_length=500)
    shortName: str | None = None
    type: CounterpartyTypeEnum = "ЮЛ"
    aliases: list[str] = Field(default_factory=list)


class CounterpartyUpdate(BaseModel):
    inn: str | None = None
    kpp: str | None = None
    name: str | None = None
    shortName: str | None = None
    type: CounterpartyTypeEnum | None = None
    aliases: list[str] | None = None


class CounterpartyResponse(BaseModel):
    id: str
    companyId: str
    inn: str
    kpp: str | None = None
    name: str
    shortName: str | None = None
    type: str
    aliases: list[str]
    createdAt: str
    updatedAt: str


class OrganizationCreate(BaseModel):
    company_id: str
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str = Field(min_length=1, max_length=500)
    bankAccount: str | None = None
    bankBik: str | None = None


class OrganizationUpdate(BaseModel):
    inn: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    name: str | None = None
    bankAccount: str | None = None
    bankBik: str | None = None


class OrganizationResponse(BaseModel):
    id: str
    companyId: str
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str
    bankAccount: str | None = None
    bankBik: str | None = None
    createdAt: str
    updatedAt: str


class NomenclatureCreate(BaseModel):
    company_id: str
    code: str
    name: str = Field(min_length=1, max_length=500)
    unit: str
    unitLabel: str = ""
    vatRate: int = 20


class NomenclatureUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    unit: str | None = None
    unitLabel: str | None = None
    vatRate: int | None = None


class NomenclatureResponse(BaseModel):
    id: str
    companyId: str
    code: str
    name: str
    unit: str
    unitLabel: str
    vatRate: int
    createdAt: str
    updatedAt: str


class ContractCreate(BaseModel):
    company_id: str
    number: str
    date: str
    counterpartyId: str
    organizationId: str
    type: str
    amountLimit: float | None = None


class ContractUpdate(BaseModel):
    number: str | None = None
    date: str | None = None
    counterpartyId: str | None = None
    organizationId: str | None = None
    type: str | None = None
    amountLimit: float | None = None


class ContractResponse(BaseModel):
    id: str
    companyId: str
    number: str
    date: str
    counterpartyId: str
    organizationId: str
    type: str
    amountLimit: float | None = None
    createdAt: str
    updatedAt: str


# ===== AccountingDoc (Учётные документы 1С) =====

AccountingDocTypeEnum = Literal[
    "receipt", "invoice-received", "payment-out", "payment-in",
    "sales", "invoice-issued", "reconciliation",
]

MatchStatusEnum = Literal["matched", "unmatched", "discrepancy", "pending"]


class AccountingDocLineSchema(BaseModel):
    nomenclatureCode: str | None = None
    nomenclatureName: str
    quantity: float
    price: float
    amount: float
    vatRate: float = 20
    vatAmount: float | None = None


class AccountingDocCreate(BaseModel):
    company_id: str
    external_id: str
    doc_type: AccountingDocTypeEnum
    number: str
    date: str
    counterparty_name: str = ""
    counterparty_inn: str | None = None
    organization_name: str | None = None
    amount: float = 0
    vat_amount: float | None = None
    status_1c: str = "Проведён"
    lines: list[AccountingDocLineSchema] = Field(default_factory=list)
    warehouse_code: str | None = None


class AccountingDocUpdate(BaseModel):
    match_status: MatchStatusEnum | None = None
    matched_entry_id: str | None = None
    match_details: dict | None = None


class AccountingDocResponse(BaseModel):
    id: str
    companyId: str
    externalId: str
    docType: str
    number: str
    date: str
    counterpartyName: str
    counterpartyInn: str | None = None
    organizationName: str | None = None
    amount: float
    vatAmount: float | None = None
    status1c: str
    lines: list[AccountingDocLineSchema]
    matchedEntryId: str | None = None
    matchStatus: str
    matchDetails: dict | None = None
    warehouseCode: str | None = None
    createdAt: str
    updatedAt: str


class AccountingDocImportRequest(BaseModel):
    company_id: str
    docs: list[AccountingDocCreate]


class AccountingDocImportResponse(BaseModel):
    total: int
    created: int
    updated: int
    errors: list[str] = Field(default_factory=list)


# ===== Reconciliation =====

class ReconciliationSummaryResponse(BaseModel):
    matched: int = 0
    unmatchedAcc: int = 0
    unmatchedEntry: int = 0
    discrepancy: int = 0
    totalAccDocs: int = 0
    totalEntries: int = 0


class ManualMatchRequest(BaseModel):
    doc_id: str
    entry_id: str


class UnmatchRequest(BaseModel):
    doc_id: str


# ===== НСИ: Warehouse (Склады) =====

WarehouseTypeEnum = Literal["warehouse", "station", "office", "other"]


class WarehouseCreate(BaseModel):
    company_id: str
    code: str
    name: str = Field(min_length=1, max_length=500)
    address: str | None = None
    type: WarehouseTypeEnum = "warehouse"


class WarehouseUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    address: str | None = None
    type: WarehouseTypeEnum | None = None


class WarehouseResponse(BaseModel):
    id: str
    companyId: str
    code: str
    name: str
    address: str | None = None
    type: str
    createdAt: str
    updatedAt: str


# ===== НСИ: BankAccount (Банковские счета) =====

class BankAccountCreate(BaseModel):
    company_id: str
    number: str
    bankName: str = ""
    bik: str
    corrAccount: str | None = None
    currency: str = "RUB"
    organizationId: str | None = None


class BankAccountUpdate(BaseModel):
    number: str | None = None
    bankName: str | None = None
    bik: str | None = None
    corrAccount: str | None = None
    currency: str | None = None
    organizationId: str | None = None


class BankAccountResponse(BaseModel):
    id: str
    companyId: str
    number: str
    bankName: str
    bik: str
    corrAccount: str | None = None
    currency: str
    organizationId: str | None = None
    createdAt: str
    updatedAt: str
