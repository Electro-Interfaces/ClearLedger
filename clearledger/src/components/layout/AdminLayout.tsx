/**
 * Shell приложения «Управление» — самостоятельного продукта пространства (не раздел Учёта).
 * Управление контейнером и компанией: продукты, люди, доступы, объекты, справочники, аудит.
 * Приложения-продукты (Учёт, Координатор) своей админки НЕ имеют — она вынесена сюда.
 *
 * Каркас тот же, что у Учёта (`MainLayout`): шапка → левое меню разделов → рабочая
 * область → экосистемный рельс справа. Человек ходит между продуктами пространства и
 * не переучивается: навигация всегда слева, выход и тема всегда справа.
 *
 * Разделы — маршруты (`/admin/eco/*`, `/admin/company/*`), а не вкладки: на раздел можно
 * дать ссылку, работает «назад», и открытый раздел переживает перезагрузку.
 */
import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ShieldCheck } from 'lucide-react'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Menu } from 'lucide-react'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { AdminNavContent, AdminSidebar } from '@/components/layout/AdminSidebar'
import { AppLauncher } from '@/components/layout/AppLauncher'
import { EcoRail } from '@/components/layout/EcoRail'
import { HeaderUserMenu } from '@/components/layout/HeaderUserMenu'
import { findSection, type AdminScope } from '@/config/adminNav'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'
import { usePersistentState } from '@/hooks/usePersistentState'
import { isApiEnabled } from '@/services/apiClient'
import * as userService from '@/services/userService'
import { LAST_SECTION_KEY, type AdminOutletContext } from '@/hooks/useAdminSpace'

const SIDEBAR_STORAGE_KEY = 'cl-admin-sidebar-open'

function readSidebarOpen(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) !== 'false' // по умолчанию развёрнут
  } catch {
    return true
  }
}

/** Разбор адреса раздела: `/admin/company/roles` → scope + code. */
function useCurrentSection() {
  const { pathname } = useLocation()
  const [, , scope, code] = pathname.split('/')
  const section = findSection(scope as AdminScope, code)
  // Последний открытый раздел запоминается: человек возвращается в «Управление»
  // туда, где работал, а не на первый экран (`LAST_SECTION_KEY` читает редирект `/admin`).
  useEffect(() => {
    if (section) {
      try { localStorage.setItem(LAST_SECTION_KEY, pathname) } catch { /* ignore */ }
    }
  }, [section, pathname])
  return section
}

export function AdminLayout() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { canApp, companyId: activeCompanyId, isLoading } = useCompany()
  const isSuper = !!user?.is_superadmin
  const isMobile = useMaxWidth(1024)
  const section = useCurrentSection()

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(readSidebarOpen)
  useEffect(() => {
    try { localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarOpen)) } catch { /* ignore */ }
  }, [sidebarOpen])

  // Список компаний для управления: суперадмину — все компании контейнера, админу — свои.
  const companiesQuery = useQuery({
    queryKey: ['admin-companies'],
    queryFn: userService.listCompanies,
    enabled: isApiEnabled(),
  })
  const companies = companiesQuery.data ?? []
  const [selectedId, setSelectedId] = usePersistentState('cl-admin-company', '')
  const company = companies.find((c) => c.id === (selectedId || activeCompanyId)) ?? companies[0]
  const canManage = isSuper || (user?.companies ?? []).some((c) => c.id === company?.id && c.role === 'admin')

  // «Управление» — приложение пространства: пускаем по праву роли (целиком или на раздел).
  if (!isLoading && !canApp('admin')) return <Navigate to="/" replace />

  return (
    <SidebarProvider
      open={sidebarOpen}
      onOpenChange={setSidebarOpen}
      className="flex h-dvh max-h-dvh flex-col overflow-hidden"
    >
      <header className="h-[var(--header-height)] shrink-0 border-b border-border/50 bg-card/95 backdrop-blur-xl">
        <div className="flex h-full items-center justify-between gap-3 px-4 md:px-6">
          {/* Левый блок: бургер (моб.) + логотип продукта. Логотип ведёт на рабочий
              стол экосистемы — тем же жестом, что в Учёте. */}
          <div className="flex shrink-0 items-center gap-3 md:gap-4">
            {isMobile && (
              <Button variant="ghost" size="icon" className="shrink-0" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
                <Menu className="h-5 w-5" />
              </Button>
            )}
            <button
              onClick={() => navigate('/')}
              title="К рабочему столу экосистемы"
              className="flex shrink-0 items-center gap-3"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 shadow-lg">
                <ShieldCheck className="h-5 w-5 text-white" />
              </div>
              <div className="hidden flex-col leading-none sm:flex">
                <h1 className="text-lg font-semibold tracking-tight text-foreground">Управление</h1>
                <p className="text-xs text-muted-foreground">пространством</p>
              </div>
            </button>
          </div>

          {/* Центр: какой компанией управляем + переход в соседние продукты. */}
          <div className="flex min-w-0 flex-1 items-center justify-center gap-2 px-2">
            {companiesQuery.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : companies.length > 1 ? (
              <Select value={company?.id ?? ''} onValueChange={setSelectedId}>
                <SelectTrigger className="h-10 w-full min-w-[112px] max-w-[240px] border-border bg-secondary text-sm font-medium [&>span]:truncate">
                  <SelectValue placeholder="Выберите компанию" />
                </SelectTrigger>
                <SelectContent>
                  {companies.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      <span className="flex items-center gap-2">
                        <span className="size-2.5 shrink-0 rounded-full" style={{ background: c.color ?? '#888' }} />
                        {c.short_name || c.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="truncate text-sm font-medium text-muted-foreground">{company?.name ?? ''}</span>
            )}
            <AppLauncher />
          </div>

          <div className="flex shrink-0 items-center gap-1.5 md:gap-2">
            <HeaderUserMenu />
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {!isMobile && <AdminSidebar />}

        {isMobile && (
          <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <SheetContent side="left" className="mobile-safe-left w-72 p-0">
              <SheetTitle className="sr-only">Разделы управления</SheetTitle>
              <SheetDescription className="sr-only">Навигация приложения «Управление»</SheetDescription>
              <div className="h-full overflow-y-auto px-1.5 py-3">
                <AdminNavContent onNavigate={() => setMobileMenuOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
        )}

        <SidebarInset className="overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6">
            {/* Ширину не ограничиваем: в разделах таблицы (сотрудники, объекты, аудит),
                им нужна вся рабочая область — так же, как экранам Учёта. */}
            <div className="w-full space-y-4">
              {/* Заголовок раздела — из реестра разделов: одно место на все экраны. */}
              {section && (
                <div className="flex items-center gap-2.5">
                  <section.icon className="h-6 w-6 text-primary" />
                  <div className="min-w-0">
                    <h2 className="text-xl font-bold leading-tight">{section.label}</h2>
                    <p className="truncate text-sm text-muted-foreground">{section.hint}</p>
                  </div>
                </div>
              )}
              <Outlet context={{ company, companies, canManage, selectCompany: setSelectedId } satisfies AdminOutletContext} />
            </div>
          </div>
        </SidebarInset>

        {/* Тот же экосистемный рельс, что в приложениях: отсюда — в приложения и на стол. */}
        <aside className="hidden w-12 shrink-0 flex-col items-center gap-1 border-l border-border/50 bg-card py-2 md:flex">
          <EcoRail standalone />
        </aside>
      </div>
    </SidebarProvider>
  )
}
