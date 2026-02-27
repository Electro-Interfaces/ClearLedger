/**
 * Предэкспортная валидация для EnterpriseData.
 *
 * Проверяет готовность записей к экспорту в 1С:БП.
 */

import type { DataEntry } from '@/types'
import { mapToOneCDocType } from './oneCMapping'

export interface ExportIssue {
  entryId: string
  entryTitle: string
  issue: string
  severity: 'error' | 'warning'
}

export interface ExportValidationResult {
  canExport: boolean
  entriesReady: DataEntry[]
  entriesWithIssues: DataEntry[]
  issues: ExportIssue[]
  totalReady: number
  totalWithIssues: number
}

/**
 * Валидация записей перед экспортом в EnterpriseData.
 */
export function validateForExport(entries: DataEntry[]): ExportValidationResult {
  const issues: ExportIssue[] = []
  const entriesReady: DataEntry[] = []
  const entriesWithIssues: DataEntry[] = []

  for (const entry of entries) {
    const entryIssues: ExportIssue[] = []

    // 1. Статус — только verified или transferred
    if (entry.status !== 'verified' && entry.status !== 'transferred') {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: `Статус "${entry.status}" — экспорт только verified/transferred`,
        severity: 'error',
      })
    }

    // 2. Маппинг в тип 1С
    const mapping = mapToOneCDocType(entry.docTypeId)
    if (!mapping) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: `Тип "${entry.docTypeId || 'не указан'}" не имеет маппинга в 1С:БП`,
        severity: 'error',
      })
    }

    // 3. Обязательные поля
    const meta = entry.metadata
    if (!meta.docNumber && !meta.number) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: 'Не указан номер документа',
        severity: 'warning',
      })
    }

    if (!meta.docDate && !meta.date) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: 'Не указана дата документа',
        severity: 'warning',
      })
    }

    if (!meta.amount) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: 'Не указана сумма',
        severity: 'warning',
      })
    }

    // 4. Контрагент привязан
    if (!meta['_ref.counterpartyId'] && !meta.counterparty) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: 'Контрагент не привязан к справочнику',
        severity: 'warning',
      })
    }

    // 5. Для СФ — НДС указан
    if (entry.docTypeId === 'invoice-factura' && !meta.amountVat && !meta.nds) {
      entryIssues.push({
        entryId: entry.id,
        entryTitle: entry.title,
        issue: 'Для счёт-фактуры не указан НДС',
        severity: 'warning',
      })
    }

    if (entryIssues.some((i) => i.severity === 'error')) {
      entriesWithIssues.push(entry)
    } else {
      entriesReady.push(entry)
    }

    issues.push(...entryIssues)
  }

  return {
    canExport: entriesReady.length > 0,
    entriesReady,
    entriesWithIssues,
    issues,
    totalReady: entriesReady.length,
    totalWithIssues: entriesWithIssues.length,
  }
}
