import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Outlet, Link } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { MainLayout } from '@/components/layout/MainLayout'
import { WorkspaceLayout } from '@/components/workspace/WorkspaceLayout'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-[50vh]">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  )
}

function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
      <h1 className="text-6xl font-bold text-muted-foreground">404</h1>
      <p className="text-lg text-muted-foreground">Страница не найдена</p>
      <Link to="/" className="text-primary hover:underline">На главную</Link>
    </div>
  )
}

function Providers() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <CompanyProvider>
          <TooltipProvider>
            <Outlet />
            <Toaster position="bottom-right" richColors closeButton />
          </TooltipProvider>
        </CompanyProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

const router = createBrowserRouter([
  {
    element: <Providers />,
    children: [
      {
        element: <MainLayout />,
        children: [
          { path: '/', element: <WorkspaceLayout /> },
          {
            path: '/settings',
            element: (
              <Suspense fallback={<PageLoader />}>
                <SettingsPage />
              </Suspense>
            ),
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
