/* eslint-disable react-refresh/only-export-components -- контролируемый переход входа для регрессии фильтров */
import { createContext, useContext, useState, type ReactNode } from 'react'
const Company = createContext({ companyId: '' })
export const useCompany = () => useContext(Company)
export function TestCompany({ children }: { children: ReactNode }) {
  const [companyId, setCompanyId] = useState('')
  return <Company.Provider value={{ companyId }}>
    <button onClick={() => setCompanyId('qa-a')}>Войти в А</button>
    <button onClick={() => setCompanyId('qa-b')}>Переключить на Б</button>
    {children}
  </Company.Provider>
}
