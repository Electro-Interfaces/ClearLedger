import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Outlet, Link, Navigate, useParams } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { CompanyProvider, useCompany } from '@/contexts/CompanyContext'
import { TabsProvider } from '@/contexts/TabsContext'
import { FilterProvider } from '@/contexts/FilterContext'
import { SupportProvider } from '@/contexts/SupportContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { TabFilterSync } from '@/components/layout/TabFilterSync'
import { OneCAutoSync } from '@/components/onec/OneCAutoSync'
import { WorkspaceLayout } from '@/components/workspace/WorkspaceLayout'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

const IntakePage = lazy(() => import('@/pages/IntakePage').then((m) => ({ default: m.IntakePage })))
const FilesPage = lazy(() => import('@/pages/FilesPage').then((m) => ({ default: m.FilesPage })))
const ChannelsPage = lazy(() => import('@/pages/ChannelsPage').then((m) => ({ default: m.ChannelsPage })))
const ChannelDetailPage = lazy(() => import('@/pages/ChannelDetailPage').then((m) => ({ default: m.ChannelDetailPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const CatalogPage = lazy(() => import('@/pages/CatalogPage').then((m) => ({ default: m.CatalogPage })))
const LocationsPage = lazy(() => import('@/pages/LocationsPage').then((m) => ({ default: m.LocationsPage })))
const ContractorsPage = lazy(() => import('@/pages/ContractorsPage').then((m) => ({ default: m.ContractorsPage })))
const MetrikaPage = lazy(() => import('@/pages/MetrikaPage').then((m) => ({ default: m.MetrikaPage })))
const OrganizationPage = lazy(() => import('@/pages/OrganizationPage').then((m) => ({ default: m.OrganizationPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const AdminLayout = lazy(() => import('@/components/layout/AdminLayout').then((m) => ({ default: m.AdminLayout })))
const MessagesPage = lazy(() => import('@/pages/MessagesPage').then((m) => ({ default: m.MessagesPage })))
const ConnectionPage = lazy(() => import('@/pages/oneC/ConnectionPage').then((m) => ({ default: m.ConnectionPage })))
const SyncPage = lazy(() => import('@/pages/oneC/SyncPage').then((m) => ({ default: m.SyncPage })))
const ReferencesPage = lazy(() => import('@/pages/oneC/ReferencesPage').then((m) => ({ default: m.ReferencesPage })))
const PeriodsPage = lazy(() => import('@/pages/oneC/PeriodsPage').then((m) => ({ default: m.PeriodsPage })))
const DocumentsPage = lazy(() => import('@/pages/oneC/DocumentsPage').then((m) => ({ default: m.DocumentsPage })))
const MappingsPage = lazy(() => import('@/pages/oneC/MappingsPage').then((m) => ({ default: m.MappingsPage })))
const ExportPacketsPage = lazy(() => import('@/pages/oneC/ExportPacketsPage').then((m) => ({ default: m.ExportPacketsPage })))
const PolicyPage = lazy(() => import('@/pages/oneC/PolicyPage').then((m) => ({ default: m.PolicyPage })))
const PostingTemplatesPage = lazy(() => import('@/pages/oneC/PostingTemplatesPage').then((m) => ({ default: m.PostingTemplatesPage })))
const PricesPage = lazy(() => import('@/pages/oneC/PricesPage').then((m) => ({ default: m.PricesPage })))
const BatchesPage = lazy(() => import('@/pages/oneC/BatchesPage').then((m) => ({ default: m.BatchesPage })))
const FuelMappingsPage = lazy(() => import('@/pages/FuelMappingsPage').then((m) => ({ default: m.FuelMappingsPage })))
const MonthCloseForecastPage = lazy(() => import('@/pages/MonthCloseForecastPage').then((m) => ({ default: m.MonthCloseForecastPage })))
const ReconciliationPage = lazy(() => import('@/pages/ReconciliationPage').then((m) => ({ default: m.ReconciliationPage })))
const NormalizationWorkspacePage = lazy(() => import('@/pages/NormalizationWorkspacePage').then((m) => ({ default: m.NormalizationWorkspacePage })))
const EcosystemHomePage = lazy(() => import('@/pages/EcosystemHomePage').then((m) => ({ default: m.EcosystemHomePage })))
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const AcceptInvitePage = lazy(() => import('@/pages/AcceptInvitePage').then((m) => ({ default: m.AcceptInvitePage })))
const ResetPasswordPage = lazy(() => import('@/pages/ResetPasswordPage').then((m) => ({ default: m.ResetPasswordPage })))
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

/**
 * Гард fuel-only роутов (1С, нормализация, закрытие месяца).
 * Для energy-профиля (РусГидро, сеть ЭЗС) этих разделов нет — прямой переход
 * по URL редиректит на рабочий стол. Fuel-профиль (ГИГ) проходит без изменений.
 */
function RequireFuel({ children }: { children: React.ReactNode }) {
  const { company } = useCompany()
  if (company.profileId === 'energy') return <Navigate to="/workspace" replace />
  return <>{children}</>
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
            <CompanyScopedProviders />
          </CompanyProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

function CompanyScopedProviders() {
  const { companyId } = useCompany()
  return (
    <TabsProvider key={companyId}>
      <FilterProvider>
        <SupportProvider>
          <TooltipProvider>
            <TabFilterSync />
            <OneCAutoSync />
            <Outlet />
            <Toaster position="bottom-right" richColors closeButton />
          </TooltipProvider>
        </SupportProvider>
      </FilterProvider>
    </TabsProvider>
  )
}

/** Редирект старого маршрута канала на коннектор с сохранением id. */
function ChannelDetailRedirect() {
  const { id } = useParams()
  return <Navigate to={`/connectors/${id}`} replace />
}

const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

const router = createBrowserRouter([
  {
    element: <Providers />,
    children: [
      { path: '/login', element: <LazyPage><LoginPage /></LazyPage> },
      { path: '/invite/:token', element: <LazyPage><AcceptInvitePage /></LazyPage> },
      { path: '/reset-password/:token', element: <LazyPage><ResetPasswordPage /></LazyPage> },
      {
        path: '/',
        element: <ProtectedRoute><LazyPage><EcosystemHomePage /></LazyPage></ProtectedRoute>,
      },
      {
        // Центр управления — отдельное приложение экосистемы, свой shell (не в Ledger).
        path: '/admin',
        element: <ProtectedRoute><LazyPage><AdminLayout /></LazyPage></ProtectedRoute>,
      },
      {
        element: <ProtectedRoute><MainLayout /></ProtectedRoute>,
        children: [
          { path: '/workspace', element: <WorkspaceLayout /> },
          { path: '/objects', element: <LazyPage><LocationsPage cockpitVariant="full" /></LazyPage> },
          { path: '/files', element: <LazyPage><FilesPage /></LazyPage> },
          { path: '/messages', element: <LazyPage><MessagesPage /></LazyPage> },
          { path: '/intake', element: <LazyPage><IntakePage /></LazyPage> },
          { path: '/connectors', element: <LazyPage><ChannelsPage /></LazyPage> },
          { path: '/metrika', element: <LazyPage><MetrikaPage /></LazyPage> },
          { path: '/connectors/:id', element: <LazyPage><ChannelDetailPage /></LazyPage> },
          // Старые маршруты → «Коннекторы» (редирект). /sources пока доступен (настройка
          // подключения встраивается в коннектор в Фазе 3).
          { path: '/channels', element: <Navigate to="/connectors" replace /> },
          { path: '/channels/:id', element: <ChannelDetailRedirect /> },
          { path: '/sources', element: <LazyPage><SourcesPage /></LazyPage> },
          { path: '/catalog', element: <LazyPage><CatalogPage /></LazyPage> },
          { path: '/locations', element: <Navigate to="/objects" replace /> },
          { path: '/contractors', element: <LazyPage><ContractorsPage /></LazyPage> },
          { path: '/organization', element: <LazyPage><OrganizationPage /></LazyPage> },
          { path: '/1c/connection', element: <RequireFuel><LazyPage><ConnectionPage /></LazyPage></RequireFuel> },
          { path: '/1c/sync', element: <RequireFuel><LazyPage><SyncPage /></LazyPage></RequireFuel> },
          { path: '/1c/references', element: <RequireFuel><LazyPage><ReferencesPage /></LazyPage></RequireFuel> },
          { path: '/1c/documents', element: <RequireFuel><LazyPage><DocumentsPage /></LazyPage></RequireFuel> },
          { path: '/1c/periods', element: <RequireFuel><LazyPage><PeriodsPage /></LazyPage></RequireFuel> },
          { path: '/1c/mappings', element: <RequireFuel><LazyPage><MappingsPage /></LazyPage></RequireFuel> },
          { path: '/1c/export', element: <RequireFuel><LazyPage><ExportPacketsPage /></LazyPage></RequireFuel> },
          { path: '/1c/policy', element: <RequireFuel><LazyPage><PolicyPage /></LazyPage></RequireFuel> },
          { path: '/1c/posting-templates', element: <RequireFuel><LazyPage><PostingTemplatesPage /></LazyPage></RequireFuel> },
          { path: '/1c/prices', element: <RequireFuel><LazyPage><PricesPage /></LazyPage></RequireFuel> },
          { path: '/1c/batches', element: <RequireFuel><LazyPage><BatchesPage /></LazyPage></RequireFuel> },
          { path: '/1c/fuel-mappings', element: <RequireFuel><LazyPage><FuelMappingsPage /></LazyPage></RequireFuel> },
          { path: '/forecast', element: <LazyPage><MonthCloseForecastPage /></LazyPage> },
          { path: '/normalization', element: <LazyPage><NormalizationWorkspacePage /></LazyPage> },
          { path: '/reconciliation', element: <LazyPage><ReconciliationPage /></LazyPage> },
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
