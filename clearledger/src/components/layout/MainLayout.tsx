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

// Состояние левого сайдбара сохраняется между запусками. По умолчанию (первый
// запуск, нет сохранённого значения) — свёрнут: рабочая область получает
// максимум ширины, навигация доступна по иконкам с тултипами. Выбор пользователя
// (развернул/свернул) уважается при перезагрузке.
// NB: ui-Sidebar (shadcn) пишет cookie, но НЕ читает её при инициализации
// (SSR-паттерн Next.js), поэтому персистим сами через localStorage.
const SIDEBAR_STORAGE_KEY = 'clearledger-sidebar-open'

function readSidebarOpen(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true' // null/иное → свёрнут
  } catch {
    return false
  }
}

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
  // Свёрнут/развёрнут сайдбар (десктоп). Инициализация из localStorage, дефолт — свёрнут.
  const [sidebarOpen, setSidebarOpen] = useState(readSidebarOpen)
  useEffect(() => {
    try { localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarOpen)) } catch { /* ignore */ }
  }, [sidebarOpen])
  // ≤1024: компактный shell (гамбургер-меню в drawer, без десктопных вкладок) —
  // чтобы планшеты не теряли ширину под inline-сайдбар (согласовано с WorkspaceLayout).
  const isMobile = useMaxWidth(1024)
  const location = useLocation()
  const navigate = useNavigate()
  const { companyModules } = useCompany()
  // RBAC route-guard: прямой переход на недоступный по модулям роут → на рабочий стол.
  useEffect(() => {
    if (!routeAllowed(location.pathname, companyModules)) navigate('/workspace', { replace: true })
  }, [location.pathname, companyModules, navigate])
  // «Открытие приложения» → рабочий стол. Холодный старт вкладки (нет метки сессии)
  // сбрасывает запомненный браузером экран на рабочий стол. F5 и переходы внутри
  // сессии метку сохраняют (sessionStorage переживает reload, но не закрытие вкладки),
  // поэтому текущий экран и deep-link в рамках сессии не теряются.
  //
  // Сбрасывается ТОЛЬКО экран рабочей области (её браузер и восстанавливает
  // «продолжить с того же места»). Прямая ссылка на служебную страницу —
  // /settings, /connectors/:id, /admin — уважается: иначе ломаются ссылки из
  // писем и открытие в новой вкладке, где sessionStorage всегда пуст и любой
  // переход выглядит холодным стартом.
  useEffect(() => {
    try {
      if (sessionStorage.getItem('cl-booted')) return
      sessionStorage.setItem('cl-booted', '1')
      if (location.pathname !== '/workspace' && isWorkspacePath(location.pathname)) {
        navigate('/workspace', { replace: true })
      }
    } catch { /* ignore */ }
    // читаем стартовый путь один раз при монтировании — deps намеренно пустые
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Рабочие области с фиксированной высотой (без скролла страницы, h-full внутри):
  // рабочий стол, разрезы «Сверка данных», нормализация и хранилище «Документы».
  // На десктопе overflow решает per-tab KeepAliveOutlet; здесь — только для мобильной ветки.
  const isWorkspace = isWorkspacePath(location.pathname)

  return (
    <SidebarProvider
      open={sidebarOpen}
      onOpenChange={setSidebarOpen}
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
