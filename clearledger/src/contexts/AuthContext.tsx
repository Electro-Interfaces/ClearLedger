/**
 * Упрощённый контекст аутентификации — demo-only.
 * Всегда авторизован как бухгалтер ГИГ.
 */

import { createContext, useContext, type ReactNode } from 'react'

interface AuthUser {
  id: string
  email: string
  name: string
  role: string
}

interface AuthContextType {
  user: AuthUser
  isAuthenticated: true
}

const GIG_USER: AuthUser = {
  id: 'gig-user',
  email: 'buhgalter@gig.ru',
  name: 'Бухгалтер ГИГ',
  role: 'admin',
}

const AuthContext = createContext<AuthContextType>({
  user: GIG_USER,
  isAuthenticated: true,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <AuthContext.Provider value={{ user: GIG_USER, isAuthenticated: true }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
