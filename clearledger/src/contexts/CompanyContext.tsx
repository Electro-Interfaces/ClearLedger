import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react'
import { defaultCompanies, defaultCompanyId, emptyCustomization, type Company, type CompanyCustomization } from '@/config/companies'
import { getProfile, type ProfileId, type CompanyProfile } from '@/config/profiles'
import { getCategoriesForProfile, type Category } from '@/config/categories'
import { useQueryClient } from '@tanstack/react-query'

interface CompanyContextType {
  company: Company
  companyId: string
  setCompanyId: (id: string) => void
  companies: Company[]
  profile: CompanyProfile
  categories: Category[]
  customization: CompanyCustomization
  /** Все кастомизации по companyId */
  customizations: Record<string, CompanyCustomization>
  /** Обновить компанию (профиль, имя, цвет...) */
  updateCompany: (id: string, updates: Partial<Company>) => void
  /** Добавить новую компанию */
  addCompany: (company: Company) => void
  /** Удалить компанию */
  removeCompany: (id: string) => void
  /** Обновить кастомизацию для компании */
  updateCustomization: (companyId: string, customization: CompanyCustomization) => void
  /** Категории, отфильтрованные по кастомизации */
  effectiveCategories: Category[]
}

const CompanyContext = createContext<CompanyContextType | null>(null)

const STORAGE_KEY = 'clearledger-company'
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

function getInitialCompanyId(companies: Company[]): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && companies.some((c) => c.id === stored)) return stored
  } catch { /* ignore */ }
  return defaultCompanyId
}

/** Применить кастомизацию: убрать отключённые категории/подкатегории/типы */
function applyCustomization(categories: Category[], custom: CompanyCustomization): Category[] {
  return categories
    .filter((cat) => !custom.disabledCategories.includes(cat.id))
    .map((cat) => ({
      ...cat,
      subcategories: cat.subcategories
        .filter((sub) => !custom.disabledSubcategories.includes(`${cat.id}/${sub.id}`))
        .map((sub) => ({
          ...sub,
          documentTypes: sub.documentTypes.filter((dt) => !custom.disabledDocTypes.includes(dt.id)),
        }))
        .filter((sub) => sub.documentTypes.length > 0),
    }))
    .filter((cat) => cat.subcategories.length > 0)
}

export function CompanyProvider({ children }: { children: ReactNode }) {
  const [companiesList, setCompaniesList] = useState<Company[]>(() =>
    loadFromStorage(COMPANIES_KEY, defaultCompanies),
  )
  const [customizations, setCustomizations] = useState<Record<string, CompanyCustomization>>(() =>
    loadFromStorage(CUSTOM_KEY, {}),
  )
  const [companyId, setCompanyIdState] = useState(() => getInitialCompanyId(companiesList))
  const queryClient = useQueryClient()

  const setCompanyId = useCallback(
    (id: string) => {
      setCompanyIdState(id)
      try { localStorage.setItem(STORAGE_KEY, id) } catch { /* ignore */ }
      queryClient.invalidateQueries()
    },
    [queryClient],
  )

  const updateCompany = useCallback((id: string, updates: Partial<Company>) => {
    setCompaniesList((prev) => {
      const next = prev.map((c) => (c.id === id ? { ...c, ...updates, id } : c))
      saveToStorage(COMPANIES_KEY, next)
      return next
    })
    queryClient.invalidateQueries()
  }, [queryClient])

  const addCompany = useCallback((company: Company) => {
    setCompaniesList((prev) => {
      const next = [...prev, company]
      saveToStorage(COMPANIES_KEY, next)
      return next
    })
  }, [])

  const removeCompany = useCallback((id: string) => {
    setCompaniesList((prev) => {
      const next = prev.filter((c) => c.id !== id)
      saveToStorage(COMPANIES_KEY, next)
      return next
    })
    setCustomizations((prev) => {
      const next = { ...prev }
      delete next[id]
      saveToStorage(CUSTOM_KEY, next)
      return next
    })
    // Если удалили текущую — переключиться
    setCompanyIdState((current) => {
      if (current === id) {
        const fallback = companiesList.find((c) => c.id !== id)?.id ?? defaultCompanyId
        try { localStorage.setItem(STORAGE_KEY, fallback) } catch { /* ignore */ }
        return fallback
      }
      return current
    })
  }, [companiesList])

  const updateCustomization = useCallback((cId: string, customization: CompanyCustomization) => {
    setCustomizations((prev) => {
      const next = { ...prev, [cId]: customization }
      saveToStorage(CUSTOM_KEY, next)
      return next
    })
    queryClient.invalidateQueries()
  }, [queryClient])

  const company = companiesList.find((c) => c.id === companyId) ?? companiesList[0] ?? defaultCompanies[0]
  const customization = customizations[companyId] ?? emptyCustomization()
  const profile = useMemo(() => getProfile(company.profileId), [company.profileId])
  const categories = useMemo(() => getCategoriesForProfile(company.profileId), [company.profileId])
  const effectiveCategories = useMemo(
    () => applyCustomization(categories, customization),
    [categories, customization],
  )

  return (
    <CompanyContext.Provider
      value={{
        company, companyId, setCompanyId,
        companies: companiesList,
        profile, categories, customization, customizations,
        updateCompany, addCompany, removeCompany, updateCustomization,
        effectiveCategories,
      }}
    >
      {children}
    </CompanyContext.Provider>
  )
}

export function useCompany() {
  const ctx = useContext(CompanyContext)
  if (!ctx) throw new Error('useCompany must be used within CompanyProvider')
  return ctx
}
