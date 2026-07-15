import { useEffect, useState } from 'react'
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AppSidebar, SidebarNavContent } from './AppSidebar'
import { MobileBottomNav } from './MobileBottomNav'
import { Header } from './Header'
import { WorkspaceTabBar } from './WorkspaceTabBar'
import { KeepAliveOutlet } from './KeepAliveOutlet'
import InteractionHost from '@/components/support/InteractionHost'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useMaxWidth } from '@/hooks/use-mobile'
import { isWorkspacePath } from '@/config/tabRegistry'
import { useCompany } from '@/contexts/CompanyContext'
import { routeAllowed } from '@/config/accessModules'

/**
 * Layout с скроллящимся sidebar — паттерн из shadcn issue #6651:
 *   SidebarProvider [flex flex-col min-h-svh]   ← перекрываем дефолт flex-row
 *     ├── Header (обычный, h-header shrink-0)
 *     └── div [flex flex-1 min-h-0]              ← вложенная flex-row группа
 *           ├── AppSidebar (внутри fixed h-svh + gap-резерв)
 *           └── SidebarInset
 *                 └── div [flex-1 min-h-0 overflow-y-auto]
 */
export function MainLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  // ≤1024: компактный shell (гамбургер-меню в drawer, без десктопных вкладок) —
  // чтобы планшеты не теряли ширину под inline-сайдбар (согласовано с WorkspaceLayout).
  const isMobile = useMaxWidth(1024)
  const location = useLocation()
  const navigate = useNavigate()
  const { companyModules } = useCompany()
  // RBAC route-guard: прямой переход на недоступный по модулям роут → на рабочий стол.
  useEffect(() => {
    if (!routeAllowed(location.pathname, companyModules)) navigate('/', { replace: true })
  }, [location.pathname, companyModules, navigate])
  // Рабочие области с фиксированной высотой (без скролла страницы, h-full внутри):
  // рабочий стол, разрезы «Сверка данных», нормализация и хранилище «Документы».
  // На десктопе overflow решает per-tab KeepAliveOutlet; здесь — только для мобильной ветки.
  const isWorkspace = isWorkspacePath(location.pathname)

  return (
    <SidebarProvider
      className="flex flex-col h-dvh max-h-dvh overflow-hidden"
      style={{ '--header-height': '5rem' } as React.CSSProperties}
    >
      {/* Header — первый child в flex-col, sibling sidebar+inset группы.
          Так sidebar занимает только высоту ПОД header. */}
      <Header
        onMobileMenuToggle={() => setMobileMenuOpen(!mobileMenuOpen)}
        isMobile={isMobile}
      />

      <div className="flex flex-1 min-h-0">
        {!isMobile && <AppSidebar />}

        {isMobile && (
          <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
            <SheetContent side="left" className="p-0 w-72 mobile-safe-left">
              <SheetTitle className="sr-only">Меню навигации</SheetTitle>
              <SheetDescription className="sr-only">Навигация TradeLedger</SheetDescription>
              {/* Именно контент, НЕ <AppSidebar>: ui-Sidebar на мобиле рендерит
                  собственный (закрытый) Sheet — шторка получалась пустой. */}
              <div className="h-full overflow-y-auto px-1.5 py-3">
                <SidebarNavContent onNavigate={() => setMobileMenuOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
        )}

        <SidebarInset id="workspace-area" className="overflow-hidden">
          {isMobile ? (
            // Мобильный: одностраничная навигация без вкладок (как раньше).
            isWorkspace ? (
              // max-md:pb-14 — запас под нижнюю навигацию (<768px); workspace-страницы
              // (/, /files, /reconciliation, /normalization) не перекрываются навбаром.
              <div className="flex-1 min-h-0 overflow-hidden max-md:pb-14">
                <Outlet />
              </div>
            ) : (
              // pb-20 — запас под нижнюю навигацию (h-14, <768px); ≥768 её нет → pb-12
              <div className="flex-1 min-h-0 overflow-y-auto px-4 md:px-6 pt-4 pb-20 md:pb-12">
                <Outlet />
              </div>
            )
          ) : (
            // Десктоп: полоса вкладок + keep-alive рабочая область.
            <>
              <WorkspaceTabBar />
              <KeepAliveOutlet />
            </>
          )}
        </SidebarInset>

        {/* Правая вспомогательная область «Взаимодействие» (Чат / Заявки / Инфо).
            Десктоп: пристыкованная панель-вкладки, двигает контент; мобайл: оверлей. */}
        <InteractionHost />
      </div>

      {/* Нижняя навигация телефонов (<768px; сама скрывается md:hidden) */}
      {isMobile && <MobileBottomNav />}
    </SidebarProvider>
  )
}
