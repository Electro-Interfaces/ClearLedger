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

export type IntakeStage = 'detect' | 'extract' | 'classify' | 'dedup' | 'save'

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
  | 'bulk_archived' | 'bulk_excluded'

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

