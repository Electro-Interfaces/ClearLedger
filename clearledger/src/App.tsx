import { createBrowserRouter, RouterProvider, Outlet, Navigate, Link } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { MainLayout } from '@/components/layout/MainLayout'
import { Dashboard } from '@/pages/Dashboard'
import { IntakePage } from '@/pages/IntakePage'
import { ManualEntryPage } from '@/pages/ManualEntryPage'
import { ConnectorsPage } from '@/pages/ConnectorsPage'
import { ConnectorDetailPage } from '@/pages/ConnectorDetailPage'
import { DataCategoryPage } from '@/pages/DataCategoryPage'
import { DataDetailPage } from '@/pages/DataDetailPage'
import { SearchPage } from '@/pages/SearchPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { CompaniesPage } from '@/pages/CompaniesPage'
import { CompanyEditPage } from '@/pages/CompanyEditPage'
import { InboxPage } from '@/pages/InboxPage'
import { InboxDetailPage } from '@/pages/InboxDetailPage'
import { LoginPage } from '@/pages/LoginPage'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

/** Защищённый роут — редирект на /login если не авторизован */
function ProtectedRoute() {
  const { isAuthenticated, isLoading, isApiMode } = useAuth()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (isApiMode && !isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

/** Роут логина — редирект на / если уже залогинен */
function LoginRoute() {
  const { isAuthenticated, isApiMode } = useAuth()
  if (!isApiMode || isAuthenticated) return <Navigate to="/" replace />
  return <LoginPage />
}

/** 404 страница */
function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
      <h1 className="text-6xl font-bold text-muted-foreground">404</h1>
      <p className="text-lg text-muted-foreground">Страница не найдена</p>
      <Link to="/" className="text-primary hover:underline">
        На главную
      </Link>
    </div>
  )
}

function Providers() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <CompanyProvider>
            <TooltipProvider>
              <Outlet />
              <Toaster position="bottom-right" richColors closeButton />
            </TooltipProvider>
          </CompanyProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

const router = createBrowserRouter([
  {
    element: <Providers />,
    children: [
      { path: '/login', element: <LoginRoute /> },
      {
        element: <ProtectedRoute />,
        children: [
          {
            element: <MainLayout />,
            children: [
              { path: '/', element: <Dashboard /> },
              { path: '/inbox', element: <InboxPage /> },
              { path: '/inbox/:id', element: <InboxDetailPage /> },
              { path: '/input', element: <IntakePage /> },
              { path: '/input/upload', element: <Navigate to="/input" replace /> },
              { path: '/input/photo', element: <Navigate to="/input" replace /> },
              { path: '/input/manual', element: <ManualEntryPage /> },
              { path: '/connectors', element: <ConnectorsPage /> },
              { path: '/connectors/new', element: <ConnectorDetailPage /> },
              { path: '/connectors/:id', element: <ConnectorDetailPage /> },
              { path: '/data/:category', element: <DataCategoryPage /> },
              { path: '/data/:category/:id', element: <DataDetailPage /> },
              { path: '/search', element: <SearchPage /> },
              { path: '/settings', element: <SettingsPage /> },
              { path: '/settings/companies', element: <CompaniesPage /> },
              { path: '/settings/companies/:id', element: <CompanyEditPage /> },
              { path: '*', element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
  },
], { basename })

export default function App() {
  return <RouterProvider router={router} />
}
