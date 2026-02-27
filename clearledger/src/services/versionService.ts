/**
 * Сервис версионности документов.
 *
 * Каждая версия — отдельная DataEntry + свой файл в SourceRecord.
 * Связь через metadata-ключи: _version, _versionRootId, _prevVersionId, _versionNote, _isLatestVersion.
 */

import type { DataEntry } from '@/types'
import * as svc from './dataEntryService'
import { createLink } from './linkService'

export interface VersionInfo {
  id: string
  version: number
  isLatest: boolean
  note?: string
  createdAt: string
  title: string
  status: DataEntry['status']
}

/**
 * Получить историю версий по любому ID из цепочки.
 */
export async function getVersionHistory(companyId: string, entryId: string): Promise<VersionInfo[]> {
  const entry = await svc.getEntry(companyId, entryId)
  if (!entry) return []

  const rootId = entry.metadata._versionRootId || entry.id
  const allEntries = await svc.getEntries(companyId)
  const versions = allEntries.filter(
    (e) => e.id === rootId || e.metadata._versionRootId === rootId,
  )

  return versions
    .map((e) => ({
      id: e.id,
      version: parseInt(e.metadata._version || '1', 10),
      isLatest: e.metadata._isLatestVersion !== 'false',
      note: e.metadata._versionNote,
      createdAt: e.createdAt,
      title: e.title,
      status: e.status,
    }))
    .sort((a, b) => a.version - b.version)
}

/**
 * Получить последнюю версию из цепочки.
 */
export async function getLatestVersion(companyId: string, entryId: string): Promise<DataEntry | undefined> {
  const history = await getVersionHistory(companyId, entryId)
  const latest = history.find((v) => v.isLatest) || history[history.length - 1]
  if (!latest) return undefined
  return svc.getEntry(companyId, latest.id)
}

/**
 * Подготовить metadata для новой версии (вызывается из IntakePage после создания entry).
 * Помечает старую версию как неактуальную, возвращает metadata для новой.
 */
export async function prepareNewVersionMetadata(
  companyId: string,
  prevEntryId: string,
  note?: string,
): Promise<Record<string, string>> {
  const prevEntry = await svc.getEntry(companyId, prevEntryId)
  if (!prevEntry) return {}

  const rootId = prevEntry.metadata._versionRootId || prevEntry.id
  const prevVersion = parseInt(prevEntry.metadata._version || '1', 10)

  // Помечаем предыдущую как неактуальную
  await svc.updateEntry(companyId, prevEntryId, {
    metadata: { ...prevEntry.metadata, _isLatestVersion: 'false' },
  })

  // Если это первая версия (без _versionRootId), добавляем ей metadata
  if (!prevEntry.metadata._versionRootId) {
    await svc.updateEntry(companyId, prevEntryId, {
      metadata: {
        ...prevEntry.metadata,
        _version: '1',
        _versionRootId: prevEntry.id,
        _isLatestVersion: 'false',
      },
    })
  }

  const newMetadata: Record<string, string> = {
    _version: String(prevVersion + 1),
    _versionRootId: rootId,
    _prevVersionId: prevEntryId,
    _isLatestVersion: 'true',
  }
  if (note) newMetadata._versionNote = note

  return newMetadata
}

/**
 * Финализировать создание новой версии — добавить correction link.
 */
export async function finalizeNewVersion(
  _companyId: string,
  newEntryId: string,
  prevEntryId: string,
): Promise<void> {
  await createLink(newEntryId, prevEntryId, 'correction', 'Исправленная версия')
}

/**
 * Сделать указанную версию актуальной (откат).
 */
export async function setActiveVersion(companyId: string, entryId: string): Promise<void> {
  const entry = await svc.getEntry(companyId, entryId)
  if (!entry) return

  const rootId = entry.metadata._versionRootId || entry.id
  const allEntries = await svc.getEntries(companyId)
  const versions = allEntries.filter(
    (e) => e.id === rootId || e.metadata._versionRootId === rootId,
  )

  for (const v of versions) {
    const isTarget = v.id === entryId
    if ((v.metadata._isLatestVersion !== 'false') !== isTarget) {
      await svc.updateEntry(companyId, v.id, {
        metadata: { ...v.metadata, _isLatestVersion: isTarget ? 'true' : 'false' },
      })
    }
  }
}
