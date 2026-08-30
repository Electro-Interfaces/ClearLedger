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
import { getApiOrganization, setApiCompany, setApiOrganization } from '@/services/apiClient'
import * as referenceService from '@/services/referenceService'
import { useQuery } from '@tanstack/react-query'
import { useAppNames, useDisabledApps, useRegistryModules, intersectAccess } from '@/hooks/useCompanyRegistry'

interface CompanyContextType {
  company: Company
  companyId: string
  companies: Company[]
  setCompanyId: (id: string) => void
  /**
   * Организации (юрлица) активной компании и выбранная из них.
   *
   * Компания — это КЛИЕНТ (одна база 1С), организация — юрлицо внутри его учёта.
   * У аутсорсера их обычно несколько: ООО и ИП одного владельца в одной базе, и без
   * выбора их цифры складываются в одну. Пусто = все организации, законный сводный режим.
   */
  organizations: { id: string; name: string; inn?: string }[]
  organizationId: string | null
  setOrganizationId: (id: string | null) => void
  companyRole: 'user' | 'admin'   // роль текущего пользователя в активной компании
  isCompanyAdmin: boolean         // admin в активной компании ИЛИ суперадмин
  /** Надзирает ли человек за чужой работой: администратор — за всей компанией,
   *  руководитель подразделения — за своей веткой, рядовой — ни за кем.
   *  От этого зависит раздел «Компания». */
  oversees: boolean
  // Что показывать в активной компании: права RBAC ∩ состав поставки (реестр Ядра).
  // null = ничто не ограничивает (полный доступ и реестр молчит).
  companyModules: string[] | null
  /**
   * Доступ к продукту пространства целиком: `canApp('admin')`, `canApp('support')`.
   * Правило то же, что на сервере (access_catalog.app_allowed): доступ есть, если роль
   * даёт приложение целиком ИЛИ любой его модуль.
   */
  canApp: (appCode: string) => boolean
  /** Доступ к разделу продукта: `canModule('admin', 'members')`. */
  canModule: (appCode: string, moduleCode: string) => boolean
  /** Как продукт называется В ЭТОЙ компании: `appName('auditor', 'Аудитор')`. */
  appName: (appCode: string, fallback: string) => string
  profile: CompanyProfile
  categories: Category[]
  customization: CompanyCustomization
  effectiveCategories: Category[]
  isLoading: boolean
}

const CompanyContext = createContext<CompanyContextType | null>(null)

const activeKey = (userId: string) => `tl-active-company-${userId}`

// Плейсхолдер для неавторизованного состояния: company ещё нет, но дочерние
// провайдеры (FilterProvider) и страница /login должны отрисоваться. Реальные
// потребители company живут за ProtectedRoute и без логина не монтируются.
//
// 🔴 id ПУСТОЙ, а не '_'. С непустым плейсхолдером все проверки вида
// `enabled: !!companyId` его пропускали — он truthy, — и на первом кадре, пока `/me`
// ещё не ответил, запросы уходили с `company_id=_`. Сервер такой компании не знает и
// отвечает 400; в консоли это выглядело как поломка приложения, хотя следом всё
// перезапрашивалось уже правильно. Лечить это по месту (`companyId !== '_'` в трёх
// файлах) значит чинить симптом: каждый новый потребитель наступает заново.
const PLACEHOLDER_COMPANY: Company = {
  id: '', name: '', shortName: '', color: '#3b82f6', profileId: 'fuel',
}

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
    if (!user) { setApiCompany(null); setCompanyIdState(''); return }
    const saved = localStorage.getItem(activeKey(user.id))
    const valid = saved && companies.some((c) => c.id === saved)
    const next = valid ? saved! : (companies[0]?.id ?? '')
    setApiCompany(next)  // синхронно до setState — чтобы первые запросы несли X-Company-Id
    setCompanyIdState(next)
  }, [user, companies])

  // Изоляция: при СМЕНЕ активной компании (не первый выбор) — сброс кэшей.
  const prevId = useRef<string | null>(null)
  useEffect(() => {
    if (!companyId) return
    // Заголовок X-Company-Id ставим ПЕРЕД сбросом кэша — чтобы рефетчи после
    // qc.clear() уже несли новую компанию (fuel/store скоупятся по нему).
    setApiCompany(companyId)
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
    setApiCompany(id)  // синхронно — заголовок готов до рефетчей
    setCompanyIdState(id)
  }, [user, companies])

  // Организации активной компании: список нужен и переключателю, и для сброса
  // выбора при смене компании — юрлицо одного клиента не должно утечь в другого.
  const orgsQ = useQuery({
    queryKey: ['own-organizations', companyId],
    queryFn: () => referenceService.getOrganizations(companyId),
    enabled: !!companyId,
  })
  const organizations = useMemo(
    () => (orgsQ.data ?? []).map((o) => ({ id: o.id, name: o.name, inn: o.inn })),
    [orgsQ.data],
  )
  const [organizationId, setOrganizationIdState] = useState<string | null>(getApiOrganization())

  useEffect(() => {
    // Выбранная организация обязана принадлежать активной компании: иначе после
    // переключения клиента экран покажет пустоту, а причина будет невидима.
    if (organizationId && organizations.length &&
        !organizations.some((o) => o.id === organizationId)) {
      setApiOrganization(null)
      setOrganizationIdState(null)
    }
  }, [organizations, organizationId])

  const setOrganizationId = useCallback((id: string | null) => {
    setApiOrganization(id)          // синхронно — заголовок готов до рефетчей
    setOrganizationIdState(id)
    qc.clear()                      // разрез данных сменился целиком
  }, [qc])

  const company = companies.find((c) => c.id === companyId)

  const profile = useMemo<CompanyProfile | null>(
    () => (company ? getProfile(company.profileId) : null),
    [company?.profileId],
  )
  const categories = useMemo<Category[]>(
    () => (company ? getCategoriesForProfile(company.profileId) : []),
    [company?.profileId],
  )

  // Состав поставки компании из серверного реестра Ядра (до ранних return — правило хуков).
  const registryModules = useRegistryModules(companyId)
  // Продукты, выключенные компании в реестре: их нет в поставке, и показывать их
  // нельзя никому — ни по роли, ни суперадмину (решение МАГа 16.08.2026 про
  // «Аудитора» в сетевых пространствах).
  const disabledApps = useDisabledApps(companyId)
  const appNames = useAppNames(companyId)

  // Нет доступных компаний (обычный юзер без членства) — заглушка.
  if (!authLoading && user && companies.length === 0) {
    return <NoCompaniesScreen />
  }

  // Авторизован, но активная компания ещё не выбрана (эффект не отработал) —
  // короткая загрузка. ВАЖНО: блокируем ТОЛЬКО при наличии user, иначе экран
  // «Загрузка…» перекрыл бы страницу /login для неавторизованного.
  if (user && (!company || !profile)) {
    return (
      <div className="flex items-center justify-center h-screen text-muted-foreground">
        Загрузка…
      </div>
    )
  }

  // Неавторизован → company ещё нет: даём плейсхолдер, чтобы /login и дочерние
  // провайдеры отрисовались (ProtectedRoute сам уведёт на /login).
  const activeCompany: Company = company ?? PLACEHOLDER_COMPANY
  const activeProfile: CompanyProfile = profile ?? getProfile(activeCompany.profileId)

  // Роль в активной компании: суперадмин → admin; иначе роль членства из /me.
  const activeRef = user?.companies?.find((c) => c.id === companyId)
  const companyRole: 'user' | 'admin' = user?.is_superadmin
    ? 'admin'
    : (activeRef?.role === 'admin' ? 'admin' : 'user')
  const isCompanyAdmin = !!user?.is_superadmin || companyRole === 'admin'
  // Администратор надзирает всегда; остальным признак считает сервер по
  // штатной структуре — здесь его не пересчитываем, иначе появится второй
  // источник правды, и он разойдётся с первым.
  const oversees = isCompanyAdmin || !!activeRef?.oversees
  // Модули активной компании = ПРАВА (RBAC) ∩ СОСТАВ ПОСТАВКИ (реестр Ядра).
  // Права: admin/суперадмин → null (полный доступ). Состав: что подключено компании
  // в /admin → «Приложения»; отключённый раздел не показываем и админу — он не куплен,
  // а не «запрещён». Реестр недоступен → null, ограничивает только RBAC (см. хук).
  const rbacModules: string[] | null = isCompanyAdmin ? null : (activeRef?.modules ?? null)
  const companyModules: string[] | null = intersectAccess(rbacModules, registryModules)

  // Права на продукты пространства (Управление, Координатор, Чаты…) считаются по сырым
  // ключам роли: `companyModules` — про модули Учёта и для этого не годится.
  const canApp = (appCode: string) => {
    // Сначала состав поставки: выключенного продукта нет ни у кого. Раньше здесь
    // стояли только права, и у администратора кнопка выключенного «Аудитора»
    // оставалась в шапке — потому что права ему ничего не запрещают.
    if (disabledApps.includes(appCode)) return false
    if (rbacModules === null) return true
    return rbacModules.includes(appCode) || rbacModules.some((k) => k.startsWith(`${appCode}:`))
  }
  const appName = (appCode: string, fallback: string) => appNames[appCode] || fallback
  const canModule = (appCode: string, moduleCode: string) => {
    if (rbacModules === null) return true
    return rbacModules.includes(appCode) || rbacModules.includes(`${appCode}:${moduleCode}`)
  }

  return (
    <CompanyContext.Provider
      value={{
        company: activeCompany,
        companyId: companyId || activeCompany.id,
        companies,
        setCompanyId,
        organizations,
        organizationId,
        setOrganizationId,
        companyRole,
        isCompanyAdmin,
        oversees,
        companyModules,
        canApp,
        canModule,
        appName,
        profile: activeProfile,
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
