/**
 * Контекст активной компании (мультитенантность).
 *
 * Список компаний — из AuthContext (user.companies; суперадмину бэкенд /me
 * уже отдаёт все). Активная компания персистится под пользователя и валидируется
 * по списку доступных. При смене компании — полная зачистка кэшей (React Query +
 * модульные кэши сервисов), чтобы данные компаний не перемешивались.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  defaultCompanies, emptyCustomization,
  type Company, type CompanyCustomization,
} from '@/config/companies'
import { getProfile, type CompanyProfile, type ProfileId } from '@/config/profiles'
import { getCategoriesForProfile, type Category } from '@/config/categories'
import { useAuth } from '@/contexts/AuthContext'
import type { CompanyRef } from '@/services/authService'
import { resetServiceCaches, setServicesCompany } from '@/services/cacheReset'

interface CompanyContextType {
  company: Company
  companyId: string
  companies: Company[]
  setCompanyId: (id: string) => void
  profile: CompanyProfile
  categories: Category[]
  customization: CompanyCustomization
  effectiveCategories: Category[]
  isLoading: boolean
}

const CompanyContext = createContext<CompanyContextType | null>(null)

const activeKey = (userId: string) => `tl-active-company-${userId}`

/** CompanyRef (snake_case с бэка) → Company (тип фронта), достраивая из конфига. */
function toCompany(c: CompanyRef): Company {
  const known = defaultCompanies.find((d) => d.id === c.id)
  return {
    id: c.id,
    name: c.name,
    shortName: c.short_name ?? known?.shortName ?? c.name,
    inn: known?.inn,
    color: c.color ?? known?.color ?? '#3b82f6',
    profileId: (c.profile_id ?? known?.profileId ?? 'fuel') as ProfileId,
  }
}

export function CompanyProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth()
  const qc = useQueryClient()

  const companies = useMemo<Company[]>(
    () => (user?.companies ?? []).map(toCompany),
    [user],
  )

  const [companyId, setCompanyIdState] = useState<string>('')

  // Выбор активной компании при появлении пользователя / смене списка.
  useEffect(() => {
    if (!user) { setCompanyIdState(''); return }
    const saved = localStorage.getItem(activeKey(user.id))
    const valid = saved && companies.some((c) => c.id === saved)
    const next = valid ? saved! : (companies[0]?.id ?? '')
    setCompanyIdState(next)
  }, [user, companies])

  // Изоляция: при СМЕНЕ активной компании (не первый выбор) — сброс кэшей.
  const prevId = useRef<string | null>(null)
  useEffect(() => {
    if (!companyId) return
    if (prevId.current && prevId.current !== companyId) {
      qc.clear()
      resetServiceCaches()
    }
    setServicesCompany(companyId)  // синхронизируем модульный _companyId сервисов
    prevId.current = companyId
  }, [companyId, qc])

  const setCompanyId = useCallback((id: string) => {
    if (!user) return
    if (!companies.some((c) => c.id === id)) return  // валидация: id ∈ доступные
    localStorage.setItem(activeKey(user.id), id)
    setCompanyIdState(id)
  }, [user, companies])

  const company = companies.find((c) => c.id === companyId)

  const profile = useMemo<CompanyProfile | null>(
    () => (company ? getProfile(company.profileId) : null),
    [company?.profileId],
  )
  const categories = useMemo<Category[]>(
    () => (company ? getCategoriesForProfile(company.profileId) : []),
    [company?.profileId],
  )

  // Нет доступных компаний (обычный юзер без членства) — заглушка.
  if (!authLoading && user && companies.length === 0) {
    return <NoCompaniesScreen />
  }

  // Ждём пользователя/активную компанию — не пускаем потребителей на пустом company.
  if (!company || !profile) {
    return (
      <div className="flex items-center justify-center h-screen text-muted-foreground">
        Загрузка…
      </div>
    )
  }

  return (
    <CompanyContext.Provider
      value={{
        company,
        companyId,
        companies,
        setCompanyId,
        profile,
        categories,
        customization: emptyCustomization(),
        effectiveCategories: categories,
        isLoading: authLoading,
      }}
    >
      {children}
    </CompanyContext.Provider>
  )
}

function NoCompaniesScreen() {
  const { logout } = useAuth()
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-4 text-center px-4">
      <h1 className="text-xl font-semibold">Нет доступных компаний</h1>
      <p className="text-muted-foreground max-w-md">
        Вашей учётной записи не назначено ни одной компании. Обратитесь к администратору.
      </p>
      <button
        onClick={logout}
        className="text-primary hover:underline"
      >
        Выйти
      </button>
    </div>
  )
}

export function useCompany() {
  const ctx = useContext(CompanyContext)
  if (!ctx) throw new Error('useCompany must be used within CompanyProvider')
  return ctx
}
