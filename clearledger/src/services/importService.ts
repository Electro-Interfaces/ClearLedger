/**
 * Импорт данных из JSON (формат ExportPayload).
 * Merge-стратегия: skip existing, import new.
 */

import type { DataEntry, Connector } from '@/types'
import type { ExportPayload } from './exportService'
import { getItem, setItem, entriesKey } from './storage'
import { getConnectors } from './connectorService'
import { logEvent } from './auditService'

export interface ImportResult {
  imported: number
  skipped: number
  errors: string[]
}

/** Валидация формата ExportPayload */
function validatePayload(data: unknown): data is ExportPayload {
  if (!data || typeof data !== 'object') return false
  const obj = data as Record<string, unknown>
  return (
    obj.version === '1.0' &&
    typeof obj.companyId === 'string' &&
    Array.isArray(obj.entries)
  )
}

/** Импорт из JSON-файла */
export async function importFromJson(file: File, companyId: string): Promise<ImportResult> {
  const result: ImportResult = { imported: 0, skipped: 0, errors: [] }

  let payload: ExportPayload
  try {
    const text = await file.text()
    const parsed = JSON.parse(text)
    if (!validatePayload(parsed)) {
      result.errors.push('Неверный формат файла. Ожидается экспорт ClearLedger.')
      return result
    }
    payload = parsed
  } catch {
    result.errors.push('Не удалось прочитать JSON-файл.')
    return result
  }

  if (payload.companyId !== companyId) {
    result.errors.push(
      `Файл экспортирован для компании "${payload.companyId}", а текущая — "${companyId}".`,
    )
    return result
  }

  // Import entries
  const existingEntries = getItem<DataEntry[]>(entriesKey(companyId), [])
  const existingIds = new Set(existingEntries.map((e) => e.id))

  const newEntries: DataEntry[] = []
  for (const entry of payload.entries) {
    if (existingIds.has(entry.id)) {
      result.skipped++
    } else {
      newEntries.push(entry)
      result.imported++
    }
  }

  if (newEntries.length > 0) {
    setItem(entriesKey(companyId), [...existingEntries, ...newEntries])
  }

  // Import connectors
  if (payload.connectors?.length) {
    const existingConnectors = await getConnectors(companyId)
    const connectorIds = new Set(existingConnectors.map((c) => c.id))
    const newConnectors: Connector[] = []

    for (const conn of payload.connectors) {
      if (!connectorIds.has(conn.id)) {
        newConnectors.push(conn)
      }
    }

    if (newConnectors.length > 0) {
      setItem(`clearledger-connectors-${companyId}`, [...existingConnectors, ...newConnectors])
    }
  }

  logEvent({
    companyId,
    action: 'exported', // reuse action for import tracking
    details: `Импорт: ${result.imported} записей, ${result.skipped} пропущено`,
  })

  return result
}
