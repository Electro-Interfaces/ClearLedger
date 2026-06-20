import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Outlet, Link } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { FilterProvider } from '@/contexts/FilterContext'
import { SupportProvider } from '@/contexts/SupportContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { WorkspaceLayout } from '@/components/workspace/WorkspaceLayout'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

const IntakePage = lazy(() => import('@/pages/IntakePage').then((m) => ({ default: m.IntakePage })))
const ChannelsPage = lazy(() => import('@/pages/ChannelsPage').then((m) => ({ default: m.ChannelsPage })))
const ChannelDetailPage = lazy(() => import('@/pages/ChannelDetailPage').then((m) => ({ default: m.ChannelDetailPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const CatalogPage = lazy(() => import('@/pages/CatalogPage').then((m) => ({ default: m.CatalogPage })))
const LocationsPage = lazy(() => import('@/pages/LocationsPage').then((m) => ({ default: m.LocationsPage })))
const ContractorsPage = lazy(() => import('@/pages/ContractorsPage').then((m) => ({ default: m.ContractorsPage })))
const OrganizationPage = lazy(() => import('@/pages/OrganizationPage').then((m) => ({ default: m.OrganizationPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const AdminPage = lazy(() => import('@/pages/AdminPage').then((m) => ({ default: m.AdminPage })))
const ConnectionPage = lazy(() => import('@/pages/oneC/ConnectionPage').then((m) => ({ default: m.ConnectionPage })))
const ReferencesPage = lazy(() => import('@/pages/oneC/ReferencesPage').then((m) => ({ default: m.ReferencesPage })))
const PeriodsPage = lazy(() => import('@/pages/oneC/PeriodsPage').then((m) => ({ default: m.PeriodsPage })))
const DocumentsPage = lazy(() => import('@/pages/oneC/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const MappingsPage = lazy(() => import('@/pages/oneC/MappingsPage').then((m) => ({ default: m.MappingsPage })))
const ExportPacketsPage = lazy(() => import('@/pages/oneC/ExportPacketsPage').then((m) => ({ default: m.ExportPacketsPage })))
const PolicyPage = lazy(() => import('@/pages/oneC/PolicyPage').then((m) => ({ default: m.PolicyPage })))
const PostingTemplatesPage = lazy(() => import('@/pages/oneC/PostingTemplatesPage').then((m) => ({ default: m.PostingTemplatesPage })))
const PricesPage = lazy(() => import('@/pages/oneC/PricesPage').then((m) => ({ default: m.PricesPage })))
const BatchesPage = lazy(() => import('@/pages/oneC/BatchesPage').then((m) => ({ default: m.BatchesPage })))
const MonthCloseForecastPage = lazy(() => import('@/pages/MonthCloseForecastPage').then((m) => ({ default: m.MonthCloseForecastPage })))
const ReconciliationPage = lazy(() => import('@/pages/ReconciliationPage').then((m) => ({ default: m.ReconciliationPage })))
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const AcceptInvitePage = lazy(() => import('@/pages/AcceptInvitePage').then((m) => ({ default: m.AcceptInvitePage })))
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
        <AuthProvider>
          <CompanyProvider>
            <FilterProvider>
              <SupportProvider>
                <TooltipProvider>
                  <Outlet />
                  <Toaster position="bottom-right" richColors closeButton />
                </TooltipProvider>
              </SupportProvider>
            </FilterProvider>
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
      { path: '/login', element: <LazyPage><LoginPage /></LazyPage> },
      { path: '/invite/:token', element: <LazyPage><AcceptInvitePage /></LazyPage> },
      {
        element: <ProtectedRoute><MainLayout /></ProtectedRoute>,
        children: [
          { path: '/', element: <WorkspaceLayout /> },
          { path: '/intake', element: <LazyPage><IntakePage /></LazyPage> },
          { path: '/channels', element: <LazyPage><ChannelsPage /></LazyPage> },
          { path: '/channels/:id', element: <LazyPage><ChannelDetailPage /></LazyPage> },
          { path: '/sources', element: <LazyPage><SourcesPage /></LazyPage> },
          { path: '/catalog', element: <LazyPage><CatalogPage /></LazyPage> },
          { path: '/locations', element: <LazyPage><LocationsPage /></LazyPage> },
          { path: '/contractors', element: <LazyPage><ContractorsPage /></LazyPage> },
          { path: '/organization', element: <LazyPage><OrganizationPage /></LazyPage> },
          { path: '/1c/connection', element: <LazyPage><ConnectionPage /></LazyPage> },
          { path: '/1c/references', element: <LazyPage><ReferencesPage /></LazyPage> },
          { path: '/1c/documents', element: <LazyPage><DocumentsPage /></LazyPage> },
          { path: '/1c/periods', element: <LazyPage><PeriodsPage /></LazyPage> },
          { path: '/1c/mappings', element: <LazyPage><MappingsPage /></LazyPage> },
          { path: '/1c/export', element: <LazyPage><ExportPacketsPage /></LazyPage> },
          { path: '/1c/policy', element: <LazyPage><PolicyPage /></LazyPage> },
          { path: '/1c/posting-templates', element: <LazyPage><PostingTemplatesPage /></LazyPage> },
          { path: '/1c/prices', element: <LazyPage><PricesPage /></LazyPage> },
          { path: '/1c/batches', element: <LazyPage><BatchesPage /></LazyPage> },
          { path: '/forecast', element: <LazyPage><MonthCloseForecastPage /></LazyPage> },
          { path: '/reconciliation', element: <LazyPage><ReconciliationPage /></LazyPage> },
          { path: '/settings', element: <LazyPage><SettingsPage /></LazyPage> },
          { path: '/admin', element: <LazyPage><AdminPage /></LazyPage> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
], { basename })

export default function App() {
  return <RouterProvider router={router} />
}
