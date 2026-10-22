// Изолированная проверка UI: никакой авторизации и обращений к рабочему стеку.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HourlyOccupancy } from '../src/components/workspace/analytics/HourlyOccupancy'
import type { Tz } from '../src/components/workspace/analytics/TzToggle'
import '../src/index.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
function Fixture() {
  const [companyId, setCompanyId] = useState('company-a')
  const [stations, setStations] = useState(['S01', 'S02'])
  const [tz, setTz] = useState<Tz>('msk')
  const narrow = { stations, regions: ['region-test'], dim: 'user_type', dimVal: 'ФЛ', key: stations.join(',') }
  return <main className="min-h-screen bg-background text-foreground">
    <div className="flex flex-wrap gap-3 p-4 text-sm">
      <strong>Тест UI · синтетические ответы API</strong>
      <button onClick={() => setStations(['S01'])}>Одна станция</button>
      <button onClick={() => setStations(['S01', 'S02'])}>Несколько станций</button>
      <button onClick={() => setCompanyId('company-b')}>Другая компания</button>
    </div>
    <HourlyOccupancy key={`${companyId}|${narrow.key}`} companyId={companyId} dateFrom="2026-10-01" dateTo="2026-10-02" narrow={narrow} tz={tz} onTzChange={setTz} />
  </main>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><Fixture /></QueryClientProvider></React.StrictMode>)
