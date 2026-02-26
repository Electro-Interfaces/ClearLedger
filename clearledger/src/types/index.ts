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
  createdAt: string
  updatedAt: string
}

/**
 * Специальные ключи metadata для intake pipeline:
 * _blobId — ссылка на blob в IndexedDB
 * _fingerprint — SHA-256 hash файла
 * _duplicateOf — ID оригинала если дубль
 * _confidence — уверенность классификации (0-100)
 * _sourceType — детальный тип источника
 * _extractedText — извлечённый текст (для поиска)
 * _email.from, _email.subject, _email.messageId
 * _1c.guid, _1c.docType, _1c.number
 * _links — JSON-строка массива связей
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
  | 'text' | 'json' | 'dbf' | 'word' | 'unknown'

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
}

export interface IntakeClassification {
  categoryId: string
  subcategoryId: string
  docTypeId?: string
  confidence: number // 0-100
  title: string
  metadata: Record<string, string>
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
}

export interface KpiData {
  uploadedToday: number
  totalVerified: number
  inProcessing: number
  errors: number
}

export interface RecentAction {
  id: string
  time: string
  fileName: string
  action: string
  status: EntryStatus
}
