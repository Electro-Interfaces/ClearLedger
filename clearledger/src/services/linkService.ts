/**
 * LinkService — управление связями между документами.
 * Хранит DocumentLink[] в localStorage.
 */

import { nanoid } from 'nanoid'
import type { DocumentLink, LinkType } from '@/types'

const STORAGE_KEY = 'clearledger-links'

function getAll(): DocumentLink[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as DocumentLink[]) : []
  } catch {
    return []
  }
}

function saveAll(links: DocumentLink[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(links))
}

/** Получить все связи для записи (как source или target) */
export function getLinksForEntry(entryId: string): DocumentLink[] {
  return getAll().filter(
    (l) => l.sourceEntryId === entryId || l.targetEntryId === entryId,
  )
}

/** Получить связанные entry ID (без дубликатов) */
export function getLinkedEntryIds(entryId: string): string[] {
  const links = getLinksForEntry(entryId)
  const ids = new Set<string>()
  for (const link of links) {
    if (link.sourceEntryId !== entryId) ids.add(link.sourceEntryId)
    if (link.targetEntryId !== entryId) ids.add(link.targetEntryId)
  }
  return [...ids]
}

/** Создать связь между двумя записями */
export function createLink(
  sourceEntryId: string,
  targetEntryId: string,
  type: LinkType,
  label?: string,
): DocumentLink {
  const links = getAll()

  // Проверяем дубликат связи
  const exists = links.some(
    (l) =>
      l.type === type &&
      ((l.sourceEntryId === sourceEntryId && l.targetEntryId === targetEntryId) ||
       (l.sourceEntryId === targetEntryId && l.targetEntryId === sourceEntryId)),
  )
  if (exists) {
    return links.find(
      (l) =>
        l.type === type &&
        ((l.sourceEntryId === sourceEntryId && l.targetEntryId === targetEntryId) ||
         (l.sourceEntryId === targetEntryId && l.targetEntryId === sourceEntryId)),
    )!
  }

  const link: DocumentLink = {
    id: nanoid(),
    sourceEntryId,
    targetEntryId,
    type,
    label,
    createdAt: new Date().toISOString(),
  }
  links.push(link)
  saveAll(links)
  return link
}

/** Удалить связь */
export function removeLink(linkId: string): void {
  const links = getAll().filter((l) => l.id !== linkId)
  saveAll(links)
}

/** Получить все связи определённого типа */
export function getLinksByType(type: LinkType): DocumentLink[] {
  return getAll().filter((l) => l.type === type)
}

/** Удалить все связи записи (при удалении записи) */
export function removeLinksForEntry(entryId: string): void {
  const links = getAll().filter(
    (l) => l.sourceEntryId !== entryId && l.targetEntryId !== entryId,
  )
  saveAll(links)
}
