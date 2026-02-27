import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react'
import { defaultCompanies, defaultCompanyId, emptyCustomization, type Company, type CompanyCustomization } from '@/config/companies'
import { getProfile, type CompanyProfile } from '@/config/profiles'
import { getCategoriesForProfile, type Category } from '@/config/categories'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as companySvc from '@/services/companyService'

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
  /** Загрузка данных компаний */
  isLoading: boolean
}

const CompanyContext = createContext<CompanyContextType | null>(null)

const STORAGE_KEY = 'clearledger-company'

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
  const queryClient = useQueryClient()

  // Загрузка компаний через useQuery (API или localStorage)
  const companiesQuery = useQuery({
    queryKey: ['companies'],
    queryFn: companySvc.getCompanies,
    staleTime: 10 * 60 * 1000,
    // initialData чтобы не было мигания при первой загрузке
    placeholderData: defaultCompanies,
  })

  // Загрузка кастомизаций
  const customizationsQuery = useQuery({
    queryKey: ['customizations'],
    queryFn: companySvc.getCustomizations,
    staleTime: 10 * 60 * 1000,
    placeholderData: {},
  })

  const companiesList = companiesQuery.data ?? defaultCompanies
  const customizations = customizationsQuery.data ?? {}

  const [companyId, setCompanyIdState] = useState(() => getInitialCompanyId(companiesList))

  const setCompanyId = useCallback(
    (id: string) => {
      setCompanyIdState(id)
      try { localStorage.setItem(STORAGE_KEY, id) } catch { /* ignore */ }
      queryClient.invalidateQueries()
    },
    [queryClient],
  )

  // Мутации
  const updateCompanyMut = useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<Company> }) =>
      companySvc.updateCompany(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] })
    },
  })

  const addCompanyMut = useMutation({
    mutationFn: (company: Company) => companySvc.createCompany(company),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] })
    },
  })

  const removeCompanyMut = useMutation({
    mutationFn: (id: string) => companySvc.deleteCompany(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['companies'] })
      queryClient.invalidateQueries({ queryKey: ['customizations'] })
      // Если удалили текущую — переключиться
      setCompanyIdState((current) => {
        if (current === id) {
          const fallback = companiesList.find((c) => c.id !== id)?.id ?? defaultCompanyId
          try { localStorage.setItem(STORAGE_KEY, fallback) } catch { /* ignore */ }
          return fallback
        }
        return current
      })
    },
  })

  const updateCustomizationMut = useMutation({
    mutationFn: ({ cId, customization }: { cId: string; customization: CompanyCustomization }) =>
      companySvc.updateCustomization(cId, customization),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customizations'] })
      queryClient.invalidateQueries()
    },
  })

  // Обратная совместимость — те же сигнатуры, что раньше
  const updateCompany = useCallback((id: string, updates: Partial<Company>) => {
    updateCompanyMut.mutate({ id, updates })
  }, [updateCompanyMut])

  const addCompany = useCallback((company: Company) => {
    addCompanyMut.mutate(company)
  }, [addCompanyMut])

  const removeCompany = useCallback((id: string) => {
    removeCompanyMut.mutate(id)
  }, [removeCompanyMut])

  const updateCustomization = useCallback((cId: string, customization: CompanyCustomization) => {
    updateCustomizationMut.mutate({ cId, customization })
  }, [updateCustomizationMut])

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
        isLoading: companiesQuery.isLoading,
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
