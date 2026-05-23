/**
 * Обёртка над localStorage для типизированного доступа.
 */

export function getItem<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function setItem<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage full or unavailable
  }
}

export function removeItem(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

// ── ID-генератор для нового DataEntry в localStorage-режиме ──

import { nanoid } from 'nanoid'
export const nextId = (): string => nanoid()

// ── Ключи кеша на компанию ───────────────────────────────────
// Используются как fallback для referenceService и других сервисов,
// когда VITE_API_URL не задан. В API-режиме всё хранится в Postgres.

export const entriesKey         = (companyId: string) => `clearledger-entries-${companyId}`
export const counterpartiesKey  = (companyId: string) => `clearledger-counterparties-${companyId}`
export const organizationsKey   = (companyId: string) => `clearledger-organizations-${companyId}`
export const nomenclatureKey    = (companyId: string) => `clearledger-nomenclature-${companyId}`
export const contractsKey       = (companyId: string) => `clearledger-contracts-${companyId}`
export const warehousesKey      = (companyId: string) => `clearledger-warehouses-${companyId}`
export const bankAccountsKey    = (companyId: string) => `clearledger-bank-accounts-${companyId}`
export const balancesKey        = (companyId: string) => `clearledger-balances-${companyId}`
export const accountingDocsKey  = (companyId: string) => `clearledger-accounting-docs-${companyId}`
