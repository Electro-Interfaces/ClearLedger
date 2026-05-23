/**
 * LinkService — управление связями между документами.
 * Dual-mode: localStorage (demo) / API (production).
 */

import { nanoid } from 'nanoid'
import type { DocumentLink, LinkType } from '@/types'
import { isApiEnabled, get, post, del } from './apiClient'
import { apiToLink, linkToApi, type ApiDocumentLink } from './apiMappers'

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
export async function getLinksForEntry(entryId: string): Promise<DocumentLink[]> {
  if (isApiEnabled()) {
    return (await get<ApiDocumentLink[]>(`/api/document-links/entry/${entryId}`)).map(apiToLink)
  }
  return getAll().filter(
    (l) => l.sourceEntryId === entryId || l.targetEntryId === entryId,
  )
}

/** Получить связанные entry ID (без дубликатов) */
export async function getLinkedEntryIds(entryId: string): Promise<string[]> {
  const links = await getLinksForEntry(entryId)
  const ids = new Set<string>()
  for (const link of links) {
    if (link.sourceEntryId !== entryId) ids.add(link.sourceEntryId)
    if (link.targetEntryId !== entryId) ids.add(link.targetEntryId)
  }
  return [...ids]
}

/** Создать связь между двумя записями */
export async function createLink(
  sourceEntryId: string,
  targetEntryId: string,
  type: LinkType,
  label?: string,
): Promise<DocumentLink> {
  if (isApiEnabled()) {
    const body = linkToApi(sourceEntryId, targetEntryId, type, label)
    const a = await post<ApiDocumentLink>('/api/document-links', body)
    return apiToLink(a)
  }

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
export async function removeLink(linkId: string): Promise<void> {
  if (isApiEnabled()) {
    await del(`/api/document-links/${linkId}`)
    return
  }
  const links = getAll().filter((l) => l.id !== linkId)
  saveAll(links)
}

/** Получить все связи определённого типа */
export async function getLinksByType(type: LinkType): Promise<DocumentLink[]> {
  if (isApiEnabled()) {
    return (await get<ApiDocumentLink[]>('/api/document-links', { link_type: type })).map(apiToLink)
  }
  return getAll().filter((l) => l.type === type)
}

/** Удалить все связи записи (при удалении записи) */
export async function removeLinksForEntry(entryId: string): Promise<void> {
  if (isApiEnabled()) {
    // Каскад на бэкенде (ON DELETE CASCADE) или batch delete
    const links = await getLinksForEntry(entryId)
    await Promise.all(links.map((l) => del(`/api/document-links/${l.id}`)))
    return
  }
  const links = getAll().filter(
    (l) => l.sourceEntryId !== entryId && l.targetEntryId !== entryId,
  )
  saveAll(links)
}
