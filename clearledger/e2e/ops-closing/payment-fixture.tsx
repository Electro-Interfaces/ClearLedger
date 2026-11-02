import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TestCompany } from './company'
import { OpsPaymentsPanel } from '../../src/components/balance/OpsPaymentsPanel'
import '../../src/index.css'

const client = new QueryClient({ defaultOptions: { queries: {
  retry: false, staleTime: 60_000, refetchOnWindowFocus: false,
} } })
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}><TestCompany><main className="p-4">
    <OpsPaymentsPanel />
  </main></TestCompany></QueryClientProvider>,
)
