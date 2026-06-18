/**
 * Сервис аутентификации — вызовы API auth.
 */

import * as api from './apiClient'

/** Краткая карточка компании (как в backend CompanyBrief, snake_case по проводу). */
export interface CompanyRef {
  id: string
  slug: string
  name: string
  short_name?: string | null
  color?: string | null
  profile_id: string
}

/** Ответ /api/auth/me — пользователь + доступные компании (мультитенантность). */
export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  is_superadmin: boolean
  default_company_id?: string | null
  companies: CompanyRef[]
}

/** Базовый пользователь из login/register (без списка компаний). */
export interface BasicUser {
  id: string
  email: string
  name: string
  role: string
  company_id?: string | null
  is_superadmin?: boolean
  is_active?: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: BasicUser
}

/** Логин по email + пароль */
export async function login(email: string, password: string): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/login', { email, password })
  api.setToken(result.access_token)
  return result
}

/** Регистрация нового пользователя */
export async function register(data: {
  email: string
  name: string
  password: string
  company_id: string
  role?: string
}): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/register', data)
  api.setToken(result.access_token)
  return result
}

/** Получить текущего пользователя + список доступных компаний по токену */
export async function getMe(): Promise<AuthUser> {
  return api.get<AuthUser>('/api/auth/me')
}

/** Продлить токен (выдаёт новый JWT) */
export async function refreshToken(): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/refresh')
  api.setToken(result.access_token)
  return result
}

/** Выход */
export function logout(): void {
  api.clearToken()
}
