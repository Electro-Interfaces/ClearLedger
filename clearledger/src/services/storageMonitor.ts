/**
 * Мониторинг использования localStorage.
 * Предупреждения при >80%, критическое при >95%.
 */

import { getItem, setItem } from './storage'

export interface StorageUsage {
  usedBytes: number
  totalBytes: number
  percent: number
  entries: number
  audit: number
  other: number
}

export interface StorageBreakdown {
  key: string
  bytes: number
  percent: number
}

const TOTAL_ESTIMATE = 5 * 1024 * 1024 // 5MB — типичный лимит localStorage

function byteLength(str: string): number {
  // Быстрая оценка: UTF-16 → ~2 байта на символ, но JSON в localStorage — в основном ASCII
  return new Blob([str]).size
}

/** Общее использование localStorage */
export function getStorageUsage(): StorageUsage {
  let usedBytes = 0
  let entries = 0
  let audit = 0
  let other = 0

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key) continue
    const value = localStorage.getItem(key) ?? ''
    const size = byteLength(key) + byteLength(value)
    usedBytes += size

    if (key.startsWith('clearledger-entries-')) {
      entries += size
    } else if (key.startsWith('clearledger-audit-')) {
      audit += size
    } else {
      other += size
    }
  }

  return {
    usedBytes,
    totalBytes: TOTAL_ESTIMATE,
    percent: Math.round((usedBytes / TOTAL_ESTIMATE) * 100),
    entries,
    audit,
    other,
  }
}

/** Проверка порога предупреждения */
export function isStorageWarning(threshold = 80): boolean {
  return getStorageUsage().percent >= threshold
}

/** Проверка критического порога */
export function isStorageCritical(threshold = 95): boolean {
  return getStorageUsage().percent >= threshold
}

/** Детализация по ключам clearledger-* */
export function getStorageBreakdown(): StorageBreakdown[] {
  const items: StorageBreakdown[] = []
  let totalUsed = 0

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key || !key.startsWith('clearledger-')) continue
    const value = localStorage.getItem(key) ?? ''
    const bytes = byteLength(key) + byteLength(value)
    totalUsed += bytes
    items.push({ key, bytes, percent: 0 })
  }

  for (const item of items) {
    item.percent = totalUsed > 0 ? Math.round((item.bytes / totalUsed) * 100) : 0
  }

  return items.sort((a, b) => b.bytes - a.bytes)
}

/** Автоочистка старого аудита, оставляет keepLast записей */
export function cleanupOldAudit(companyId: string, keepLast = 1000): number {
  const key = `clearledger-audit-${companyId}`
  const events = getItem<unknown[]>(key, [])
  if (events.length <= keepLast) return 0
  const removed = events.length - keepLast
  setItem(key, events.slice(-keepLast))
  return removed
}

/** Форматирование байт в читаемый вид */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(2)} МБ`
}
