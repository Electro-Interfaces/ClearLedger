/**
 * CRUD для каналов данных (localStorage).
 * Канал = pipeline обработки данных: несколько источников → обработка → сверка → результат.
 */

import { getItem, setItem } from './storage'
import { getSource } from './sourceService'
import type { Channel, ChannelStream, ChannelStage, SyncLogEntry } from '@/types/channel'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-channels'

/** Создать дефолтные потоки из типов документов источника */
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
    enabled: dt.id !== 'price', // цены выключены по умолчанию
  }))
}

/** Создать дефолтные этапы pipeline */
function defaultStages(sourceIds: string[]): ChannelStage[] {
  const stages: ChannelStage[] = []
  let order = 0

  // Этап загрузки для каждого источника
  for (const sourceId of sourceIds) {
    const source = getSource(sourceId)
    stages.push({
      id: nanoid(6),
      type: 'fetch',
      name: `Загрузка: ${source?.name ?? sourceId}`,
      sourceId,
      config: {},
      enabled: true,
      order: order++,
    })
  }

  // Нормализация
  stages.push({
    id: nanoid(6),
    type: 'normalize',
    name: 'Нормализация данных',
    config: {},
    enabled: true,
    order: order++,
  })

  // Сверка (если больше 1 источника)
  if (sourceIds.length > 1) {
    stages.push({
      id: nanoid(6),
      type: 'reconcile',
      name: 'Сверка источников',
      config: {},
      enabled: true,
      order: order++,
    })
  }

  return stages
}

/** Миграция: старый формат (sourceId) → новый (sourceIds, stations) */
function migrateChannel(ch: any): Channel {
  if (!ch.sourceIds) {
    ch.sourceIds = ch.sourceId ? [ch.sourceId] : []
  }
  if (!ch.stages) {
    ch.stages = defaultStages(ch.sourceIds)
  }
  if (!ch.reconcileRules) {
    ch.reconcileRules = []
  }
  if (!ch.rootCatalog) {
    ch.rootCatalog = '/Нефтепродукты АЗС'
  }
  if (!ch.config) {
    ch.config = {}
  }
  // Миграция потоков: добавить sourceId если нет
  if (ch.streams) {
    const primarySourceId = ch.sourceIds[0] ?? ch.sourceId ?? ''
    for (const s of ch.streams) {
      if (!s.sourceId) s.sourceId = primarySourceId
    }
  }
  // Миграция станций: stationCodes:number[] → stations:ChannelStation[]
  // с системой по умолчанию из config.systemCode (если был) или 65.
  if (!ch.config.stations && Array.isArray(ch.config.stationCodes)) {
    const fallbackSystem = Number(ch.config.systemCode ?? 65)
    ch.config.stations = ch.config.stationCodes.map((code: number) => ({
      code: Number(code), systemId: fallbackSystem,
    }))
  }
  // Удаляем устаревшее description вида «сеть 65, станция 5» — оно сужает
  // канал до одной сети, что больше не верно для ГИГ.
  if (typeof ch.description === 'string' && /сеть\s*65,\s*станция/i.test(ch.description)) {
    ch.description = ch.description
      .replace(/\s*\(сеть\s*65,\s*станция[^)]*\)\s*/i, '')
      .trim()
  }
  return ch as Channel
}

export function getChannels(): Channel[] {
  return getItem<any[]>(STORAGE_KEY, []).map(migrateChannel)
}

export function getChannel(id: string): Channel | undefined {
  return getChannels().find((c) => c.id === id)
}

export function createChannel(data: {
  name: string
  sourceIds: string[]
  description?: string
  config?: Record<string, any>
  templateId?: string
  schedule?: import('@/types/channel').ScheduleConfig
}): Channel {
  const channel: Channel = {
    id: nanoid(10),
    name: data.name,
    sourceIds: data.sourceIds,
    sourceId: data.sourceIds[0], // legacy compat
    status: 'draft',
    description: data.description,
    config: data.config ?? {},
    duplicatePolicy: 'skip',
    schedule: data.schedule ?? 'manual',
    templateId: data.templateId,
    periodDays: 7,
    streams: data.sourceIds.flatMap((sid) => defaultStreamsFromSource(sid)),
    stages: defaultStages(data.sourceIds),
    reconcileRules: [],
    rootCatalog: '/Нефтепродукты АЗС',
    docsLoaded: 0,
    syncLog: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
  const channels = getChannels()
  channels.push(channel)
  setItem(STORAGE_KEY, channels)
  return channel
}

export function updateChannel(id: string, updates: Partial<Channel>): Channel | undefined {
  const channels = getChannels()
  const idx = channels.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  channels[idx] = { ...channels[idx], ...updates, updatedAt: new Date().toISOString() }
  setItem(STORAGE_KEY, channels)
  return channels[idx]
}

export function deleteChannel(id: string): boolean {
  const channels = getChannels()
  const filtered = channels.filter((c) => c.id !== id)
  if (filtered.length === channels.length) return false
  setItem(STORAGE_KEY, filtered)
  return true
}

export function addSyncLog(channelId: string, entries: SyncLogEntry[]): void {
  const channels = getChannels()
  const idx = channels.findIndex((c) => c.id === channelId)
  if (idx === -1) return
  const log = [...entries, ...(channels[idx].syncLog || [])].slice(0, 100)
  channels[idx].syncLog = log
  channels[idx].lastSync = new Date().toISOString()
  channels[idx].updatedAt = new Date().toISOString()
  setItem(STORAGE_KEY, channels)
}

/** Добавить источник к каналу */
export function addSourceToChannel(channelId: string, sourceId: string): Channel | undefined {
  const ch = getChannel(channelId)
  if (!ch) return undefined
  if (ch.sourceIds.includes(sourceId)) return ch

  const newSourceIds = [...ch.sourceIds, sourceId]
  const newStreams = [...ch.streams, ...defaultStreamsFromSource(sourceId)]

  // Добавить fetch-этап для нового источника
  const source = getSource(sourceId)
  const maxOrder = ch.stages.reduce((max, s) => Math.max(max, s.order), -1)
  const fetchStage: ChannelStage = {
    id: nanoid(6),
    type: 'fetch',
    name: `Загрузка: ${source?.name ?? sourceId}`,
    sourceId,
    config: {},
    enabled: true,
    order: maxOrder + 1,
  }

  // Добавить reconcile если стало >1 источника и ещё нет
  const stages = [...ch.stages, fetchStage]
  if (newSourceIds.length > 1 && !stages.some((s) => s.type === 'reconcile')) {
    stages.push({
      id: nanoid(6),
      type: 'reconcile',
      name: 'Сверка источников',
      config: {},
      enabled: true,
      order: maxOrder + 2,
    })
  }

  return updateChannel(channelId, {
    sourceIds: newSourceIds,
    sourceId: newSourceIds[0],
    streams: newStreams,
    stages,
  })
}

/** Убрать источник из канала */
export function removeSourceFromChannel(channelId: string, sourceId: string): Channel | undefined {
  const ch = getChannel(channelId)
  if (!ch) return undefined

  const newSourceIds = ch.sourceIds.filter((id) => id !== sourceId)
  const newStreams = ch.streams.filter((s) => s.sourceId !== sourceId)
  let newStages = ch.stages.filter((s) => s.sourceId !== sourceId)

  // Убрать reconcile если остался 1 источник
  if (newSourceIds.length <= 1) {
    newStages = newStages.filter((s) => s.type !== 'reconcile')
  }

  return updateChannel(channelId, {
    sourceIds: newSourceIds,
    sourceId: newSourceIds[0],
    streams: newStreams,
    stages: newStages,
  })
}
