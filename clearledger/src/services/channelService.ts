/**
 * CRUD для каналов данных (localStorage).
 * Канал = работа с данными из источника (расписание, периоды, потоки, каталоги).
 */

import { getItem, setItem } from './storage'
import { getSource } from './sourceService'
import type { Channel, ChannelStream, SyncLogEntry } from '@/types/channel'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-channels'

/** Создать дефолтные потоки из типов документов источника */
function defaultStreamsFromSource(sourceId: string): ChannelStream[] {
  const source = getSource(sourceId)
  if (!source) return []
  return source.docTypes.map((dt) => ({
    id: nanoid(6),
    docTypeId: dt.id,
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

export function getChannels(): Channel[] {
  return getItem<Channel[]>(STORAGE_KEY, [])
}

export function getChannel(id: string): Channel | undefined {
  return getChannels().find((c) => c.id === id)
}

export function createChannel(data: {
  name: string
  sourceId: string
  description?: string
}): Channel {
  const channel: Channel = {
    id: nanoid(10),
    name: data.name,
    sourceId: data.sourceId,
    status: 'draft',
    description: data.description,
    duplicatePolicy: 'skip',
    schedule: 'manual',
    periodDays: 7,
    streams: defaultStreamsFromSource(data.sourceId),
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
