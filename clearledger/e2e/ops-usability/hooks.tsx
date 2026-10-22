/* eslint-disable react-refresh/only-export-components -- тестовый контекст и его хуки */
import { createContext, useContext, useState, type ReactNode } from 'react'

const initial = { from: '2026-10-01', to: '2026-10-22' }
const Context = createContext({ period: initial, setPeriod: (period: typeof initial) => { void period } })

export function Scope({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState(initial)
  return <Context.Provider value={{ period, setPeriod }}>{children}</Context.Provider>
}

export function useFilters() {
  return { ...useContext(Context), regionIds: [], locationIds: [], stationCodes: [] }
}

export function useCompany() {
  return { companyId: 'qa-company', company: { profileId: 'energy' } }
}
