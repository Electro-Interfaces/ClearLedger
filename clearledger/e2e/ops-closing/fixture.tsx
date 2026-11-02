import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TestCompany } from './company'
import { OpsClosingPanel } from '../../src/components/balance/OpsClosingPanel'
import '../../src/index.css'

const client = new QueryClient({ defaultOptions: { queries: {
  retry: false, staleTime: 60_000, refetchOnWindowFocus: false,
} } })
createRoot(document.getElementById('root')!).render(
  <BrowserRouter><QueryClientProvider client={client}><TestCompany>
    <main><OpsClosingPanel /></main>
  </TestCompany></QueryClientProvider></BrowserRouter>,
)
