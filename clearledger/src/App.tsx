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

const IntakePage = lazy(() => import('@/pages/IntakePage').then((m) => ({ default: m.IntakePage })))
const ChannelsPage = lazy(() => import('@/pages/ChannelsPage').then((m) => ({ default: m.ChannelsPage })))
const ChannelDetailPage = lazy(() => import('@/pages/ChannelDetailPage').then((m) => ({ default: m.ChannelDetailPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const ConnectionPage = lazy(() => import('@/pages/oneC/ConnectionPage').then((m) => ({ default: m.ConnectionPage })))
const ReferencesPage = lazy(() => import('@/pages/oneC/ReferencesPage').then((m) => ({ default: m.ReferencesPage })))
const PeriodsPage = lazy(() => import('@/pages/oneC/PeriodsPage').then((m) => ({ default: m.PeriodsPage })))
// ShiftReportsPage не используется как отдельная страница — просмотр через RawPanel

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-[50vh]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    }>
      {children}
    </Suspense>
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

const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

const router = createBrowserRouter([
  {
    element: <Providers />,
    children: [
      {
        element: <MainLayout />,
        children: [
          { path: '/', element: <WorkspaceLayout /> },
          { path: '/intake', element: <LazyPage><IntakePage /></LazyPage> },
          { path: '/channels', element: <LazyPage><ChannelsPage /></LazyPage> },
          { path: '/channels/:id', element: <LazyPage><ChannelDetailPage /></LazyPage> },
          { path: '/sources', element: <LazyPage><SourcesPage /></LazyPage> },
          { path: '/1c/connection', element: <LazyPage><ConnectionPage /></LazyPage> },
          { path: '/1c/references', element: <LazyPage><ReferencesPage /></LazyPage> },
          { path: '/1c/periods', element: <LazyPage><PeriodsPage /></LazyPage> },
          { path: '/settings', element: <LazyPage><SettingsPage /></LazyPage> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
], { basename })

export default function App() {
  return <RouterProvider router={router} />
}
