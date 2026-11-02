/**
 * Контекст аутентификации.
 *
 * API-режим (задан VITE_API_URL): реальный логин через /api/auth, токен в
 * localStorage, на маунте подтягивается /auth/me со списком доступных компаний.
 * Demo-режим (без VITE_API_URL): локальный псевдо-суперадмин со всеми
 * компаниями — чтобы офлайн-localStorage-разработка работала без логина.
 */
import {
  createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode,
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
  login: (email: string, password: string, otp?: string) => Promise<void>
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
  const profileVersion = useRef(0)

  const loadProfile = useCallback(async (expectedToken: string, version: number, options?: { signal?: AbortSignal }) => {
    const current = () => version === profileVersion.current
      && (api.getToken() === expectedToken || api.getToken() === null)
    try {
      const me = await authService.getMe(options)
      if (current() && api.getToken() === expectedToken) {
        setUser(me); setTokenState(expectedToken)
      }
    } catch (error) {
      // A current HTTP401 may already have cleared its own token in apiClient.
      // Unmounted/replaced loads own neither React state nor shared storage.
      if (current()) {
        api.clearToken()
        setUser(null); setTokenState(null)
      }
      throw error
    } finally {
      if (current()) setLoading(false)
    }
  }, [])

  // На маунте в API-режиме — подтянуть /me при наличии токена.
  useEffect(() => {
    if (!apiEnabled) return
    let alive = true
    const version = ++profileVersion.current
    const controller = new AbortController()
    const cleanup = () => { alive = false; profileVersion.current += 1; controller.abort() }
    const t = api.getToken()
    if (!t) {
      // Стенд, открытый из кабинета сайта, узнаётся по базовому пути сборки
      // (/demo-run/<стенд>/app/). Отдельного флага не заводим: сборка под кабинет
      // и есть признак показа, а лишняя переменная разъехалась бы с ней.
      if (import.meta.env.BASE_URL.startsWith('/demo-run/')) {
        authService.demoSession()
          .then(() => authService.getMe({ signal: controller.signal }))
          .then((me) => { if (alive) { setUser(me); setTokenState(api.getToken()) } })
          // Молча падаем на форму входа: показ без сессии — это неудобно,
          // но экран ошибки посреди демонстрации хуже.
          .catch(() => { if (alive) setUser(null) })
          .finally(() => { if (alive) setLoading(false) })
        return cleanup
      }
      setUser(null); setLoading(false); return cleanup
    }
    // Bootstrap has no caller to receive the error; loadProfile already closes
    // the current session on failure, while stale completions are ignored.
    void loadProfile(t, version, { signal: controller.signal }).catch(() => {})
    return cleanup
  }, [apiEnabled, loadProfile])

  const login = useCallback(async (email: string, password: string, otp?: string) => {
    const version = ++profileVersion.current
    const previousToken = api.getToken()
    const res = await authService.login(email, password, otp)
    if (version !== profileVersion.current || api.getToken() !== previousToken) return
    api.setToken(res.access_token)
    await loadProfile(res.access_token, version)
  }, [loadProfile])

  const applySession = useCallback(async (accessToken: string) => {
    const version = ++profileVersion.current
    api.setToken(accessToken)
    await loadProfile(accessToken, version)
  }, [loadProfile])

  const refreshMe = useCallback(async () => {
    const version = profileVersion.current
    const expectedToken = api.getToken()
    const me = await authService.getMe()
    if (version === profileVersion.current && api.getToken() === expectedToken) setUser(me)
  }, [])

  const logout = useCallback(() => {
    profileVersion.current += 1
    authService.logout()
    setUser(null)
    setTokenState(null)
    setLoading(false)
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
