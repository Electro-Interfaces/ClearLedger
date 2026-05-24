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
    cloud_api_key: str | None = None


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
    # meta может содержать произвольные структуры (fuel_breakdown[], массивы
    # видов оплат, вложенные dict) — не ограничиваем str.
    metadata: dict
    ocr_data: dict | None = None
    source_id: str | None = None
    # Слой данных (см. docs/sverka-spec.md §0): raw (L1) | clean (L2).
    layer: str = "raw"
    derived_from_entry_id: str | None = None
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
    # lines может быть list (старая структура — построчные данные ClearLedger)
    # или dict {tabular, postings, fetched_at} (новая — данные из 1С через
    # fetch_doc_lines + fetch_postings). См. docs/sverka-spec.md §3.1.
    lines: list[AccountingDocLineSchema] | dict
    matchedEntryId: str | None = None
    matchStatus: str
    matchDetails: dict | None = None
    warehouseCode: str | None = None
    # Расширенные поля для сверки (docs/sverka-spec.md §7a):
    externalNumber: str | None = None      # № входящего документа поставщика (ТТН №)
    externalDate: str | None = None        # дата входящего документа (ТТН дата)
    operationType: str | None = None       # ВидОперации из 1С
    periodStatus: str = "open"             # open | closed (из таблицы periods)
    discrepancyStatus: str = "pending"     # pending | none | rounding | minor | material | critical | unmatched
    discrepancySummary: str | None = None  # короткая свёртка для строки таблицы
    discrepancyDetails: list | dict | None = None  # полный список расхождений
    createdAt: str
    updatedAt: str


class AccountingDocsPage(BaseModel):
    items: list[AccountingDocResponse]
    total: int
    limit: int
    offset: int


class AccountingDocsStats(BaseModel):
    total: int
    byType: dict[str, int]
    bySource: dict[str, int]


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
    company_id: str
    doc_id: str
    entry_id: str


class UnmatchRequest(BaseModel):
    company_id: str
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


# ===== НСИ: пагинированные ответы для UI справочников =====

class CounterpartiesPage(BaseModel):
    items: list[CounterpartyResponse]
    total: int
    limit: int
    offset: int


class OrganizationsPage(BaseModel):
    items: list[OrganizationResponse]
    total: int
    limit: int
    offset: int


class NomenclaturePage(BaseModel):
    items: list[NomenclatureResponse]
    total: int
    limit: int
    offset: int


class WarehousesPage(BaseModel):
    items: list[WarehouseResponse]
    total: int
    limit: int
    offset: int


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


# ===== Интеграция 1С =====

class OneCConnectionCreate(BaseModel):
    company_id: str
    name: str = Field(default="1С:Бухгалтерия", max_length=255)
    mode: Literal["odata", "com"] = "odata"
    odata_url: str = Field(min_length=1, max_length=500)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    exchange_path: str | None = None
    sync_interval_sec: int = Field(default=300, ge=60, le=86400)


class OneCConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    mode: Literal["odata", "com"] | None = None
    odata_url: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = None
    exchange_path: str | None = None
    sync_interval_sec: int | None = Field(default=None, ge=60, le=86400)
    status: Literal["inactive", "active", "error"] | None = None


class OneCConnectionResponse(BaseModel):
    id: str
    company_id: str
    name: str
    mode: str
    odata_url: str
    username: str
    exchange_path: str | None = None
    status: str
    last_sync_at: datetime | None = None
    sync_interval_sec: int
    created_at: datetime
    updated_at: datetime


class OneCTestResult(BaseModel):
    available: bool
    catalogs: list[str] = Field(default_factory=list)
    error: str | None = None


class OneCSyncStats(BaseModel):
    processed: int = 0
    created: int = 0
    updated: int = 0
    errors: int = 0


class OneCSyncResult(BaseModel):
    status: str
    stats: OneCSyncStats
    details: dict = Field(default_factory=dict)
    log_id: str


class OneCSyncLogResponse(BaseModel):
    id: str
    connection_id: str
    direction: str
    sync_type: str
    status: str
    items_processed: int
    items_created: int
    items_updated: int
    items_errors: int
    details: dict
    started_at: datetime
    finished_at: datetime | None = None


class OneCSyncStatusResponse(BaseModel):
    is_syncing: bool
    current_log: OneCSyncLogResponse | None = None
    connection_status: str
    last_sync_at: datetime | None = None


# ===== Export Packets (L3 — docs/sverka-spec.md §0) =====

ExportPacketKind = Literal["shift_orp", "purchase_ttn", "cash_pko", "production", "correction"]
ExportPacketStatus = Literal["draft", "queued", "sent", "acked", "rejected"]


class ExportPacketCreate(BaseModel):
    company_id: str
    kind: ExportPacketKind
    source_entry_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class ExportPacketUpdate(BaseModel):
    status: ExportPacketStatus | None = None
    payload: dict | None = None
    sent_at: datetime | None = None
    acked_at: datetime | None = None
    reject_reason: str | None = None
    target_doc_id: str | None = None


class ExportPacketResponse(BaseModel):
    id: str
    companyId: str = Field(alias="company_id")
    kind: str
    sourceEntryIds: list[str] = Field(alias="source_entry_ids")
    status: str
    payload: dict
    sentAt: datetime | None = Field(default=None, alias="sent_at")
    ackedAt: datetime | None = Field(default=None, alias="acked_at")
    rejectReason: str | None = Field(default=None, alias="reject_reason")
    targetDocId: str | None = Field(default=None, alias="target_doc_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")
    model_config = {"populate_by_name": True}


# ===== Reconcile Mappings (docs/sverka-spec.md §4) =====

ReconcileMappingKind = Literal["station", "fuel", "paytype", "nomenclature", "counterparty"]
ReconcileMappingMethod = Literal["manual", "auto", "ai", "imported_from_bp"]


class ReconcileMappingCreate(BaseModel):
    company_id: str
    kind: ReconcileMappingKind
    source_key: str = Field(min_length=1, max_length=255)
    target_ref: str = Field(min_length=1, max_length=36)
    target_name: str | None = None
    confidence: int = Field(default=100, ge=0, le=100)
    method: ReconcileMappingMethod = "manual"
    note: str | None = None


class ReconcileMappingUpdate(BaseModel):
    source_key: str | None = Field(default=None, max_length=255)
    target_ref: str | None = Field(default=None, max_length=36)
    target_name: str | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    method: ReconcileMappingMethod | None = None
    note: str | None = None


class ReconcileMappingResponse(BaseModel):
    id: str
    companyId: str = Field(alias="company_id")
    kind: str
    sourceKey: str = Field(alias="source_key")
    targetRef: str = Field(alias="target_ref")
    targetName: str | None = Field(default=None, alias="target_name")
    confidence: int
    method: str
    note: str | None = None
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")
    model_config = {"populate_by_name": True, "from_attributes": True}
