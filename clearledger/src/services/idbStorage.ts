/**
 * IndexedDB key-value хранилище для тяжёлых данных.
 * Заменяет localStorage для entries, references, snapshots, accounting-docs.
 * Лимит IndexedDB: сотни МБ (vs 5 МБ localStorage).
 */

import { openDB, type IDBPDatabase } from 'idb'

const DB_NAME = 'clearledger-data'
const DB_VERSION = 1
const STORE_NAME = 'kv'

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME)
        }
      },
    })
  }
  return dbPromise
}

/** Прочитать значение из IndexedDB */
export async function getItemIDB<T>(key: string, fallback: T): Promise<T> {
  try {
    const db = await getDb()
    const value = await db.get(STORE_NAME, key)
    if (value !== undefined) return value as T
  } catch { /* ignore */ }
  return fallback
}

/** Записать значение в IndexedDB */
export async function setItemIDB(key: string, value: unknown): Promise<void> {
  try {
    const db = await getDb()
    await db.put(STORE_NAME, value, key)
  } catch { /* ignore */ }
}

/** Удалить ключ из IndexedDB */
export async function removeItemIDB(key: string): Promise<void> {
  try {
    const db = await getDb()
    await db.delete(STORE_NAME, key)
  } catch { /* ignore */ }
}

/** Получить все ключи (для мониторинга / миграции) */
export async function getAllKeysIDB(): Promise<string[]> {
  try {
    const db = await getDb()
    return (await db.getAllKeys(STORE_NAME)) as string[]
  } catch { return [] }
}

/** Оценка размера данных в IndexedDB */
export async function getIDBSizeEstimate(): Promise<{ usedBytes: number; keys: number }> {
  try {
    if (navigator.storage?.estimate) {
      const est = await navigator.storage.estimate()
      return { usedBytes: est.usage ?? 0, keys: (await getAllKeysIDB()).length }
    }
  } catch { /* ignore */ }
  return { usedBytes: 0, keys: 0 }
}

// ============================================================
// Миграция localStorage → IndexedDB (одноразовая)
// ============================================================

const MIGRATION_FLAG = 'clearledger-idb-migrated'

/** Перенести данные из localStorage в IndexedDB и очистить localStorage */
export async function migrateLocalStorageToIDB(): Promise<number> {
  // Уже мигрировали?
  if (localStorage.getItem(MIGRATION_FLAG) === 'true') return 0

  const keysToMigrate: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key?.startsWith('clearledger-')) continue
    // Мигрируем только тяжёлые данные (массивы), не флаги
    if (
      key.startsWith('clearledger-entries-') ||
      key.startsWith('clearledger-counterparties-') ||
      key.startsWith('clearledger-organizations-') ||
      key.startsWith('clearledger-nomenclature-') ||
      key.startsWith('clearledger-contracts-') ||
      key.startsWith('clearledger-warehouses-') ||
      key.startsWith('clearledger-bank-accounts-') ||
      key.startsWith('clearledger-balances-') ||
      key.startsWith('clearledger-accounting-docs-') ||
      key.startsWith('clearledger-journal-') ||
      key.startsWith('clearledger-osv-') ||
      key.startsWith('clearledger-chartOfAccounts-') ||
      key.startsWith('clearledger-accountingPolicy-') ||
      key.startsWith('clearledger-filings-') ||
      key.startsWith('clearledger-fixedAssets-') ||
      key.startsWith('clearledger-audit-')
    ) {
      keysToMigrate.push(key)
    }
  }

  if (keysToMigrate.length === 0) {
    localStorage.setItem(MIGRATION_FLAG, 'true')
    return 0
  }

  let migrated = 0
  for (const key of keysToMigrate) {
    try {
      const raw = localStorage.getItem(key)
      if (raw !== null) {
        const data = JSON.parse(raw)
        await setItemIDB(key, data)
        localStorage.removeItem(key)
        migrated++
      }
    } catch {
      // Если не удалось распарсить — просто удаляем из localStorage
      localStorage.removeItem(key)
    }
  }

  localStorage.setItem(MIGRATION_FLAG, 'true')
  return migrated
}
