/**
 * NormalizationService — привязка строковых полей к справочникам НСИ.
 *
 * Обогащает metadata ключами _ref.* при нахождении совпадений.
 * Lazy: не перестраиваем старые записи, нормализуем при intake или по запросу.
 */

import type {
  DataEntry,
  NormalizationState, NormalizationSummary,
  EntryValidationResult, EntryEnrichmentResult, ComplianceFinding,
  AuditMissingEntry,
} from '@/types'
import type { ProfileId } from '@/config/profiles'
import {
  findCounterpartyByInn, findCounterpartyByName,
  findContractsByCounterparty, findOrganizationByInn,
} from './referenceService'
import { getCounterpartyFromMeta, getDocNumberFromMeta, normalizeCounterparty } from '@/lib/textUtils'
import { validateEntry } from './validationService'
import { suggestBundleMembers } from './bundleService'
import { getEntries, updateEntry, createEntry } from './dataEntryService'
import { getItem, setItem } from './storage'
import { nanoid } from 'nanoid'

export interface NormalizationResult {
  enrichment: Record<string, string>
  matchConfidence: number
}

/**
 * Найти контрагента в справочнике по ИНН (точно) или имени (fuzzy).
 * Возвращает enrichment-ключи _ref.counterpartyId, _ref.matchConfidence и т.д.
 */
export async function resolveCounterparty(
  metadata: Record<string, string>,
  companyId: string,
): Promise<NormalizationResult> {
  const enrichment: Record<string, string> = {}
  let confidence = 0

  // 1. Точное сопоставление по ИНН
  const inn = metadata.inn?.trim()
  if (inn) {
    const cp = await findCounterpartyByInn(companyId, inn)
    if (cp) {
      enrichment['_ref.counterpartyId'] = cp.id
      enrichment['_ref.counterpartyName'] = cp.name
      if (cp.kpp) enrichment['_ref.counterpartyKpp'] = cp.kpp
      confidence = 1
      return { enrichment, matchConfidence: confidence }
    }
  }

  // 2. Fuzzy по имени
  const name = getCounterpartyFromMeta(metadata)
  if (name) {
    const result = await findCounterpartyByName(companyId, name)
    if (result) {
      enrichment['_ref.counterpartyId'] = result.counterparty.id
      enrichment['_ref.counterpartyName'] = result.counterparty.name
      if (result.counterparty.kpp) enrichment['_ref.counterpartyKpp'] = result.counterparty.kpp
      if (result.counterparty.inn) enrichment['_ref.counterpartyInn'] = result.counterparty.inn
      confidence = result.confidence
    }
  }

  return { enrichment, matchConfidence: confidence }
}

/**
 * Найти организацию в справочнике по ИНН.
 */
export async function resolveOrganization(
  metadata: Record<string, string>,
  companyId: string,
): Promise<Record<string, string>> {
  const enrichment: Record<string, string> = {}
  const orgInn = metadata.orgInn?.trim() || metadata.organizationInn?.trim()
  if (!orgInn) return enrichment

  const org = await findOrganizationByInn(companyId, orgInn)
  if (org) {
    enrichment['_ref.organizationId'] = org.id
    enrichment['_ref.organizationName'] = org.name
  }
  return enrichment
}

/**
 * Найти договор по номеру или привязке к контрагенту.
 */
export async function resolveContract(
  metadata: Record<string, string>,
  counterpartyId: string | undefined,
  companyId: string,
): Promise<Record<string, string>> {
  const enrichment: Record<string, string> = {}
  if (!counterpartyId) return enrichment

  const contracts = await findContractsByCounterparty(companyId, counterpartyId)
  if (contracts.length === 0) return enrichment

  const contractNum = metadata.contractNumber || metadata.parentDocNumber || metadata.docNumber
  if (contractNum) {
    const exact = contracts.find((c) => c.number === contractNum)
    if (exact) {
      enrichment['_ref.contractId'] = exact.id
      enrichment['_ref.contractNumber'] = exact.number
      if (exact.amountLimit) enrichment['_ref.contractAmountLimit'] = String(exact.amountLimit)
      return enrichment
    }
  }

  // Если один договор — привязываем
  if (contracts.length === 1) {
    enrichment['_ref.contractId'] = contracts[0].id
    enrichment['_ref.contractNumber'] = contracts[0].number
    if (contracts[0].amountLimit) enrichment['_ref.contractAmountLimit'] = String(contracts[0].amountLimit)
  }

  return enrichment
}

/**
 * Полное обогащение записи из справочников.
 */
export async function enrichFromReference(
  entry: DataEntry,
  companyId: string,
): Promise<Record<string, string>> {
  const cpResult = await resolveCounterparty(entry.metadata, companyId)
  const orgEnrich = await resolveOrganization(entry.metadata, companyId)
  const contractEnrich = await resolveContract(
    entry.metadata,
    cpResult.enrichment['_ref.counterpartyId'],
    companyId,
  )

  return {
    ...cpResult.enrichment,
    ...(cpResult.matchConfidence > 0 ? { '_ref.matchConfidence': String(cpResult.matchConfidence) } : {}),
    ...orgEnrich,
    ...contractEnrich,
  }
}

// ============================================================
// Batch Normalization (Layer 2 pipeline)
// ============================================================

const normKey = (companyId: string) => `clearledger-normalization-${companyId}`

/** Фильтр: бухгалтерские записи, не архивные, не исключённые */
function accountingEntries(entries: DataEntry[]): DataEntry[] {
  return entries.filter(
    (e) =>
      e.docPurpose === 'accounting' &&
      e.status !== 'archived' &&
      !e.metadata._excluded,
  )
}

// 1. Чтение state из localStorage
export function getNormalizationState(companyId: string): NormalizationState | null {
  return getItem<NormalizationState | null>(normKey(companyId), null)
}

// 2. Запись state в localStorage
export function saveNormalizationState(state: NormalizationState): void {
  setItem(normKey(state.companyId), state)
}

// 3. Батч-валидация
export async function runValidationBatch(
  companyId: string,
  profileId: ProfileId,
  onProgress?: (done: number, total: number) => void,
): Promise<EntryValidationResult[]> {
  const all = await getEntries(companyId)
  const entries = accountingEntries(all)
  const results: EntryValidationResult[] = []

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]
    const vr = validateEntry(entry, profileId)
    results.push({
      entryId: entry.id,
      entryTitle: entry.title,
      categoryId: entry.categoryId,
      completeness: vr.completeness,
      errorCount: vr.issues.filter((x) => x.severity === 'error').length,
      warningCount: vr.issues.filter((x) => x.severity === 'warning').length,
      isValid: vr.isValid,
      issues: vr.issues.map((x) => ({ severity: x.severity, label: x.label, message: x.message })),
      validatedAt: new Date().toISOString(),
    })
    if ((i + 1) % 50 === 0) {
      onProgress?.(i + 1, entries.length)
      await new Promise((r) => setTimeout(r, 0))
    }
  }
  onProgress?.(entries.length, entries.length)
  return results
}

// 4. Батч-обогащение
export async function runEnrichmentBatch(
  companyId: string,
  onProgress?: (done: number, total: number) => void,
): Promise<EntryEnrichmentResult[]> {
  const all = await getEntries(companyId)
  const entries = accountingEntries(all)
  const results: EntryEnrichmentResult[] = []

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]
    const cpResult = await resolveCounterparty(entry.metadata, companyId)
    const cpId = cpResult.enrichment['_ref.counterpartyId']
    const contractEnrich = await resolveContract(entry.metadata, cpId, companyId)

    let bundleCount = 0
    try {
      const suggestions = await suggestBundleMembers(companyId, entry.id)
      bundleCount = suggestions.length
    } catch { /* ignore */ }

    const alreadyApplied = !!entry.metadata['_ref.counterpartyId']

    // Полный набор enrichment-ключей для применения
    const fullEnrichment: Record<string, string> = {
      ...cpResult.enrichment,
      ...(cpResult.matchConfidence > 0 ? { '_ref.matchConfidence': String(cpResult.matchConfidence) } : {}),
      ...contractEnrich,
    }

    results.push({
      entryId: entry.id,
      entryTitle: entry.title,
      counterpartyMatch: cpResult.matchConfidence > 0
        ? { name: cpResult.enrichment['_ref.counterpartyName'] || '', confidence: cpResult.matchConfidence }
        : null,
      contractMatch: contractEnrich['_ref.contractNumber']
        ? { number: contractEnrich['_ref.contractNumber'] }
        : null,
      bundleSuggestionCount: bundleCount,
      enrichmentApplied: alreadyApplied,
      fullEnrichment,
      enrichedAt: new Date().toISOString(),
    })

    if ((i + 1) % 50 === 0) {
      onProgress?.(i + 1, entries.length)
      await new Promise((r) => setTimeout(r, 0))
    }
  }
  onProgress?.(entries.length, entries.length)
  return results
}

// 5. Батч-проверка соответствия
export async function runComplianceBatch(companyId: string): Promise<ComplianceFinding[]> {
  const all = await getEntries(companyId)
  const entries = accountingEntries(all)
  const findings: ComplianceFinding[] = []
  const now = new Date().toISOString()

  // 5a. bundle_inconsistency — записи в одном бандле с разными контрагентами
  const bundleGroups = new Map<string, DataEntry[]>()
  for (const e of entries) {
    const rootId = e.metadata._bundleRootId
    if (rootId) {
      if (!bundleGroups.has(rootId)) bundleGroups.set(rootId, [])
      bundleGroups.get(rootId)!.push(e)
    }
  }
  for (const [rootId, group] of bundleGroups) {
    const cps = new Set(group.map((e) => normalizeCounterparty(getCounterpartyFromMeta(e.metadata))).filter(Boolean))
    if (cps.size > 1) {
      findings.push({
        id: nanoid(),
        severity: 'warning',
        category: 'bundle_inconsistency',
        title: 'Разные контрагенты в комплекте',
        description: `Бандл ${rootId}: найдены контрагенты ${[...cps].join(', ')}`,
        affectedEntryIds: group.map((e) => e.id),
        detectedAt: now,
      })
    }
  }

  // 5b. amount_duplicate — одинаковые (дата, сумма, контрагент)
  const amountGroups = new Map<string, DataEntry[]>()
  for (const e of entries) {
    const date = e.metadata.docDate?.trim()
    const amount = e.metadata.amount?.trim()
    if (!date || !amount) continue // нужны оба поля
    const cp = normalizeCounterparty(getCounterpartyFromMeta(e.metadata))
    const key = `${date}|${amount}|${cp}`
    if (!amountGroups.has(key)) amountGroups.set(key, [])
    amountGroups.get(key)!.push(e)
  }
  for (const [, group] of amountGroups) {
    if (group.length > 1) {
      findings.push({
        id: nanoid(),
        severity: 'warning',
        category: 'amount_duplicate',
        title: 'Дублирование суммы',
        description: `${group.length} записей с одинаковой датой, суммой и контрагентом`,
        affectedEntryIds: group.map((e) => e.id),
        detectedAt: now,
      })
    }
  }

  // 5c. numbering_gap — пропуски нумерации по docTypeId
  const typeGroups = new Map<string, { num: number; id: string }[]>()
  for (const e of entries) {
    if (!e.docTypeId) continue
    const docNum = getDocNumberFromMeta(e.metadata)
    const trailing = docNum.match(/(\d+)\s*$/)
    if (!trailing) continue
    if (!typeGroups.has(e.docTypeId)) typeGroups.set(e.docTypeId, [])
    typeGroups.get(e.docTypeId)!.push({ num: parseInt(trailing[1], 10), id: e.id })
  }
  for (const [docType, items] of typeGroups) {
    if (items.length < 2) continue
    items.sort((a, b) => a.num - b.num)
    const gaps: number[] = []
    for (let i = 1; i < items.length; i++) {
      const diff = items[i].num - items[i - 1].num
      if (diff > 1) {
        for (let g = items[i - 1].num + 1; g < items[i].num && gaps.length < 5; g++) {
          gaps.push(g)
        }
      }
    }
    if (gaps.length > 0) {
      findings.push({
        id: nanoid(),
        severity: 'info',
        category: 'numbering_gap',
        title: `Пропуск нумерации: ${docType}`,
        description: `Пропущены номера: ${gaps.join(', ')}${gaps.length >= 5 ? '...' : ''}`,
        affectedEntryIds: items.map((x) => x.id),
        detectedAt: now,
      })
    }
  }

  return findings
}

// 6. Оркестратор pipeline
export async function runNormalizationPipeline(
  companyId: string,
  profileId: ProfileId,
  onProgress?: (phase: string, done: number, total: number) => void,
): Promise<NormalizationState> {
  const validationResults = await runValidationBatch(companyId, profileId, (d, t) => onProgress?.('validation', d, t))
  const enrichmentResults = await runEnrichmentBatch(companyId, (d, t) => onProgress?.('enrichment', d, t))
  onProgress?.('compliance', 0, 1)
  const complianceFindings = await runComplianceBatch(companyId)
  onProgress?.('compliance', 1, 1)

  const totalEntries = validationResults.length
  const validCount = validationResults.filter((r) => r.isValid).length
  const enrichedCount = enrichmentResults.filter((r) => r.counterpartyMatch || r.contractMatch).length
  const issuesCount = validationResults.reduce((s, r) => s + r.errorCount + r.warningCount, 0)
  const criticalFindings = complianceFindings.filter((f) => f.severity === 'critical').length

  const all = await getEntries(companyId)
  const entries = accountingEntries(all)
  const pendingCount = entries.filter((e) => e.status === 'new' || e.status === 'recognized').length

  const state: NormalizationState = {
    companyId,
    summary: {
      totalEntries,
      pendingCount,
      validatedCount: totalEntries,
      validPercent: totalEntries > 0 ? Math.round((validCount / totalEntries) * 100) : 0,
      enrichedCount,
      enrichedPercent: totalEntries > 0 ? Math.round((enrichedCount / totalEntries) * 100) : 0,
      issuesCount,
      complianceFindings: complianceFindings.length,
      criticalFindings,
      lastRunAt: new Date().toISOString(),
    },
    validationResults,
    enrichmentResults,
    complianceFindings,
    updatedAt: new Date().toISOString(),
  }

  saveNormalizationState(state)
  return state
}

// 7. Получить summary (из кеша или вычислить на лету)
export async function getNormalizationSummary(
  companyId: string,
  _profileId: ProfileId,
): Promise<NormalizationSummary> {
  const cached = getNormalizationState(companyId)
  if (cached) return cached.summary

  const all = await getEntries(companyId)
  const entries = accountingEntries(all)
  const pendingCount = entries.filter((e) => e.status === 'new' || e.status === 'recognized').length

  return {
    totalEntries: entries.length,
    pendingCount,
    validatedCount: 0,
    validPercent: 0,
    enrichedCount: 0,
    enrichedPercent: 0,
    issuesCount: 0,
    complianceFindings: 0,
    criticalFindings: 0,
  }
}

// 8. Применить обогащение к записи
export async function applyEnrichment(
  companyId: string,
  entryId: string,
  enrichment: Record<string, string>,
): Promise<void> {
  const all = await getEntries(companyId)
  const entry = all.find((e) => e.id === entryId)
  if (!entry) return

  await updateEntry(companyId, entryId, {
    metadata: { ...entry.metadata, ...enrichment },
  })
}

// 9. Применить обогащение из аудита (одно поле)
export async function applyAuditEnrichment(
  companyId: string,
  entryId: string,
  metadataKey: string,
  proposedValue: string,
): Promise<void> {
  await applyEnrichment(companyId, entryId, { [metadataKey]: proposedValue })
}

// 10. Создать запись из предложения аудита (документ 1С, не найденный в CL)
export async function createEntryFromAuditProposal(
  companyId: string,
  proposal: AuditMissingEntry,
): Promise<DataEntry> {
  return createEntry({
    title: proposal.proposedEntry.title,
    categoryId: proposal.proposedEntry.categoryId,
    subcategoryId: proposal.proposedEntry.subcategoryId,
    docTypeId: proposal.proposedEntry.docTypeId,
    companyId,
    source: 'api',
    sourceLabel: 'Аудит TSupport',
    status: 'recognized',
    docPurpose: 'accounting',
    syncStatus: 'confirmed',
    metadata: { ...proposal.proposedEntry.metadata, _auditSource: 'tsupport' },
  })
}
