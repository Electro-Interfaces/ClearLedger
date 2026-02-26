/**
 * Сервис аутентификации — вызовы API auth.
 */

import * as api from './apiClient'

export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

/** Логин по email + пароль */
export async function login(email: string, password: string): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/login', { email, password })
  api.setToken(result.access_token)
  return result
}

/** Регистрация нового пользователя (admin/owner) */
export async function register(data: {
  email: string
  name: string
  password: string
  role?: string
}): Promise<TokenResponse> {
  const result = await api.post<TokenResponse>('/api/auth/register', data)
  return result
}

/** Получить текущего пользователя по токену */
export async function getMe(): Promise<AuthUser> {
  return api.get<AuthUser>('/api/auth/me')
}

/** Выход */
export function logout(): void {
  api.clearToken()
}
