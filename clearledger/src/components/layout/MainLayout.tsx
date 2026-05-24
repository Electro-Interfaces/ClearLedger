import { useState } from 'react'
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar'
import { Sheet, SheetContent, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { AppSidebar } from './AppSidebar'
import { Header } from './Header'
import { Outlet, useLocation } from 'react-router-dom'
import { useIsMobile } from '@/hooks/use-mobile'

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
  const isMobile = useIsMobile()
  const location = useLocation()
  const isWorkspace = location.pathname === '/'

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
              <SheetDescription className="sr-only">Навигация GIG Fuel Ledger</SheetDescription>
              <AppSidebar />
            </SheetContent>
          </Sheet>
        )}

        <SidebarInset className="overflow-hidden">
          {isWorkspace ? (
            <div className="flex-1 min-h-0 overflow-hidden">
              <Outlet />
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto pb-12">
              <Outlet />
            </div>
          )}
        </SidebarInset>
      </div>
    </SidebarProvider>
  )
}
