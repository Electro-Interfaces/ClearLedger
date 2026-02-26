/**
 * Dev Tools — ядро.
 * Утилиты для разработки: генерация данных, сброс seed, статистика.
 * Используется только в dev-режиме (import.meta.env.DEV).
 */

import type { EntryStatus } from '@/config/statuses'
import type { DataEntry } from '@/types'
import { getItem, setItem, removeItem, entriesKey } from './storage'
import { getEntries, createEntry, seedIfNeeded } from './dataEntryService'
import { getConnectors } from './connectorService'
import { getAllDocumentTypes } from '@/config/categories'
import { defaultCompanies } from '@/config/companies'
import type { ProfileId } from '@/config/profiles'

// ---- Константы ----

const SEED_KEY = 'clearledger-seeded'
const LS_PREFIX = 'clearledger-'

const ALL_STATUSES: EntryStatus[] = ['new', 'recognized', 'verified', 'transferred', 'error']
const ALL_SOURCES: DataEntry['source'][] = ['upload', 'manual', 'api', 'email', 'paste']

const SOURCE_LABELS: Record<string, string> = {
  upload: 'Загрузка файла',
  manual: 'Ручной ввод',
  api: 'API интеграция',
  email: 'Email',
  paste: 'Вставка текста',
}

const COUNTERPARTIES = [
  'ООО "Лукойл"', 'ПАО "Газпром нефть"', 'ООО "ТНК"', 'АО "Роснефть"',
  'ООО "Башнефть"', 'ИП Иванов А.А.', 'ООО "ТрансНефть"', 'АО "Сургутнефтегаз"',
  'ООО "Славнефть"', 'ПАО "Татнефть"',
]

// ---- Утилиты ----

function randomItem<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

function randomDate(daysBack: number): string {
  const now = Date.now()
  const offset = Math.random() * daysBack * 24 * 60 * 60 * 1000
  return new Date(now - offset).toISOString()
}

function getAllClearledgerKeys(): string[] {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key?.startsWith(LS_PREFIX)) keys.push(key)
  }
  return keys
}

// ---- Публичные функции ----

/** Удалить seed-флаг и все записи, заново вызвать seedIfNeeded() */
export function resetSeed(): void {
  removeItem(SEED_KEY)
  // Удалить все записи по компаниям
  for (const company of defaultCompanies) {
    removeItem(entriesKey(company.id))
  }
  // Удалить также кастомные компании
  for (const key of getAllClearledgerKeys()) {
    if (key.startsWith('clearledger-entries-')) {
      removeItem(key)
    }
  }
  removeItem('clearledger-entry-counter')
  seedIfNeeded()
}

/** Полная очистка всех clearledger-* ключей в localStorage */
export function clearAllData(): void {
  for (const key of getAllClearledgerKeys()) {
    removeItem(key)
  }
}

/** Генерация N записей с рандомными данными */
export async function generateEntries(
  companyId: string,
  profileId: ProfileId,
  count: number = 50,
): Promise<DataEntry[]> {
  const docTypes = getAllDocumentTypes(profileId)
  if (docTypes.length === 0) return []

  const created: DataEntry[] = []
  for (let i = 0; i < count; i++) {
    const dt = randomItem(docTypes)
    const source = randomItem(ALL_SOURCES)
    const status = randomItem(ALL_STATUSES)
    const docNumber = `${randomInt(100, 9999)}`
    const amount = `${randomInt(1000, 500000)}`
    const createdAt = randomDate(30)

    const entry = await createEntry({
      title: `${dt.label} №${docNumber}`,
      categoryId: dt.categoryId,
      subcategoryId: dt.subcategoryId,
      docTypeId: dt.id,
      companyId,
      status,
      source,
      sourceLabel: SOURCE_LABELS[source] ?? source,
      metadata: {
        docNumber,
        docDate: new Date(createdAt).toISOString().slice(0, 10),
        counterparty: randomItem(COUNTERPARTIES),
        amount,
      },
    })

    // Перезаписываем createdAt для рандомизации даты
    const entries = getItem<DataEntry[]>(entriesKey(companyId), [])
    const idx = entries.findIndex((e) => e.id === entry.id)
    if (idx !== -1) {
      entries[idx].createdAt = createdAt
      entries[idx].updatedAt = createdAt
      setItem(entriesKey(companyId), entries)
    }

    created.push(entry)
  }
  return created
}

/** Статистика хранилища */
export interface StorageStats {
  totalKeys: number
  totalSizeKB: number
  entriesByCompany: Record<string, number>
  connectorsByCompany: Record<string, number>
}

export async function getStorageStats(): Promise<StorageStats> {
  const keys = getAllClearledgerKeys()
  let totalSize = 0
  for (const key of keys) {
    const val = localStorage.getItem(key)
    if (val) totalSize += key.length + val.length
  }

  const entriesByCompany: Record<string, number> = {}
  const connectorsByCompany: Record<string, number> = {}

  for (const company of defaultCompanies) {
    const entries = await getEntries(company.id)
    if (entries.length > 0) entriesByCompany[company.id] = entries.length
    const connectors = getConnectors(company.id)
    if (connectors.length > 0) connectorsByCompany[company.id] = connectors.length
  }

  // Кастомные компании из localStorage
  for (const key of keys) {
    if (key.startsWith('clearledger-entries-')) {
      const cid = key.replace('clearledger-entries-', '')
      if (!(cid in entriesByCompany)) {
        const entries = await getEntries(cid)
        if (entries.length > 0) entriesByCompany[cid] = entries.length
      }
    }
  }

  return {
    totalKeys: keys.length,
    totalSizeKB: Math.round((totalSize * 2) / 1024), // UTF-16
    entriesByCompany,
    connectorsByCompany,
  }
}

/** Массовая смена статуса всех записей компании */
export function setAllStatuses(companyId: string, status: EntryStatus): number {
  const entries = getItem<DataEntry[]>(entriesKey(companyId), [])
  const now = new Date().toISOString()
  let changed = 0
  for (const entry of entries) {
    if (entry.status !== status) {
      entry.status = status
      entry.updatedAt = now
      changed++
    }
  }
  if (changed > 0) setItem(entriesKey(companyId), entries)
  return changed
}

/** Удаление всех записей одной компании */
export async function deleteAllEntries(companyId: string): Promise<number> {
  const entries = await getEntries(companyId)
  const count = entries.length
  removeItem(entriesKey(companyId))
  return count
}
