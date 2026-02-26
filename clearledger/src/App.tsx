import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Outlet, Navigate, Link } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { MainLayout } from '@/components/layout/MainLayout'
import { Dashboard } from '@/pages/Dashboard'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

// Lazy-loaded pages (code-split)
const IntakePage = lazy(() => import('@/pages/IntakePage').then((m) => ({ default: m.IntakePage })))
const ManualEntryPage = lazy(() => import('@/pages/ManualEntryPage').then((m) => ({ default: m.ManualEntryPage })))
const ConnectorsPage = lazy(() => import('@/pages/ConnectorsPage').then((m) => ({ default: m.ConnectorsPage })))
const ConnectorDetailPage = lazy(() => import('@/pages/ConnectorDetailPage').then((m) => ({ default: m.ConnectorDetailPage })))
const DataCategoryPage = lazy(() => import('@/pages/DataCategoryPage').then((m) => ({ default: m.DataCategoryPage })))
const DataDetailPage = lazy(() => import('@/pages/DataDetailPage').then((m) => ({ default: m.DataDetailPage })))
const SearchPage = lazy(() => import('@/pages/SearchPage').then((m) => ({ default: m.SearchPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const CompaniesPage = lazy(() => import('@/pages/CompaniesPage').then((m) => ({ default: m.CompaniesPage })))
const CompanyEditPage = lazy(() => import('@/pages/CompanyEditPage').then((m) => ({ default: m.CompanyEditPage })))
const InboxPage = lazy(() => import('@/pages/InboxPage').then((m) => ({ default: m.InboxPage })))
const InboxDetailPage = lazy(() => import('@/pages/InboxDetailPage').then((m) => ({ default: m.InboxDetailPage })))
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-[50vh]">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  )
}

function LazyPage({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>
}

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
  return <LazyPage><LoginPage /></LazyPage>
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
              { path: '/inbox', element: <LazyPage><InboxPage /></LazyPage> },
              { path: '/inbox/:id', element: <LazyPage><InboxDetailPage /></LazyPage> },
              { path: '/input', element: <LazyPage><IntakePage /></LazyPage> },
              { path: '/input/upload', element: <Navigate to="/input" replace /> },
              { path: '/input/photo', element: <Navigate to="/input" replace /> },
              { path: '/input/manual', element: <LazyPage><ManualEntryPage /></LazyPage> },
              { path: '/connectors', element: <LazyPage><ConnectorsPage /></LazyPage> },
              { path: '/connectors/new', element: <LazyPage><ConnectorDetailPage /></LazyPage> },
              { path: '/connectors/:id', element: <LazyPage><ConnectorDetailPage /></LazyPage> },
              { path: '/data/:category', element: <LazyPage><DataCategoryPage /></LazyPage> },
              { path: '/data/:category/:id', element: <LazyPage><DataDetailPage /></LazyPage> },
              { path: '/search', element: <LazyPage><SearchPage /></LazyPage> },
              { path: '/settings', element: <LazyPage><SettingsPage /></LazyPage> },
              { path: '/settings/companies', element: <LazyPage><CompaniesPage /></LazyPage> },
              { path: '/settings/companies/:id', element: <LazyPage><CompanyEditPage /></LazyPage> },
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
