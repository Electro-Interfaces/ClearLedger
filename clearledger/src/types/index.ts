import type { EntryStatus } from '@/config/statuses'

export type EntrySource =
  | 'upload' | 'photo' | 'manual' | 'api'
  | 'email' | 'oneC' | 'whatsapp' | 'telegram' | 'paste'

export interface DataEntry {
  id: string
  title: string
  categoryId: string
  subcategoryId: string
  docTypeId?: string
  companyId: string
  status: EntryStatus
  source: EntrySource
  sourceLabel: string
  fileUrl?: string
  fileType?: string
  fileSize?: number
  ocrData?: OcrResult
  metadata: Record<string, string>
  /** Ссылка на Source+Extract в IndexedDB (sourceStore) */
  sourceId?: string
  createdAt: string
  updatedAt: string
}

// ---- Source / Extract (IndexedDB, структурированное хранилище) ----

/** Оригинальный файл, immutable */
export interface SourceRecord {
  id: string           // nanoid
  blob: Blob
  fileName: string
  mimeType: string
  size: number
  fingerprint: string  // SHA-256
  createdAt: string    // ISO
}

/** Результат pipeline, может перезапускаться */
export interface ExtractRecord {
  id: string           // = sourceId (1:1)
  sourceId: string
  fullText: string     // ВЕСЬ текст, без обрезки
  fields: ExtractedField[]
  classification: {
    categoryId: string
    subcategoryId: string
    docTypeId?: string
    confidence: number
  }
  extractedAt: string
}

export interface ExtractedField {
  key: string          // docNumber, docDate, amount, inn, counterparty
  value: string
  confidence: number   // 0-100
  source: 'regex' | 'ocr' | 'parser'
}

/**
 * Специальные ключи metadata:
 * _fingerprint — SHA-256 hash файла (для dedup)
 * _duplicateOf — ID оригинала если дубль
 * _email.from, _email.subject, _email.messageId
 * _1c.guid, _1c.docType, _1c.number
 * _links — JSON-строка массива связей
 *
 * DEPRECATED (перенесены в SourceRecord/ExtractRecord):
 * _blobId, _extractedText, _confidence, _sourceType
 */

export interface OcrResult {
  text: string
  fields: OcrField[]
  confidence: number
}

export interface OcrField {
  key: string
  label: string
  value: string
  confidence: number
}

export interface Connector {
  id: string
  name: string
  type: string
  url: string
  status: 'active' | 'error' | 'disabled'
  lastSync?: string
  lastSyncAt?: string
  syncStatus?: 'idle' | 'syncing' | 'synced' | 'error'
  recordsCount: number
  errorsCount: number
  categoryId: string
  interval: number
  companyId: string
}

export interface SyncLog {
  id: string
  connectorId: string
  timestamp: string
  status: 'success' | 'error'
  recordsProcessed: number
  message?: string
}

// ---- Intake Pipeline Types ----

export type IntakeFileType =
  | 'pdf' | 'image' | 'excel' | 'csv' | 'xml' | 'email'
  | 'text' | 'json' | 'dbf' | 'word' | 'whatsapp' | 'telegram' | 'unknown'

export type IntakeStage = 'detect' | 'extract' | 'classify' | 'verify' | 'dedup' | 'save'

export interface IntakeItem {
  id: string
  fileName: string
  file?: File
  pastedText?: string
  mimeType: string
  size: number
  stage: IntakeStage
  progress: number // 0-100
  status: 'processing' | 'done' | 'error' | 'duplicate'
  error?: string
  /** Результат detect */
  fileType?: IntakeFileType
  /** Результат extract */
  extractedText?: string
  /** Результат classify */
  classification?: IntakeClassification
  /** Результат dedup */
  duplicateOf?: { id: string; title: string } | null
  fingerprint?: string
  /** Сохранённая запись */
  entryId?: string
  /** Вложения email, обработанные через pipeline */
  childItems?: IntakeItem[]
}

export interface IntakeClassification {
  categoryId: string
  subcategoryId: string
  docTypeId?: string
  confidence: number // 0-100
  title: string
  metadata: Record<string, string>
}

// ---- Document Links (граф связей) ----

export type LinkType =
  | 'email-attachment'   // email → вложение
  | 'duplicate'          // дубликат (dedup)
  | 'related'            // связанные (один контрагент / номер / дата)
  | 'correction'         // исправление / дополнение
  | 'manual'             // ручная связь пользователя
  | 'subordinate'        // подчинённость: source = родитель, target = ребёнок

export interface DocumentLink {
  id: string
  sourceEntryId: string   // откуда
  targetEntryId: string   // куда
  type: LinkType
  label?: string          // описание связи
  createdAt: string
}

export interface UploadItem {
  id: string
  file: File
  categoryId: string
  subcategoryId: string
  progress: number
  status: 'pending' | 'uploading' | 'done' | 'error'
  error?: string
}

export interface FilterState {
  search: string
  status: EntryStatus | 'all'
  source: string
  dateFrom?: string
  dateTo?: string
  subcategory: string
  showArchived?: boolean
  showExcluded?: boolean
  showAllVersions?: boolean
}

export interface KpiData {
  uploadedToday: number
  totalVerified: number
  inProcessing: number
  errors: number
}

// ---- Audit ----

export type AuditAction =
  | 'created' | 'verified' | 'rejected' | 'transferred'
  | 'archived' | 'restored' | 'excluded' | 'included'
  | 'updated' | 'version_created' | 'exported'
  | 'bulk_archived' | 'bulk_excluded' | 'connector_synced'

export interface AuditEvent {
  id: string
  entryId?: string
  companyId: string
  userId: string
  userName: string
  action: AuditAction
  details?: string
  timestamp: string
}

// ---- Reports ----

export interface PeriodReport {
  dateFrom: string
  dateTo: string
  uploaded: number
  verified: number
  rejected: number
  transferred: number
  archived: number
  avgVerificationTimeMs?: number
}

export interface CounterpartyStat {
  counterparty: string
  count: number
  verified: number
  rejected: number
}

export interface SourceStat {
  source: string
  label: string
  count: number
}

export interface ErrorStat {
  reason: string
  count: number
}

// ---- Pagination / Filters ----

export interface PaginatedResult<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface AdvancedFilters {
  dateFrom?: string
  dateTo?: string
  amountMin?: number
  amountMax?: number
  counterparty?: string
  status?: string
  categoryId?: string
  source?: string
  docTypeId?: string
}

// ---- Bundle (бизнес-комплекты документов) ----

/** Роль документа в комплекте — enum, а не свободный текст (как в 1С:УТ) */
export type BundleRole =
  | 'contract'        // Договор (корень цепочки)
  | 'addendum'        // Допсоглашение
  | 'act'             // Акт (выполненных работ, приёма-передачи, сверки)
  | 'invoice'         // Счёт на оплату
  | 'invoice-factura' // Счёт-фактура
  | 'upd'             // Универсальный передаточный документ
  | 'payment'         // Оплата (платёжное поручение, ПКО/РКО)
  | 'waybill'         // Накладная (ТОРГ-12, ТТН)
  | 'other'           // Прочее (паспорт качества, сертификат и т.д.)

export interface BundleNode {
  entry: DataEntry
  children: BundleNode[]
  depth: number
}

export interface BundleTree {
  root: BundleNode
  totalCount: number
}

export interface BundleSuggestion {
  entry: DataEntry
  score: number       // 0-100
  reasons: string[]   // ["Совпадение контрагента", "Ссылка на номер договора"]
}

/** Результат валидации допустимой пары родитель→ребёнок */
export interface BundleValidation {
  allowed: boolean
  reason?: string     // причина отказа
}

// ---- НСИ: Справочники (Reference Data) ----

export type CounterpartyType = 'ЮЛ' | 'ФЛ' | 'ИП'

export interface Counterparty {
  id: string
  companyId: string
  inn: string
  kpp?: string
  name: string
  shortName?: string
  type: CounterpartyType
  aliases: string[]
  createdAt: string
  updatedAt: string
}

export interface Organization {
  id: string
  companyId: string
  inn: string
  kpp?: string
  ogrn?: string
  name: string
  bankAccount?: string
  bankBik?: string
  createdAt: string
  updatedAt: string
}

export interface Nomenclature {
  id: string
  companyId: string
  code: string
  name: string
  unit: string       // код ОКЕИ
  unitLabel: string   // наименование единицы
  vatRate: number     // % НДС (0, 10, 20)
  createdAt: string
  updatedAt: string
}

export interface Contract {
  id: string
  companyId: string
  number: string
  date: string
  counterpartyId: string
  organizationId: string
  type: string        // "Поставка", "Услуги", "Аренда" и т.д.
  amountLimit?: number
  createdAt: string
  updatedAt: string
}

// ---- Учётные документы 1С (AccountingDoc) ----

export type AccountingDocType =
  | 'receipt'           // ПоступлениеТоваровУслуг
  | 'invoice-received'  // СчётФактураПолученный
  | 'payment-out'       // ПлатёжноеПоручение
  | 'payment-in'        // ПоступлениеНаРасчётныйСчёт
  | 'sales'             // Реализация
  | 'invoice-issued'    // СчётФактураВыданный
  | 'reconciliation'    // АктСверкиВзаиморасчётов

export type MatchStatus = 'matched' | 'unmatched' | 'discrepancy' | 'pending'

export interface AccountingDocLine {
  nomenclatureCode?: string
  nomenclatureName: string
  quantity: number
  price: number
  amount: number
  vatRate: number
  vatAmount?: number
}

export interface AccountingDoc {
  id: string
  companyId: string
  externalId: string         // GUID 1С
  docType: AccountingDocType
  number: string
  date: string               // ISO date
  counterpartyName: string
  counterpartyInn?: string
  organizationName?: string
  amount: number
  vatAmount?: number
  status1c: string           // "Проведён" / "Не проведён"
  lines: AccountingDocLine[]
  matchedEntryId?: string    // ссылка на DataEntry
  matchStatus: MatchStatus
  matchDetails?: MatchDetails
  warehouseCode?: string
  createdAt: string
  updatedAt: string
}

export interface MatchDetails {
  score: number              // 0-100
  amountDiff?: number        // разница сумм
  dateDiff?: number          // разница дат (дни)
  missingLines: string[]     // позиции без пары
  extraLines: string[]       // лишние позиции
  confidence: number         // 0-100
}

export interface ReconciliationSummary {
  matched: number
  unmatchedAcc: number       // документы 1С без оригинала
  unmatchedEntry: number     // записи CL без пары в 1С
  discrepancy: number
  totalAccDocs: number
  totalEntries: number
}

// ---- НСИ: Склады ----

export type WarehouseType = 'warehouse' | 'station' | 'office' | 'other'

export interface Warehouse {
  id: string
  companyId: string
  code: string
  name: string
  address?: string
  type: WarehouseType
  createdAt: string
  updatedAt: string
}

// ---- НСИ: Банковские счета ----

export interface BankAccount {
  id: string
  companyId: string
  number: string           // номер расчётного счёта
  bankName: string
  bik: string
  corrAccount?: string
  currency: string         // "RUB"
  organizationId?: string
  createdAt: string
  updatedAt: string
}

// ---- Верификация (сверка с эталоном) ----

export type VerificationCheckStatus = 'pass' | 'fail' | 'warning' | 'info'

export type VerificationOverallStatus = 'approved' | 'needs_review' | 'rejected'

export interface VerificationCheck {
  field: string
  checkType: string
  status: VerificationCheckStatus
  confidence: number   // 0-100
  message: string
  suggestion?: string
}

export interface VerificationResult {
  entryId: string
  checks: VerificationCheck[]
  overallStatus: VerificationOverallStatus
  overallConfidence: number  // 0-100
  enrichment?: Record<string, string>
}

