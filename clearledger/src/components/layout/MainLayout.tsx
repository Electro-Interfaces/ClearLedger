import { useState, useEffect, lazy, Suspense } from 'react'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AppSidebar } from './AppSidebar'
import { Header } from './Header'
import { MobileBottomNav } from './MobileBottomNav'
import { Outlet, useNavigate } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'
import { AppBreadcrumb } from './AppBreadcrumb'
import { KeyboardHelp } from '@/components/common/KeyboardHelp'

const DevPanel = import.meta.env.DEV
  ? lazy(() => import('@/components/dev/DevPanel').then((m) => ({ default: m.DevPanel })))
  : null

export function MainLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [showKeyboardHelp, setShowKeyboardHelp] = useState(false)
  const isMobile = useIsMobile()
  const navigate = useNavigate()

  // Ctrl+K → глобальный поиск, ? → справка по горячим клавишам
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        navigate('/search')
      }
      const target = e.target as HTMLElement
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
      if (e.key === '?' && !isInput && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        setShowKeyboardHelp(true)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [navigate])

  return (
    <SidebarProvider>
      <div className="bg-background text-foreground w-full max-w-none min-h-screen">
        <Header
          onMobileMenuToggle={() => setMobileMenuOpen(!mobileMenuOpen)}
          isMobile={isMobile}
        />

        {isMobile ? (
          <>
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetContent side="left" className="p-0 w-80 mobile-safe-left">
                <SheetTitle className="sr-only">Меню навигации</SheetTitle>
                <SheetDescription className="sr-only">
                  Навигационное меню ClearLedger
                </SheetDescription>
                <AppSidebar />
              </SheetContent>
            </Sheet>

            <main
              className="flex-1 min-h-0 min-w-0 w-full max-w-none overflow-y-auto"
              style={{ WebkitOverflowScrolling: 'touch', touchAction: 'pan-y' }}
            >
              <div className="px-4 md:px-6 w-full max-w-none pt-4 pb-20">
                <AppBreadcrumb />
                <Outlet />
              </div>
            </main>

            <MobileBottomNav />
          </>
        ) : (
          <div className="flex w-full max-w-none" style={{ paddingTop: 'var(--header-height)' }}>
            <AppSidebar />

            <main className="flex-1 min-w-0 w-full max-w-none overflow-y-auto">
              <div className="px-4 md:px-6 lg:px-8 w-full max-w-none py-6">
                <AppBreadcrumb />
                <Outlet />
              </div>
            </main>
          </div>
        )}

        {DevPanel && (
          <Suspense>
            <DevPanel />
          </Suspense>
        )}

        <KeyboardHelp open={showKeyboardHelp} onOpenChange={setShowKeyboardHelp} />
      </div>
    </SidebarProvider>
  )
}
