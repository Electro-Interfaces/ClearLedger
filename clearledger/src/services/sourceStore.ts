/**
 * IndexedDB-хранилище для Source (оригинальные файлы) и Extract (результат pipeline).
 * Заменяет blobStore.ts — структурированное хранение для Слоя 2.
 */

import { openDB, type IDBPDatabase } from 'idb'
import type { SourceRecord, ExtractRecord } from '@/types'
import { isApiEnabled, downloadBlob } from './apiClient'

const DB_NAME = 'clearledger-store'
const DB_VERSION = 1
const SOURCES_STORE = 'sources'
const EXTRACTS_STORE = 'extracts'

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(SOURCES_STORE)) {
          db.createObjectStore(SOURCES_STORE, { keyPath: 'id' })
        }
        if (!db.objectStoreNames.contains(EXTRACTS_STORE)) {
          db.createObjectStore(EXTRACTS_STORE, { keyPath: 'id' })
        }
      },
    })
  }
  return dbPromise
}

// ---- Sources (оригинальный файл, immutable) ----

export async function saveSource(record: SourceRecord): Promise<void> {
  const db = await getDb()
  await db.put(SOURCES_STORE, record)
}

export async function getSource(id: string): Promise<SourceRecord | undefined> {
  const db = await getDb()
  return db.get(SOURCES_STORE, id)
}

export async function deleteSource(id: string): Promise<void> {
  const db = await getDb()
  const tx = db.transaction([SOURCES_STORE, EXTRACTS_STORE], 'readwrite')
  await Promise.all([
    tx.objectStore(SOURCES_STORE).delete(id),
    tx.objectStore(EXTRACTS_STORE).delete(id),
    tx.done,
  ])
}

export async function getSourceBlobUrl(id: string): Promise<string | null> {
  if (isApiEnabled()) {
    try {
      const blob = await downloadBlob(`/api/files/${id}`)
      return URL.createObjectURL(blob)
    } catch {
      return null
    }
  }
  const source = await getSource(id)
  return source ? URL.createObjectURL(source.blob) : null
}

/** Получить fingerprint из sources для dedup */
export async function getSourceByFingerprint(fingerprint: string): Promise<SourceRecord | undefined> {
  const db = await getDb()
  const all = await db.getAll(SOURCES_STORE) as SourceRecord[]
  return all.find((s) => s.fingerprint === fingerprint)
}

// ---- Extracts (результат pipeline, может перезаписываться) ----

export async function saveExtract(record: ExtractRecord): Promise<void> {
  const db = await getDb()
  await db.put(EXTRACTS_STORE, record)
}

export async function getExtract(id: string): Promise<ExtractRecord | undefined> {
  const db = await getDb()
  return db.get(EXTRACTS_STORE, id)
}

export async function deleteExtract(id: string): Promise<void> {
  const db = await getDb()
  await db.delete(EXTRACTS_STORE, id)
}

// ---- Миграция / очистка ----

export async function clearAll(): Promise<void> {
  const db = await getDb()
  const tx = db.transaction([SOURCES_STORE, EXTRACTS_STORE], 'readwrite')
  await Promise.all([
    tx.objectStore(SOURCES_STORE).clear(),
    tx.objectStore(EXTRACTS_STORE).clear(),
    tx.done,
  ])
}
