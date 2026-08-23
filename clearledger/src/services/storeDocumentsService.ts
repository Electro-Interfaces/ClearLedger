import { del, downloadBlob, get, post, upload } from './apiClient'

export interface StoreDocumentBrief {
  shift_no?: number | null
  record_id: string
  document_id: string
  kind: string
  source: string
  projection_source: string
  document_role: string | null
  accounting_group_id: string | null
  station_id: number | null
  number: string | null
  document_at: string | null
  counterparty: string | null
  counterparty_inn: string | null
  amount: number
  vat_amount: number | null
  operational_status: string | null
  sync_status: string | null
  accounting_status: string | null
  discrepancy_status: string | null
  requires_attention: boolean
  has_files: boolean
  has_fuel: boolean
  revision: number
}

export interface StoreDocumentStats {
  attention: number
  missing_evidence: number
  not_accounting_ready: number
  onec_mismatch: number
}

export interface StoreDocumentsResponse {
  documents: StoreDocumentBrief[]
  total: number
  limit: number
  offset: number
  stats: StoreDocumentStats
  rebuilt_at: string | null
  rebuild_allowed: boolean
}

// У чека, смены и переоценки унифицированного бланка нет: чек печатает касса,
// смена это архив продаж, переоценка оформляется приказом по ценам.
// Расхождение печатается своим бланком: ТОРГ-2 для приёмки, ИНВ-19 для
// пересчёта. По ним предъявляют претензию и проводят результат.
export const DIFF_PRINTABLE_KINDS = new Set(['purchase', 'inventory'])

export const PRINTABLE_KINDS = new Set([
  'purchase', 'return_purchase', 'return_sale', 'transfer', 'inventory',
  'writeoff', 'gain', 'retail_sale_sidegoods', 'production_release', 'recipe',
])

// Бланк отдаётся API и требует токен, поэтому просто ссылкой его не открыть:
// забираем ответ и показываем в окне, которое открыли по самому клику — иначе
// браузер посчитает окно всплывающим и закроет.
export async function openStoreDocumentPrintForm(
  recordId: string, variant: 'main' | 'diff' = 'main',
): Promise<void> {
  const target = window.open('', '_blank')
  try {
    const blob = await downloadBlob(
      `/api/store/documents/${recordId}/print?variant=${variant}`)
    const url = URL.createObjectURL(blob)
    if (target) {
      target.location.href = url
    } else {
      window.location.href = url
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (reason) {
    target?.close()
    throw reason
  }
}

export function rebuildStoreDocuments() {
  return post<{ records: number; created: number; updated: number; removed: number }>(
    '/api/store/documents/rebuild', {},
  )
}

export interface StoreDocumentFilters {
  dateFrom: string
  dateTo: string
  stations: string[]
  kind?: string
  search?: string
  supplier?: string
  /** Показать только документы одной кассовой смены. */
  shiftNo?: number
  operationalStatus?: string
  syncStatus?: string
  accountingStatus?: string
  discrepancyStatus?: string
  source?: string
  warehouse?: string
  attention?: boolean
  hasFiles?: boolean
  counter?: StoreDocumentCounter
  limit: number
  offset: number
}

export type StoreDocumentCounter = keyof StoreDocumentStats

export interface StoreDocumentIssue {
  code: string
  /** Кто чинит: человек в интерфейсе, разработка кодом, либо никто. */
  owner: 'человек' | 'разработка' | 'никто'
  text: string
  hint: string
}

export interface StoreDocumentStep {
  code: string
  text: string
  at: string | null
  done: boolean
}

export interface StoreDocumentDetail extends StoreDocumentBrief {
  issues?: StoreDocumentIssue[]
  timeline?: StoreDocumentStep[]
  header: Record<string, unknown>
  file_write_allowed: boolean
  line_refs: Array<{ section: string; line_id: string; ordinal: number }>
  document: Record<string, unknown> & {
    detail_mode?: 'lines' | 'header_only'
    detail_note?: string
  }
}

export type StoreDocumentRelation =
  | { kind: string; movement: { id: string; kind: string; count: number } }
  | { kind: string; related: StoreDocumentBrief }

export interface StoreDocumentFile {
  id: string
  role: string
  file_name: string
  mime: string
  size_bytes: number
  sha256: string
  revision: number
  uploaded_at: string
  tombstoned_at: string | null
  download_url: string
}

export interface StoreDocumentBundle {
  detail: StoreDocumentDetail
  relations: StoreDocumentRelation[]
  files: StoreDocumentFile[]
}

export interface StoreDocumentPayloadResponse {
  available: boolean
  status?: string | null
  detail?: string
  payload?: unknown
}

/** Очередь работы: что разобрать и почему. */
export interface StoreTriageQueue {
  code: string
  title: string
  reason: string
  action: string
  count: number
  amount: number
  oldest_at: string | null
}

export function getStoreTriage(params: {
  stations?: string[]; dateFrom?: string; dateTo?: string
}): Promise<{ queues: StoreTriageQueue[]; total: number }> {
  return get('/api/store/documents/triage', {
    stations: params.stations?.length ? params.stations.join(',') : undefined,
    date_from: params.dateFrom,
    date_to: params.dateTo,
  })
}

/** Смена в реестре: одна строка на смену вместо десятков документов. */
export interface StoreShiftBrief {
  station_id: number | null
  shift_no: number
  documents: number
  revenue: number
  started_at: string | null
  finished_at: string | null
  requires_attention: boolean
  kinds: Record<string, number>
}

/** Паспорт смены: состояние разрезов и что осталось сделать. */
export interface StoreShiftPassport {
  station_id: number
  shift_no: number
  started_at: string | null
  finished_at: string | null
  status: string
  revenue: number
  vat: number | null
  cheques: number
  documents: number
  composition: { kind: string; count: number; amount: number; attention: number }[]
  cost_estimated: { item_uuid: string | null; status: string; quantity_millis: number | null }[]
  influenced_by: {
    record_id: string; kind: string; number: string | null; document_at: string | null
    amount: number; counterparty: string | null; operational_status: string | null
  }[]
  actions: { code: string; text: string; hint?: string }[]
  packet_uuid: string | null
}

export function listStoreShifts(params: {
  stations?: string[]; dateFrom?: string; dateTo?: string
}): Promise<{ shifts: StoreShiftBrief[]; total: number }> {
  return get('/api/store/documents/shifts', {
    stations: params.stations?.length ? params.stations.join(',') : undefined,
    date_from: params.dateFrom,
    date_to: params.dateTo,
  })
}

export function getStoreShiftPassport(stationId: number, shiftNo: number): Promise<StoreShiftPassport> {
  return get(`/api/store/documents/shifts/${stationId}/${shiftNo}`)
}

export function listStoreDocuments(filters: StoreDocumentFilters): Promise<StoreDocumentsResponse> {
  return get('/api/store/documents', {
    date_from: filters.dateFrom,
    date_to: filters.dateTo,
    stations: filters.stations.length ? filters.stations.join(',') : undefined,
    kind: filters.kind,
    q: filters.search,
    supplier: filters.supplier,
    shift_no: filters.shiftNo,
    operational_status: filters.operationalStatus,
    sync_status: filters.syncStatus,
    accounting_status: filters.accountingStatus,
    discrepancy_status: filters.discrepancyStatus,
    source: filters.source,
    warehouse: filters.warehouse,
    attention: filters.attention === undefined ? undefined : String(filters.attention),
    has_files: filters.hasFiles === undefined ? undefined : String(filters.hasFiles),
    counter: filters.counter,
    limit: filters.limit,
    offset: filters.offset,
  })
}

export async function getStoreDocumentBundle(recordId: string): Promise<StoreDocumentBundle> {
  const [detail, relations, files] = await Promise.all([
    get<StoreDocumentDetail>(`/api/store/documents/${recordId}`),
    get<{ relations: StoreDocumentRelation[] }>(`/api/store/documents/${recordId}/relations`),
    get<{ files: StoreDocumentFile[] }>(`/api/store/documents/${recordId}/files`),
  ])
  return { detail, relations: relations.relations, files: files.files }
}

export function getStoreDocumentPayload(recordId: string): Promise<StoreDocumentPayloadResponse> {
  return get(`/api/store/documents/${recordId}/payload`)
}

export function uploadStoreDocumentFile(recordId: string, file: File, role: string, note?: string) {
  const form = new FormData()
  form.append('file', file)
  const query = new URLSearchParams({ role })
  if (note) query.set('note', note)
  return upload<{ id: string; created: boolean; sha256: string }>(
    `/api/store/documents/${recordId}/files?${query.toString()}`, form,
  )
}

export function tombstoneStoreDocumentFile(recordId: string, fileId: string, reason: string) {
  return del<{ id: string; tombstoned: boolean }>(
    `/api/store/documents/${recordId}/files/${fileId}?reason=${encodeURIComponent(reason)}`,
  )
}

export async function downloadStoreDocumentFile(file: StoreDocumentFile): Promise<void> {
  const blob = await downloadBlob(file.download_url)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = file.file_name
  anchor.click()
  URL.revokeObjectURL(url)
}
