/**
 * localStorage абстракция для ClearLedger.
 * Единый слой доступа к хранилищу с типизацией.
 */

export function getItem<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw !== null) return JSON.parse(raw) as T
  } catch { /* corrupted data — ignore */ }
  return fallback
}

export function setItem(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch (err) {
    if (err instanceof DOMException && err.name === 'QuotaExceededError') {
      // Ленивый импорт sonner чтобы избежать циклических зависимостей при инициализации
      import('sonner').then(({ toast }) => {
        toast.error('Хранилище переполнено! Экспортируйте данные и очистите аудит в Настройках.')
      }).catch(() => { /* ignore */ })
    }
  }
}

export function removeItem(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch { /* ignore */ }
}

// ---- Counter (autoincrement ID) ----

const COUNTER_KEY = 'clearledger-entry-counter'

export function nextId(): string {
  const current = getItem<number>(COUNTER_KEY, 0)
  const next = current + 1
  setItem(COUNTER_KEY, next)
  return String(next)
}

// ---- Typed storage keys ----

export function entriesKey(companyId: string): string {
  return `clearledger-entries-${companyId}`
}

export function counterpartiesKey(companyId: string): string {
  return `clearledger-counterparties-${companyId}`
}

export function organizationsKey(companyId: string): string {
  return `clearledger-organizations-${companyId}`
}

export function nomenclatureKey(companyId: string): string {
  return `clearledger-nomenclature-${companyId}`
}

export function contractsKey(companyId: string): string {
  return `clearledger-contracts-${companyId}`
}

export function warehousesKey(companyId: string): string {
  return `clearledger-warehouses-${companyId}`
}

export function bankAccountsKey(companyId: string): string {
  return `clearledger-bank-accounts-${companyId}`
}

export function accountingDocsKey(companyId: string): string {
  return `clearledger-accounting-docs-${companyId}`
}

// ---- Миграция: добавление docPurpose / syncStatus ----

const MIGRATION_V2_KEY = 'clearledger-migrated-v2'

/**
 * Миграция существующих записей: добавление docPurpose и syncStatus.
 * Вызывается при инициализации приложения (один раз).
 */
export function migrateEntries(): void {
  if (getItem<boolean>(MIGRATION_V2_KEY, false)) return

  const prefix = 'clearledger-entries-'
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key?.startsWith(prefix)) continue

    const entries = getItem<Record<string, unknown>[]>(key, [])
    let changed = false

    for (const entry of entries) {
      if (!entry.docPurpose) {
        // Записи с _excluded → archive
        if (entry.metadata && (entry.metadata as Record<string, string>)._excluded === 'true') {
          entry.docPurpose = 'archive'
        } else {
          entry.docPurpose = 'accounting'
        }
        changed = true
      }
      if (!entry.syncStatus) {
        if (entry.status === 'transferred') {
          entry.syncStatus = 'exported'
        } else {
          entry.syncStatus = 'not_applicable'
        }
        changed = true
      }
    }

    if (changed) setItem(key, entries)
  }

  setItem(MIGRATION_V2_KEY, true)
}
