import { createRoot } from 'react-dom/client'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { StationGantt } from '../../src/components/sites/StationGantt'
import { TechConnectionSummary, TechConnectionStatus } from '../../src/components/sites/TechConnectionSummary'
import { TechConnectionWorkflow } from '../../src/components/sites/TechConnectionWorkflow'
import { getProjectRoadmap, type SiteDetail, type TechConnection } from '../../src/services/sitesService'
import '../../src/index.css'
const identity = await fetch('/api/__test/identity').then(r => r.json())
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
function Fixture() {
  const [tab, setTab] = useState('gantt')
  const q = useQuery({ queryKey: ['roadmap',identity.companyId],queryFn: () => getProjectRoadmap(identity.companyId,identity.siteId) })
  return <main className="mx-auto max-w-7xl p-4 space-y-4"><h1 className="font-semibold">Тестовый проект · представления ТП</h1>
    <nav className="flex gap-3">{[['gantt','Гант'],['summary','Сводка ТП'],['tp','Присоединение']].map(([key,name]) => <button className="rounded border p-2" key={key} onClick={() => setTab(key)}>{name}</button>)}</nav>
    <TechConnectionStatus view={q.data?.techConnection ?? undefined} onOpen={() => setTab('tp')} />
    {tab === 'gantt' ? <StationGantt site={identity.site as SiteDetail} companyId={identity.companyId} onItem={() => setTab('tp')} /> : tab === 'summary' ? q.data?.techConnection && <TechConnectionSummary view={q.data.techConnection} siteId={identity.siteId} />
      : <TechConnectionWorkflow {...identity} tc={{steps: []} as unknown as TechConnection} onDone={async () => {}} />}
  </main>
}
createRoot(document.getElementById('root')!).render(<MemoryRouter><QueryClientProvider client={client}><Fixture /></QueryClientProvider></MemoryRouter>)
