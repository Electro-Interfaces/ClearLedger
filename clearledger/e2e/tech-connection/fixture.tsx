import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { TechConnectionWorkflow } from '../../src/components/sites/TechConnectionWorkflow'
import type { TechConnection } from '../../src/services/sitesService'
import '../../src/index.css'
const identity = await fetch('/api/__test/identity').then(r => r.json())
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}>
  <main className="mx-auto max-w-5xl p-4"><h1 className="mb-4 text-lg font-semibold">Тестовый проект · Присоединение</h1>
    <TechConnectionWorkflow {...identity} tc={{ steps: [{ key: 'applied', label: 'Заявка направлена' }, { key: 'supply_contract', label: 'Договор со сбытом' }] } as TechConnection}
      onDone={async () => {}} /><Toaster /></main>
</QueryClientProvider>)
