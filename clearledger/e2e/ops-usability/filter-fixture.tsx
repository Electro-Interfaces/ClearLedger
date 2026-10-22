import { createRoot } from 'react-dom/client'
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FilterProvider, useFilters } from '../../src/contexts/FilterContext'
import { TestCompany, useCompany } from './filter-company'
const client = new QueryClient()
function Result() {
  const { state, setPeriod } = useFilters()
  const location = useLocation(), navigate = useNavigate()
  return <>
    <output aria-label="Выборка">{JSON.stringify(state)}</output>
    <output aria-label="Адрес">{location.search}</output>
    <button onClick={() => setPeriod({ from: '2026-08-01', to: '2026-08-31' })}>Выбрать август</button>
    <button onClick={() => navigate(-1)}>Назад</button>
    <button onClick={() => {
      const s = { ...state, period: { from: '2026-07-01', to: '2026-07-31' } }
      navigate(`?f=${encodeURIComponent(JSON.stringify(s))}`)
    }}>Открыть ссылку на июль</button>
  </>
}
function Scope() {
  const { companyId } = useCompany()
  return <FilterProvider key={companyId}><Result /></FilterProvider>
}
createRoot(document.getElementById('root')!).render(
  <BrowserRouter><QueryClientProvider client={client}><TestCompany><Scope /></TestCompany></QueryClientProvider></BrowserRouter>,
)
