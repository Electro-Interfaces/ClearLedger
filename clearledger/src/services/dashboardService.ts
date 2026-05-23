/**
 * Dashboard KPI + виджеты.
 * Расширенные метрики поверх базового computeKpi.
 */

import type { DataEntry, CounterpartyStat, SourceStat, ErrorStat } from '@/types'
import { getEntries } from './dataEntryService'

/** Расширенные KPI */
export interface ExtendedKpi {
  uploadedToday: number
  totalVerified: number
  inProcessing: number
  errors: number
  transferredToday: number
  weekCount: number
  rejectionRate: number
  avgVerificationTimeMs?: number
  syncPending: number
  syncConfirmed: number
}

function activeEntries(entries: DataEntry[]): DataEntry[] {
  return entries.filter(
    (e) => e.status !== 'archived' && e.metadata._excluded !== 'true' && e.metadata._isLatestVersion !== 'false'
      && e.docPurpose !== 'archive',
  )
}

export async function computeExtendedKpi(companyId: string): Promise<ExtendedKpi> {
  const all = await getEntries(companyId)
  const entries = activeEntries(all)
  const today = new Date().toISOString().slice(0, 10)
  const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)

  const totalDecided = entries.filter((e) =>
    e.status === 'verified' || e.status === 'transferred' || e.status === 'error',
  ).length
  const errorsCount = entries.filter((e) => e.status === 'error').length

  return {
    uploadedToday: entries.filter((e) => e.createdAt.startsWith(today)).length,
    totalVerified: entries.filter((e) => e.status === 'verified' || e.status === 'transferred').length,
    inProcessing: entries.filter((e) => e.status === 'new' || e.status === 'recognized').length,
    errors: errorsCount,
    transferredToday: entries.filter((e) => e.status === 'transferred' && e.updatedAt.startsWith(today)).length,
    weekCount: entries.filter((e) => e.createdAt.slice(0, 10) >= weekAgo).length,
    rejectionRate: totalDecided > 0 ? Math.round((errorsCount / totalDecided) * 100) : 0,
    syncPending: entries.filter((e) => e.syncStatus === 'pending' || e.syncStatus === 'exported').length,
    syncConfirmed: entries.filter((e) => e.syncStatus === 'confirmed').length,
  }
}

/** Топ-N контрагентов */
export async function getTopCounterparties(companyId: string, limit = 5): Promise<CounterpartyStat[]> {
  const all = await getEntries(companyId)
  const entries = activeEntries(all)

  const map = new Map<string, { count: number; verified: number; rejected: number }>()
  for (const e of entries) {
    const cp = e.metadata.counterparty || e.metadata.inn || ''
    if (!cp) continue
    const stat = map.get(cp) ?? { count: 0, verified: 0, rejected: 0 }
    stat.count++
    if (e.status === 'verified' || e.status === 'transferred') stat.verified++
    if (e.status === 'error') stat.rejected++
    map.set(cp, stat)
  }

  return Array.from(map.entries())
    .map(([counterparty, stat]) => ({ counterparty, ...stat }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
}

/** Распределение по источникам */
export async function getSourceDistribution(companyId: string): Promise<SourceStat[]> {
  const all = await getEntries(companyId)
  const entries = activeEntries(all)

  const map = new Map<string, { label: string; count: number }>()
  for (const e of entries) {
    const stat = map.get(e.source) ?? { label: e.sourceLabel, count: 0 }
    stat.count++
    map.set(e.source, stat)
  }

  return Array.from(map.entries())
    .map(([source, stat]) => ({ source, ...stat }))
    .sort((a, b) => b.count - a.count)
}

/** Последние ошибки */
export async function getRecentErrors(companyId: string, limit = 5): Promise<ErrorStat[]> {
  const all = await getEntries(companyId)
  const errors = all.filter((e) => e.status === 'error')

  const map = new Map<string, number>()
  for (const e of errors) {
    const reason = e.metadata.rejectReason || 'Не указана'
    map.set(reason, (map.get(reason) ?? 0) + 1)
  }

  return Array.from(map.entries())
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
}
