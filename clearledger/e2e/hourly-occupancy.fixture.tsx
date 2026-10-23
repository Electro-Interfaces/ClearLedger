// Изолированная проверка UI: никакой авторизации и обращений к рабочему стеку.
import React, { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HourlyOccupancy } from '../src/components/workspace/analytics/HourlyOccupancy'
import type { Tz } from '../src/components/workspace/analytics/TzToggle'
import { ExportButton } from '../src/components/workspace/analytics/ExportButton'
import '../src/index.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
export function Fixture() {
  const [companyId, setCompanyId] = useState('company-a')
  const [stations, setStations] = useState(['S01', 'S02'])
  const [tz, setTz] = useState<Tz>('msk')
  const report = useRef<HTMLDivElement>(null)
  const narrow = { stations, regions: ['region-test'], dim: 'user_type', dimVal: 'ФЛ', key: stations.join(',') }
  return <main className="min-h-screen bg-background text-foreground">
    <div className="flex flex-wrap gap-3 p-4 text-sm">
      <strong>Тест UI · синтетические ответы API</strong>
      <button onClick={() => setStations(['S01'])}>Одна станция</button>
      <button onClick={() => setStations(['S01', 'S02'])}>Несколько станций</button>
      <button onClick={() => setCompanyId('company-b')}>Другая компания</button>
      <button onClick={() => setStations(Array.from({ length: 48 }, (_, i) => `S${String(i + 1).padStart(2, '0')}`))}>Много станций</button>
      <ExportButton title="Занятость по часам" subtitle="Синтетический контур: ФЛ, тестовый регион" getEl={() => report.current} />
    </div>
    <div ref={report}><HourlyOccupancy key={`${companyId}|${narrow.key}`} companyId={companyId} dateFrom="2026-10-01" dateTo="2026-10-02" narrow={narrow} tz={tz} onTzChange={setTz} />
      <table hidden data-export-name="Заголовок строки"><thead><tr><th>Станция</th><th>Занято, мин</th></tr></thead><tbody><tr><th>Контрольная станция</th><td>90</td></tr></tbody></table>
    </div>
  </main>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><Fixture /></QueryClientProvider></React.StrictMode>)
