/**
 * Контекст аутентификации.
 *
 * API-режим (задан VITE_API_URL): реальный логин через /api/auth, токен в
 * localStorage, на маунте подтягивается /auth/me со списком доступных компаний.
 * Demo-режим (без VITE_API_URL): локальный псевдо-суперадмин со всеми
 * компаниями — чтобы офлайн-localStorage-разработка работала без логина.
 */
import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from 'react'
import * as authService from '@/services/authService'
import type { AuthUser } from '@/services/authService'
import * as api from '@/services/apiClient'
import { defaultCompanies } from '@/config/companies'
import { queryClient } from '@/lib/queryClient'
import { resetServiceCaches } from '@/services/cacheReset'

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  /** Усыновить сессию по готовому access-токену (после принятия приглашения). */
  applySession: (accessToken: string) => Promise<void>
  /** Перечитать свой профиль — после смены фото или имени в учётной записи. */
  refreshMe: () => Promise<void>
}

// Demo-пользователь (офлайн без бэкенда): суперадмин со всеми компаниями.
const DEMO_USER: AuthUser = {
  id: 'demo',
  email: 'demo@local',
  name: 'Demo',
  role: 'admin',
  is_superadmin: true,
  default_company_id: defaultCompanies[0]?.id ?? null,
  companies: defaultCompanies.map((c) => ({
    id: c.id, slug: c.id, name: c.name,
    short_name: c.shortName, color: c.color, profile_id: c.profileId,
  })),
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const apiEnabled = api.isApiEnabled()
  const [user, setUser] = useState<AuthUser | null>(apiEnabled ? null : DEMO_USER)
  const [token, setTokenState] = useState<string | null>(() => api.getToken())
  const [loading, setLoading] = useState<boolean>(apiEnabled)

  // На маунте в API-режиме — подтянуть /me при наличии токена.
  useEffect(() => {
    if (!apiEnabled) return
    let alive = true
    const t = api.getToken()
    if (!t) {
      // Стенд, открытый из кабинета сайта, узнаётся по базовому пути сборки
      // (/demo-run/<стенд>/app/). Отдельного флага не заводим: сборка под кабинет
      // и есть признак показа, а лишняя переменная разъехалась бы с ней.
      if (import.meta.env.BASE_URL.startsWith('/demo-run/')) {
        authService.demoSession()
          .then(() => authService.getMe())
          .then((me) => { if (alive) { setUser(me); setTokenState(api.getToken()) } })
          // Молча падаем на форму входа: показ без сессии — это неудобно,
          // но экран ошибки посреди демонстрации хуже.
          .catch(() => { if (alive) setUser(null) })
          .finally(() => { if (alive) setLoading(false) })
        return
      }
      setUser(null); setLoading(false); return
    }
    authService.getMe()
      .then((me) => { if (alive) { setUser(me); setTokenState(t) } })
      .catch(() => { api.clearToken(); if (alive) { setUser(null); setTokenState(null) } })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [apiEnabled])

  const login = useCallback(async (email: string, password: string) => {
    const res = await authService.login(email, password)  // токен сохранён сервисом
    const me = await authService.getMe()
    setTokenState(res.access_token)
    setUser(me)
  }, [])

  const applySession = useCallback(async (accessToken: string) => {
    api.setToken(accessToken)
    const me = await authService.getMe()
    setTokenState(accessToken)
    setUser(me)
  }, [])

  const refreshMe = useCallback(async () => {
    setUser(await authService.getMe())
  }, [])

  const logout = useCallback(() => {
    authService.logout()
    setUser(null)
    setTokenState(null)
    // Полная зачистка чужих данных из памяти при выходе.
    resetServiceCaches()
    queryClient.clear()
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, token, isAuthenticated: !!user, loading, login, logout, applySession, refreshMe }}
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
