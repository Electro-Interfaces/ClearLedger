import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { NavigationHistoryProvider } from '../../src/contexts/NavigationHistoryContext'
import { TabsProvider } from '../../src/contexts/TabsContext'
import ContractorsPage from '../../src/pages/ContractorsPage'
import '../../src/index.css'
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
createRoot(document.getElementById('root')!).render(
  <BrowserRouter><QueryClientProvider client={client}><TabsProvider>
    <NavigationHistoryProvider scope="counterparty-qa">
      <div className="border-b p-2 text-sm">Локальная проверка · вымышленные записи <button onClick={() => document.documentElement.classList.toggle('dark')}>Тема</button></div>
      <ContractorsPage /><Toaster />
    </NavigationHistoryProvider>
  </TabsProvider></QueryClientProvider></BrowserRouter>,
)
