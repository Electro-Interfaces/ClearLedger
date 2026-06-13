/**
 * Каналы данных — ДВУХРЕЖИМНЫЙ сервис.
 *
 * VITE_API_URL задан  → бэкенд `/api/channels` (реальные каналы компании).
 * VITE_API_URL не задан → localStorage (офлайн-режим, как было).
 *
 * Чтения (getChannels/getChannel) — СИНХРОННЫЕ из кэша (в API-режиме кэш
 * наполняет loadChannels через useChannels/гидрацию). Записи — АСИНХРОННЫЕ.
 */

import { getItem, setItem } from './storage'
import { getSource } from './sourceService'
import { get, post, patch, del, isApiEnabled } from './apiClient'
import type {
  Channel, ChannelStream, ChannelStage, SyncLogEntry, ScheduleConfig,
} from '@/types/channel'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-channels'

export interface ChannelStats {
  total: number
  active: number
  errors: number
  todayEntries: number
}

// ─── API-режим: типы ответа + кэш ─────────────────────────────────────────
interface ApiStream { id: string; source_id: string; doc_type_id: string | null; name: string; enabled: boolean }
interface ApiStage { id: string; stage_type: string; name: string; order_index: number; enabled: boolean }
interface ApiChannel {
  id: string
  company_id: string
  name: string
  description: string | null
  status: string
  template_id: string | null
  schedule: Record<string, any>
  duplicate_policy: string
  config: Record<string, any>
  period_days: number
  last_sync_at: string | null
  streams: ApiStream[]
  stages: ApiStage[]
}

function scheduleFromApi(s: Record<string, any>): ScheduleConfig | string {
  if (!s || !s.mode || s.mode === 'manual') return 'manual'
  return s as unknown as ScheduleConfig
}

function chFromApi(r: ApiChannel): Channel {
  const sourceIds = [...new Set(r.streams.map((s) => s.source_id))]
  return {
    id: r.id,
    name: r.name,
    sourceIds,
    sourceId: sourceIds[0],
    status: (r.status as Channel['status']) ?? 'draft',
    description: r.description ?? undefined,
    config: r.config ?? {},
    duplicatePolicy: (r.duplicate_policy as Channel['duplicatePolicy']) ?? 'skip',
    schedule: scheduleFromApi(r.schedule),
    templateId: r.template_id ?? undefined,
    periodDays: r.period_days ?? 7,
    streams: r.streams.map((s) => ({
      id: s.id, sourceId: s.source_id, docTypeId: s.doc_type_id ?? '',
      name: s.name, catalogTemplate: '', filters: {}, enabled: s.enabled,
    })),
    stages: r.stages.map((s) => ({
      id: s.id, type: s.stage_type as ChannelStage['type'], name: s.name,
      config: {}, enabled: s.enabled, order: s.order_index,
    })),
    reconcileRules: [],
    rootCatalog: (r.config && r.config.rootCatalog) || '/Нефтепродукты АЗС',
    lastSync: r.last_sync_at ?? undefined,
    docsLoaded: 0,
    syncLog: [],
    createdAt: r.last_sync_at ?? '',
    updatedAt: r.last_sync_at ?? '',
  }
}

let _cache: Channel[] | null = null
let _companyId: string | null = null

function _requireCompany(): string {
  if (!_companyId) throw new Error('channelService: companyId не задан (нужна loadChannels до записи)')
  return _companyId
}

async function _refetchOne(id: string): Promise<Channel | undefined> {
  const r = await get<ApiChannel>(`/api/channels/${id}`)
  const ch = chFromApi(r)
  _cache = (_cache ?? []).map((x) => (x.id === id ? ch : x))
  return ch
}

// ─── localStorage-режим (как было) ────────────────────────────────────────
function defaultStreamsFromSource(sourceId: string): ChannelStream[] {
  const source = getSource(sourceId)
  if (!source) return []
  return source.docTypes.map((dt) => ({
    id: nanoid(6),
    docTypeId: dt.id,
    sourceId,
    name: dt.name,
    catalogTemplate: dt.id === 'shift_report'
      ? '/Смены/{станция}/{год}-{месяц}/'
      : dt.id === 'receipt'
        ? '/ТТН/{станция}/{год}-{месяц}/'
        : `/Справочники/`,
    filters: {},
    enabled: dt.id !== 'price',
  }))
}

function defaultStages(sourceIds: string[]): ChannelStage[] {
  const stages: ChannelStage[] = []
  let order = 0
  for (const sourceId of sourceIds) {
    const source = getSource(sourceId)
    stages.push({
      id: nanoid(6), type: 'fetch', name: `Загрузка: ${source?.name ?? sourceId}`,
      sourceId, config: {}, enabled: true, order: order++,
    })
  }
  stages.push({ id: nanoid(6), type: 'normalize', name: 'Нормализация данных', config: {}, enabled: true, order: order++ })
  if (sourceIds.length > 1) {
    stages.push({ id: nanoid(6), type: 'reconcile', name: 'Сверка источников', config: {}, enabled: true, order: order++ })
  }
  return stages
}

function migrateChannel(ch: any): Channel {
  if (!ch.sourceIds) ch.sourceIds = ch.sourceId ? [ch.sourceId] : []
  if (!ch.stages) ch.stages = defaultStages(ch.sourceIds)
  if (!ch.reconcileRules) ch.reconcileRules = []
  if (!ch.rootCatalog) ch.rootCatalog = '/Нефтепродукты АЗС'
  if (!ch.config) ch.config = {}
  if (ch.streams) {
    const primarySourceId = ch.sourceIds[0] ?? ch.sourceId ?? ''
    for (const s of ch.streams) if (!s.sourceId) s.sourceId = primarySourceId
  }
  if (!ch.config.stations && Array.isArray(ch.config.stationCodes)) {
    const fallbackSystem = Number(ch.config.systemCode ?? 65)
    ch.config.stations = ch.config.stationCodes.map((code: number) => ({ code: Number(code), systemId: fallbackSystem }))
  }
  if (typeof ch.description === 'string' && /сеть\s*65,\s*станция/i.test(ch.description)) {
    ch.description = ch.description.replace(/\s*\(сеть\s*65,\s*станция[^)]*\)\s*/i, '').trim()
  }
  return ch as Channel
}

function lsGetChannels(): Channel[] {
  return getItem<any[]>(STORAGE_KEY, []).map(migrateChannel)
}

// ─── Публичный API ────────────────────────────────────────────────────────
/** Синхронное чтение: кэш (API) или localStorage. */
export function getChannels(): Channel[] {
  if (isApiEnabled()) return _cache ?? []
  return lsGetChannels()
}

export function getChannel(id: string): Channel | undefined {
  return getChannels().find((c) => c.id === id)
}

/** Гидрация кэша из бэкенда (для useChannels / старта). */
export async function loadChannels(companyId: string): Promise<Channel[]> {
  if (!isApiEnabled()) return lsGetChannels()
  _companyId = companyId
  const rows = await get<ApiChannel[]>('/api/channels', { company_id: companyId })
  _cache = rows.map(chFromApi)
  return _cache
}

/** Сводка по каналам (computed; бэкенд-эндпоинта статистики нет). */
export async function getChannelStats(companyId: string): Promise<ChannelStats> {
  const list = await loadChannels(companyId)
  return {
    total: list.length,
    active: list.filter((c) => c.status === 'active').length,
    errors: list.filter((c) => c.status === 'error').length,
    todayEntries: list.reduce((sum, c) => sum + (c.docsLoaded || 0), 0),
  }
}

export async function createChannel(data: {
  name: string
  sourceIds: string[]
  description?: string
  config?: Record<string, any>
  templateId?: string
  schedule?: ScheduleConfig
}): Promise<Channel> {
  if (isApiEnabled()) {
    // source_bindings: backend source_type → source_id (из кэша источников)
    const bindings: Record<string, string> = {}
    for (const sid of data.sourceIds) {
      const s = getSource(sid)
      if (s?.backendType) bindings[s.backendType] = sid
    }
    const r = await post<ApiChannel>('/api/channels', {
      company_id: _requireCompany(),
      name: data.name,
      template_id: data.templateId,
      description: data.description,
      source_bindings: bindings,
    })
    const ch = chFromApi(r)
    _cache = [...(_cache ?? []), ch]
    // довносим config/period/schedule, если заданы (бэкенд create их не берёт)
    if (data.config || data.schedule) {
      return (await updateChannel(ch.id, { config: data.config, schedule: data.schedule })) ?? ch
    }
    return ch
  }
  // localStorage
  const channel: Channel = {
    id: nanoid(10), name: data.name, sourceIds: data.sourceIds, sourceId: data.sourceIds[0],
    status: 'draft', description: data.description, config: data.config ?? {},
    duplicatePolicy: 'skip', schedule: data.schedule ?? 'manual', templateId: data.templateId,
    periodDays: 7, streams: data.sourceIds.flatMap((sid) => defaultStreamsFromSource(sid)),
    stages: defaultStages(data.sourceIds), reconcileRules: [], rootCatalog: '/Нефтепродукты АЗС',
    docsLoaded: 0, syncLog: [], createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
  }
  const channels = lsGetChannels()
  channels.push(channel)
  setItem(STORAGE_KEY, channels)
  return channel
}

export async function updateChannel(id: string, updates: Partial<Channel>): Promise<Channel | undefined> {
  if (isApiEnabled()) {
    const body: Record<string, unknown> = {}
    if (updates.name !== undefined) body.name = updates.name
    if (updates.description !== undefined) body.description = updates.description
    if (updates.status !== undefined) body.status = updates.status
    if (updates.duplicatePolicy !== undefined) body.duplicate_policy = updates.duplicatePolicy
    if (updates.periodDays !== undefined) body.period_days = updates.periodDays
    if (updates.config !== undefined) body.config = updates.config
    if (updates.schedule !== undefined && typeof updates.schedule !== 'string') body.schedule = updates.schedule
    if (updates.schedule === 'manual') body.schedule = { mode: 'manual' }
    const r = await patch<ApiChannel>(`/api/channels/${id}`, body)
    const ch = chFromApi(r)
    _cache = (_cache ?? []).map((x) => (x.id === id ? ch : x))
    return ch
  }
  const channels = lsGetChannels()
  const idx = channels.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  channels[idx] = { ...channels[idx], ...updates, updatedAt: new Date().toISOString() }
  setItem(STORAGE_KEY, channels)
  return channels[idx]
}

export async function deleteChannel(id: string): Promise<boolean> {
  if (isApiEnabled()) {
    await del(`/api/channels/${id}`)
    _cache = (_cache ?? []).filter((c) => c.id !== id)
    return true
  }
  const channels = lsGetChannels()
  const filtered = channels.filter((c) => c.id !== id)
  if (filtered.length === channels.length) return false
  setItem(STORAGE_KEY, filtered)
  return true
}

export async function addSyncLog(channelId: string, entries: SyncLogEntry[]): Promise<void> {
  if (isApiEnabled()) {
    // В API-режиме синклоги пишет бэкенд (run/ingest); здесь — оптимистично в кэш
    _cache = (_cache ?? []).map((c) => c.id === channelId
      ? { ...c, syncLog: [...entries, ...(c.syncLog || [])].slice(0, 100), lastSync: new Date().toISOString() }
      : c)
    return
  }
  const channels = lsGetChannels()
  const idx = channels.findIndex((c) => c.id === channelId)
  if (idx === -1) return
  channels[idx].syncLog = [...entries, ...(channels[idx].syncLog || [])].slice(0, 100)
  channels[idx].lastSync = new Date().toISOString()
  channels[idx].updatedAt = new Date().toISOString()
  setItem(STORAGE_KEY, channels)
}

/** Запустить канал (API-режим: бэкенд-оркестратор; localStorage: см. channelSyncService). */
export async function runChannel(id: string): Promise<any> {
  if (!isApiEnabled()) throw new Error('runChannel: доступно только в API-режиме')
  const res = await post<any>(`/api/channels/${id}/run`)
  await _refetchOne(id)
  return res
}

/** Добавить источник к каналу */
export async function addSourceToChannel(channelId: string, sourceId: string): Promise<Channel | undefined> {
  if (isApiEnabled()) {
    const s = getSource(sourceId)
    await post<ApiChannel>(`/api/channels/${channelId}/streams`, {
      source_id: sourceId, name: s?.name,
    })
    return _refetchOne(channelId)
  }
  const ch = getChannel(channelId)
  if (!ch) return undefined
  if (ch.sourceIds.includes(sourceId)) return ch
  const newSourceIds = [...ch.sourceIds, sourceId]
  const newStreams = [...ch.streams, ...defaultStreamsFromSource(sourceId)]
  const source = getSource(sourceId)
  const maxOrder = ch.stages.reduce((max, s) => Math.max(max, s.order), -1)
  const fetchStage: ChannelStage = {
    id: nanoid(6), type: 'fetch', name: `Загрузка: ${source?.name ?? sourceId}`,
    sourceId, config: {}, enabled: true, order: maxOrder + 1,
  }
  const stages = [...ch.stages, fetchStage]
  if (newSourceIds.length > 1 && !stages.some((s) => s.type === 'reconcile')) {
    stages.push({ id: nanoid(6), type: 'reconcile', name: 'Сверка источников', config: {}, enabled: true, order: maxOrder + 2 })
  }
  return updateChannel(channelId, { sourceIds: newSourceIds, sourceId: newSourceIds[0], streams: newStreams, stages })
}

/** Убрать источник из канала */
export async function removeSourceFromChannel(channelId: string, sourceId: string): Promise<Channel | undefined> {
  if (isApiEnabled()) {
    const ch = getChannel(channelId)
    const stream = ch?.streams.find((s) => s.sourceId === sourceId)
    if (stream) await del(`/api/channels/${channelId}/streams/${stream.id}`)
    return _refetchOne(channelId)
  }
  const ch = getChannel(channelId)
  if (!ch) return undefined
  const newSourceIds = ch.sourceIds.filter((id) => id !== sourceId)
  const newStreams = ch.streams.filter((s) => s.sourceId !== sourceId)
  let newStages = ch.stages.filter((s) => s.sourceId !== sourceId)
  if (newSourceIds.length <= 1) newStages = newStages.filter((s) => s.type !== 'reconcile')
  return updateChannel(channelId, { sourceIds: newSourceIds, sourceId: newSourceIds[0], streams: newStreams, stages: newStages })
}
