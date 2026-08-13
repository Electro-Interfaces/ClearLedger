import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider, Outlet, Link, Navigate, useParams } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { CompanyProvider, useCompany } from '@/contexts/CompanyContext'
import { useAppEnabled } from '@/hooks/useCompanyRegistry'
import { SPACE_PAGES, SPACE_PRODUCTS, isCarvedProfile } from '@/config/spaceProducts'
import { TabsProvider } from '@/contexts/TabsContext'
import { FilterProvider } from '@/contexts/FilterContext'
import { SupportProvider } from '@/contexts/SupportContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { MainLayout } from '@/components/layout/MainLayout'
import { TabFilterSync } from '@/components/layout/TabFilterSync'
import { DocumentTitle } from '@/components/layout/DocumentTitle'
import { OneCAutoSync } from '@/components/onec/OneCAutoSync'
import { WorkspaceLayout, ProductStub } from '@/components/workspace/WorkspaceLayout'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Loader2 } from 'lucide-react'

const IntakePage = lazy(() => import('@/pages/IntakePage').then((m) => ({ default: m.IntakePage })))
const FilesPage = lazy(() => import('@/pages/FilesPage').then((m) => ({ default: m.FilesPage })))
const ChannelsPage = lazy(() => import('@/pages/ChannelsPage').then((m) => ({ default: m.ChannelsPage })))
const ChannelDetailPage = lazy(() => import('@/pages/ChannelDetailPage').then((m) => ({ default: m.ChannelDetailPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const CatalogPage = lazy(() => import('@/pages/CatalogPage').then((m) => ({ default: m.CatalogPage })))
const ConnectionsPage = lazy(() => import('@/pages/ConnectPages').then((m) => ({ default: m.ConnectionsPage })))
const NotificationsPage = lazy(() => import('@/pages/ConnectPages').then((m) => ({ default: m.NotificationsPage })))
const SpaceAppsPage = lazy(() => import('@/pages/ConnectPages').then((m) => ({ default: m.SpaceAppsPage })))
const LocationsPage = lazy(() => import('@/pages/LocationsPage').then((m) => ({ default: m.LocationsPage })))
const ContractorsPage = lazy(() => import('@/pages/ContractorsPage').then((m) => ({ default: m.ContractorsPage })))
const MetrikaPage = lazy(() => import('@/pages/MetrikaPage').then((m) => ({ default: m.MetrikaPage })))
const OrganizationPage = lazy(() => import('@/pages/OrganizationPage').then((m) => ({ default: m.OrganizationPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const AdminLayout = lazy(() => import('@/components/layout/AdminLayout').then((m) => ({ default: m.AdminLayout })))
const AdminSectionPage = lazy(() => import('@/pages/AdminSectionPage').then((m) => ({ default: m.AdminSectionPage })))
const AdminHomeRedirect = lazy(() => import('@/pages/AdminSectionPage').then((m) => ({ default: m.AdminHomeRedirect })))
const MessagesPage = lazy(() => import('@/pages/MessagesPage').then((m) => ({ default: m.MessagesPage })))
const TicketsAppPage = lazy(() => import('@/pages/TicketsAppPage').then((m) => ({ default: m.TicketsAppPage })))
const TasksLayout = lazy(() => import('@/pages/tasks/TasksLayout').then((m) => ({ default: m.TasksLayout })))
const TasksWorkPage = lazy(() => import('@/pages/tasks/TasksWorkPage').then((m) => ({ default: m.TasksWorkPage })))
const TasksCompanyPage = lazy(() => import('@/pages/tasks/TasksWorkPage').then((m) => ({ default: m.TasksCompanyPage })))
const TasksOverviewPage = lazy(() => import('@/pages/tasks/TasksOverviewPage').then((m) => ({ default: m.TasksOverviewPage })))
const TasksSetupPage = lazy(() => import('@/pages/tasks/TasksSetupPage').then((m) => ({ default: m.TasksSetupPage })))
const PulseAppPage = lazy(() => import('@/pulse/PulseAppPage').then((m) => ({ default: m.PulseAppPage })))
const PulseBusinessPage = lazy(() => import('@/pulse/PulseSections').then((m) => ({ default: m.PulseBusinessPage })))
const PulseTeamPage = lazy(() => import('@/pulse/PulseSections').then((m) => ({ default: m.PulseTeamPage })))
const PulseWeekPage = lazy(() => import('@/pulse/PulseSections').then((m) => ({ default: m.PulseWeekPage })))
const PulseLayout = lazy(() => import('@/pulse/PulseLayout').then((m) => ({ default: m.PulseLayout })))
const InfoPage = lazy(() => import('@/pages/InfoPage').then((m) => ({ default: m.InfoPage })))
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

/**
 * Гард продукта пространства («Проекты», …): прямая ссылка не должна обходить ни роль,
 * ни состав поставки. Не подключено компании или не дано ролью → на рабочий стол
 * пространства. Реестр молчит (офлайн/старый бэкенд) — пускаем: это состав, а не защита.
 */
function RequireApp({ code, children }: { code: string; children: React.ReactNode }) {
  const { companyId, canApp } = useCompany()
  const enabled = useAppEnabled(companyId, code)
  if (!canApp(code) || enabled === false) return <Navigate to="/" replace />
  return <>{children}</>
}

/**
 * «Учёт» (`/workspace`). Там, где разрез на продукты включён (energy), разделов у Учёта
 * не остаётся — они разошлись по продуктам, поэтому маршрут ведёт на рабочий стол.
 * У топливного профиля Учёт остаётся единым продуктом со всеми разделами.
 */
function LedgerWorkspace() {
  const { company } = useCompany()
  if (isCarvedProfile(company.profileId)) return <Navigate to="/" replace />
  return <WorkspaceLayout />
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
            <DocumentTitle />
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

/** Страницы Ядра (`SPACE_PAGES`) — общий блок левого меню, один и тот же во всех продуктах. */
const SPACE_PAGE_ELEMENTS: Record<string, React.ReactNode> = {
  '/objects': <LazyPage><LocationsPage cockpitVariant="full" /></LazyPage>,
  '/intake': <LazyPage><IntakePage /></LazyPage>,
  '/files': <LazyPage><FilesPage /></LazyPage>,
  '/contractors': <LazyPage><ContractorsPage /></LazyPage>,
}

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
        // «Управление» — отдельное приложение экосистемы, свой shell (не в Ledger).
        // Разделы — вложенные маршруты: на раздел даётся ссылка, работает «назад».
        path: '/admin',
        element: <ProtectedRoute><LazyPage><AdminLayout /></LazyPage></ProtectedRoute>,
        children: [
          { index: true, element: <LazyPage><AdminHomeRedirect /></LazyPage> },
          { path: ':scope/:section', element: <LazyPage><AdminSectionPage /></LazyPage> },
        ],
      },
      {
        element: <ProtectedRoute><MainLayout /></ProtectedRoute>,
        children: [
          { path: '/workspace', element: <LedgerWorkspace /> },
          // Продукты пространства — разделы Учёта, ставшие самостоятельными рабочими
          // местами (`config/spaceProducts.ts`): своя плитка на столе, свой ключ доступа
          // в роли, своё левое меню. Маршруты строятся из той же карты, что и меню.
          ...SPACE_PRODUCTS.filter((p) => p.modes.length).map((p) => ({
            path: p.route,
            element: <RequireApp code={p.code}><WorkspaceLayout modes={p.modes} /></RequireApp>,
          })),
          // «Подключения» собраны из страниц, рабочей области у них нет — корень ведёт
          // на первую страницу приложения.
          { path: '/connect', element: <Navigate to="/connections" replace /> },
          // Функции Ядра открыты из КАЖДОГО рабочего места — под его адресом
          // (`/finance/objects`): экран один, но видно, откуда смотрят, и от этого
          // зависят права (`finance:objects`).
          ...SPACE_PRODUCTS.flatMap((p) => SPACE_PAGES.map((path) => ({
            path: `${p.route}${path}`,
            element: <RequireApp code={p.code}>{SPACE_PAGE_ELEMENTS[path]}</RequireApp>,
          }))),
          // Продукты, заведённые в реестре, но пока без своих экранов: маршрут нужен —
          // иначе плитка со стола вела бы в «страница не найдена». За ним заставка,
          // объясняющая, что здесь появится (`PRODUCT_SETUP_NOTE`).
          { path: '/netlink', element: <RequireApp code="netlink"><ProductStub code="netlink" /></RequireApp> },
          { path: '/accounting', element: <RequireApp code="accounting"><ProductStub code="accounting" /></RequireApp> },
          { path: '/diagnostics', element: <RequireApp code="diag"><ProductStub code="diag" /></RequireApp> },
          // Рабочие места компании без объектов (профиль `office`) стали продуктами
          // пространства со своими разделами — маршруты им строит карта выше
          // (`SPACE_PRODUCTS`). Здесь остались старые адреса двух бывших приложений:
          // «Продажи» и «Услуги» слились в «Реализацию», и закладка на них обязана
          // приводить в её раздел, а не в «страница не найдена».
          { path: '/trade', element: <Navigate to="/revenue?mode=rev_goods" replace /> },
          { path: '/services', element: <Navigate to="/revenue?mode=rev_services" replace /> },
          { path: '/objects', element: <LazyPage><LocationsPage cockpitVariant="full" /></LazyPage> },
          { path: '/files', element: <LazyPage><FilesPage /></LazyPage> },
          { path: '/messages', element: <LazyPage><MessagesPage /></LazyPage> },
          // «Заявки» — витрина Поддержки (docs/TICKETS.md). Продуктом пространства
          // больше не числится: её открывают из «Пульса», Центра управления и
          // карточки объекта, поэтому гарда по продукту здесь нет.
          { path: '/tickets', element: <LazyPage><TicketsAppPage /></LazyPage> },
          // «Задачи» — работа компании на своём движке Ядра (docs/TASKS.md).
          // Разделы приложения — своими путями, их пункты — во второй колонке
          // (TasksLayout), как у «Пульса»: это тоже приложение Ядра, а не продукт
          // разреза, и в CoreMode его разделы не заводятся.
          // Гард по продукту: задачи видят только те, кому продукт подключён.
          {
            path: '/tasks',
            element: <RequireApp code="plan"><LazyPage><TasksLayout /></LazyPage></RequireApp>,
            children: [
              { index: true, element: <LazyPage><TasksWorkPage /></LazyPage> },
              { path: 'company', element: <LazyPage><TasksCompanyPage /></LazyPage> },
              { path: 'overview', element: <LazyPage><TasksOverviewPage /></LazyPage> },
              { path: 'setup', element: <LazyPage><TasksSetupPage /></LazyPage> },
            ],
          },
          // «Пульс» — рабочее место руководителя (ecosystem-deploy/docs/PULSE.md):
          // разделы в рельсе приложения, их пункты — во второй колонке (PulseLayout),
          // как в «Продажах» и «Проектах».
          {
            path: '/pulse',
            // Гард такой же, как у продуктов разреза: «Пульс» показывает выручку сети,
            // нарушения SLA и поимённую активность людей, а в пространстве есть внешние
            // участники — прямая ссылка не должна обходить право на продукт.
            element: <RequireApp code="pulse"><LazyPage><PulseLayout /></LazyPage></RequireApp>,
            children: [
              { index: true, element: <LazyPage><PulseAppPage /></LazyPage> },
              { path: 'business', element: <LazyPage><PulseBusinessPage /></LazyPage> },
              { path: 'team', element: <LazyPage><PulseTeamPage /></LazyPage> },
              { path: 'week', element: <LazyPage><PulseWeekPage /></LazyPage> },
            ],
          },
          // «Инфо» — знание пространства: то же приложение, что открывается
          // подсказкой в рабочей области, только целиком (docs/INFO.md).
          { path: '/info', element: <LazyPage><InfoPage /></LazyPage> },
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
          // Разделы, переехавшие из «Управления» в «Подключения» (30.07.2026).
          { path: '/connections', element: <LazyPage><ConnectionsPage /></LazyPage> },
          { path: '/notifications', element: <LazyPage><NotificationsPage /></LazyPage> },
          { path: '/apps', element: <LazyPage><SpaceAppsPage /></LazyPage> },
          { path: '/admin/company/connections', element: <Navigate to="/connections" replace /> },
          { path: '/admin/company/notify', element: <Navigate to="/notifications" replace /> },
          { path: '/admin/company/apps', element: <Navigate to="/apps" replace /> },
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
