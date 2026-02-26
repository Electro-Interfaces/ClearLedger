/**
 * Экспорт данных компании для передачи в Слой 2 (Python).
 * JSON dump всех DataEntry + metadata.
 */

import type { DataEntry } from '@/types'
import type { Connector } from '@/types'
import { getEntries } from './dataEntryService'
import { getConnectors } from './connectorService'

export interface ExportPayload {
  version: '1.0'
  exportedAt: string
  companyId: string
  entries: DataEntry[]
  connectors: Connector[]
}

export async function exportAllData(companyId: string): Promise<void> {
  const payload: ExportPayload = {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    companyId,
    entries: await getEntries(companyId),
    connectors: getConnectors(companyId),
  }

  const json = JSON.stringify(payload, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `clearledger-export-${companyId}-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
