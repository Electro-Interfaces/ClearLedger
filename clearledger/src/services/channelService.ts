/**
 * CRUD для каналов данных (localStorage).
 */

import { getItem, setItem } from './storage'
import type { Channel, ChannelType } from '@/types/channel'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-channels'

export function getChannels(): Channel[] {
  return getItem<Channel[]>(STORAGE_KEY, [])
}

export function getChannel(id: string): Channel | undefined {
  return getChannels().find((c) => c.id === id)
}

export function createChannel(data: {
  name: string
  type: ChannelType
  endpoint?: string
  description?: string
  config?: Record<string, string>
}): Channel {
  const channel: Channel = {
    id: nanoid(10),
    name: data.name,
    type: data.type,
    status: 'draft',
    description: data.description,
    endpoint: data.endpoint,
    config: data.config ?? {},
    docsLoaded: 0,
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
