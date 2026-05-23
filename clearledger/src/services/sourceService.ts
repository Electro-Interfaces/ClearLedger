/**
 * CRUD для источников данных (localStorage).
 * Источник = подключение (URL, credentials) + доступные типы документов.
 */

import { getItem, setItem } from './storage'
import type { Source, SourceType, SourceDocType } from '@/types/channel'
import { defaultStsDocTypes, defaultMstoDocTypes, defaultTradecorpDocTypes } from '@/types/channel'
import { nanoid } from 'nanoid'

const STS_LEGACY_TYPES = new Set(['sts-ops', 'sts-prices', 'sts-coupons', 'sts-tanks'])

const STORAGE_KEY = 'gig-sources'
const MIGRATION_KEY = 'gig-sources-migration-v2'

/**
 * Миграция STS-источников к единому источнику.
 *
 * До v2 в gig-sources было 5 STS-источников: основной "rest" + 4 «sub»
 * (sts-ops, sts-prices, sts-coupons, sts-tanks). У всех одинаковые
 * credentials, разница только в doc_type. В v2 — один "rest"-источник
 * со всеми 6 doc_type и `systemIds` для обеих сетей (65, 15).
 *
 * Миграция идемпотентна — флаг `gig-sources-migration-v2` в localStorage.
 */
function migrateStsSourcesV2(sources: any[]): { sources: any[]; changed: boolean } {
  if (localStorage.getItem(MIGRATION_KEY)) return { sources, changed: false }

  let changed = false
  const filtered = sources.filter((s) => {
    if (STS_LEGACY_TYPES.has(s.type)) {
      changed = true
      return false
    }
    return true
  })

  const mainSts = filtered.find((s) => s.type === 'rest')
  if (mainSts) {
    mainSts.docTypes = defaultStsDocTypes()
    if (mainSts.connection?.systemCode && !mainSts.connection.systemIds) {
      // Старый systemCode=65 → новый systemIds="65,15" (две тех. сети ГИГ).
      mainSts.connection.systemIds = `${mainSts.connection.systemCode},15`
    }
    mainSts.updatedAt = new Date().toISOString()
    changed = true
  }

  localStorage.setItem(MIGRATION_KEY, '1')
  return { sources: filtered, changed }
}

export function getSources(): Source[] {
  const raw = getItem<Source[]>(STORAGE_KEY, [])
  const { sources, changed } = migrateStsSourcesV2(raw as any[])
  if (changed) setItem(STORAGE_KEY, sources)
  return sources as Source[]
}

export function getSource(id: string): Source | undefined {
  return getSources().find((s) => s.id === id)
}

export function createSource(data: {
  name: string
  type: SourceType
  description?: string
  connection?: Record<string, string>
  docTypes?: SourceDocType[]
}): Source {
  const source: Source = {
    id: nanoid(10),
    name: data.name,
    type: data.type,
    status: 'draft',
    description: data.description,
    connection: data.connection ?? {},
    docTypes: data.docTypes ?? (
      data.type === 'rest' ? defaultStsDocTypes() :
      data.type === 'msto' ? defaultMstoDocTypes() :
      data.type === 'tradecorp' ? defaultTradecorpDocTypes() :
      []
    ),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  const sources = getSources()
  sources.push(source)
  setItem(STORAGE_KEY, sources)
  return source
}

export function updateSource(id: string, updates: Partial<Source>): Source | undefined {
  const sources = getSources()
  const idx = sources.findIndex((s) => s.id === id)
  if (idx === -1) return undefined
  sources[idx] = { ...sources[idx], ...updates, updatedAt: new Date().toISOString() }
  setItem(STORAGE_KEY, sources)
  return sources[idx]
}

export function deleteSource(id: string): boolean {
  const sources = getSources()
  const filtered = sources.filter((s) => s.id !== id)
  if (filtered.length === sources.length) return false
  setItem(STORAGE_KEY, filtered)
  return true
}
