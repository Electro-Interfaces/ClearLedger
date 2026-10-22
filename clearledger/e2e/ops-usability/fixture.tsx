/* eslint-disable react-refresh/only-export-components -- самостоятельная тестовая точка входа */
import { useState, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { Scope } from './hooks'
import { SheetTable, type Cols } from '../../src/components/report-kit/SheetTable'
// Экспорт добавляется только тестовым Vite-плагином; production-модуль не меняется.
import * as FilterBar from '../../src/components/workspace/WorkspaceFilterBar'
import { NetworkStatePanel } from '../../src/components/workspace/NetworkStatePanel'
import { NetworkReliabilityPanel } from '../../src/components/workspace/NetworkReliabilityPanel'
import { NetworkVendorsPanel } from '../../src/components/workspace/NetworkVendorsPanel'
import { OpsTicketsPanel } from '../../src/components/workspace/OpsTicketsPanel'
import '../../src/index.css'

const head = ['№', 'Станция', 'Регион', 'Что со станцией', 'Без зарядок, дн', 'Приездов', 'Последняя зарядка', 'В работе']
const rows = Array.from({ length: 60 }, (_, i) => [i + 1, `Учебная ЭЗС ${i + 1}`,
  i < 25 ? 'Москва' : 'Длинное название региона', 'Проверка', i, i < 25 ? 1 : 1234567,
  '20.10.2026', i < 25 ? '—' : 'Учебная заявка №123456789 на проверку станции'])
const widths = { 0: 96, 1: 240, 2: 172, 3: 320 }
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
const PeriodControl = (FilterBar as unknown as Record<string, ComponentType>)['PeriodControl']
const screen = new URLSearchParams(location.search).get('screen') ?? 'table'
const panels = { state: NetworkStatePanel, reliability: NetworkReliabilityPanel, vendors: NetworkVendorsPanel, tickets: OpsTicketsPanel }

function App() {
  const [cols, setCols] = useState<Cols>({ order: head.map((_, i) => i), hidden: [] })
  const Panel = panels[screen as keyof typeof panels]
  return <main className="p-3">
    <PeriodControl />
    <div className="h-8" />
    {Panel ? <Panel /> : <SheetTable head={head} rows={rows} caption="Проверка" lines={[]}
      cols={cols} onCols={setCols} defaultWidths={widths} />}
  </main>
}

createRoot(document.getElementById('root')!).render(
  <BrowserRouter><QueryClientProvider client={client}><Scope><App /></Scope></QueryClientProvider></BrowserRouter>,
)
