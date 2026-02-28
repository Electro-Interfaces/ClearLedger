/**
 * Экспорт данных: JSON, Excel, CSV, 1С XML, EnterpriseData XML.
 * Dual-mode: в API mode CSV/XML скачиваются с сервера.
 */

import type { DataEntry } from '@/types'
import type { Connector } from '@/types'
import { getEntries } from './dataEntryService'
import { getConnectors } from './connectorService'
import { generateEnterpriseDataXml } from './enterpriseDataExport'
import { isApiEnabled, downloadBlob } from './apiClient'
import * as XLSX from 'xlsx'

// ---- Types ----

export interface ExportOptions {
  columns?: string[]
  dateFormat?: 'dd.mm.yyyy' | 'yyyy-mm-dd'
  encoding?: 'utf-8' | 'windows-1251'
  fileName?: string
}

export interface ExportPayload {
  version: '1.0'
  exportedAt: string
  companyId: string
  entries: DataEntry[]
  connectors: Connector[]
}

// ---- Helpers ----

function triggerDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function formatDateValue(iso: string, fmt: 'dd.mm.yyyy' | 'yyyy-mm-dd'): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  if (fmt === 'yyyy-mm-dd') return d.toISOString().slice(0, 10)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}.${d.getFullYear()}`
}

const DEFAULT_COLUMNS = ['id', 'title', 'categoryId', 'subcategoryId', 'status', 'docPurpose', 'syncStatus', 'source', 'sourceLabel', 'createdAt', 'updatedAt']

const COLUMN_LABELS: Record<string, string> = {
  id: 'ID',
  title: 'Название',
  categoryId: 'Категория',
  subcategoryId: 'Подкатегория',
  docTypeId: 'Тип документа',
  status: 'Статус',
  docPurpose: 'Назначение',
  syncStatus: 'Синхронизация 1С',
  source: 'Источник',
  sourceLabel: 'Метка источника',
  createdAt: 'Создан',
  updatedAt: 'Обновлён',
  counterparty: 'Контрагент',
  amount: 'Сумма',
  inn: 'ИНН',
  docNumber: 'Номер документа',
  docDate: 'Дата документа',
}

function entryToRow(entry: DataEntry, columns: string[], dateFormat: 'dd.mm.yyyy' | 'yyyy-mm-dd'): Record<string, string> {
  const row: Record<string, string> = {}
  for (const col of columns) {
    const label = COLUMN_LABELS[col] ?? col
    if (col in entry) {
      const val = (entry as unknown as Record<string, unknown>)[col]
      if (col === 'createdAt' || col === 'updatedAt') {
        row[label] = formatDateValue(String(val), dateFormat)
      } else {
        row[label] = String(val ?? '')
      }
    } else if (entry.metadata[col] !== undefined) {
      row[label] = entry.metadata[col]
    } else {
      row[label] = ''
    }
  }
  return row
}

// ---- Export: JSON (existing) ----

export async function exportAllData(companyId: string): Promise<void> {
  if (isApiEnabled()) {
    const blob = await downloadBlob(`/api/export/json?company_id=${encodeURIComponent(companyId)}`)
    triggerDownload(blob, `clearledger-export-${companyId}-${new Date().toISOString().slice(0, 10)}.json`)
    return
  }

  const payload: ExportPayload = {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    companyId,
    entries: await getEntries(companyId),
    connectors: await getConnectors(companyId),
  }

  const json = JSON.stringify(payload, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  triggerDownload(blob, `clearledger-export-${companyId}-${new Date().toISOString().slice(0, 10)}.json`)
}

// ---- Export: Excel ----

export function exportToExcel(entries: DataEntry[], options?: ExportOptions): void {
  const columns = options?.columns ?? DEFAULT_COLUMNS
  const dateFormat = options?.dateFormat ?? 'dd.mm.yyyy'
  const rows = entries.map((e) => entryToRow(e, columns, dateFormat))

  const ws = XLSX.utils.json_to_sheet(rows)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Документы')

  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  triggerDownload(blob, options?.fileName ?? `clearledger-${new Date().toISOString().slice(0, 10)}.xlsx`)
}

// ---- Export: CSV ----

export async function exportToCsv(entries: DataEntry[], options?: ExportOptions & { companyId?: string }): Promise<void> {
  // В API mode — серверный export
  if (isApiEnabled() && options?.companyId) {
    const blob = await downloadBlob(`/api/export/csv?company_id=${encodeURIComponent(options.companyId)}`)
    triggerDownload(blob, options?.fileName ?? `clearledger-${new Date().toISOString().slice(0, 10)}.csv`)
    return
  }

  const columns = options?.columns ?? DEFAULT_COLUMNS
  const dateFormat = options?.dateFormat ?? 'dd.mm.yyyy'
  const labels = columns.map((c) => COLUMN_LABELS[c] ?? c)

  const lines: string[] = [labels.join(';')]
  for (const entry of entries) {
    const row = entryToRow(entry, columns, dateFormat)
    lines.push(labels.map((l) => `"${(row[l] ?? '').replace(/"/g, '""')}"`).join(';'))
  }

  const content = '\uFEFF' + lines.join('\r\n') // BOM for Excel
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  triggerDownload(blob, options?.fileName ?? `clearledger-${new Date().toISOString().slice(0, 10)}.csv`)
}

// ---- Export: 1С CommerceML XML ----

function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function exportTo1C(entries: DataEntry[], options?: ExportOptions): void {
  const dateFormat = options?.dateFormat ?? 'yyyy-mm-dd'
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<КоммерческаяИнформация ВерсияСхемы="2.10" ДатаФормирования="' + new Date().toISOString() + '">',
    '  <Документы>',
  ]

  for (const e of entries) {
    lines.push('    <Документ>')
    lines.push(`      <Ид>${escapeXml(e.id)}</Ид>`)
    lines.push(`      <Наименование>${escapeXml(e.title)}</Наименование>`)
    lines.push(`      <Дата>${formatDateValue(e.createdAt, dateFormat)}</Дата>`)
    lines.push(`      <Статус>${escapeXml(e.status)}</Статус>`)
    lines.push(`      <Категория>${escapeXml(e.categoryId)}</Категория>`)
    lines.push(`      <Подкатегория>${escapeXml(e.subcategoryId)}</Подкатегория>`)
    if (e.metadata.counterparty) {
      lines.push(`      <Контрагент>${escapeXml(e.metadata.counterparty)}</Контрагент>`)
    }
    if (e.metadata.inn) {
      lines.push(`      <ИНН>${escapeXml(e.metadata.inn)}</ИНН>`)
    }
    if (e.metadata.amount) {
      lines.push(`      <Сумма>${escapeXml(e.metadata.amount)}</Сумма>`)
    }
    if (e.metadata.docNumber) {
      lines.push(`      <НомерДокумента>${escapeXml(e.metadata.docNumber)}</НомерДокумента>`)
    }
    if (e.metadata.docDate) {
      lines.push(`      <ДатаДокумента>${escapeXml(e.metadata.docDate)}</ДатаДокумента>`)
    }
    lines.push('    </Документ>')
  }

  lines.push('  </Документы>')
  lines.push('</КоммерческаяИнформация>')

  const xml = lines.join('\n')
  const blob = new Blob([xml], { type: 'application/xml;charset=utf-8' })
  triggerDownload(blob, options?.fileName ?? `clearledger-1c-${new Date().toISOString().slice(0, 10)}.xml`)
}

// ---- Export: EnterpriseData XML (для 1С:Бухгалтерия) ----

export async function exportToEnterpriseData(
  entries: DataEntry[],
  companyId: string,
  options?: ExportOptions,
): Promise<{ documentsExported: number }> {
  const result = await generateEnterpriseDataXml(entries, companyId)
  const blob = new Blob([result.xml], { type: 'application/xml;charset=utf-8' })
  triggerDownload(
    blob,
    options?.fileName ?? `clearledger-enterprise-data-${new Date().toISOString().slice(0, 10)}.xml`,
  )
  return { documentsExported: result.documentsExported }
}
