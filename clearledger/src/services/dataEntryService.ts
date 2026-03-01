/**
 * Бизнес-логика CRUD + workflow для DataEntry.
 *
 * Dual-mode:
 * - API mode (VITE_API_URL): все операции через FastAPI
 * - Demo mode: localStorage через storage.ts
 */

import type { DataEntry, OcrResult, DocPurpose, SyncStatus } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import { getItem, setItem, nextId, entriesKey } from './storage'
import { deleteSource } from './sourceStore'
import { mockEntries } from './mockData'
import { apiToEntry, type ApiEntry } from './apiMappers'
import { getAllDocumentTypes } from '@/config/categories'

// ============================================================
// LocalStorage helpers (demo mode)
// ============================================================

function loadEntries(companyId: string): DataEntry[] {
  return getItem<DataEntry[]>(entriesKey(companyId), [])
}

function saveEntries(companyId: string, entries: DataEntry[]): void {
  setItem(entriesKey(companyId), entries)
}

// ---- Seed (при первом запуске, demo mode) ----

const SEED_KEY = 'clearledger-seeded'
const SEED_V2_KEY = 'clearledger-seeded-v2'
const SEED_GENERATED_COUNT = 200

const SEED_COUNTERPARTIES = [
  'ООО "Лукойл"', 'ПАО "Газпром нефть"', 'АО "Роснефть"',
  'ООО "Башнефть"', 'АО "Сургутнефтегаз"', 'ПАО "Татнефть"',
]

const SEED_SOURCES: DataEntry['source'][] = [
  'upload', 'photo', 'manual', 'api', 'email', 'oneC', 'whatsapp', 'telegram', 'paste',
]

const SEED_SOURCE_LABELS: Record<string, string> = {
  upload: 'Загрузка', photo: 'Фото', manual: 'Ручной ввод', api: 'API',
  email: 'Email', oneC: '1С', whatsapp: 'WhatsApp', telegram: 'Telegram', paste: 'Вставка',
}

function seedRandom<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function seedRandomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

function seedGenerateInn(): string {
  let inn = ''
  for (let i = 0; i < 10; i++) inn += String(Math.floor(Math.random() * 10))
  return inn
}

export function seedIfNeeded(): void {
  if (isApiEnabled()) return // seed делается на сервере

  // Шаг 1: seed mock-записей (однократно)
  if (!getItem<boolean>(SEED_KEY, false)) {
    const byCompany = new Map<string, DataEntry[]>()
    for (const entry of mockEntries) {
      const list = byCompany.get(entry.companyId) ?? []
      list.push(entry)
      byCompany.set(entry.companyId, list)
    }
    for (const [companyId, entries] of byCompany) {
      saveEntries(companyId, entries)
    }
    const maxId = Math.max(...mockEntries.map((e) => Number(e.id) || 0), 0)
    setItem('clearledger-entry-counter', maxId)
    setItem(SEED_KEY, true)
  }

  // Шаг 2: генерация 200 записей для НПК (однократно, v2)
  if (!getItem<boolean>(SEED_V2_KEY, false)) {
    seedGenerateNpkEntries()
    setItem(SEED_V2_KEY, true)
  }
}

/** Синхронная генерация 200 записей для НПК (fuel профиль) */
function seedGenerateNpkEntries(): void {
  const docTypes = getAllDocumentTypes('fuel')
  if (docTypes.length === 0) return

  const npkEntries = loadEntries('npk')
  let counter = getItem<number>('clearledger-entry-counter', 0)
  const now = Date.now()

  for (let i = 0; i < SEED_GENERATED_COUNT; i++) {
    counter++
    const dt = seedRandom(docTypes)
    const source = seedRandom(SEED_SOURCES)
    const docNumber = `${seedRandomInt(100, 9999)}`
    const amount = `${seedRandomInt(1000, 500000)}`
    const daysBack = Math.random() * 60
    const entryDate = new Date(now - daysBack * 24 * 60 * 60 * 1000)
    const createdAt = entryDate.toISOString()
    const docDate = createdAt.slice(0, 10)

    // docPurpose: 80% accounting, 10% reference, 10% context
    const purposeRoll = Math.random()
    const docPurpose: DocPurpose = purposeRoll < 0.8 ? 'accounting' : purposeRoll < 0.9 ? 'reference' : 'context'

    // syncStatus зависит от docPurpose
    let syncStatus: SyncStatus = 'not_applicable'
    if (docPurpose === 'accounting') {
      const syncRoll = Math.random()
      syncStatus = syncRoll < 0.4 ? 'not_applicable'
        : syncRoll < 0.6 ? 'pending'
        : syncRoll < 0.8 ? 'exported'
        : syncRoll < 0.95 ? 'confirmed'
        : 'rejected_1c'
    }

    // status: 25% verified, 25% recognized, 20% new, 15% transferred, 15% error
    const statusRoll = Math.random()
    const status: EntryStatus = statusRoll < 0.25 ? 'verified'
      : statusRoll < 0.50 ? 'recognized'
      : statusRoll < 0.70 ? 'new'
      : statusRoll < 0.85 ? 'transferred'
      : 'error'

    npkEntries.push({
      id: String(counter),
      title: `${dt.label} №${docNumber}`,
      categoryId: dt.categoryId,
      subcategoryId: dt.subcategoryId,
      docTypeId: dt.id,
      companyId: 'npk',
      status,
      docPurpose,
      syncStatus,
      source,
      sourceLabel: SEED_SOURCE_LABELS[source] ?? source,
      metadata: {
        docNumber,
        docDate,
        counterparty: seedRandom(SEED_COUNTERPARTIES),
        amount,
        inn: seedGenerateInn(),
      },
      createdAt,
      updatedAt: createdAt,
    })
  }

  saveEntries('npk', npkEntries)
  setItem('clearledger-entry-counter', counter)
}

// ============================================================
// CRUD (dual-mode)
// ============================================================

export async function getEntries(companyId: string): Promise<DataEntry[]> {
  if (isApiEnabled()) {
    const res = await get<{ items: ApiEntry[]; total: number }>('/api/entries', {
      company_id: companyId,
      limit: 500,
    })
    return res.items.map(apiToEntry)
  }
  return loadEntries(companyId)
}

// ---- Пагинация (только API mode) ----

export interface PaginatedParams {
  offset?: number
  limit?: number
  status?: string
  categoryId?: string
  search?: string
}

export interface PaginatedResult {
  items: DataEntry[]
  total: number
  hasMore: boolean
}

export async function getEntriesPaginated(
  companyId: string,
  params: PaginatedParams = {},
): Promise<PaginatedResult> {
  const { offset = 0, limit = 50, status, categoryId, search } = params

  if (isApiEnabled()) {
    const queryParams: Record<string, string | number | undefined> = {
      company_id: companyId,
      offset,
      limit,
    }
    if (status && status !== 'all') queryParams.status = status
    if (categoryId) queryParams.category_id = categoryId
    if (search) queryParams.search = search

    const res = await get<{ items: ApiEntry[]; total: number }>('/api/entries', queryParams)
    const items = res.items.map(apiToEntry)
    return {
      items,
      total: res.total,
      hasMore: offset + items.length < res.total,
    }
  }

  // Demo mode — клиентская пагинация
  let entries = loadEntries(companyId)
  if (status && status !== 'all') entries = entries.filter((e) => e.status === status)
  if (categoryId) entries = entries.filter((e) => e.categoryId === categoryId)
  if (search) {
    const q = search.toLowerCase()
    entries = entries.filter((e) =>
      e.title.toLowerCase().includes(q) ||
      Object.values(e.metadata).some((v) => v.toLowerCase().includes(q)),
    )
  }

  const total = entries.length
  const items = entries.slice(offset, offset + limit)
  return {
    items,
    total,
    hasMore: offset + items.length < total,
  }
}

export async function getEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  if (isApiEnabled()) {
    try {
      const a = await get<ApiEntry>(`/api/entries/${id}`)
      return apiToEntry(a)
    } catch {
      return undefined
    }
  }
  return loadEntries(companyId).find((e) => e.id === id)
}

export interface CreateEntryInput {
  title: string
  categoryId: string
  subcategoryId: string
  docTypeId?: string
  companyId: string
  status?: EntryStatus
  docPurpose?: DataEntry['docPurpose']
  syncStatus?: DataEntry['syncStatus']
  source: DataEntry['source']
  sourceLabel: string
  fileUrl?: string
  fileType?: string
  fileSize?: number
  ocrData?: OcrResult
  metadata: Record<string, string>
  sourceId?: string
}

export async function createEntry(input: CreateEntryInput): Promise<DataEntry> {
  if (isApiEnabled()) {
    const a = await post<ApiEntry>('/api/entries', {
      company_id: input.companyId,
      title: input.title,
      category_id: input.categoryId,
      subcategory_id: input.subcategoryId,
      doc_type_id: input.docTypeId,
      source_type: input.source,
      source_label: input.sourceLabel,
      metadata: input.metadata,
    })
    return apiToEntry(a)
  }

  const now = new Date().toISOString()
  const docPurpose = input.docPurpose ?? 'accounting'
  const syncStatus = input.syncStatus ?? 'not_applicable'
  const entry: DataEntry = {
    id: nextId(),
    title: input.title,
    categoryId: input.categoryId,
    subcategoryId: input.subcategoryId,
    docTypeId: input.docTypeId,
    companyId: input.companyId,
    status: input.status ?? 'new',
    docPurpose,
    syncStatus,
    source: input.source,
    sourceLabel: input.sourceLabel,
    fileUrl: input.fileUrl,
    fileType: input.fileType,
    fileSize: input.fileSize,
    ocrData: input.ocrData,
    metadata: input.metadata,
    sourceId: input.sourceId,
    createdAt: now,
    updatedAt: now,
  }
  const entries = loadEntries(input.companyId)
  entries.push(entry)
  saveEntries(input.companyId, entries)
  return entry
}

export async function updateEntry(
  companyId: string,
  id: string,
  updates: Partial<Omit<DataEntry, 'id' | 'companyId' | 'createdAt'>>,
): Promise<DataEntry | undefined> {
  if (isApiEnabled()) {
    const body: Record<string, unknown> = {}
    if (updates.title !== undefined) body.title = updates.title
    if (updates.categoryId !== undefined) body.category_id = updates.categoryId
    if (updates.subcategoryId !== undefined) body.subcategory_id = updates.subcategoryId
    if (updates.docTypeId !== undefined) body.doc_type_id = updates.docTypeId
    if (updates.status !== undefined) body.status = updates.status
    if (updates.docPurpose !== undefined) body.doc_purpose = updates.docPurpose
    if (updates.syncStatus !== undefined) body.sync_status = updates.syncStatus
    if (updates.sourceLabel !== undefined) body.source_label = updates.sourceLabel
    if (updates.metadata !== undefined) body.metadata = updates.metadata
    const a = await patch<ApiEntry>(`/api/entries/${id}`, body)
    return apiToEntry(a)
  }

  const entries = loadEntries(companyId)
  const idx = entries.findIndex((e) => e.id === id)
  if (idx === -1) return undefined
  entries[idx] = { ...entries[idx], ...updates, updatedAt: new Date().toISOString() }
  saveEntries(companyId, entries)
  return entries[idx]
}

export async function deleteEntry(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try {
      await del(`/api/entries/${id}`)
      return true
    } catch {
      return false
    }
  }

  const entries = loadEntries(companyId)
  const entry = entries.find((e) => e.id === id)
  if (!entry) return false

  const filtered = entries.filter((e) => e.id !== id)
  saveEntries(companyId, filtered)

  if (entry.sourceId) {
    deleteSource(entry.sourceId).catch(() => { /* best effort */ })
  }
  return true
}

// ============================================================
// Workflow
// ============================================================

export async function verifyEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  const entry = await getEntry(companyId, id)
  const updates: Partial<DataEntry> = { status: 'verified' }
  if (entry && entry.docPurpose !== 'accounting') {
    updates.syncStatus = 'not_applicable'
  }
  return updateEntry(companyId, id, updates)
}

export async function rejectEntry(companyId: string, id: string, reason?: string): Promise<DataEntry | undefined> {
  if (reason) {
    const entry = await getEntry(companyId, id)
    if (entry) {
      return updateEntry(companyId, id, {
        status: 'error',
        metadata: { ...entry.metadata, rejectReason: reason },
      })
    }
  }
  return updateEntry(companyId, id, { status: 'error' })
}

export async function transferEntries(companyId: string, ids: string[]): Promise<number> {
  if (isApiEnabled()) {
    let count = 0
    for (const id of ids) {
      try {
        await patch(`/api/entries/${id}`, { status: 'transferred', sync_status: 'pending' })
        count++
      } catch { /* skip */ }
    }
    return count
  }

  const entries = loadEntries(companyId)
  let count = 0
  const now = new Date().toISOString()
  for (const entry of entries) {
    if (ids.includes(entry.id) && entry.status === 'verified') {
      entry.status = 'transferred'
      if (entry.docPurpose === 'accounting') {
        entry.syncStatus = 'pending'
      }
      entry.updatedAt = now
      count++
    }
  }
  if (count > 0) saveEntries(companyId, entries)
  return count
}

// ============================================================
// Lifecycle: archive / restore / exclude / include
// ============================================================

export async function archiveEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  const entry = await getEntry(companyId, id)
  if (!entry || entry.status === 'archived') return entry
  return updateEntry(companyId, id, {
    status: 'archived',
    metadata: { ...entry.metadata, _prevStatus: entry.status },
  })
}

export async function restoreEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  const entry = await getEntry(companyId, id)
  if (!entry || entry.status !== 'archived') return entry
  const prevStatus = (entry.metadata._prevStatus as EntryStatus) || 'new'
  const metadata = { ...entry.metadata }
  delete metadata._prevStatus
  return updateEntry(companyId, id, { status: prevStatus, metadata })
}

export async function excludeEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  const entry = await getEntry(companyId, id)
  if (!entry) return undefined
  return updateEntry(companyId, id, {
    metadata: { ...entry.metadata, _excluded: 'true' },
  })
}

export async function includeEntry(companyId: string, id: string): Promise<DataEntry | undefined> {
  const entry = await getEntry(companyId, id)
  if (!entry) return undefined
  const metadata = { ...entry.metadata }
  delete metadata._excluded
  return updateEntry(companyId, id, { metadata })
}

export async function replaceWithCorrected(companyId: string, originalId: string): Promise<string> {
  await archiveEntry(companyId, originalId)
  return originalId
}

// ============================================================
// Inbox
// ============================================================

export async function getInboxEntries(companyId: string): Promise<DataEntry[]> {
  if (isApiEnabled()) {
    const [resNew, resRecognized] = await Promise.all([
      get<{ items: ApiEntry[]; total: number }>('/api/entries', {
        company_id: companyId,
        status: 'new',
        limit: 200,
      }),
      get<{ items: ApiEntry[]; total: number }>('/api/entries', {
        company_id: companyId,
        status: 'recognized',
        limit: 200,
      }),
    ])
    return [...resNew.items, ...resRecognized.items].map(apiToEntry)
  }
  return loadEntries(companyId).filter(
    (e) => e.status === 'new' || e.status === 'recognized',
  )
}

export async function getInboxCount(companyId: string): Promise<number> {
  const inbox = await getInboxEntries(companyId)
  return inbox.length
}

// ============================================================
// Search
// ============================================================

export async function searchEntries(companyId: string, query: string): Promise<DataEntry[]> {
  if (isApiEnabled()) {
    const res = await get<{ items: ApiEntry[]; total: number }>('/api/entries', {
      company_id: companyId,
      search: query,
      limit: 100,
    })
    return res.items.map(apiToEntry)
  }
  const q = query.toLowerCase()
  return loadEntries(companyId).filter((e) =>
    e.title.toLowerCase().includes(q) ||
    Object.values(e.metadata).some((v) => v.toLowerCase().includes(q)),
  )
}

// ============================================================
// KPI
// ============================================================

export interface ComputedKpi {
  uploadedToday: number
  totalVerified: number
  inProcessing: number
  errors: number
  transferredToday: number
}

export interface CategoryStat {
  categoryId: string
  label: string
  count: number
}

export async function computeCategoryStats(companyId: string): Promise<CategoryStat[]> {
  if (isApiEnabled()) {
    try {
      return await get<CategoryStat[]>('/api/stats/categories', { company_id: companyId })
    } catch {
      // fallback — клиентский расчёт
    }
  }

  const allEntries = await getEntries(companyId)
  const entries = allEntries.filter(
    (e) => e.status !== 'archived' && e.metadata._excluded !== 'true' && e.metadata._isLatestVersion !== 'false'
      && e.docPurpose !== 'archive',
  )
  const countMap = new Map<string, number>()
  for (const e of entries) {
    countMap.set(e.categoryId, (countMap.get(e.categoryId) || 0) + 1)
  }
  return Array.from(countMap.entries()).map(([categoryId, count]) => ({
    categoryId,
    label: categoryId,
    count,
  }))
}

// ============================================================
// DocPurpose / SyncStatus setters
// ============================================================

export async function setDocPurpose(
  companyId: string,
  id: string,
  docPurpose: DataEntry['docPurpose'],
): Promise<DataEntry | undefined> {
  const updates: Partial<DataEntry> = { docPurpose }
  // Автоматическая коррекция syncStatus при смене назначения
  if (docPurpose !== 'accounting') {
    updates.syncStatus = 'not_applicable'
  }
  return updateEntry(companyId, id, updates)
}

export async function setSyncStatus(
  companyId: string,
  id: string,
  syncStatus: DataEntry['syncStatus'],
): Promise<DataEntry | undefined> {
  return updateEntry(companyId, id, { syncStatus })
}

// ============================================================
// KPI
// ============================================================

export async function computeKpi(companyId: string): Promise<ComputedKpi> {
  if (isApiEnabled()) {
    try {
      return await get<ComputedKpi>('/api/stats/kpi', { company_id: companyId })
    } catch {
      // fallback — клиентский расчёт
    }
  }

  const allEntries = await getEntries(companyId)
  // Исключаем archived, excluded, старые версии и архивные по назначению из KPI
  const entries = allEntries.filter(
    (e) => e.status !== 'archived' && e.metadata._excluded !== 'true' && e.metadata._isLatestVersion !== 'false'
      && e.docPurpose !== 'archive',
  )
  const today = new Date().toISOString().slice(0, 10)
  return {
    uploadedToday: entries.filter((e) => e.createdAt.startsWith(today)).length,
    totalVerified: entries.filter((e) => e.status === 'verified' || e.status === 'transferred').length,
    inProcessing: entries.filter((e) => e.status === 'new' || e.status === 'recognized').length,
    errors: entries.filter((e) => e.status === 'error').length,
    transferredToday: entries.filter(
      (e) => e.status === 'transferred' && e.updatedAt.startsWith(today),
    ).length,
  }
}
