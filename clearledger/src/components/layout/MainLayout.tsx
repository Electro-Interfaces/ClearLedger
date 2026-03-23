import { useState } from 'react'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AppSidebar } from './AppSidebar'
import { Header } from './Header'
import { Outlet, useLocation } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'

export function MainLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const isMobile = useIsMobile()
  const location = useLocation()
  const isWorkspace = location.pathname === '/'

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
              <SheetContent side="left" className="p-0 w-72 mobile-safe-left">
                <SheetTitle className="sr-only">Меню навигации</SheetTitle>
                <SheetDescription className="sr-only">Навигация GIG Fuel Ledger</SheetDescription>
                <AppSidebar />
              </SheetContent>
            </Sheet>
            <main
              className="w-full"
              style={{ paddingTop: 'var(--header-height)' }}
            >
              <Outlet />
            </main>
          </>
        ) : (
          <div className="flex w-full max-w-none" style={{ paddingTop: 'var(--header-height)' }}>
            <AppSidebar />
            <main className="flex-1 min-w-0 w-full max-w-none overflow-hidden">
              {isWorkspace ? (
                <Outlet />
              ) : (
                <div className="px-4 md:px-6 lg:px-8 w-full max-w-[1000px] py-6 overflow-y-auto h-[calc(100vh-var(--header-height))]">
                  <Outlet />
                </div>
              )}
            </main>
          </div>
        )}
      </div>
    </SidebarProvider>
  )
}
