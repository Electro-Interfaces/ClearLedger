/**
 * CRUD для источников данных (localStorage).
 * Источник = подключение (URL, credentials) + доступные типы документов.
 */

import { getItem, setItem } from './storage'
import type { Source, SourceType, SourceDocType } from '@/types/channel'
import { defaultStsDocTypes } from '@/types/channel'
import { nanoid } from 'nanoid'

const STORAGE_KEY = 'gig-sources'

export function getSources(): Source[] {
  return getItem<Source[]>(STORAGE_KEY, [])
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
    docTypes: data.docTypes ?? (data.type === 'rest' ? defaultStsDocTypes() : []),
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
