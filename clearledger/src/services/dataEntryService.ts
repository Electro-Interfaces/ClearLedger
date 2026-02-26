/**
 * Бизнес-логика CRUD + workflow для DataEntry.
 * Хранение в localStorage через storage.ts.
 */

import type { DataEntry, OcrResult } from '@/types'
import type { EntryStatus } from '@/config/statuses'
import { getItem, setItem, nextId, entriesKey } from './storage'
import { deleteSource } from './sourceStore'
import { mockEntries } from './mockData'

// ---- Helpers ----

function loadEntries(companyId: string): DataEntry[] {
  return getItem<DataEntry[]>(entriesKey(companyId), [])
}

function saveEntries(companyId: string, entries: DataEntry[]): void {
  setItem(entriesKey(companyId), entries)
}

// ---- Seed (при первом запуске) ----

const SEED_KEY = 'clearledger-seeded'

export function seedIfNeeded(): void {
  if (getItem<boolean>(SEED_KEY, false)) return
  // Группируем mock-записи по companyId
  const byCompany = new Map<string, DataEntry[]>()
  for (const entry of mockEntries) {
    const list = byCompany.get(entry.companyId) ?? []
    list.push(entry)
    byCompany.set(entry.companyId, list)
  }
  for (const [companyId, entries] of byCompany) {
    saveEntries(companyId, entries)
  }
  // Обновляем счётчик ID
  const maxId = Math.max(...mockEntries.map((e) => Number(e.id) || 0), 0)
  setItem('clearledger-entry-counter', maxId)
  setItem(SEED_KEY, true)
}

// ---- CRUD ----

export function getEntries(companyId: string): DataEntry[] {
  return loadEntries(companyId)
}

export function getEntry(companyId: string, id: string): DataEntry | undefined {
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

export function createEntry(input: CreateEntryInput): DataEntry {
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

export function updateEntry(
  companyId: string,
  id: string,
  updates: Partial<Omit<DataEntry, 'id' | 'companyId' | 'createdAt'>>,
): DataEntry | undefined {
  const entries = loadEntries(companyId)
  const idx = entries.findIndex((e) => e.id === id)
  if (idx === -1) return undefined
  entries[idx] = { ...entries[idx], ...updates, updatedAt: new Date().toISOString() }
  saveEntries(companyId, entries)
  return entries[idx]
}

export function deleteEntry(companyId: string, id: string): boolean {
  const entries = loadEntries(companyId)
  const entry = entries.find((e) => e.id === id)
  if (!entry) return false

  const filtered = entries.filter((e) => e.id !== id)
  saveEntries(companyId, filtered)

  // Cleanup: удалить source + extract из IndexedDB
  if (entry.sourceId) {
    deleteSource(entry.sourceId).catch(() => { /* best effort */ })
  }

  return true
}

// ---- Workflow ----

export function verifyEntry(companyId: string, id: string): DataEntry | undefined {
  return updateEntry(companyId, id, { status: 'verified' })
}

export function rejectEntry(companyId: string, id: string, reason?: string): DataEntry | undefined {
  const updates: Partial<DataEntry> = { status: 'error' }
  if (reason) {
    const entry = getEntry(companyId, id)
    if (entry) {
      updates.metadata = { ...entry.metadata, rejectReason: reason }
    }
  }
  return updateEntry(companyId, id, updates)
}

export function transferEntries(companyId: string, ids: string[]): number {
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

// ---- Inbox ----

export function getInboxEntries(companyId: string): DataEntry[] {
  return loadEntries(companyId).filter(
    (e) => e.status === 'new' || e.status === 'recognized',
  )
}

export function getInboxCount(companyId: string): number {
  return loadEntries(companyId).filter(
    (e) => e.status === 'new' || e.status === 'recognized',
  ).length
}

// ---- Search ----

export function searchEntries(companyId: string, query: string): DataEntry[] {
  const q = query.toLowerCase()
  return loadEntries(companyId).filter((e) =>
    e.title.toLowerCase().includes(q) ||
    Object.values(e.metadata).some((v) => v.toLowerCase().includes(q)),
  )
}

// ---- KPI (computed from real data) ----

export interface ComputedKpi {
  uploadedToday: number
  totalVerified: number
  inProcessing: number
  errors: number
  transferredToday: number
}

export function computeKpi(companyId: string): ComputedKpi {
  const entries = loadEntries(companyId)
  const today = new Date().toISOString().slice(0, 10) // YYYY-MM-DD
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
