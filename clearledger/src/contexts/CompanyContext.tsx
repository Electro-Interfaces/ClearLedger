/**
 * Контекст компании — упрощённый, одна компания ГИГ.
 */

import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { defaultCompanies, emptyCustomization, type Company, type CompanyCustomization } from '@/config/companies'
import { getProfile, type CompanyProfile } from '@/config/profiles'
import { getCategoriesForProfile, type Category } from '@/config/categories'

interface CompanyContextType {
  company: Company
  companyId: string
  companies: Company[]
  profile: CompanyProfile
  categories: Category[]
  customization: CompanyCustomization
  effectiveCategories: Category[]
  isLoading: false
}

const CompanyContext = createContext<CompanyContextType | null>(null)

export function CompanyProvider({ children }: { children: ReactNode }) {
  const company = defaultCompanies[0]
  const customization = emptyCustomization()
  const profile = useMemo(() => getProfile(company.profileId), [company.profileId])
  const categories = useMemo(() => getCategoriesForProfile(company.profileId), [company.profileId])

  return (
    <CompanyContext.Provider
      value={{
        company,
        companyId: company.id,
        companies: defaultCompanies,
        profile,
        categories,
        customization,
        effectiveCategories: categories,
        isLoading: false,
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
