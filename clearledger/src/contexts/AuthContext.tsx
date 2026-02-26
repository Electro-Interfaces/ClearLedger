/**
 * Контекст аутентификации.
 *
 * Два режима:
 * - API mode (VITE_API_URL задан): JWT-авторизация через FastAPI
 * - Demo mode (нет API): автоматический вход как demo-пользователь
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { isApiEnabled, getToken } from '@/services/apiClient'
import * as authService from '@/services/authService'
import type { AuthUser } from '@/services/authService'

interface AuthContextType {
  user: AuthUser | null
  isLoading: boolean
  isAuthenticated: boolean
  /** API-авторизация включена? */
  isApiMode: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

const DEMO_USER: AuthUser = {
  id: 'demo',
  email: 'demo@clearledger.ru',
  name: 'Демо-пользователь',
  role: 'admin',
  is_active: true,
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const apiMode = isApiEnabled()
  const [user, setUser] = useState<AuthUser | null>(apiMode ? null : DEMO_USER)
  const [isLoading, setIsLoading] = useState(apiMode)

  // При старте: проверить токен
  useEffect(() => {
    if (!apiMode) return
    const token = getToken()
    if (!token) {
      setIsLoading(false)
      return
    }
    authService.getMe()
      .then(setUser)
      .catch(() => {
        authService.logout()
        setUser(null)
      })
      .finally(() => setIsLoading(false))
  }, [apiMode])

  const login = useCallback(async (email: string, password: string) => {
    const result = await authService.login(email, password)
    setUser(result.user)
  }, [])

  const logout = useCallback(() => {
    authService.logout()
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        isApiMode: apiMode,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
