/**
 * AccountingDocService — CRUD учётных документов 1С + сверка.
 *
 * Dual-mode: localStorage (v0.2) / API (production).
 */

import type {
  AccountingDoc,
  AccountingDocType,
  MatchStatus,
  ReconciliationSummary,
  MatchDetails,
} from '@/types'
import { isApiEnabled, get, post, del } from './apiClient'
import { getItem, setItem, accountingDocsKey, entriesKey } from './storage'
import { nanoid } from 'nanoid'
import type { DataEntry } from '@/types'

// ============================================================
// localStorage helpers
// ============================================================

function loadList<T>(key: string): T[] {
  return getItem<T[]>(key, [])
}

function saveList<T>(key: string, items: T[]): void {
  setItem(key, items)
}

// ============================================================
// CRUD
// ============================================================

export async function getAccountingDocs(
  companyId: string,
  filters?: {
    docType?: AccountingDocType
    counterparty?: string
    dateFrom?: string
    dateTo?: string
    matchStatus?: MatchStatus
  },
): Promise<AccountingDoc[]> {
  if (isApiEnabled()) {
    const params: Record<string, string> = { company_id: companyId }
    if (filters?.docType) params.doc_type = filters.docType
    if (filters?.counterparty) params.counterparty = filters.counterparty
    if (filters?.dateFrom) params.date_from = filters.dateFrom
    if (filters?.dateTo) params.date_to = filters.dateTo
    if (filters?.matchStatus) params.match_status = filters.matchStatus
    return get<AccountingDoc[]>('/api/accounting-docs', params)
  }

  let docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  if (filters?.docType) docs = docs.filter((d) => d.docType === filters.docType)
  if (filters?.counterparty) {
    const q = filters.counterparty.toLowerCase()
    docs = docs.filter((d) => d.counterpartyName.toLowerCase().includes(q))
  }
  if (filters?.dateFrom) docs = docs.filter((d) => d.date >= filters.dateFrom!)
  if (filters?.dateTo) docs = docs.filter((d) => d.date <= filters.dateTo!)
  if (filters?.matchStatus) docs = docs.filter((d) => d.matchStatus === filters.matchStatus)
  return docs
}

export async function getAccountingDoc(companyId: string, id: string): Promise<AccountingDoc | undefined> {
  if (isApiEnabled()) {
    return get<AccountingDoc>(`/api/accounting-docs/${id}`)
  }
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  return docs.find((d) => d.id === id)
}

export async function createAccountingDoc(
  companyId: string,
  input: Omit<AccountingDoc, 'id' | 'companyId' | 'matchStatus' | 'createdAt' | 'updatedAt'>,
): Promise<AccountingDoc> {
  if (isApiEnabled()) {
    return post<AccountingDoc>('/api/accounting-docs', { ...input, company_id: companyId })
  }
  const now = new Date().toISOString()
  const doc: AccountingDoc = {
    id: nanoid(),
    companyId,
    matchStatus: 'pending',
    createdAt: now,
    updatedAt: now,
    ...input,
  }
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  docs.push(doc)
  saveList(accountingDocsKey(companyId), docs)
  return doc
}

export async function deleteAccountingDoc(companyId: string, id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try { await del(`/api/accounting-docs/${id}`); return true } catch { return false }
  }
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const filtered = docs.filter((d) => d.id !== id)
  if (filtered.length === docs.length) return false
  saveList(accountingDocsKey(companyId), filtered)
  return true
}

// ============================================================
// Импорт (массовый upsert)
// ============================================================

export interface ImportAccountingDocsResult {
  total: number
  created: number
  updated: number
  errors: string[]
}

export async function importAccountingDocs(
  companyId: string,
  docs: Omit<AccountingDoc, 'id' | 'companyId' | 'matchStatus' | 'createdAt' | 'updatedAt'>[],
): Promise<ImportAccountingDocsResult> {
  if (isApiEnabled()) {
    return post<ImportAccountingDocsResult>('/api/accounting-docs/import', {
      company_id: companyId,
      docs: docs.map((d) => ({
        company_id: companyId,
        external_id: d.externalId,
        doc_type: d.docType,
        number: d.number,
        date: d.date,
        counterparty_name: d.counterpartyName,
        counterparty_inn: d.counterpartyInn,
        organization_name: d.organizationName,
        amount: d.amount,
        vat_amount: d.vatAmount,
        status_1c: d.status1c,
        lines: d.lines.map((l) => ({
          nomenclatureCode: l.nomenclatureCode,
          nomenclatureName: l.nomenclatureName,
          quantity: l.quantity,
          price: l.price,
          amount: l.amount,
          vatRate: l.vatRate,
          vatAmount: l.vatAmount,
        })),
        warehouse_code: d.warehouseCode,
      })),
    })
  }

  // localStorage upsert
  const existing = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const byExtId = new Map(existing.map((d) => [d.externalId, d]))
  const now = new Date().toISOString()
  let created = 0
  let updated = 0

  for (const input of docs) {
    const found = byExtId.get(input.externalId)
    if (found) {
      Object.assign(found, {
        number: input.number,
        date: input.date,
        counterpartyName: input.counterpartyName,
        counterpartyInn: input.counterpartyInn,
        organizationName: input.organizationName,
        amount: input.amount,
        vatAmount: input.vatAmount,
        status1c: input.status1c,
        lines: input.lines,
        warehouseCode: input.warehouseCode,
        updatedAt: now,
      })
      updated++
    } else {
      const doc: AccountingDoc = {
        id: nanoid(),
        companyId,
        matchStatus: 'pending',
        createdAt: now,
        updatedAt: now,
        externalId: input.externalId,
        docType: input.docType,
        number: input.number,
        date: input.date,
        counterpartyName: input.counterpartyName,
        counterpartyInn: input.counterpartyInn,
        organizationName: input.organizationName,
        amount: input.amount,
        vatAmount: input.vatAmount,
        status1c: input.status1c,
        lines: input.lines,
        warehouseCode: input.warehouseCode,
      }
      existing.push(doc)
      byExtId.set(doc.externalId, doc)
      created++
    }
  }

  saveList(accountingDocsKey(companyId), existing)
  return { total: docs.length, created, updated, errors: [] }
}

// ============================================================
// Сверка (Reconciliation)
// ============================================================

export async function runReconciliation(companyId: string): Promise<{
  matched: number
  unmatched: number
  discrepancy: number
  total: number
}> {
  if (isApiEnabled()) {
    return post(`/api/reconciliation/run?company_id=${encodeURIComponent(companyId)}`)
  }
  // Локальная сверка
  return runLocalReconciliation(companyId)
}

export async function getReconciliationSummary(companyId: string): Promise<ReconciliationSummary> {
  if (isApiEnabled()) {
    return get<ReconciliationSummary>('/api/reconciliation/summary', { company_id: companyId })
  }
  return computeLocalSummary(companyId)
}

export async function manualMatch(companyId: string, docId: string, entryId: string): Promise<void> {
  if (isApiEnabled()) {
    await post('/api/reconciliation/match', { company_id: companyId, doc_id: docId, entry_id: entryId })
    return
  }
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const doc = docs.find((d) => d.id === docId)
  if (doc) {
    doc.matchedEntryId = entryId
    doc.matchStatus = 'matched'
    doc.matchDetails = { score: 100, confidence: 100, missingLines: [], extraLines: [] }
    doc.updatedAt = new Date().toISOString()
    saveList(accountingDocsKey(companyId), docs)
  }
}

export async function unmatch(companyId: string, docId: string): Promise<void> {
  if (isApiEnabled()) {
    await post('/api/reconciliation/unmatch', { company_id: companyId, doc_id: docId })
    return
  }
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const doc = docs.find((d) => d.id === docId)
  if (doc) {
    doc.matchedEntryId = undefined
    doc.matchStatus = 'pending'
    doc.matchDetails = undefined
    doc.updatedAt = new Date().toISOString()
    saveList(accountingDocsKey(companyId), docs)
  }
}

// ============================================================
// Локальный алгоритм сверки (аналог серверного)
// ============================================================

function normalizeDocNumber(raw: string): string {
  return raw
    .replace(/^(ТТН|СФ|АКТ|УПД|ПП|ПКО|РКО|ТОРГ|ТН)/i, '')
    .replace(/[№#\-/\s]/g, '')
    .toUpperCase()
}

function parseDate(val: string): Date | null {
  const d = new Date(val)
  return isNaN(d.getTime()) ? null : d
}

function computeScore(doc: AccountingDoc, entry: DataEntry): { score: number; details: MatchDetails } {
  let score = 0
  const meta = entry.metadata || {}
  const missingLines: string[] = []
  const extraLines: string[] = []

  // ИНН
  const entryInn = meta.inn || meta.counterpartyInn || ''
  if (doc.counterpartyInn && entryInn && doc.counterpartyInn.trim() === entryInn.trim()) {
    score += 40
  }

  // Номер
  const entryNum = meta.docNumber || meta['_1c.number'] || ''
  if (doc.number && entryNum) {
    const normDoc = normalizeDocNumber(doc.number)
    const normEntry = normalizeDocNumber(entryNum)
    if (normDoc && normEntry) {
      if (normDoc === normEntry) score += 25
      else if (normDoc.includes(normEntry) || normEntry.includes(normDoc)) score += 15
    }
  }

  // Дата
  const docDate = parseDate(doc.date)
  const entryDate = meta.docDate ? parseDate(meta.docDate) : null
  let dateDiff: number | undefined
  if (docDate && entryDate) {
    dateDiff = Math.abs(Math.round((docDate.getTime() - entryDate.getTime()) / 86400000))
    if (dateDiff <= 3) score += 20
    else if (dateDiff <= 7) score += 10
  }

  // Сумма
  let amountDiff: number | undefined
  const entryAmountStr = meta.amount || meta.totalAmount || ''
  const entryAmount = parseFloat(entryAmountStr.replace(',', '.').replace(/\s/g, ''))
  if (doc.amount && !isNaN(entryAmount)) {
    amountDiff = doc.amount - entryAmount
    const pctDiff = doc.amount > 0 ? Math.abs(amountDiff) / doc.amount * 100 : 0
    if (pctDiff <= 1) score += 15
    else if (pctDiff <= 5) score += 8
  }

  return {
    score,
    details: {
      score,
      amountDiff,
      dateDiff,
      missingLines,
      extraLines,
      confidence: Math.min(score, 100),
    },
  }
}

function runLocalReconciliation(companyId: string) {
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const entries = loadList<DataEntry>(entriesKey(companyId))
  const usedEntries = new Set<string>()
  let matched = 0
  let unmatched = 0
  let discrepancy = 0

  for (const doc of docs) {
    let bestScore = 0
    let bestEntry: DataEntry | null = null
    let bestDetails: MatchDetails | null = null

    for (const entry of entries) {
      if (usedEntries.has(entry.id)) continue
      const { score, details } = computeScore(doc, entry)
      if (score > bestScore) {
        bestScore = score
        bestEntry = entry
        bestDetails = details
      }
    }

    if (bestScore >= 55 && bestEntry && bestDetails) {
      usedEntries.add(bestEntry.id)
      const hasDiscrepancy = (bestDetails.amountDiff != null && Math.abs(bestDetails.amountDiff) > 0.01)
        || (bestDetails.dateDiff != null && bestDetails.dateDiff > 0)

      if (hasDiscrepancy && bestScore < 75) {
        doc.matchStatus = 'discrepancy'
        discrepancy++
      } else {
        doc.matchStatus = 'matched'
        matched++
      }
      doc.matchedEntryId = bestEntry.id
      doc.matchDetails = bestDetails
    } else {
      doc.matchStatus = 'unmatched'
      doc.matchedEntryId = undefined
      doc.matchDetails = undefined
      unmatched++
    }
    doc.updatedAt = new Date().toISOString()
  }

  saveList(accountingDocsKey(companyId), docs)
  return { matched, unmatched, discrepancy, total: docs.length }
}

function computeLocalSummary(companyId: string): ReconciliationSummary {
  const docs = loadList<AccountingDoc>(accountingDocsKey(companyId))
  const entries = loadList<DataEntry>(entriesKey(companyId))
  const matchedEntryIds = new Set(
    docs.filter((d) => d.matchStatus === 'matched' && d.matchedEntryId).map((d) => d.matchedEntryId!),
  )

  return {
    matched: docs.filter((d) => d.matchStatus === 'matched').length,
    unmatchedAcc: docs.filter((d) => d.matchStatus === 'unmatched' || d.matchStatus === 'pending').length,
    unmatchedEntry: entries.length - matchedEntryIds.size,
    discrepancy: docs.filter((d) => d.matchStatus === 'discrepancy').length,
    totalAccDocs: docs.length,
    totalEntries: entries.length,
  }
}
