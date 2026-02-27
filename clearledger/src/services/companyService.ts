/**
 * CompanyService — CRUD компаний.
 * Dual-mode: localStorage (demo) / API (production).
 */

import type { Company, CompanyCustomization } from '@/config/companies'
import { defaultCompanies, emptyCustomization } from '@/config/companies'
import { isApiEnabled, get, post, patch, del } from './apiClient'
import { apiToCompany, companyToApi, type ApiCompany } from './apiMappers'

// ============================================================
// localStorage helpers (demo mode)
// ============================================================

const COMPANIES_KEY = 'clearledger-companies'
const CUSTOM_KEY = 'clearledger-customizations'

function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return fallback
}

function saveToStorage(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* ignore */ }
}

// ============================================================
// Companies CRUD
// ============================================================

export async function getCompanies(): Promise<Company[]> {
  if (isApiEnabled()) {
    const list = await get<ApiCompany[]>('/api/companies')
    return list.map(apiToCompany)
  }
  return loadFromStorage(COMPANIES_KEY, defaultCompanies)
}

export async function createCompany(company: Company): Promise<Company> {
  if (isApiEnabled()) {
    const res = await post<ApiCompany>('/api/companies', companyToApi(company))
    return apiToCompany(res)
  }
  const list = loadFromStorage<Company[]>(COMPANIES_KEY, defaultCompanies)
  list.push(company)
  saveToStorage(COMPANIES_KEY, list)
  return company
}

export async function updateCompany(id: string, updates: Partial<Company>): Promise<Company | undefined> {
  if (isApiEnabled()) {
    const body: Record<string, unknown> = {}
    if (updates.name !== undefined) body.name = updates.name
    if (updates.shortName !== undefined) body.short_name = updates.shortName
    if (updates.profileId !== undefined) body.profile_id = updates.profileId
    if (updates.color !== undefined) body.color = updates.color
    if (updates.inn !== undefined) body.inn = updates.inn
    const res = await patch<ApiCompany>(`/api/companies/${id}`, body)
    return apiToCompany(res)
  }
  const list = loadFromStorage<Company[]>(COMPANIES_KEY, defaultCompanies)
  const idx = list.findIndex((c) => c.id === id)
  if (idx === -1) return undefined
  list[idx] = { ...list[idx], ...updates, id }
  saveToStorage(COMPANIES_KEY, list)
  return list[idx]
}

export async function deleteCompany(id: string): Promise<boolean> {
  if (isApiEnabled()) {
    try {
      await del(`/api/companies/${id}`)
      return true
    } catch {
      return false
    }
  }
  const list = loadFromStorage<Company[]>(COMPANIES_KEY, defaultCompanies)
  const filtered = list.filter((c) => c.id !== id)
  if (filtered.length === list.length) return false
  saveToStorage(COMPANIES_KEY, filtered)
  // Очистка кастомизаций
  const customs = loadFromStorage<Record<string, CompanyCustomization>>(CUSTOM_KEY, {})
  delete customs[id]
  saveToStorage(CUSTOM_KEY, customs)
  return true
}

// ============================================================
// Customizations
// ============================================================

export async function getCustomizations(): Promise<Record<string, CompanyCustomization>> {
  if (isApiEnabled()) {
    try {
      return await get<Record<string, CompanyCustomization>>('/api/settings/customizations')
    } catch {
      return {}
    }
  }
  return loadFromStorage(CUSTOM_KEY, {})
}

export async function getCustomization(companyId: string): Promise<CompanyCustomization> {
  const all = await getCustomizations()
  return all[companyId] ?? emptyCustomization()
}

export async function updateCustomization(
  companyId: string,
  customization: CompanyCustomization,
): Promise<void> {
  if (isApiEnabled()) {
    await patch(`/api/settings/customizations-${companyId}`, customization)
    return
  }
  const customs = loadFromStorage<Record<string, CompanyCustomization>>(CUSTOM_KEY, {})
  customs[companyId] = customization
  saveToStorage(CUSTOM_KEY, customs)
}
