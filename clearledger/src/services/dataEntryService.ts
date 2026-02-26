/**
 * Бизнес-логика CRUD + workflow для DataEntry.
 *
 * Dual-mode:
 * - API mode (VITE_API_URL): все операции через FastAPI
 * - Demo mode: localStorage через storage.ts
 */

import type { DataEntry, OcrResult } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import { getItem, setItem, nextId, entriesKey } from './storage'
import { deleteSource } from './sourceStore'
import { mockEntries } from './mockData'

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

export function seedIfNeeded(): void {
  if (isApiEnabled()) return // seed делается на сервере
  if (getItem<boolean>(SEED_KEY, false)) return
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

// ============================================================
// API response → DataEntry mapping
// ============================================================

interface ApiEntry {
  id: string
  company_id: string
  source_id: string | null
  title: string
  category_id: string
  subcategory_id: string
  doc_type_id: string | null
  status: string
  source_type: string
  source_label: string
  metadata: Record<string, string>
  created_at: string
  updated_at: string
  verified_at: string | null
  verified_by: string | null
  transferred_at: string | null
}

function apiToEntry(a: ApiEntry): DataEntry {
  return {
    id: a.id,
    title: a.title,
    categoryId: a.category_id,
    subcategoryId: a.subcategory_id,
    docTypeId: a.doc_type_id ?? undefined,
    companyId: a.company_id,
    status: a.status as EntryStatus,
    source: a.source_type as DataEntry['source'],
    sourceLabel: a.source_label,
    metadata: a.metadata,
    sourceId: a.source_id ?? undefined,
    createdAt: a.created_at,
    updatedAt: a.updated_at,
  }
}

// ============================================================
// CRUD (dual-mode)
// ============================================================

export async function getEntries(companyId: string): Promise<DataEntry[]> {
  if (isApiEnabled()) {
    const res = await get<{ items: ApiEntry[]; total: number }>('/api/entries', {
      company_id: companyId,
      limit: 200,
    })
    return res.items.map(apiToEntry)
  }
  return loadEntries(companyId)
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
  const entry: DataEntry = {
    id: nextId(),
    title: input.title,
    categoryId: input.categoryId,
    subcategoryId: input.subcategoryId,
    docTypeId: input.docTypeId,
    companyId: input.companyId,
    status: input.status ?? 'new',
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
  return updateEntry(companyId, id, { status: 'verified' })
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
        await patch(`/api/entries/${id}`, { status: 'transferred' })
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
      entry.updatedAt = now
      count++
    }
  }
  if (count > 0) saveEntries(companyId, entries)
  return count
}

// ============================================================
// Inbox
// ============================================================

export async function getInboxEntries(companyId: string): Promise<DataEntry[]> {
  if (isApiEnabled()) {
    const res = await get<{ items: ApiEntry[]; total: number }>('/api/entries', {
      company_id: companyId,
      status: 'new',
      limit: 200,
    })
    return res.items.map(apiToEntry)
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
  const entries = await getEntries(companyId)
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

export async function computeKpi(companyId: string): Promise<ComputedKpi> {
  const entries = await getEntries(companyId)
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
