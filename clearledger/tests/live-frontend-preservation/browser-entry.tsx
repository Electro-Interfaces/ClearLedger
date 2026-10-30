import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { PassportTab } from '../../src/components/sites/ProjectTabs'
import { getSite, type SiteDetail } from '../../src/services/sitesService'
import { captureApiContextGuard, setApiCompany, setToken } from '../../src/services/apiClient'
import '../../src/index.css'

// Synthetic process-local session: never reads a user's browser profile or token.
setToken('synthetic-passport-session')
setApiCompany('company-A')
const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

function Fixture() {
  const [company, setCompany] = useState('company-A')
  const [reopen, setReopen] = useState(0)
  const [sessionRender, setSessionRender] = useState(0)
  const [loaded, setLoaded] = useState<{ company: string; reopen: number; site: SiteDetail } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const guard = captureApiContextGuard()
    void getSite(company, 'project-' + company).then((site) => {
      guard()
      if (active) setLoaded({ company, reopen, site })
    }).catch((failure: unknown) => {
      if (active && !(failure instanceof DOMException && failure.name === 'AbortError')) setError(String(failure))
    })
    return () => { active = false }
  }, [company, reopen])

  async function reload() {
    const guard = captureApiContextGuard()
    const site = await getSite(company, 'project-' + company)
    guard()
    setLoaded({ company, reopen, site })
  }

  return <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4" data-session-render={sessionRender}>
    <h1 className="text-xl font-semibold">Тестовая копия · Паспорт СМР</h1>
    <nav aria-label="Тестовый контекст" className="flex flex-wrap gap-3">
      <button onClick={() => { setApiCompany('company-A'); setCompany('company-A') }}>Компания A</button>
      <button onClick={() => { setApiCompany('company-B'); setCompany('company-B') }}>Компания B</button>
      <button onClick={() => { setToken('synthetic-passport-session'); setSessionRender((v) => v + 1) }}>Новый сеанс</button>
      <button onClick={() => { setToken('synthetic-passport-new-session'); setSessionRender((v) => v + 1) }}>Другой сеанс</button>
      <button onClick={() => setReopen((v) => v + 1)}>Открыть карточку заново</button>
      <button onClick={() => document.documentElement.classList.toggle('dark')}>Тема</button>
    </nav>
    <p>Текущая компания: {company}</p>
    {error ? <p role="alert">{error}</p> : loaded?.company === company && loaded.reopen === reopen
      ? <PassportTab key={`${company}:${reopen}`} companyId={company} site={loaded.site} onDone={reload} />
      : <p role="status">Загрузка паспорта…</p>}
    <Toaster />
  </main>
}

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}><BrowserRouter><Fixture /></BrowserRouter></QueryClientProvider>,
)
