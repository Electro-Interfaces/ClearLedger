"""
Pydantic v2 схемы — Request / Response для всех сущностей.
snake_case на стороне Python; apiClient на фронте конвертирует camelCase <-> snake_case.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field


def _normalize_email(value: str) -> str:
    """Единая нормализация email: обрезка пробелов + нижний регистр.
    Гарантирует, что логин, регистрация, сброс пароля и приглашения работают
    с одним и тем же значением (иначе письмо сброса не находит пользователя,
    а `User@x` и `user@x` создаются как разные аккаунты)."""
    return value.strip().lower()


# Email с нормализацией на входе. EmailStr валидирует формат, AfterValidator —
# приводит к канону. Использовать во ВСЕХ схемах, где email приходит от клиента.
NormEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]


# ===== Auth =====

class LoginRequest(BaseModel):
    email: NormEmail
    password: str = Field(min_length=4)


class ForgotPasswordRequest(BaseModel):
    email: NormEmail


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=6)


class RegisterRequest(BaseModel):
    email: NormEmail
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=255)
    company_id: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_id: str | None = None  # компания по умолчанию (может быть None у суперадмина)
    is_superadmin: bool = False
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse | None = None


class CompanyBrief(BaseModel):
    """Краткая карточка компании для списка доступных пользователю (/auth/me)."""
    id: str
    slug: str
    name: str
    short_name: str | None = None
    color: str | None = None
    profile_id: str
    role: str = "user"   # роль пользователя в этой компании (user|admin); суперадмин — admin
    modules: list[str] | None = None   # RBAC: разрешённые модули; null = полный доступ


class MeResponse(BaseModel):
    """Текущий пользователь + список доступных компаний (для мультитенантности)."""
    id: str
    email: str
    name: str
    role: str
    is_superadmin: bool
    default_company_id: str | None = None
    companies: list[CompanyBrief]


# ===== Управление пользователями (админ компании) =====

class UserCreate(BaseModel):
    company_id: str
    email: NormEmail
    name: str = Field(min_length=1, max_length=255)   # ФИО
    password: str = Field(min_length=6)
    role: Literal["user", "admin"] = "user"
    position: str | None = Field(None, max_length=150)  # должность


class UserAdminUpdate(BaseModel):
    company_id: str | None = None   # контекст компании (для админа компании); суперадмин может без него
    name: str | None = None         # ФИО (глобально)
    role: Literal["user", "admin"] | None = None
    position: str | None = None     # должность (per-company); "" → очистить
    # Принадлежность к пространству: свой сотрудник или внешний участник (подрядчик,
    # поставщик). Это НЕ права — права в role; это «кто он», видно в чатах и заявках.
    party_type: Literal["internal", "partner", "vendor"] | None = None
    # Какую организацию представляет внешний участник (id карточки юрлица); "" → очистить.
    organization_id: str | None = None


class CompanyMembership(BaseModel):
    """Членство пользователя в компании с ролью и должностью в ней."""
    slug: str
    name: str
    role: str
    position: str | None = None
    modules: list[str] | None = None   # RBAC: разрешённые модули; null = полный доступ


class MemberModulesUpdate(BaseModel):
    """Смена набора модулей доступа члена компании. modules=null → полный доступ."""
    company_id: str
    modules: list[str] | None = None


class MemberAccessUpdate(BaseModel):
    """Назначение доступа члену: именованная роль ИЛИ ad-hoc набор модулей."""
    company_id: str
    mode: Literal["role", "custom"] = "custom"
    role_id: str | None = None          # для mode="role"
    modules: list[str] | None = None    # для mode="custom"; null = полный доступ


class MemberScopeUpdate(BaseModel):
    """Скоуп данных члена — объекты, по которым он видит данные.

    Ортогонален правам: `modules` решают, какие экраны открыты, `object_scope` —
    по каким объектам на них видны данные. null или пусто = вся сеть компании.
    """
    company_id: str
    object_scope: list[str] | None = None


# ===== Роли доступа (hybrid RBAC) =====

class CompanyRoleResponse(BaseModel):
    id: str
    name: str
    modules: list[str] | None = None    # null = все модули
    is_system: bool = False
    members_count: int = 0


class CompanyRoleCreate(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=100)
    modules: list[str] | None = None


class CompanyRoleUpdate(BaseModel):
    company_id: str
    name: str = Field(min_length=1, max_length=100)
    modules: list[str] | None = None    # полная замена набора


class UserAdminResponse(BaseModel):
    id: str
    email: str
    name: str                       # ФИО
    role: str                       # роль в контексте запроса (компании) или глобальная
    position: str | None = None     # должность в контексте компании
    party_type: str | None = None   # internal | partner — свой сотрудник или внешний участник
    organization_id: str | None = None   # кого представляет внешний участник
    organization_name: str | None = None # имя организации (для UI)
    modules: list[str] | None = None  # эффективные RBAC-модули; null = полный доступ
    role_id: str | None = None      # назначенная именованная роль доступа (company_roles)
    role_name: str | None = None    # имя назначенной роли (для UI)
    object_scope: list[str] | None = None  # скоуп данных: объекты; null = вся сеть
    is_superadmin: bool
    companies: list[CompanyMembership] = []


class GrantCompanyBody(BaseModel):
    company_id: str                 # slug или UUID компании для выдачи членства
    role: Literal["user", "admin"] = "user"


# ===== Приглашения сотрудников =====

class InvitationCreate(BaseModel):
    company_id: str
    email: NormEmail
    role: Literal["user", "admin"] = "user"
    position: str | None = Field(None, max_length=150)


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    position: str | None = None
    status: str
    created_at: datetime
    expires_at: datetime
    # Ссылка отдаётся ТОЛЬКО в ответ на создание и перевыпуск: токен хранится
    # хешем, восстановить его позже нельзя. Нужна, чтобы админ мог передать
    # приглашение мессенджером, не полагаясь на почту.
    invite_url: str | None = None
    # Честный признак: ушло письмо или SMTP не сконфигурирован. Без него
    # интерфейс рапортовал «отправлено» даже когда почта не настроена.
    email_sent: bool | None = None


class AcceptPreview(BaseModel):
    """Данные для страницы принятия приглашения (публичные)."""
    email: str
    company_name: str
    role: str
    user_exists: bool


class AcceptInvite(BaseModel):
    name: str | None = Field(None, max_length=255)
    password: str | None = Field(None, min_length=6)


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


class _CpExtra(BaseModel):
    """Расширенные реквизиты контрагента — полная карточка (ручной ввод + промо из raw)."""
    fullName: str | None = None
    okpo: str | None = None
    ogrn: str | None = None
    okved: str | None = None
    legalAddress: str | None = None
    actualAddress: str | None = None
    phone: str | None = None
    email: str | None = None
    directorName: str | None = None
    directorPosition: str | None = None
    bankAccount: str | None = None
    bankBik: str | None = None
    bankName: str | None = None


class CounterpartyCreate(_CpExtra):
    company_id: str
    inn: str
    kpp: str | None = None
    name: str = Field(min_length=1, max_length=500)
    shortName: str | None = None
    type: CounterpartyTypeEnum = "ЮЛ"
    aliases: list[str] = Field(default_factory=list)


class CounterpartyUpdate(_CpExtra):
    inn: str | None = None
    kpp: str | None = None
    name: str | None = None
    shortName: str | None = None
    type: CounterpartyTypeEnum | None = None
    aliases: list[str] | None = None


class CounterpartyResponse(_CpExtra):
    id: str
    companyId: str
    inn: str
    kpp: str | None = None
    name: str
    shortName: str | None = None
    type: str
    kind: str = "external"
    aliases: list[str]
    headRef: str | None = None        # Ref_Key головного контрагента (иерархия)
    externalRef: str | None = None
    raw: dict | None = None           # полный снимок реквизитов 1С
    createdAt: str
    updatedAt: str


class _OrgExtra(BaseModel):
    """Расширенные реквизиты организации — полная карточка БП 3.0."""
    bankAccount: str | None = None
    bankBik: str | None = None
    # Идентификация
    vid: str | None = None               # ЮЛ / ИП / ОП / ФЛ
    fullName: str | None = None
    prefix: str | None = None
    okpo: str | None = None
    # Государственная регистрация
    regDate: str | None = None
    okved: str | None = None
    oktmo: str | None = None
    okato: str | None = None
    okopf: str | None = None
    okfs: str | None = None
    registrationCert: str | None = None
    # Налоговый орган и фонды
    ifnsCode: str | None = None
    ifnsName: str | None = None
    pfrRegNumber: str | None = None
    fssRegNumber: str | None = None
    fssSubordination: str | None = None
    # Адреса и контакты
    legalAddress: str | None = None
    actualAddress: str | None = None
    postalAddress: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    # Ответственные лица
    directorName: str | None = None
    directorPosition: str | None = None
    accountantName: str | None = None
    cashierName: str | None = None


class OrganizationCreate(_OrgExtra):
    company_id: str
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str = Field(min_length=1, max_length=500)


class OrganizationUpdate(_OrgExtra):
    inn: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    name: str | None = None


class OrganizationResponse(_OrgExtra):
    id: str
    companyId: str
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name: str
    externalRef: str | None = None   # Ref_Key из 1С (None → заведена вручную)
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
    externalRef: str | None = None    # GUID номенклатуры в 1С (для маппингов)
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
    kind: str | None = None
    currency: str | None = None
    validUntil: str | None = None
    vatRate: str | None = None
    amountInclVat: bool | None = None
    settlementKind: str | None = None
    comment: str | None = None
    basis: str | None = None
    isClosed: bool = False
    scopeType: str = "unassigned"


class ContractUpdate(BaseModel):
    number: str | None = None
    date: str | None = None
    counterpartyId: str | None = None
    organizationId: str | None = None
    type: str | None = None
    amountLimit: float | None = None
    kind: str | None = None
    currency: str | None = None
    validUntil: str | None = None
    vatRate: str | None = None
    amountInclVat: bool | None = None
    settlementKind: str | None = None
    comment: str | None = None
    basis: str | None = None
    isClosed: bool | None = None
    scopeType: str | None = None


class ContractResponse(BaseModel):
    id: str
    companyId: str
    number: str
    date: str
    counterpartyId: str
    organizationId: str
    type: str
    amountLimit: float | None = None
    kind: str | None = None
    currency: str | None = None
    validUntil: str | None = None
    vatRate: str | None = None
    amountInclVat: bool | None = None
    settlementKind: str | None = None
    comment: str | None = None
    basis: str | None = None
    isClosed: bool = False
    scopeType: str = "unassigned"
    externalRef: str | None = None
    raw: dict | None = None           # полный снимок реквизитов 1С
    createdAt: str
    updatedAt: str


# ===== Платёжная дисциплина по станции × роль (v2.8) =====
# Реестр «Договоры и оплаты ЭЗС» (energy/РусГидро). См.
# SOURCE_CONTRACTS_PAYMENTS_RUSHYDRO.md.

class SettlementUpsert(BaseModel):
    company_id: str
    locationId: str
    role: str                              # energy | rent
    contractId: str | None = None
    counterpartyId: str | None = None
    paidThrough: str | None = None         # ISO 'YYYY-MM-01' (оплачено по)
    paymentStatus: str = "unknown"         # paid | unpaid | unknown | special
    basis: str | None = None               # договор | разрешение | постановление | ...
    comment: str | None = None
    period: str | None = None
    source: str | None = None


class SettlementResponse(BaseModel):
    id: str
    companyId: str
    locationId: str
    role: str
    contractId: str | None = None
    counterpartyId: str | None = None
    paidThrough: str | None = None
    paymentStatus: str
    basis: str | None = None
    comment: str | None = None
    period: str | None = None
    createdAt: str
    updatedAt: str


class SettlementDetail(BaseModel):
    """Строка детализации платёжной дисциплины: станция × контрагент × договор × оплата."""
    locationId: str
    stationCode: str | None = None
    stationName: str | None = None
    buNumber: str | None = None
    role: str
    counterpartyId: str | None = None      # мягкая ссылка (UUID Counterparty или GUID 1С)
    counterpartyName: str | None = None
    contractNumber: str | None = None
    basis: str | None = None
    paidThrough: str | None = None
    paymentStatus: str
    comment: str | None = None
    # v2.10 (реестры РусГидро): ежемесячная плата (постоянная часть) и сроки договора.
    amountGross: float | None = None       # с НДС, руб/мес
    amountNet: float | None = None         # без НДС, руб/мес
    vatPct: float | None = None
    contractStart: str | None = None
    contractEnd: str | None = None
    extra: dict | None = None              # переменная часть/сроки оплаты/ср. тариф...


class EnergyPeriodPoint(BaseModel):
    """Месяц входящей э/э по сети: объём, средний тариф, оценка стоимости."""
    period: str                            # 'YYYY-MM-01'
    kwh: float = 0                         # Σ объёма входящей э/э
    stations: int = 0                      # станций с объёмом
    tariffAvg: float | None = None         # средний входящий тариф (реальный, из файла тарифов), руб/кВт·ч с НДС
    tariffEst: float | None = None         # оценочный тариф: средневзвеш. по объёму, использованный для costEst (для месяцев без сетки)
    costEst: float | None = None           # оценка стоимости: Σ kwh×тариф (мес или ср. станции)
    saleKwh: float | None = None           # реализация: отпущено клиентам в сессиях за месяц, кВт·ч (mv_charge_daily)
    saleRevenue: float | None = None       # выручка реализации, ₽ = Σ coalesce(client_amount, amount)


class EnergySupplierRow(BaseModel):
    """Поставщик э/э: станции на договоре + объём за окно периода."""
    name: str
    inn: str | None = None
    stations: int = 0
    kwh: float = 0                         # Σ объёма по станциям поставщика за окно
    tariffAvg: float | None = None         # средневзвешенный тариф (по объёму)
    unpaid: int = 0                        # станций со статусом «не оплачено»


class EnergyPeriodsSummary(BaseModel):
    """Витрина «Энергозакупка»: реальные объёмы/тарифы входящей э/э по месяцам."""
    series: list[EnergyPeriodPoint] = Field(default_factory=list)
    suppliers: list[EnergySupplierRow] = Field(default_factory=list)
    totalKwh: float = 0
    totalCostEst: float | None = None
    stationsWithVolumes: int = 0
    stationsWithTariff: int = 0
    lastPeriod: str | None = None


class ReestrStreamStat(BaseModel):
    """Поток канала реестров: строки L1 и сопряжение со справочником объектов."""
    stream: str                            # svodnaya | arenda | tariffs | svod
    label: str
    l1Rows: int = 0
    resolved: int = 0                      # строк, сопоставленных с объектом
    orphans: int = 0                       # строк без объекта («сироты»)


class ReestrOrphanRow(BaseModel):
    """Строка реестра без объекта в справочнике (кандидат на дозагрузку станций)."""
    stream: str
    bu: str | None = None                  # № по БУ
    zoi: str | None = None                 # № ZOI-1
    name: str | None = None
    kwh: float | None = None               # Σ объёма э/э (важность для «Сводной»)


class ReestrEntityStat(BaseModel):
    """L2-сущность, которую наполняет канал реестров."""
    key: str                               # counterparties | contracts | settlements | periods
    label: str
    records: int = 0
    note: str | None = None


class ReestrModel(BaseModel):
    """Модель нормализации канала реестров: потоки (L1) → сопряжение со
    справочником объектов → L2-сущности. Аналог charge-sessions/model."""
    streams: list[ReestrStreamStat] = Field(default_factory=list)
    entities: list[ReestrEntityStat] = Field(default_factory=list)
    orphans: list[ReestrOrphanRow] = Field(default_factory=list)
    objectsLinked: int = 0                 # уникальных объектов с данными реестра
    objectsTotal: int = 0                  # объектов в справочнике (для %)


class DispenseReconMonth(BaseModel):
    """Месяц сверки: отпуск по сводной выработке vs сумма зарядных сессий."""
    period: str                            # 'YYYY-MM-01'
    fileKwh: float = 0                     # кВт·ч по сводной (слот obshaya)
    sessionsKwh: float = 0                 # кВт·ч по charge_sessions
    deltaKwh: float = 0                    # file − sessions
    deltaPct: float | None = None          # delta / sessions, %
    fileStations: int = 0
    sessStations: int = 0


class DispenseReconStation(BaseModel):
    """Станция с наибольшим расхождением сводная↔сессии за пересечение периодов."""
    locationId: str
    name: str
    fileKwh: float = 0
    sessionsKwh: float = 0
    deltaKwh: float = 0


class DispenseRecon(BaseModel):
    """Сверка отпуска: ручная сводная контрагента ↔ транзакционные сессии.
    Месяцы пересечения обоих рядов + полный диапазон сводной для контекста."""
    months: list[DispenseReconMonth] = Field(default_factory=list)
    topStations: list[DispenseReconStation] = Field(default_factory=list)
    filePeriodFrom: str | None = None
    filePeriodTo: str | None = None


class RoleDiscipline(BaseModel):
    """Сводка по одной роли (energy|rent): счётчики статусов оплаты."""
    role: str
    total: int = 0
    paid: int = 0
    unpaid: int = 0
    unknown: int = 0
    special: int = 0
    withProblem: int = 0                    # непустой проблемный комментарий


class PaymentDisciplineSummary(BaseModel):
    """Агрегат для витрин «Дебиторка/взаиморасчёты» и «Энергозакупка» + KPI листа
    «Показатели» (контрагенты без оплат, ЭЗС без договоров)."""
    stationsCovered: int = 0               # станций, по которым есть хоть одна запись
    byRole: list[RoleDiscipline] = Field(default_factory=list)
    stationsNoEnergy: int = 0              # станций без записи энергоснабжения
    stationsNoRent: int = 0               # станций без записи аренды
    counterpartiesUnpaidEnergy: int = 0
    counterpartiesUnpaidRent: int = 0
    l1Raw: int = 0                         # сырьё реестра (DataEntry layer=raw)
    l2Clean: int = 0                       # нормализовано (DataEntry layer=clean)
    settlements: int = 0                   # всего записей платёжной дисциплины


# ===== Ось договор ↔ торговые точки (Фаза 2) =====

class LocationBrief(BaseModel):
    id: str
    code: str
    name: str
    type: str


class CounterpartyBrief(BaseModel):
    externalRef: str | None = None
    name: str
    inn: str | None = None


class ContractScopeUpdate(BaseModel):
    """Установить охват договора по точкам. Для company/unassigned — locationIds игнор."""
    scopeType: str  # company | locations | unassigned
    locationIds: list[str] = Field(default_factory=list)


class CounterpartyLocationsResponse(BaseModel):
    """Где работает контрагент (агрегат по его договорам)."""
    scope: str                      # company | locations | none
    locations: list[LocationBrief]
    contractsCount: int
    unassignedCount: int


class CounterpartyDocGroup(BaseModel):
    """Группа документов БП контрагента по виду документа."""
    docType: str
    count: int
    amount: float


class CounterpartyDocBrief(BaseModel):
    """Последний документ БП контрагента (для карточки в «Контрагентах»)."""
    docType: str
    number: str
    date: str
    amount: float
    operationType: str | None = None


class CounterpartyActivityResponse(BaseModel):
    """Активность контрагента в учёте (fuel/ГИГ): документы БП, сопоставленные по ИНН."""
    docs: int = 0
    amount: float = 0
    lastDate: str | None = None
    byType: list[CounterpartyDocGroup] = Field(default_factory=list)
    recent: list[CounterpartyDocBrief] = Field(default_factory=list)


class LocationContractBrief(BaseModel):
    id: str
    number: str
    date: str
    kind: str | None = None
    scopeType: str
    companyWide: bool               # True = общекомпанейский (scope=company)
    counterpartyId: str
    counterpartyName: str | None = None
    counterpartyInn: str | None = None


class LocationContractsResponse(BaseModel):
    """Договоры точки: адресные (точка ∈ contract_locations) + общекомпанейские."""
    contracts: list[LocationContractBrief]
    counterparties: list[CounterpartyBrief]


# ===== Обобщённые грани договора по разрезам (Фаза 3) =====

class ContractDimensionUpdate(BaseModel):
    """Заменить набор элементов разреза dim_type у договора. Пусто = снять ограничение."""
    refs: list[str] = Field(default_factory=list)


class ContractDimensionsResponse(BaseModel):
    """Грани договора: dim_type → список dim_ref (пусто по типу = не ограничен)."""
    dimensions: dict[str, list[str]]


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
    # lines может быть list (старая структура — построчные данные TradeLedger)
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
    externalRef: str | None = None    # GUID склада в 1С (для маппингов)
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
    channel_id: str | None = None   # маппинг уровня канала (NULL = дефолт компании)
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
    channelId: str | None = Field(default=None, alias="channel_id")
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
