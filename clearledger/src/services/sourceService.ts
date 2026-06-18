/**
 * Источники данных — ДВУХРЕЖИМНЫЙ сервис.
 *
 * VITE_API_URL задан  → бэкенд `/api/sources` (реальные источники компании).
 * VITE_API_URL не задан → localStorage (офлайн-режим, как было).
 *
 * Чтения (getSources/getSource) — СИНХРОННЫЕ из кэша: в API-режиме кэш
 * наполняется `loadSources(companyId)` (хук useSources / гидрация при старте),
 * до первой загрузки отдаёт []. Это сохраняет синхронные чтения в рендере
 * потребителей (ChannelDetailPage и пр.) без переписывания.
 * Записи (create/update/delete) — АСИНХРОННЫЕ (бэкенд → обновление кэша).
 */

import { getItem, setItem } from './storage'
import { get, post, patch, del, isApiEnabled } from './apiClient'
import type { Source, SourceType, SourceDocType } from '@/types/channel'
import { defaultStsDocTypes, defaultMstoDocTypes, defaultTradecorpDocTypes } from '@/types/channel'
import { nanoid } from 'nanoid'

const STS_LEGACY_TYPES = new Set(['sts-ops', 'sts-prices', 'sts-coupons', 'sts-tanks'])

const STORAGE_KEY = 'gig-sources'
const MIGRATION_KEY = 'gig-sources-migration-v2'

// ─── API-режим: соответствие таксономий + кэш ─────────────────────────────
interface ApiSource {
  id: string
  company_id: string
  source_type: string
  name: string
  description: string | null
  status: string
  connection_config: Record<string, string>
  configured_secrets: string[]
  last_test_at: string | null
  error_message: string | null
}

/** frontend SourceType → backend source_type */
const TO_BACKEND: Record<string, string> = {
  rest: 'sts', '1c': 'onec_operational', msto: 'msto', tradecorp: 'tradecorp',
}
/** backend source_type → frontend SourceType (для отображения) */
const FROM_BACKEND: Record<string, SourceType> = {
  sts: 'rest', onec_operational: '1c', onec_accounting: '1c', neftoms: '1c',
  msto: 'msto', tradecorp: 'tradecorp',
  acquiring_sber: 'rest', ofd: 'rest', inkassation: 'rest', chestny_znak: 'rest',
}

/** Публичный маппинг backend source_type → фронтовый тип источника
 *  (для предвыбора типа в диалоге «Добавить источник», напр. из каталога). */
export const frontendSourceType = (backendType: string): SourceType =>
  FROM_BACKEND[backendType] ?? 'rest'

function docTypesFor(backendType: string): SourceDocType[] {
  if (backendType === 'sts') return defaultStsDocTypes()
  if (backendType === 'msto') return defaultMstoDocTypes()
  if (backendType === 'tradecorp') return defaultTradecorpDocTypes()
  return []
}

function fromApi(r: ApiSource): Source {
  const known = ['connected', 'disconnected', 'error', 'draft']
  return {
    id: r.id,
    name: r.name,
    type: FROM_BACKEND[r.source_type] ?? 'rest',
    backendType: r.source_type,
    status: (known.includes(r.status) ? r.status : 'draft') as Source['status'],
    description: r.description ?? undefined,
    connection: r.connection_config ?? {},
    docTypes: docTypesFor(r.source_type),
    errorMessage: r.error_message ?? undefined,
    createdAt: r.last_test_at ?? '',
    updatedAt: r.last_test_at ?? '',
  }
}

let _cache: Source[] | null = null
let _companyId: string | null = null

function _requireCompany(): string {
  if (!_companyId) throw new Error('sourceService: companyId не задан (нужна loadSources до записи)')
  return _companyId
}

// ─── localStorage-режим (как было) ────────────────────────────────────────
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
      mainSts.connection.systemIds = `${mainSts.connection.systemCode},15`
    }
    mainSts.updatedAt = new Date().toISOString()
    changed = true
  }

  localStorage.setItem(MIGRATION_KEY, '1')
  return { sources: filtered, changed }
}

function lsGetSources(): Source[] {
  const raw = getItem<Source[]>(STORAGE_KEY, [])
  const { sources, changed } = migrateStsSourcesV2(raw as any[])
  if (changed) setItem(STORAGE_KEY, sources)
  return sources as Source[]
}

// ─── Публичный API ────────────────────────────────────────────────────────
/** Синхронное чтение: кэш (API) или localStorage. */
export function getSources(): Source[] {
  if (isApiEnabled()) return _cache ?? []
  return lsGetSources()
}

export function getSource(id: string): Source | undefined {
  return getSources().find((s) => s.id === id)
}

/** Гидрация кэша из бэкенда (для useSources / старта). */
export async function loadSources(companyId: string): Promise<Source[]> {
  if (!isApiEnabled()) return lsGetSources()
  _companyId = companyId
  const rows = await get<ApiSource[]>('/api/sources', { company_id: companyId })
  _cache = rows.map(fromApi)
  return _cache
}

export async function createSource(data: {
  name: string
  type: SourceType
  /** Реальный backend source_type (sts/onec_accounting/acquiring_sber/…) — приоритетнее укрупнённого type */
  sourceType?: string
  description?: string
  connection?: Record<string, string>
  docTypes?: SourceDocType[]
}): Promise<Source> {
  const backendType = data.sourceType ?? TO_BACKEND[data.type] ?? data.type
  if (isApiEnabled()) {
    const r = await post<ApiSource>('/api/sources', {
      company_id: _requireCompany(),
      source_type: backendType,
      name: data.name,
      description: data.description,
      config: data.connection ?? {},
    })
    const s = fromApi(r)
    _cache = [...(_cache ?? []), s]
    return s
  }
  // localStorage
  const source: Source = {
    id: nanoid(10),
    name: data.name,
    type: data.type,
    backendType,
    status: 'draft',
    description: data.description,
    connection: data.connection ?? {},
    docTypes: data.docTypes ?? docTypesFor(backendType),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  const sources = lsGetSources()
  sources.push(source)
  setItem(STORAGE_KEY, sources)
  return source
}

export async function updateSource(id: string, updates: Partial<Source>): Promise<Source | undefined> {
  if (isApiEnabled()) {
    const body: Record<string, unknown> = {}
    if (updates.name !== undefined) body.name = updates.name
    if (updates.description !== undefined) body.description = updates.description
    if (updates.connection !== undefined) body.config = updates.connection
    const r = await patch<ApiSource>(`/api/sources/${id}`, body)
    const s = fromApi(r)
    _cache = (_cache ?? []).map((x) => (x.id === id ? s : x))
    return s
  }
  const sources = lsGetSources()
  const idx = sources.findIndex((s) => s.id === id)
  if (idx === -1) return undefined
  sources[idx] = { ...sources[idx], ...updates, updatedAt: new Date().toISOString() }
  setItem(STORAGE_KEY, sources)
  return sources[idx]
}

export async function deleteSource(id: string): Promise<boolean> {
  if (isApiEnabled()) {
    await del(`/api/sources/${id}`)
    _cache = (_cache ?? []).filter((s) => s.id !== id)
    return true
  }
  const sources = lsGetSources()
  const filtered = sources.filter((s) => s.id !== id)
  if (filtered.length === sources.length) return false
  setItem(STORAGE_KEY, filtered)
  return true
}
