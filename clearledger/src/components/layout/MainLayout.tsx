import { useState } from 'react'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AppSidebar } from './AppSidebar'
import { Header } from './Header'
import { MobileBottomNav } from './MobileBottomNav'
import { Outlet } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'

export function MainLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const isMobile = useIsMobile()

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
                <Outlet />
              </div>
            </main>
          </div>
        )}
      </div>
    </SidebarProvider>
  )
}
