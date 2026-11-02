import { createContext, useContext, useState, type ReactNode } from 'react'
import { setApiCompany } from '../../src/services/apiClient'

const Company = createContext({ companyId: 'qa-a' })
export const useCompany = () => useContext(Company)

export function TestCompany({ children }: { children: ReactNode }) {
  const [companyId, setCompany] = useState('qa-a')
  const choose = (id: string) => { setApiCompany(id); setCompany(id) }
  return <Company.Provider value={{ companyId }}>
    <nav aria-label="Синтетическая смена компании" className="flex gap-2 p-4">
      <button onClick={() => choose('qa-a')}>Компания А</button>
      <button onClick={() => choose('qa-b')}>Компания Б</button>
    </nav>
    {children}
  </Company.Provider>
}
