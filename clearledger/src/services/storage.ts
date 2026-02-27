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
