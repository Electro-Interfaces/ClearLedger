import { createBrowserRouter, RouterProvider, Outlet } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { MainLayout } from '@/components/layout/MainLayout'
import { Dashboard } from '@/pages/Dashboard'
import { IntakePage } from '@/pages/IntakePage'
import { UploadPage } from '@/pages/UploadPage'
import { PhotoScanPage } from '@/pages/PhotoScanPage'
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

function Providers() {
  return (
    <QueryClientProvider client={queryClient}>
      <CompanyProvider>
        <TooltipProvider>
          <Outlet />
        </TooltipProvider>
      </CompanyProvider>
    </QueryClientProvider>
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
          { path: '/', element: <Dashboard /> },
          { path: '/inbox', element: <InboxPage /> },
          { path: '/inbox/:id', element: <InboxDetailPage /> },
          { path: '/input', element: <IntakePage /> },
          { path: '/input/upload', element: <UploadPage /> },
          { path: '/input/photo', element: <PhotoScanPage /> },
          { path: '/input/manual', element: <ManualEntryPage /> },
          { path: '/connectors', element: <ConnectorsPage /> },
          { path: '/connectors/:id', element: <ConnectorDetailPage /> },
          { path: '/data/:category', element: <DataCategoryPage /> },
          { path: '/data/:category/:id', element: <DataDetailPage /> },
          { path: '/search', element: <SearchPage /> },
          { path: '/settings', element: <SettingsPage /> },
          { path: '/settings/companies', element: <CompaniesPage /> },
          { path: '/settings/companies/:id', element: <CompanyEditPage /> },
        ],
      },
    ],
  },
], { basename })

export default function App() {
  return <RouterProvider router={router} />
}
