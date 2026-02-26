/**
 * Сервис отчётов: period reports, counterparty stats, source stats, error analysis.
 * Dual-mode: localStorage (demo) / API.
 */

import type { DataEntry, PeriodReport, CounterpartyStat, SourceStat, ErrorStat } from '@/types'
import { getEntries } from './dataEntryService'
import { getEvents } from './auditService'

/** Фильтрация записей по периоду */
function filterByPeriod(entries: DataEntry[], dateFrom: string, dateTo: string): DataEntry[] {
  return entries.filter((e) => {
    const d = e.createdAt.slice(0, 10)
    return d >= dateFrom && d <= dateTo
  })
}

/** Активные записи (не старые версии, не excluded) */
function activeEntries(entries: DataEntry[]): DataEntry[] {
  return entries.filter(
    (e) => e.metadata._excluded !== 'true' && e.metadata._isLatestVersion !== 'false',
  )
}

/** Сводка за период */
export async function generatePeriodReport(
  companyId: string,
  dateFrom: string,
  dateTo: string,
): Promise<PeriodReport> {
  const all = await getEntries(companyId)
  const entries = filterByPeriod(activeEntries(all), dateFrom, dateTo)

  // Avg verification time from audit
  let avgVerificationTimeMs: number | undefined
  try {
    const events = await getEvents(companyId, { dateFrom, dateTo })
    const createdMap = new Map<string, string>()
    const verifiedTimes: number[] = []
    for (const ev of events) {
      if (ev.action === 'created' && ev.entryId) {
        createdMap.set(ev.entryId, ev.timestamp)
      }
      if (ev.action === 'verified' && ev.entryId) {
        const created = createdMap.get(ev.entryId)
        if (created) {
          verifiedTimes.push(new Date(ev.timestamp).getTime() - new Date(created).getTime())
        }
      }
    }
    if (verifiedTimes.length > 0) {
      avgVerificationTimeMs = verifiedTimes.reduce((a, b) => a + b, 0) / verifiedTimes.length
    }
  } catch { /* audit may be empty */ }

  return {
    dateFrom,
    dateTo,
    uploaded: entries.length,
    verified: entries.filter((e) => e.status === 'verified' || e.status === 'transferred').length,
    rejected: entries.filter((e) => e.status === 'error').length,
    transferred: entries.filter((e) => e.status === 'transferred').length,
    archived: entries.filter((e) => e.status === 'archived').length,
    avgVerificationTimeMs,
  }
}

/** Статистика по контрагентам */
export async function getCounterpartyStats(
  companyId: string,
  dateFrom: string,
  dateTo: string,
): Promise<CounterpartyStat[]> {
  const all = await getEntries(companyId)
  const entries = filterByPeriod(activeEntries(all), dateFrom, dateTo)

  const map = new Map<string, { count: number; verified: number; rejected: number }>()
  for (const e of entries) {
    const cp = e.metadata.counterparty || e.metadata.inn || 'Не указан'
    const stat = map.get(cp) ?? { count: 0, verified: 0, rejected: 0 }
    stat.count++
    if (e.status === 'verified' || e.status === 'transferred') stat.verified++
    if (e.status === 'error') stat.rejected++
    map.set(cp, stat)
  }

  return Array.from(map.entries())
    .map(([counterparty, stat]) => ({ counterparty, ...stat }))
    .sort((a, b) => b.count - a.count)
}

/** Распределение по источникам */
export async function getSourceStats(
  companyId: string,
  dateFrom: string,
  dateTo: string,
): Promise<SourceStat[]> {
  const all = await getEntries(companyId)
  const entries = filterByPeriod(activeEntries(all), dateFrom, dateTo)

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

/** Анализ ошибок */
export async function getErrorAnalysis(
  companyId: string,
  dateFrom: string,
  dateTo: string,
): Promise<ErrorStat[]> {
  const all = await getEntries(companyId)
  const entries = filterByPeriod(all, dateFrom, dateTo).filter((e) => e.status === 'error')

  const map = new Map<string, number>()
  for (const e of entries) {
    const reason = e.metadata.rejectReason || 'Не указана'
    map.set(reason, (map.get(reason) ?? 0) + 1)
  }

  return Array.from(map.entries())
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count)
}
