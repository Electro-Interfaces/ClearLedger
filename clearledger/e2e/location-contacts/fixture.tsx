import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { LocationContactsBlock } from '../../src/components/locations/cockpit/LocationContactsBlock'
import '../../src/index.css'
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
function Fixture() {
  const [site, setSite] = useState(0)
  return <main className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
    <h1 className="text-xl font-semibold">Тестовая копия · объект {site + 1}</h1>
    <div className="flex gap-4"><button onClick={() => setSite(0)}>Объект 1</button><button onClick={() => setSite(1)}>Объект 2</button><button onClick={() => document.documentElement.classList.toggle('dark')}>Тема</button></div>
    <LocationContactsBlock key={site} locationId={`test-site-${site}`} /><Toaster />
  </main>
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Fixture /></QueryClientProvider>)
