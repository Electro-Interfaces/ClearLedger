/**
 * IndexedDB blob-хранилище для ClearLedger.
 * Файлы (PDF, изображения и т.д.) хранятся здесь, метаданные — в localStorage.
 */

import { openDB, type IDBPDatabase } from 'idb'

const DB_NAME = 'clearledger-blobs'
const DB_VERSION = 1
const STORE_NAME = 'blobs'

interface BlobRecord {
  id: string
  data: Blob
  mimeType: string
  size: number
}

let dbPromise: Promise<IDBPDatabase> | null = null

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'id' })
        }
      },
    })
  }
  return dbPromise
}

export async function saveBlob(id: string, data: Blob): Promise<void> {
  const db = await getDb()
  const record: BlobRecord = {
    id,
    data,
    mimeType: data.type,
    size: data.size,
  }
  await db.put(STORE_NAME, record)
}

export async function getBlob(id: string): Promise<Blob | null> {
  const db = await getDb()
  const record = await db.get(STORE_NAME, id) as BlobRecord | undefined
  return record?.data ?? null
}

export async function deleteBlob(id: string): Promise<void> {
  const db = await getDb()
  await db.delete(STORE_NAME, id)
}

export async function clearBlobs(): Promise<void> {
  const db = await getDb()
  await db.clear(STORE_NAME)
}

/** Создать Object URL для blob из IndexedDB */
export async function getBlobUrl(id: string): Promise<string | null> {
  const blob = await getBlob(id)
  return blob ? URL.createObjectURL(blob) : null
}
